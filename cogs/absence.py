"""Déclarations d'absence via bouton + formulaire."""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from utils import dates as dates_utils
from utils.perms import is_raid_organizer

logger = logging.getLogger("beb-raid.absence")


def _user_display(user: discord.abc.User) -> str:
    return getattr(user, "display_name", None) or user.name


def _format_absence_period(start: date, end: date) -> str:
    if start == end:
        return f"Le {dates_utils.format_date_fr(start)}"
    return f"Du {dates_utils.format_date_fr(start)} au {dates_utils.format_date_fr(end)}"


def _channel_label(channel: discord.abc.Messageable) -> str:
    return getattr(channel, "mention", None) or f"`{getattr(channel, 'id', 'salon')}`"


def _absence_embed(user: discord.abc.User, start: date, end: date) -> discord.Embed:
    embed = discord.Embed(title="Absence", color=0xF1C40F)
    embed.add_field(name="Pseudo", value=_user_display(user), inline=False)
    embed.add_field(name="Dates", value=_format_absence_period(start, end), inline=False)
    return embed


def _absence_admin_embed(
    user: discord.abc.User,
    start: date,
    end: date,
    motif: str,
) -> discord.Embed:
    embed = discord.Embed(title="Motif d'absence", color=0xE67E22)
    embed.add_field(name="Pseudo", value=f"{_user_display(user)} (`{user.id}`)", inline=False)
    embed.add_field(name="Dates", value=_format_absence_period(start, end), inline=False)
    embed.add_field(name="Motif", value=motif or "Non renseigné", inline=False)
    return embed


class AbsenceModal(discord.ui.Modal, title="Déclarer une absence"):
    start_input = discord.ui.TextInput(
        label="Date de début",
        placeholder="10/07, demain, vendredi...",
        required=True,
        max_length=30,
    )
    end_input = discord.ui.TextInput(
        label="Date de fin",
        placeholder="15/07, dimanche...",
        required=True,
        max_length=30,
    )
    reason_input = discord.ui.TextInput(
        label="Motif",
        placeholder="Optionnel",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, cog: "AbsenceCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.submit_absence(
            interaction,
            str(self.start_input.value),
            str(self.end_input.value),
            str(self.reason_input.value or ""),
        )


class _OpenAbsenceButton(discord.ui.Button):
    def __init__(self, cog: "AbsenceCog"):
        super().__init__(
            label="Déclarer une absence",
            style=discord.ButtonStyle.primary,
            custom_id="bebraid:absence_open",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AbsenceModal(self.cog))


class AbsenceView(discord.ui.View):
    def __init__(self, cog: "AbsenceCog"):
        super().__init__(timeout=None)
        self.add_item(_OpenAbsenceButton(cog))


class AbsenceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(AbsenceView(self))
        logger.info("AbsenceCog prêt")

    async def _configured_channel(
        self,
        guild: discord.Guild,
        key: str,
    ) -> Optional[discord.abc.Messageable]:
        channel_id = db.get_guild_setting_int(guild.id, key)
        if not channel_id:
            return None
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.DiscordException as exc:
                logger.warning("Salon %s introuvable pour %s: %s", channel_id, key, exc)
                return None
        return channel if isinstance(channel, discord.abc.Messageable) else None

    async def _absence_channel(
        self,
        interaction: discord.Interaction,
    ) -> Optional[discord.abc.Messageable]:
        if interaction.guild is None:
            return None
        return await self._configured_channel(interaction.guild, db.SETTING_ABSENCE_CHANNEL)

    async def submit_absence(
        self,
        interaction: discord.Interaction,
        start_raw: str,
        end_raw: str,
        motif: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        try:
            start = dates_utils.parse_raid_date(start_raw)
            end = dates_utils.parse_raid_date(end_raw)
        except dates_utils.InvalidRaidDate as exc:
            await interaction.response.send_message(f"Date invalide : {exc}", ephemeral=True)
            return

        if end < start:
            await interaction.response.send_message(
                "Date invalide : la date de fin doit être après la date de début.",
                ephemeral=True,
            )
            return

        public_channel = await self._absence_channel(interaction)
        if public_channel is None:
            await interaction.response.send_message("Aucun salon absence disponible.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            await public_channel.send(embed=_absence_embed(interaction.user, start, end))
        except discord.DiscordException as exc:
            logger.warning("Publication absence échouée: %s", exc)
            await interaction.followup.send("Impossible de publier l'absence.", ephemeral=True)
            return

        admin_warning = ""
        admin_channel = await self._configured_channel(interaction.guild, db.SETTING_ABSENCE_ADMIN_CHANNEL)
        if admin_channel is not None:
            try:
                await admin_channel.send(embed=_absence_admin_embed(interaction.user, start, end, motif.strip()))
            except discord.DiscordException as exc:
                logger.warning("Publication motif absence échouée: %s", exc)
                admin_warning = " Motif non envoyé : erreur sur le salon admin."
        elif motif.strip():
            admin_warning = " Motif non envoyé : salon admin non configuré."

        await interaction.followup.send(
            f"Absence publiée dans {_channel_label(public_channel)}.{admin_warning}",
            ephemeral=True,
        )

    @app_commands.command(name="absence_panel", description="Poste le bouton de déclaration d'absence")
    async def absence_panel(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        target = await self._configured_channel(interaction.guild, db.SETTING_ABSENCE_CHANNEL)
        if target is None:
            await interaction.response.send_message(
                "Configure d'abord le salon absence avec `/setchannel`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        embed = discord.Embed(
            title="Absences",
            description="Clique sur le bouton pour déclarer une absence.",
            color=0xF1C40F,
        )
        try:
            await target.send(embed=embed, view=AbsenceView(self))
        except discord.DiscordException as exc:
            logger.warning("Publication bouton absence échouée: %s", exc)
            await interaction.followup.send("Impossible de poster le bouton absence.", ephemeral=True)
            return
        await interaction.followup.send(f"Bouton absence posté dans {_channel_label(target)}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AbsenceCog(bot))
