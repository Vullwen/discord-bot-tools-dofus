"""Configuration en Discord du salon des raids.

- /setchannel : définit le salon où arrivent les sondages/embeds des raids
- /showconfig : affiche la configuration courante de la guilde.
"""
from __future__ import annotations

import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from utils.perms import is_raid_organizer

_CHANNEL_LABEL = {
    db.SETTING_RAIDS_CHANNEL: "Salon des raids",
    db.SETTING_RAID_ADMIN_CHANNEL: "Salon admin raids",
    db.SETTING_ABSENCE_PANEL_CHANNEL: "Salon panel absences",
    db.SETTING_ABSENCE_CHANNEL: "Salon absence",
    db.SETTING_ABSENCE_ADMIN_CHANNEL: "Salon admin absences",
}


def _resolve_role(guild: discord.Guild, role_ref: str) -> Optional[discord.Role]:
    raw = (role_ref or "").strip()
    if not raw:
        return None

    match = re.fullmatch(r"<@&(\d+)>|(\d+)", raw)
    if match:
        role_id = int(match.group(1) or match.group(2))
        return guild.get_role(role_id)

    normalized = raw.lstrip("@").casefold()
    matches = [role for role in guild.roles if role.name.casefold() == normalized]
    return matches[0] if len(matches) == 1 else None


class SettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setchannel", description="Définit un salon du bot")
    @app_commands.describe(
        setting="Ce que tu veux configurer",
        channel="Le salon à utiliser",
    )
    @app_commands.choices(
        setting=[
            app_commands.Choice(name="Salon des raids", value=db.SETTING_RAIDS_CHANNEL),
            app_commands.Choice(name="Salon admin raids", value=db.SETTING_RAID_ADMIN_CHANNEL),
            app_commands.Choice(name="Salon panel absences", value=db.SETTING_ABSENCE_PANEL_CHANNEL),
            app_commands.Choice(name="Salon absence", value=db.SETTING_ABSENCE_CHANNEL),
            app_commands.Choice(name="Salon admin absences", value=db.SETTING_ABSENCE_ADMIN_CHANNEL),
        ]
    )
    async def setchannel(
        self,
        interaction: discord.Interaction,
        setting: app_commands.Choice[str],
        channel: discord.abc.GuildChannel,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        db.set_guild_setting(interaction.guild.id, setting.value, str(channel.id))
        label = _CHANNEL_LABEL.get(setting.value, setting.value)
        await interaction.response.send_message(
            f"✅ {label} défini sur {channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(
        name="setraidrole",
        description="Définit le rôle autorisé à créer/gérer les raids",
    )
    @app_commands.describe(
        role="ID, mention ou nom exact du rôle (vide = permission Administrateur Discord)",
    )
    async def setraidrole(
        self,
        interaction: discord.Interaction,
        role: Optional[str] = None,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        if role is None:
            db.set_guild_setting(interaction.guild.id, db.SETTING_RAID_MANAGER_ROLE, "")
            await interaction.response.send_message(
                "✅ Rôle organisateur retiré. Les membres avec la permission Administrateur peuvent créer/gérer les raids.",
                ephemeral=True,
            )
            return

        resolved = _resolve_role(interaction.guild, role)
        if resolved is None:
            await interaction.response.send_message(
                "Rôle introuvable. Donne son ID, sa mention copiée (`<@&id>`) ou son nom exact.",
                ephemeral=True,
            )
            return

        db.set_guild_setting(interaction.guild.id, db.SETTING_RAID_MANAGER_ROLE, str(resolved.id))
        await interaction.response.send_message(
            f"✅ Rôle organisateur défini : {resolved.mention}. Ses détenteurs peuvent "
            f"créer/gérer les raids.",
            ephemeral=True,
        )

    @app_commands.command(
        name="setraidnotifyrole",
        description="Définit le rôle mentionné à chaque nouveau raid",
    )
    @app_commands.describe(
        role="ID, mention ou nom exact du rôle (vide = désactive la mention)",
    )
    async def setraidnotifyrole(
        self,
        interaction: discord.Interaction,
        role: Optional[str] = None,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        if role is None:
            db.set_guild_setting(interaction.guild.id, db.SETTING_RAID_NOTIFY_ROLE, "")
            await interaction.response.send_message(
                "✅ Mention de raid désactivée (aucun rôle ne sera mentionné).",
                ephemeral=True,
            )
            return

        resolved = _resolve_role(interaction.guild, role)
        if resolved is None:
            await interaction.response.send_message(
                "Rôle introuvable. Donne son ID, sa mention copiée (`<@&id>`) ou son nom exact.",
                ephemeral=True,
            )
            return

        db.set_guild_setting(interaction.guild.id, db.SETTING_RAID_NOTIFY_ROLE, str(resolved.id))
        await interaction.response.send_message(
            f"✅ Rôle notif défini : {resolved.mention}. Il sera mentionné à l'annonce de chaque nouveau raid.",
            ephemeral=True,
        )

    @app_commands.command(name="showconfig", description="Affiche la configuration des raids de ce serveur")
    async def showconfig(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        guild = interaction.guild

        def _mention(key):
            cid = db.get_guild_setting_int(guild.id, key)
            if not cid:
                return "*(non défini)*"
            ch = guild.get_channel(cid)
            return ch.mention if ch else f"*(salon {cid} introuvable)*"

        def _role_mention(key, fallback):
            rid = db.get_guild_setting_int(guild.id, key)
            if not rid:
                return fallback
            role = guild.get_role(rid)
            return role.mention if role else f"*(rôle {rid} introuvable)*"

        embed = discord.Embed(title="⚙️ Configuration", color=0x2ECC71)
        embed.add_field(name="Salon des raids", value=_mention(db.SETTING_RAIDS_CHANNEL), inline=False)
        embed.add_field(name="Salon admin raids", value=_mention(db.SETTING_RAID_ADMIN_CHANNEL), inline=False)
        embed.add_field(
            name="Salon panel absences",
            value=_mention(db.SETTING_ABSENCE_PANEL_CHANNEL),
            inline=False,
        )
        embed.add_field(name="Salon absence", value=_mention(db.SETTING_ABSENCE_CHANNEL), inline=False)
        embed.add_field(
            name="Salon admin absences",
            value=_mention(db.SETTING_ABSENCE_ADMIN_CHANNEL),
            inline=False,
        )
        embed.add_field(
            name="Rôle organisateur",
            value=_role_mention(db.SETTING_RAID_MANAGER_ROLE, "*(non défini — permission Administrateur)*"),
            inline=False,
        )
        embed.add_field(
            name="Rôle notif raids",
            value=_role_mention(db.SETTING_RAID_NOTIFY_ROLE, "*(non défini — pas de mention)*"),
            inline=False,
        )
        embed.set_footer(text="Configure avec /setchannel, /setraidrole et /setraidnotifyrole")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
