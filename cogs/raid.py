"""Cog principal : création de raid, sondages à boutons, planification, rappel MP.

Mécanisme :
- Boutons personnalisés (custom_id encodant raid_id + choix) pour les sondages.
- Planification par asyncio one-shot + reschedule au démarrage depuis SQLite
  (robuste aux redémarrages).
"""
from __future__ import annotations

import asyncio
import logging
import unicodedata
from datetime import date, datetime, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from config import (
    ADMIN_IDS,
    PARIS,
    RAID_DEFAULT_HOUR,
    RAID_HOURS,
    RAID_NAMES,
    RAIDS_CHANNEL_ID,
    REMINDER_MINUTES,
    now_paris,
)
from utils import embeds
from utils import dates as dates_utils
from utils.poll import (
    STATE_CANCELLED,
    STATE_CHOOSING_RAID,
    STATE_DONE,
    STATE_REMINDED,
    STATE_SCHEDULED,
    STATE_VOTING_HOUR,
    tally,
)

logger = logging.getLogger("beb-raid.raid")

def _slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_only.lower().replace(" ", "_").replace("'", "")


DUREE_SECONDS = {"1h": 3600, "12h": 43200, "24h": 86400}
_HOUR_ORDER = [str(h) for h in RAID_HOURS]
_RAID_SLUGS = {name: _slugify(name) for name in RAID_NAMES}


# --------------------------------------------------------------------------- views


class _HourVoteButton(discord.ui.Button):
    def __init__(self, cog: "RaidCog", raid_id: int, hour: int):
        super().__init__(
            label=f"{hour}h",
            style=discord.ButtonStyle.secondary,
            custom_id=f"bebraid:hour:{raid_id}:{hour}",
        )
        self.cog = cog
        self.raid_id = raid_id
        self.hour = hour

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_hour_vote(interaction, self.raid_id, self.hour)


class _RaidChoiceButton(discord.ui.Button):
    def __init__(self, cog: "RaidCog", raid_id: int, name: str):
        super().__init__(
            label=name,
            style=discord.ButtonStyle.primary,
            custom_id=f"bebraid:raid:{raid_id}:{_RAID_SLUGS[name]}",
        )
        self.cog = cog
        self.raid_id = raid_id
        self.name = name

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_raid_vote(interaction, self.raid_id, self.name)


class _RegisterButton(discord.ui.Button):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(
            label="Je participe 📌",
            style=discord.ButtonStyle.success,
            custom_id=f"bebraid:reg:{raid_id}",
        )
        self.cog = cog
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_register(interaction, self.raid_id)


class HourPollView(discord.ui.View):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(timeout=None)
        for hour in RAID_HOURS:
            self.add_item(_HourVoteButton(cog, raid_id, hour))


class RaidChoiceView(discord.ui.View):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(timeout=None)
        for name in RAID_NAMES:
            self.add_item(_RaidChoiceButton(cog, raid_id, name))


class ScheduledRaidView(discord.ui.View):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(timeout=None)
        self.add_item(_RegisterButton(cog, raid_id))


# --------------------------------------------------------------------------- cog


class RaidCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (raid_id, kind) -> asyncio.Task ; kind ∈ raid_close|hour_close|remind|done
        self._tasks: dict[tuple[int, str], asyncio.Task] = {}
        self._bootstrap_task: Optional[asyncio.Task] = None

    async def cog_load(self) -> None:
        # Lancé avant bot.start() : on ne doit pas bloquer sur wait_until_ready ici.
        db.init()
        self._bootstrap_task = asyncio.create_task(self._bootstrap())

    async def _bootstrap(self) -> None:
        try:
            await self.bot.wait_until_ready()
            await self._reschedule_all()
            logger.info("RaidCog prêt, %d raid(s) actif(s) rechargé(s)", len(db.list_active_raids()))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Échec du bootstrap RaidCog")

    async def cog_unload(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        if self._bootstrap_task is not None:
            self._bootstrap_task.cancel()

    # --------------------------------------------------------------- helpers

    def _resolve_raids_channel(self, guild: discord.Guild, fallback) -> Optional[discord.abc.GuildChannel]:
        if RAIDS_CHANNEL_ID:
            ch = guild.get_channel(RAIDS_CHANNEL_ID)
            if ch is not None:
                return ch
        return fallback

    async def _creator_display(self, user_id: int) -> str:
        user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except discord.DiscordException:
                return f"<@{user_id}>"
        return getattr(user, "display_name", f"<@{user_id}>")

    async def _get_channel(self, channel_id: int):
        ch = self.bot.get_channel(channel_id)
        if ch is None:
            try:
                ch = await self.bot.fetch_channel(channel_id)
            except discord.DiscordException:
                return None
        return ch

    async def _edit_message(self, channel_id: int, message_id: int, *, embed=None, view=None) -> None:
        ch = await self._get_channel(channel_id)
        if ch is None:
            return
        try:
            msg = await ch.fetch_message(message_id)
            await msg.edit(embed=embed, view=view)
        except discord.DiscordException as exc:
            logger.warning("edit_message %s/%s échoué: %s", channel_id, message_id, exc)

    # --------------------------------------------------------------- création

    async def create_raid(
        self,
        guild: discord.Guild,
        channel,
        user: discord.abc.User,
        raid_name: Optional[str],
        date_text: str,
        duree_key: str,
        note: Optional[str] = None,
    ) -> int:
        """Crée un raid (cœur métier partagé par /raid et le ticket). Lève InvalidRaidDate."""
        raid_date = dates_utils.parse_raid_date(date_text)
        duration = timedelta(seconds=DUREE_SECONDS[duree_key])
        now = now_paris()

        if raid_name:
            state = STATE_VOTING_HOUR
            raid_closes = None
            hour_closes = now + duration
        else:
            state = STATE_CHOOSING_RAID
            raid_closes = now + duration
            hour_closes = None

        raid_id = db.create_raid(
            name=raid_name,
            date_iso=raid_date.isoformat(),
            poll_duration_seconds=int(duration.total_seconds()),
            created_by=user.id,
            guild_id=guild.id,
            channel_id=channel.id,
            state=state,
            raid_poll_closes_at=raid_closes,
            hour_poll_closes_at=hour_closes,
            note=note,
        )
        logger.info("Raid #%d créé par %s (state=%s)", raid_id, user, state)

        if state == STATE_VOTING_HOUR:
            await self._send_hour_poll(channel, raid_id)
            self._schedule(raid_id, "hour_close", hour_closes, self._close_hour_poll)
        else:
            await self._send_raid_choice(channel, raid_id)
            self._schedule(raid_id, "raid_close", raid_closes, self._close_raid_choice)

        return raid_id

    async def _send_raid_choice(self, channel, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        counts = db.get_vote_counts(raid_id, "raid")
        creator = await self._creator_display(raid["created_by"])
        embed = embeds.raid_choice_embed(raid, counts, creator)
        view = RaidChoiceView(self, raid_id)
        msg = await channel.send(embed=embed, view=view)
        db.update_raid(raid_id, raid_poll_message_id=msg.id)

    async def _send_hour_poll(self, channel, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        counts = db.get_vote_counts(raid_id, "hour")
        creator = await self._creator_display(raid["created_by"])
        embed = embeds.hour_poll_embed(raid, counts, creator)
        view = HourPollView(self, raid_id)
        msg = await channel.send(embed=embed, view=view)
        db.update_raid(raid_id, hour_poll_message_id=msg.id)

    async def _post_scheduled(self, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        creator = await self._creator_display(raid["created_by"])
        participants = db.count_participants(raid_id)
        embed = embeds.scheduled_embed(raid, participants, creator)
        view = ScheduledRaidView(self, raid_id)
        channel = await self._get_channel(raid["channel_id"])
        if channel is None:
            logger.warning("Salon introuvable pour le raid #%d", raid_id)
            return
        msg = await channel.send(embed=embed, view=view)
        db.update_raid(raid_id, scheduled_message_id=msg.id)

    # --------------------------------------------------------------- votes

    async def handle_raid_vote(self, interaction: discord.Interaction, raid_id: int, name: str) -> None:
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] != STATE_CHOOSING_RAID:
            await interaction.response.send_message("Ce sondage est terminé.", ephemeral=True)
            return
        db.cast_vote(raid_id, interaction.user.id, "raid", name)
        counts = db.get_vote_counts(raid_id, "raid")
        creator = await self._creator_display(raid["created_by"])
        await interaction.response.send_message(f"Vote enregistré : **{name}** ✅", ephemeral=True)
        await self._edit_message(
            raid["channel_id"], raid["raid_poll_message_id"],
            embed=embeds.raid_choice_embed(raid, counts, creator),
        )

    async def handle_hour_vote(self, interaction: discord.Interaction, raid_id: int, hour: int) -> None:
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] != STATE_VOTING_HOUR:
            await interaction.response.send_message("Ce sondage est terminé.", ephemeral=True)
            return
        choice = str(hour)
        db.cast_vote(raid_id, interaction.user.id, "hour", choice)
        db.add_participant(raid_id, interaction.user.id)
        counts = db.get_vote_counts(raid_id, "hour")
        creator = await self._creator_display(raid["created_by"])
        await interaction.response.send_message(f"Vote enregistré : **{hour}h** ✅", ephemeral=True)
        await self._edit_message(
            raid["channel_id"], raid["hour_poll_message_id"],
            embed=embeds.hour_poll_embed(raid, counts, creator),
        )

    async def handle_register(self, interaction: discord.Interaction, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] not in (STATE_SCHEDULED, STATE_REMINDED):
            await interaction.response.send_message("Inscription impossible pour ce raid.", ephemeral=True)
            return
        db.add_participant(raid_id, interaction.user.id)
        participants = db.count_participants(raid_id)
        creator = await self._creator_display(raid["created_by"])
        await interaction.response.send_message(
            f"Inscrit pour le rappel MP ! ({participants} participant(s))", ephemeral=True
        )
        await self._edit_message(
            raid["channel_id"], raid["scheduled_message_id"],
            embed=embeds.scheduled_embed(raid, participants, creator),
        )

    # --------------------------------------------------------------- clôtures

    async def _close_raid_choice(self, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] != STATE_CHOOSING_RAID:
            return
        counts = db.get_vote_counts(raid_id, "raid")
        winner = tally(counts, order=RAID_NAMES, default=RAID_NAMES[0])
        db.update_raid(raid_id, name=winner, state=STATE_VOTING_HOUR)
        logger.info("Raid #%d : choix=%s, lancement sondage heure", raid_id, winner)

        await self._edit_message(
            raid["channel_id"],
            raid["raid_poll_message_id"],
            embed=embeds.raid_choice_result_embed(raid, winner, counts),
            view=None,
        )

        channel = await self._get_channel(raid["channel_id"])
        if channel is None:
            return
        now = now_paris()
        hour_closes = now + timedelta(seconds=raid["poll_duration_seconds"])
        db.update_raid(raid_id, hour_poll_closes_at=hour_closes)
        await self._send_hour_poll(channel, raid_id)
        self._schedule(raid_id, "hour_close", hour_closes, self._close_hour_poll)

    async def _close_hour_poll(self, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] != STATE_VOTING_HOUR:
            return
        counts = db.get_vote_counts(raid_id, "hour")
        winner_hour = tally(counts, order=_HOUR_ORDER, default=str(RAID_DEFAULT_HOUR))
        raid_date = date.fromisoformat(raid["date"])
        scheduled_at = dates_utils.combine_date_hour(raid_date, int(winner_hour))
        db.update_raid(raid_id, state=STATE_SCHEDULED, scheduled_at=scheduled_at)
        logger.info("Raid #%d : heure=%sh, planifié à %s", raid_id, winner_hour, scheduled_at.isoformat())

        await self._edit_message(
            raid["channel_id"],
            raid["hour_poll_message_id"],
            embed=embeds.hour_poll_result_embed(raid, winner_hour, counts),
            view=None,
        )

        await self._post_scheduled(raid_id)
        self._schedule_reminder(raid_id, scheduled_at)

    def _schedule_reminder(self, raid_id: int, scheduled_at: datetime) -> None:
        now = now_paris()
        if now >= scheduled_at:
            # Le raid est déjà passé (date aujourd'hui + sondage long) -> on termine.
            db.set_raid_state(raid_id, STATE_DONE)
            logger.info("Raid #%d déjà dépassé, marqué terminé", raid_id)
            return
        remind_at = scheduled_at - timedelta(minutes=REMINDER_MINUTES)
        self._schedule(raid_id, "remind", remind_at, self._remind)
        self._schedule(raid_id, "done", scheduled_at, self._mark_done)

    async def _remind(self, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] not in (STATE_SCHEDULED, STATE_REMINDED):
            return
        participants = db.get_participants(raid_id)
        dm_embed = embeds.reminder_dm_embed(raid)
        sent = 0
        for uid in participants:
            try:
                user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
                await user.send(embed=dm_embed)
                sent += 1
            except discord.Forbidden:
                logger.info("Rappel #%d : MP refusé par %s", raid_id, uid)
            except discord.DiscordException as exc:
                logger.warning("Rappel #%d : échec MP %s: %s", raid_id, uid, exc)

        channel = await self._get_channel(raid["channel_id"])
        if channel is not None:
            try:
                await channel.send(embed=embeds.reminder_channel_embed(raid, len(participants)))
            except discord.DiscordException as exc:
                logger.warning("Rappel #%d : message salon échoué: %s", raid_id, exc)

        db.set_raid_state(raid_id, STATE_REMINDED)
        logger.info("Rappel #%d envoyé à %d/%d participant(s)", raid_id, sent, len(participants))

    async def _mark_done(self, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        if not raid:
            return
        if raid["state"] != STATE_CANCELLED:
            db.set_raid_state(raid_id, STATE_DONE)
        logger.info("Raid #%d terminé", raid_id)

    # --------------------------------------------------------------- planif

    def _schedule(self, raid_id: int, kind: str, when: datetime, coro_fn) -> None:
        now = now_paris()
        delay = max(0.0, (when - now).total_seconds())
        task = asyncio.create_task(self._run_scheduled(raid_id, kind, delay, coro_fn))
        self._tasks[(raid_id, kind)] = task

    async def _run_scheduled(self, raid_id: int, kind: str, delay: float, coro_fn) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await coro_fn(raid_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Tâche planifiée raid #%d (%s) a échoué", raid_id, kind)
        finally:
            self._tasks.pop((raid_id, kind), None)

    def _cancel_tasks(self, raid_id: int) -> None:
        for kind in ("raid_close", "hour_close", "remind", "done"):
            task = self._tasks.pop((raid_id, kind), None)
            if task is not None:
                task.cancel()

    async def _reschedule_all(self) -> None:
        for raid in db.list_active_raids():
            raid_id = raid["id"]
            state = raid["state"]
            # Réenregistrement des vues pour le routage des clics après redémarrage.
            try:
                if state == STATE_CHOOSING_RAID and raid["raid_poll_message_id"]:
                    self.bot.add_view(RaidChoiceView(self, raid_id), message_id=raid["raid_poll_message_id"])
                elif state == STATE_VOTING_HOUR and raid["hour_poll_message_id"]:
                    self.bot.add_view(HourPollView(self, raid_id), message_id=raid["hour_poll_message_id"])
                elif state in (STATE_SCHEDULED, STATE_REMINDED) and raid["scheduled_message_id"]:
                    self.bot.add_view(ScheduledRaidView(self, raid_id), message_id=raid["scheduled_message_id"])
            except discord.DiscordException as exc:
                logger.warning("add_view raid #%d échoué: %s", raid_id, exc)

            # Replanification des tâches.
            if state == STATE_CHOOSING_RAID:
                when = datetime.fromisoformat(raid["raid_poll_closes_at"])
                self._schedule(raid_id, "raid_close", when, self._close_raid_choice)
            elif state == STATE_VOTING_HOUR:
                when = datetime.fromisoformat(raid["hour_poll_closes_at"])
                self._schedule(raid_id, "hour_close", when, self._close_hour_poll)
            elif state in (STATE_SCHEDULED, STATE_REMINDED):
                scheduled_at = datetime.fromisoformat(raid["scheduled_at"])
                now = now_paris()
                if now >= scheduled_at:
                    db.set_raid_state(raid_id, STATE_DONE)
                    logger.info("Raid #%d déjà dépassé au reload -> terminé", raid_id)
                else:
                    remind_at = scheduled_at - timedelta(minutes=REMINDER_MINUTES)
                    if state == STATE_SCHEDULED:
                        self._schedule(raid_id, "remind", remind_at, self._remind)
                    self._schedule(raid_id, "done", scheduled_at, self._mark_done)

    # --------------------------------------------------------------- commandes

    @app_commands.command(name="raid", description="Crée un raid avec un sondage pour choisir l'heure")
    @app_commands.describe(
        date="Date du raid (ex: 28/06, 2026-06-28, demain, aujourd'hui, lundi)",
        duree="Durée du sondage",
        raid="Nom du raid (laisser vide = sondage pour choisir le raid d'abord)",
        note="Note optionnelle affichée sur le sondage",
    )
    @app_commands.choices(
        duree=[
            app_commands.Choice(name="1 heure", value="1h"),
            app_commands.Choice(name="12 heures", value="12h"),
            app_commands.Choice(name="24 heures", value="24h"),
        ],
        raid=[app_commands.Choice(name=name, value=name) for name in RAID_NAMES],
    )
    async def raid(
        self,
        interaction: discord.Interaction,
        date: str,
        duree: app_commands.Choice[str],
        raid: Optional[app_commands.Choice[str]] = None,
        note: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if interaction.guild is None:
            await interaction.followup.send("À utiliser dans un serveur.", ephemeral=True)
            return
        raid_name = raid.value if raid else None
        channel = self._resolve_raids_channel(interaction.guild, interaction.channel)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            await interaction.followup.send("Impossible de trouver un salon pour poster le sondage.", ephemeral=True)
            return

        try:
            raid_id = await self.create_raid(
                interaction.guild, channel, interaction.user, raid_name, date, duree.value, note
            )
        except dates_utils.InvalidRaidDate as exc:
            await interaction.followup.send(f"❌ Date invalide : {exc}", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ Raid **#{raid_id}** créé — sondage posté dans {channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="list_raids", description="Liste les raids actifs")
    async def list_raids(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        rows = db.list_active_raids()
        await interaction.followup.send(embed=embeds.list_embed(rows), ephemeral=True)

    @app_commands.command(name="cancel_raid", description="Annule un raid (créateur ou admin)")
    @app_commands.describe(raid_id="Identifiant du raid (visible via /list_raids)")
    async def cancel_raid(self, interaction: discord.Interaction, raid_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        raid = db.get_raid(raid_id)
        if not raid:
            await interaction.followup.send("Raid introuvable.", ephemeral=True)
            return
        if interaction.user.id != raid["created_by"] and interaction.user.id not in ADMIN_IDS:
            await interaction.followup.send("Permission refusée.", ephemeral=True)
            return

        self._cancel_tasks(raid_id)
        db.set_raid_state(raid_id, STATE_CANCELLED)

        # Marquer les messages visibles comme annulés.
        cancelled = embeds.cancelled_embed(raid)
        for column in ("raid_poll_message_id", "hour_poll_message_id", "scheduled_message_id"):
            if raid[column]:
                await self._edit_message(raid["channel_id"], raid[column], embed=cancelled, view=None)

        await interaction.followup.send(f"Raid **#{raid_id}** annulé.", ephemeral=True)

    @app_commands.command(name="force_close", description="Clôture immédiatement le sondage d'un raid (admin)")
    @app_commands.describe(raid_id="Identifiant du raid")
    async def force_close(self, interaction: discord.Interaction, raid_id: int) -> None:
        if interaction.user.id not in ADMIN_IDS:
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        raid = db.get_raid(raid_id)
        if not raid:
            await interaction.followup.send("Raid introuvable.", ephemeral=True)
            return

        self._cancel_tasks(raid_id)
        if raid["state"] == STATE_CHOOSING_RAID:
            await self._close_raid_choice(raid_id)
            await interaction.followup.send(f"Sondage choix du raid **#{raid_id}** clôturé.", ephemeral=True)
        elif raid["state"] == STATE_VOTING_HOUR:
            await self._close_hour_poll(raid_id)
            await interaction.followup.send(f"Sondage heure **#{raid_id}** clôturé.", ephemeral=True)
        else:
            await interaction.followup.send(f"Rien à clôturer pour le raid **#{raid_id}** (état: {raid['state']}).", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RaidCog(bot))
