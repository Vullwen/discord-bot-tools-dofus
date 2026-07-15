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
from config import DOFUS_GUILD_NAME, DOFUS_SERVER
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

    @app_commands.command(
        name="setbaserole",
        description="Définit le rôle remis après /absence kick",
    )
    @app_commands.describe(
        role="ID, mention ou nom exact du rôle (vide = désactive le changement de rôles)",
    )
    async def setbaserole(
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
            db.set_guild_setting(interaction.guild.id, db.SETTING_BASE_ROLE, "")
            await interaction.response.send_message(
                "✅ Rôle de base désactivé. `/absence kick` ne modifiera plus les rôles.",
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

        db.set_guild_setting(interaction.guild.id, db.SETTING_BASE_ROLE, str(resolved.id))
        await interaction.response.send_message(
            f"✅ Rôle de base défini : {resolved.mention}. `/absence kick` retirera les autres rôles "
            "et remettra celui-ci.",
            ephemeral=True,
        )

    @app_commands.command(
        name="setmemberrole",
        description="Définit le rôle donné après vérification Dofus",
    )
    @app_commands.describe(
        role="ID, mention ou nom exact du rôle (vide = désactive l'attribution automatique)",
    )
    async def setmemberrole(
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
            db.set_guild_setting(interaction.guild.id, db.SETTING_VERIFIED_MEMBER_ROLE, "")
            await interaction.response.send_message(
                "✅ Rôle membre vérifié désactivé. La vérification validera les persos sans donner de rôle.",
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

        db.set_guild_setting(interaction.guild.id, db.SETTING_VERIFIED_MEMBER_ROLE, str(resolved.id))
        await interaction.response.send_message(
            f"✅ Rôle membre vérifié défini : {resolved.mention}. Il sera donné après vérification validée.",
            ephemeral=True,
        )

    @app_commands.command(
        name="setunverifiedrole",
        description="Définit le rôle retiré après vérification Dofus",
    )
    @app_commands.describe(
        role="ID, mention ou nom exact du rôle à vérifier (vide = désactive le retrait automatique)",
    )
    async def setunverifiedrole(
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
            db.set_guild_setting(interaction.guild.id, db.SETTING_UNVERIFIED_MEMBER_ROLE, "")
            await interaction.response.send_message(
                "✅ Rôle à vérifier désactivé. La vérification ne retirera aucun rôle automatiquement.",
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

        db.set_guild_setting(interaction.guild.id, db.SETTING_UNVERIFIED_MEMBER_ROLE, str(resolved.id))
        await interaction.response.send_message(
            f"✅ Rôle à vérifier défini : {resolved.mention}. Il sera retiré après vérification validée.",
            ephemeral=True,
        )

    @app_commands.command(
        name="setdofusconfig",
        description="Définit la guilde et le serveur attendus pour la vérification",
    )
    @app_commands.describe(
        guilde="Nom exact de la guilde Dofus dans /whoami",
        serveur="Serveur Dofus par défaut",
    )
    async def setdofusconfig(
        self,
        interaction: discord.Interaction,
        guilde: str,
        serveur: str,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        db.set_guild_setting(interaction.guild.id, db.SETTING_DOFUS_GUILD_NAME, guilde.strip())
        db.set_guild_setting(interaction.guild.id, db.SETTING_DOFUS_SERVER, serveur.strip())
        await interaction.response.send_message(
            f"✅ Vérification Dofus configurée : guilde **{guilde.strip()}**, serveur **{serveur.strip()}**.",
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

        def _setting(key, fallback):
            value = db.get_guild_setting(guild.id, key)
            return value if value else fallback

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
        embed.add_field(
            name="Rôle de base",
            value=_role_mention(db.SETTING_BASE_ROLE, "*(non défini — /absence kick ne modifie pas les rôles)*"),
            inline=False,
        )
        embed.add_field(
            name="Rôle membre vérifié",
            value=_role_mention(db.SETTING_VERIFIED_MEMBER_ROLE, "*(non défini — la vérification ne donne pas de rôle)*"),
            inline=False,
        )
        embed.add_field(
            name="Rôle à vérifier",
            value=_role_mention(db.SETTING_UNVERIFIED_MEMBER_ROLE, "*(non défini — la vérification ne retire pas de rôle)*"),
            inline=False,
        )
        embed.add_field(
            name="Vérification Dofus",
            value=(
                f"Guilde : **{_setting(db.SETTING_DOFUS_GUILD_NAME, DOFUS_GUILD_NAME)}**\n"
                f"Serveur par défaut : **{_setting(db.SETTING_DOFUS_SERVER, DOFUS_SERVER)}**"
            ),
            inline=False,
        )
        embed.set_footer(
            text="Configure avec /setchannel, /setraidrole, /setraidnotifyrole, /setbaserole, /setmemberrole, /setunverifiedrole et /setdofusconfig"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
