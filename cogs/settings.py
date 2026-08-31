"""Configuration Discord du bot.

- /config channel : configure les salons et forums utilisés par le bot.
- /config role : configure les roles utilises par le bot.
- /config guild : configure le nom de guilde Dofus attendu.
- /config dofus : configure la verification Dofus.
- /config show : affiche la configuration courante de la guilde.
"""
from __future__ import annotations

import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from config import DOFUS_GUILD_NAME, DOFUS_SERVER
from utils.perms import is_bot_admin, is_raid_organizer

_CHANNEL_LABEL = {
    db.SETTING_RAIDS_CHANNEL: "Salon des raids",
    db.SETTING_RAID_ADMIN_CHANNEL: "Salon admin raids",
    db.SETTING_ABSENCE_PANEL_CHANNEL: "Salon panel absences",
    db.SETTING_ABSENCE_CHANNEL: "Salon absence",
    db.SETTING_ABSENCE_ADMIN_CHANNEL: "Salon admin absences",
    db.SETTING_MARKET_FORUM_CHANNEL: "Forum marché",
    db.SETTING_METAMOB_TALK_CHANNEL: "Salon Metamob",
    db.SETTING_METAMOB_FORUM_CHANNEL: "Forum Metamob",
    db.SETTING_EVENT_REGISTRATION_CHANNEL: "Salon inscriptions event",
    db.SETTING_EVENT_ADMIN_CHANNEL: "Salon admin event",
    db.SETTING_EVENT_CHANNEL: "Salon event",
}

_ROLE_LABEL = {
    db.SETTING_BOT_ADMIN_ROLE: "Rôle admin bot",
    db.SETTING_RAID_MANAGER_ROLE: "Rôle organisateur",
    db.SETTING_RAID_NOTIFY_ROLE: "Rôle notif raids",
    db.SETTING_BASE_ROLE: "Rôle de base",
    db.SETTING_VERIFIED_MEMBER_ROLE: "Rôle membre vérifié",
    db.SETTING_UNVERIFIED_MEMBER_ROLE: "Rôle à vérifier",
    db.SETTING_GUILD_MEMBER_ROLE: "Rôle membre guilde",
    db.SETTING_VISITOR_ROLE: "Rôle visiteur marché",
}

_ROLE_RESET_MESSAGE = {
    db.SETTING_BOT_ADMIN_ROLE: (
        "✅ Rôle admin bot retiré. Les admins restent ceux de `ADMIN_IDS`, le propriétaire "
        "du serveur et les membres avec la permission Administrateur."
    ),
    db.SETTING_RAID_MANAGER_ROLE: (
        "✅ Rôle organisateur retiré. Les membres avec la permission Administrateur peuvent "
        "créer/gérer les raids."
    ),
    db.SETTING_RAID_NOTIFY_ROLE: "✅ Mention de raid désactivée (aucun rôle ne sera mentionné).",
    db.SETTING_BASE_ROLE: "✅ Rôle de base désactivé. `/absence kick` ne modifiera plus les rôles.",
    db.SETTING_VERIFIED_MEMBER_ROLE: (
        "✅ Rôle membre vérifié désactivé. La vérification validera les persos sans donner de rôle."
    ),
    db.SETTING_UNVERIFIED_MEMBER_ROLE: (
        "✅ Rôle à vérifier désactivé. La vérification ne retirera aucun rôle automatiquement."
    ),
    db.SETTING_GUILD_MEMBER_ROLE: (
        "✅ Rôle membre guilde désactivé. L'acceptation d'un ticket d'accueil utilisera "
        "`verified_member` si configuré, sinon aucun rôle."
    ),
    db.SETTING_VISITOR_ROLE: "✅ Rôle visiteur marché désactivé.",
}

_ROLE_SET_DETAIL = {
    db.SETTING_BOT_ADMIN_ROLE: "Ses détenteurs peuvent gérer la configuration admin du bot.",
    db.SETTING_RAID_MANAGER_ROLE: "Ses détenteurs peuvent créer/gérer les raids.",
    db.SETTING_RAID_NOTIFY_ROLE: "Il sera mentionné à l'annonce de chaque nouveau raid.",
    db.SETTING_BASE_ROLE: "`/absence kick` retirera les autres rôles et remettra celui-ci.",
    db.SETTING_VERIFIED_MEMBER_ROLE: "Il sera donné après vérification validée.",
    db.SETTING_UNVERIFIED_MEMBER_ROLE: "Il sera retiré après vérification validée.",
    db.SETTING_GUILD_MEMBER_ROLE: "Il sera donné quand un candidat guilde est accepté.",
    db.SETTING_VISITOR_ROLE: "Il sera donné aux visiteurs qui demandent l'accès au marché.",
}

_CHANNEL_CHOICES = [
    app_commands.Choice(name="raids", value=db.SETTING_RAIDS_CHANNEL),
    app_commands.Choice(name="raid_admin", value=db.SETTING_RAID_ADMIN_CHANNEL),
    app_commands.Choice(name="absence_panel", value=db.SETTING_ABSENCE_PANEL_CHANNEL),
    app_commands.Choice(name="absence", value=db.SETTING_ABSENCE_CHANNEL),
    app_commands.Choice(name="absence_admin", value=db.SETTING_ABSENCE_ADMIN_CHANNEL),
    app_commands.Choice(name="market_forum", value=db.SETTING_MARKET_FORUM_CHANNEL),
    app_commands.Choice(name="metamob-talk", value=db.SETTING_METAMOB_TALK_CHANNEL),
    app_commands.Choice(name="metamob-forum", value=db.SETTING_METAMOB_FORUM_CHANNEL),
    app_commands.Choice(name="event-inscription", value=db.SETTING_EVENT_REGISTRATION_CHANNEL),
    app_commands.Choice(name="event-admin", value=db.SETTING_EVENT_ADMIN_CHANNEL),
    app_commands.Choice(name="event", value=db.SETTING_EVENT_CHANNEL),
]

_ROLE_CHOICES = [
    app_commands.Choice(name="bot_admin", value=db.SETTING_BOT_ADMIN_ROLE),
    app_commands.Choice(name="raid_manager", value=db.SETTING_RAID_MANAGER_ROLE),
    app_commands.Choice(name="raid_notify", value=db.SETTING_RAID_NOTIFY_ROLE),
    app_commands.Choice(name="base", value=db.SETTING_BASE_ROLE),
    app_commands.Choice(name="verified_member", value=db.SETTING_VERIFIED_MEMBER_ROLE),
    app_commands.Choice(name="unverified_member", value=db.SETTING_UNVERIFIED_MEMBER_ROLE),
    app_commands.Choice(name="guild_member", value=db.SETTING_GUILD_MEMBER_ROLE),
    app_commands.Choice(name="visitor", value=db.SETTING_VISITOR_ROLE),
]


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


def _can_set_role(interaction: discord.Interaction, key: str) -> bool:
    if key == db.SETTING_BOT_ADMIN_ROLE:
        return is_bot_admin(interaction)
    return is_raid_organizer(interaction)


class SettingsCog(commands.Cog):
    config = app_commands.Group(name="config", description="Configuration du bot")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @config.command(name="channel", description="Définit un salon du bot")
    @app_commands.describe(
        usage="Ce que tu veux configurer",
        channel="Le salon ou forum à utiliser",
    )
    @app_commands.choices(usage=_CHANNEL_CHOICES)
    async def config_channel(
        self,
        interaction: discord.Interaction,
        usage: app_commands.Choice[str],
        channel: discord.abc.GuildChannel,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        db.set_guild_setting(interaction.guild.id, usage.value, str(channel.id))
        label = _CHANNEL_LABEL.get(usage.value, usage.value)
        await interaction.response.send_message(
            f"✅ {label} défini sur {channel.mention}.",
            ephemeral=True,
        )

    @config.command(name="role", description="Définit un rôle du bot")
    @app_commands.describe(
        usage="Ce que tu veux configurer",
        role="Rôle à utiliser (vide = désactive/reset ce rôle configuré)",
    )
    @app_commands.choices(usage=_ROLE_CHOICES)
    async def config_role(
        self,
        interaction: discord.Interaction,
        usage: app_commands.Choice[str],
        role: Optional[discord.Role] = None,
    ) -> None:
        if not _can_set_role(interaction, usage.value):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        if role is None:
            db.set_guild_setting(interaction.guild.id, usage.value, "")
            await interaction.response.send_message(
                _ROLE_RESET_MESSAGE.get(usage.value, "✅ Rôle désactivé."),
                ephemeral=True,
            )
            return

        db.set_guild_setting(interaction.guild.id, usage.value, str(role.id))
        label = _ROLE_LABEL.get(usage.value, "Rôle")
        detail = _ROLE_SET_DETAIL.get(usage.value, "")
        await interaction.response.send_message(
            f"✅ {label} défini : {role.mention}. {detail}".strip(),
            ephemeral=True,
        )

    @config.command(name="dofus", description="Définit la guilde et le serveur attendus pour la vérification")
    @app_commands.describe(
        guilde="Nom exact de la guilde Dofus dans /whoami",
        serveur="Serveur Dofus par défaut (optionnel)",
    )
    async def config_dofus(
        self,
        interaction: discord.Interaction,
        guilde: str,
        serveur: Optional[str] = None,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        guild_name = guilde.strip()
        server_name = serveur.strip() if serveur is not None else None
        if not guild_name:
            await interaction.response.send_message("Le nom de guilde ne peut pas être vide.", ephemeral=True)
            return
        if serveur is not None and not server_name:
            await interaction.response.send_message("Le serveur ne peut pas être vide.", ephemeral=True)
            return

        db.set_guild_setting(interaction.guild.id, db.SETTING_DOFUS_GUILD_NAME, guild_name)
        if server_name is not None:
            db.set_guild_setting(interaction.guild.id, db.SETTING_DOFUS_SERVER, server_name)

        server_label = server_name or db.get_guild_setting(interaction.guild.id, db.SETTING_DOFUS_SERVER) or DOFUS_SERVER
        await interaction.response.send_message(
            f"✅ Vérification Dofus configurée : guilde **{guild_name}**, serveur **{server_label}**.",
            ephemeral=True,
        )

    @config.command(name="guild", description="Définit le nom de guilde Dofus attendu")
    @app_commands.describe(nom="Nom exact de la guilde Dofus dans /whoami")
    async def config_guild(
        self,
        interaction: discord.Interaction,
        nom: str,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        guild_name = nom.strip()
        if not guild_name:
            await interaction.response.send_message("Le nom de guilde ne peut pas être vide.", ephemeral=True)
            return

        db.set_guild_setting(interaction.guild.id, db.SETTING_DOFUS_GUILD_NAME, guild_name)
        await interaction.response.send_message(
            f"✅ Guilde Dofus configurée : **{guild_name}**.",
            ephemeral=True,
        )

    @config.command(name="show", description="Affiche la configuration des raids de ce serveur")
    async def config_show(self, interaction: discord.Interaction) -> None:
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
        embed.add_field(name="Forum marché", value=_mention(db.SETTING_MARKET_FORUM_CHANNEL), inline=False)
        embed.add_field(name="Salon Metamob", value=_mention(db.SETTING_METAMOB_TALK_CHANNEL), inline=False)
        embed.add_field(name="Forum Metamob", value=_mention(db.SETTING_METAMOB_FORUM_CHANNEL), inline=False)
        embed.add_field(
            name="Salon inscriptions event",
            value=_mention(db.SETTING_EVENT_REGISTRATION_CHANNEL),
            inline=False,
        )
        embed.add_field(name="Salon admin event", value=_mention(db.SETTING_EVENT_ADMIN_CHANNEL), inline=False)
        embed.add_field(name="Salon event", value=_mention(db.SETTING_EVENT_CHANNEL), inline=False)
        embed.add_field(
            name="Rôle admin bot",
            value=_role_mention(db.SETTING_BOT_ADMIN_ROLE, "*(non défini — ADMIN_IDS/propriétaire/Administrateur)*"),
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
            name="Rôle membre guilde",
            value=_role_mention(db.SETTING_GUILD_MEMBER_ROLE, "*(non défini — repli sur verified_member)*"),
            inline=False,
        )
        embed.add_field(
            name="Rôle visiteur marché",
            value=_role_mention(db.SETTING_VISITOR_ROLE, "*(non défini — aucun rôle visiteur automatique)*"),
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
        embed.set_footer(text="Configure avec /config channel, /config role, /config guild et /config dofus")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
