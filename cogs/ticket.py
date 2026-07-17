"""Gestion des salons de ticket déjà ouverts.

Les boutons de ticket existants permettent encore de créer un raid depuis le
salon privé, d'ajouter des membres et de fermer le salon.
"""
from __future__ import annotations

import logging
from typing import Optional

import discord
from discord.ext import commands

import db
from config import RAID_NAMES
from utils import dates as dates_utils
from utils import names as names_utils
from utils.perms import can_manage_ticket, is_raid_organizer

logger = logging.getLogger("dofus-raid-bot.ticket")


class RaidCreateModal(discord.ui.Modal, title="🎯 Créer un raid"):
    raid_input = discord.ui.TextInput(
        label="Raid",
        placeholder=f"{ ' / '.join(RAID_NAMES)} (laisser vide = sondage)",
        required=False,
        max_length=50,
    )
    date_input = discord.ui.TextInput(
        label="Date / heure",
        placeholder="28/06, demain 19h30, 21h… (une heure fixe l'heure)",
        required=True,
        max_length=30,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message(
                "🔒 Tu dois avoir le rôle organisateur (ou être admin) pour créer un raid.",
                ephemeral=True,
            )
            return
        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog is None:
            await interaction.response.send_message("Module de raid indisponible.", ephemeral=True)
            return

        raid_raw = (self.raid_input.value or "").strip()
        if raid_raw:
            matched = names_utils.match_raid_name(raid_raw, RAID_NAMES)
            if matched is None:
                await interaction.response.send_message(
                    f"❌ Raid inconnu. Choix possibles : {', '.join(RAID_NAMES)}.",
                    ephemeral=True,
                )
                return
            raid_name: Optional[str] = matched
        else:
            raid_name = None

        channel = raid_cog._resolve_raids_channel(interaction.guild, interaction.channel)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("Aucun salon de raids configuré.", ephemeral=True)
            return

        date_value = self.date_input.value
        try:
            dates_utils.parse_raid_date(date_value)  # validation précoce
        except dates_utils.InvalidRaidDate as exc:
            await interaction.response.send_message(f"❌ Date invalide : {exc}", ephemeral=True)
            return

        # Heure fixée -> création directe ; sinon -> menu de choix des créneaux.
        if dates_utils.parse_time(date_value) is not None:
            try:
                raid_id = await raid_cog.create_raid(
                    interaction.guild, channel, interaction.user, raid_name, date_value
                )
            except dates_utils.InvalidRaidDate as exc:
                await interaction.response.send_message(f"❌ Date invalide : {exc}", ephemeral=True)
                return
            await interaction.response.send_message(
                f"✅ Raid **#{raid_id}** créé — sondage posté dans {channel.mention}.",
                ephemeral=False,
            )
            return

        await raid_cog._prompt_hour_choice(
            interaction, interaction.guild, channel, interaction.user,
            raid_name, date_value, None,
        )


class _CreateFromTicketButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(label="🎯 Créer ce raid", style=discord.ButtonStyle.primary, custom_id="bebraid:ticket_create")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RaidCreateModal(self.cog.bot))


class _CloseTicketButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="bebraid:ticket_close")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.close_ticket(interaction)


class _AddMemberButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(
            label="➕ Ajouter un membre",
            style=discord.ButtonStyle.secondary,
            custom_id="bebraid:ticket_add",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.prompt_add_member(interaction)


class _AddMemberSelect(discord.ui.UserSelect):
    def __init__(self, cog: "TicketCog"):
        super().__init__(
            placeholder="Sélectionne un ou plusieurs membres à ajouter",
            min_values=1,
            max_values=10,
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.add_members(interaction, self.values)


class AddMemberView(discord.ui.View):
    def __init__(self, cog: "TicketCog"):
        super().__init__(timeout=300)
        self.add_item(_AddMemberSelect(cog))


class TicketChannelView(discord.ui.View):
    def __init__(self, cog: "TicketCog"):
        super().__init__(timeout=None)
        self.add_item(_CreateFromTicketButton(cog))
        self.add_item(_AddMemberButton(cog))
        self.add_item(_CloseTicketButton(cog))


class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        # Vues persistantes (custom_id fixes) : routage sur tous les messages.
        self.bot.add_view(TicketChannelView(self))
        logger.info("TicketCog prêt")

    async def close_ticket(self, interaction: discord.Interaction) -> None:
        ticket = db.get_ticket_by_channel(interaction.channel_id)
        if not can_manage_ticket(interaction, ticket):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if ticket is not None:
            db.close_ticket(interaction.channel_id)
        await interaction.response.send_message("🔒 Ticket fermé. Suppression du salon...", ephemeral=False)
        try:
            await interaction.channel.delete(reason="Ticket raid fermé")
        except discord.DiscordException as exc:
            logger.warning("Suppression du ticket %s échouée: %s", interaction.channel_id, exc)

    def _is_ticket_manager(self, interaction: discord.Interaction) -> bool:
        """Organisateur (admin/rôle) ou opener du ticket : peut ajouter des membres / fermer."""
        ticket = db.get_ticket_by_channel(interaction.channel_id)
        return can_manage_ticket(interaction, ticket)

    async def prompt_add_member(self, interaction: discord.Interaction) -> None:
        if not self._is_ticket_manager(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        await interaction.response.send_message(
            "👤 Choisis les membres à ajouter au salon :", view=AddMemberView(self), ephemeral=True
        )

    async def add_members(self, interaction: discord.Interaction, users) -> None:
        guild = interaction.guild
        channel = interaction.channel
        if guild is None or not isinstance(channel, discord.abc.GuildChannel):
            return
        added: list[str] = []
        skipped: list[str] = []
        for user in users:
            member = guild.get_member(user.id)
            if member is None:
                try:
                    member = await guild.fetch_member(user.id)
                except discord.DiscordException:
                    member = None
            if member is None:
                skipped.append(f"`{user}`")
                continue
            try:
                await channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=True,
                    attach_files=True,
                    read_message_history=True,
                    reason=f"Ajouté au ticket par {interaction.user}",
                )
                added.append(member.mention)
            except discord.DiscordException as exc:
                logger.warning("Ajout membre %s au ticket %s échoué: %s", member, channel.id, exc)
                skipped.append(member.mention)

        parts: list[str] = []
        if added:
            parts.append(f"✅ Ajouté au salon : {', '.join(added)}")
        if skipped:
            parts.append(f"⚠️ Impossible à ajouter : {', '.join(skipped)}")
        if not parts:
            parts.append("Aucun membre à ajouter.")
        await interaction.response.send_message("\n".join(parts), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketCog(bot))
