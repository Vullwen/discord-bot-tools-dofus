"""Système de ticket : permet à un groupe d'organiser un raid en salon privé.

- /raid_panel (admin) poste un panneau avec un bouton « Ouvrir un ticket raid ».
- Le bouton crée un salon privé (opener + admins), avec deux actions :
  « 🎯 Créer ce raid » (modal) et « 🔒 Fermer ».
- La création de raid depuis le ticket réutilise RaidCog.create_raid().
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from config import ADMIN_IDS, RAID_NAMES, TICKET_CATEGORY_ID
from utils import dates as dates_utils
from utils.poll import parse_duration_seconds

logger = logging.getLogger("beb-raid.ticket")


def _channel_name(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", ascii_only.lower()).strip("-_") or "raid"
    return f"raid-{cleaned}"[:100]


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
    duree_input = discord.ui.TextInput(
        label="Durée du sondage",
        placeholder="5mn, 15min, 1h, 2h30… (mini 5min)",
        required=True,
        max_length=20,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog is None:
            await interaction.response.send_message("Module de raid indisponible.", ephemeral=True)
            return

        raid_raw = (self.raid_input.value or "").strip()
        if raid_raw:
            matched = next((n for n in RAID_NAMES if n.lower() == raid_raw.lower()), None)
            if matched is None:
                await interaction.response.send_message(
                    f"❌ Raid inconnu. Choix possibles : {', '.join(RAID_NAMES)}.",
                    ephemeral=True,
                )
                return
            raid_name: Optional[str] = matched
        else:
            raid_name = None

        duree_seconds = parse_duration_seconds(self.duree_input.value)
        channel = raid_cog._resolve_raids_channel(interaction.guild, interaction.channel)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("Aucun salon de raids configuré.", ephemeral=True)
            return

        try:
            raid_id = await raid_cog.create_raid(
                interaction.guild, channel, interaction.user, raid_name, self.date_input.value, duree_seconds
            )
        except dates_utils.InvalidRaidDate as exc:
            await interaction.response.send_message(f"❌ Date invalide : {exc}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ Raid **#{raid_id}** créé — sondage posté dans {channel.mention}.",
            ephemeral=False,
        )


class _OpenTicketButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(label="🎟️ Ouvrir un ticket raid", style=discord.ButtonStyle.success, custom_id="bebraid:ticket_open")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.open_ticket(interaction)


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


class TicketPanelView(discord.ui.View):
    def __init__(self, cog: "TicketCog"):
        super().__init__(timeout=None)
        self.add_item(_OpenTicketButton(cog))


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
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(TicketChannelView(self))
        logger.info("TicketCog prêt")

    @app_commands.command(name="raid_panel", description="Poste le panneau de ticket pour organiser un raid (admin)")
    async def raid_panel(self, interaction: discord.Interaction) -> None:
        if interaction.user.id not in ADMIN_IDS:
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🎟️ Organiser un raid en groupe",
            description=(
                "Clique sur **Ouvrir un ticket raid** pour créer un salon privé.\n"
                "Tu pourras y discuter de l'orga et lancer la création du raid "
                "(le sondage sera posté dans le salon des raids)."
            ),
            color=0x2ECC71,
        )
        await interaction.channel.send(embed=embed, view=TicketPanelView(self))
        await interaction.response.send_message("Panneau de ticket posté.", ephemeral=True)

    def _resolve_ticket_category(self, guild: discord.Guild):
        # 1) réglage /setchannel (DB) ; 2) variable d'env ; 3) None.
        cid = db.get_guild_setting_int(guild.id, db.SETTING_TICKET_CATEGORY)
        if cid:
            cat = guild.get_channel(cid)
            if isinstance(cat, discord.CategoryChannel):
                return cat
        if TICKET_CATEGORY_ID:
            cat = guild.get_channel(TICKET_CATEGORY_ID)
            if isinstance(cat, discord.CategoryChannel):
                return cat
        return None

    async def open_ticket(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        opener = interaction.user
        if guild is None:
            await interaction.response.send_message("Commande à utiliser dans un serveur.", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, read_message_history=True
            ),
            opener: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True, read_message_history=True
            ),
        }
        for admin_id in ADMIN_IDS:
            member = guild.get_member(admin_id)
            if member is None:
                try:
                    member = await guild.fetch_member(admin_id)
                except discord.DiscordException:
                    member = None
            if member is not None:
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )

        category = self._resolve_ticket_category(guild)

        # Nom unique : raid-pseudo, raid-pseudo-2, raid-pseudo-3…
        base = _channel_name(opener.display_name)
        existing = {c.name for c in guild.text_channels}
        name = base
        suffix = 2
        while name in existing:
            name = f"{base}-{suffix}"
            suffix += 1

        try:
            channel = await guild.create_text_channel(
                name,
                category=category,
                overwrites=overwrites,
                reason=f"Ticket raid ouvert par {opener}",
            )
        except discord.DiscordException as exc:
            await interaction.response.send_message(f"Impossible de créer le ticket : {exc}", ephemeral=True)
            return

        db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=opener.id)

        embed = discord.Embed(
            title="🎟️ Ticket raid",
            description=(
                f"Bienvenue {opener.mention} !\n\n"
                "Discutez de l'organisation ici, puis cliquez sur **🎯 Créer ce raid** "
                "pour lancer le sondage (posté dans le salon des raids).\n"
                "Besoin d'amis dans le salon ? **➕ Ajouter un membre**.\n\n"
                "Quand c'est fini, cliquez sur **🔒 Fermer**."
            ),
            color=0xF1C40F,
        )
        await channel.send(embed=embed, view=TicketChannelView(self))
        await interaction.response.send_message(f"Ticket créé : {channel.mention}", ephemeral=True)

    async def close_ticket(self, interaction: discord.Interaction) -> None:
        ticket = db.get_ticket_by_channel(interaction.channel_id)
        is_opener = ticket is not None and interaction.user.id == ticket["opener_id"]
        if not is_opener and interaction.user.id not in ADMIN_IDS:
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
        """Opener du ticket ou admin : peut ajouter des membres / fermer."""
        ticket = db.get_ticket_by_channel(interaction.channel_id)
        is_opener = ticket is not None and interaction.user.id == ticket["opener_id"]
        return is_opener or interaction.user.id in ADMIN_IDS

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
