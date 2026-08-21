from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from typing import Iterable, Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from utils.perms import is_raid_organizer

logger = logging.getLogger("dofus-raid-bot.deathnote")

MIN_PSEUDO_LENGTH = 2


def normalize_pseudo(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value.strip())
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", ascii_only).casefold()


def _matches_entry(entry, texts: Iterable[Optional[str]]) -> bool:
    needle = entry["normalized_pseudo"]
    return any(needle in normalize_pseudo(text) for text in texts if text)


def _message_texts(message: discord.Message) -> list[Optional[str]]:
    author = getattr(message, "author", None)
    return [
        getattr(message, "content", None),
        getattr(author, "display_name", None),
        getattr(author, "global_name", None),
        getattr(author, "name", None),
    ]


def _member_texts(member: discord.Member) -> list[Optional[str]]:
    return [
        getattr(member, "display_name", None),
        getattr(member, "global_name", None),
        getattr(member, "name", None),
    ]


def _format_entry_line(row) -> str:
    created_at = datetime.fromisoformat(row["created_at"])
    reason = row["reason"].strip().rstrip(".")
    return (
        f"- **{row['pseudo']}** : {reason} "
        f"(par <@{row['created_by']}>, le {created_at:%d/%m/%Y %Hh%M})"
    )


class DeathnoteCog(commands.Cog):
    deathnote = app_commands.Group(
        name="deathnote",
        description="Gestion de la blacklist de pseudos",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _get_channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await self.bot.fetch_channel(channel_id)
        except discord.DiscordException:
            return None

    async def _notify_admins(
        self,
        *,
        guild_id: int,
        title: str,
        entry,
        member: Optional[discord.abc.User] = None,
        message: Optional[discord.Message] = None,
    ) -> None:
        channel_id = db.get_guild_setting_int(guild_id, db.SETTING_RAID_ADMIN_CHANNEL)
        if not channel_id:
            logger.warning("Deathnote match sans salon admin configuré sur guilde %s", guild_id)
            return
        channel = await self._get_channel(channel_id)
        if channel is None or not hasattr(channel, "send"):
            logger.warning("Salon admin deathnote introuvable pour guilde %s: %s", guild_id, channel_id)
            return

        reason = entry["reason"].strip().rstrip(".")
        lines = [
            f"📝 **{title}**",
            f"Pseudo blacklisté : **{entry['pseudo']}**",
            f"Raison : {reason}",
        ]
        if member is not None:
            lines.append(f"Membre Discord : {member.mention} (`{member.id}`)")
            display_name = getattr(member, "display_name", None)
            if display_name:
                lines.append(f"Nom affiché : `{display_name}`")
        if message is not None:
            lines.append(f"Salon : {message.channel.mention}")
            jump_url = getattr(message, "jump_url", None)
            if jump_url:
                lines.append(f"Message : {jump_url}")
            if message.content:
                preview = message.content.replace("\n", " ")[:300]
                lines.append(f"Contenu : `{preview}`")

        try:
            await channel.send(content="\n".join(lines))
        except discord.DiscordException as exc:
            logger.warning("Notification deathnote échouée pour %s: %s", entry["pseudo"], exc)

    def _matching_entries(self, guild_id: int, texts: Iterable[Optional[str]]):
        entries = db.list_deathnote_entries(guild_id=guild_id, limit=500)
        return [entry for entry in entries if _matches_entry(entry, texts)]

    async def _add_blacklist_entry(
        self,
        interaction: discord.Interaction,
        pseudo: str,
        raison: str,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        clean_pseudo = pseudo.strip()
        normalized = normalize_pseudo(clean_pseudo)
        if len(normalized) < MIN_PSEUDO_LENGTH:
            await interaction.response.send_message("Le pseudo doit faire au moins 2 caractères.", ephemeral=True)
            return
        reason = raison.strip()
        if not reason:
            await interaction.response.send_message("La raison ne peut pas être vide.", ephemeral=True)
            return

        db.upsert_deathnote_entry(
            guild_id=interaction.guild.id,
            pseudo=clean_pseudo,
            normalized_pseudo=normalized,
            reason=reason,
            created_by=interaction.user.id,
        )
        await interaction.response.send_message(
            f"✅ **{clean_pseudo}** ajouté à la deathnote.",
            ephemeral=True,
        )

    @deathnote.command(name="add", description="Ajoute ou met à jour un pseudo blacklisté")
    @app_commands.describe(
        pseudo="Pseudo à surveiller",
        raison="Raison de la blacklist",
    )
    async def add_entry(
        self,
        interaction: discord.Interaction,
        pseudo: str,
        raison: str,
    ) -> None:
        await self._add_blacklist_entry(interaction, pseudo, raison)

    @deathnote.command(name="list", description="Liste les pseudos blacklistés")
    async def list_entries(self, interaction: discord.Interaction) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        rows = db.list_deathnote_entries(guild_id=interaction.guild.id)
        if not rows:
            await interaction.response.send_message("Aucun pseudo dans la deathnote.", ephemeral=True)
            return

        await interaction.response.send_message(
            "\n".join(["**Deathnote**", *[_format_entry_line(row) for row in rows]]),
            ephemeral=True,
        )

    @deathnote.command(name="remove", description="Retire un pseudo de la deathnote")
    @app_commands.describe(pseudo="Pseudo à retirer")
    async def remove_entry(self, interaction: discord.Interaction, pseudo: str) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        clean_pseudo = pseudo.strip()
        removed = db.delete_deathnote_entry(
            guild_id=interaction.guild.id,
            normalized_pseudo=normalize_pseudo(clean_pseudo),
        )
        if removed:
            await interaction.response.send_message(
                f"✅ **{clean_pseudo}** retiré de la deathnote.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"**{clean_pseudo}** n'était pas dans la deathnote.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = getattr(member, "guild", None)
        if guild is None:
            return
        for entry in self._matching_entries(guild.id, _member_texts(member)):
            await self._notify_admins(
                guild_id=guild.id,
                title="Membre blacklisté détecté à l'arrivée",
                entry=entry,
                member=member,
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if getattr(getattr(message, "author", None), "bot", False):
            return
        guild = getattr(message, "guild", None)
        if guild is None:
            return

        for entry in self._matching_entries(guild.id, _message_texts(message)):
            await self._notify_admins(
                guild_id=guild.id,
                title="Pseudo blacklisté détecté dans un message",
                entry=entry,
                member=message.author,
                message=message,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DeathnoteCog(bot))
