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
    PARIS,
    RAID_DEFAULT_HOUR,
    RAID_HOURS,
    RAID_NAMES,
    RAID_POLL_CLOSE_HOUR,
    RAIDS_CHANNEL_ID,
    REMINDER_DELETE_HOURS,
    REMINDER_MINUTES,
    now_paris,
    raid_cap,
)
from utils import embeds
from utils import dates as dates_utils
from utils.perms import can_manage_raid, is_raid_organizer
from utils.poll import (
    STATE_CANCELLED,
    STATE_CHOOSING_RAID,
    STATE_DONE,
    STATE_REMINDED,
    STATE_SCHEDULED,
    STATE_VOTING_HOUR,
    parse_poll_hours,
    tally,
)

logger = logging.getLogger("beb-raid.raid")

def _slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_only.lower().replace(" ", "_").replace("'", "")


def _parse_when(value) -> datetime:
    """Convertit une valeur BDD (str ISO / datetime / None) en datetime aware.

    Retourne 'maintenant' si la valeur est absente : la tâche associée se déclenchera
    immédiatement (clôture du sondage), ce qui évite qu'un raid incohérent ne bloque
    tout le bootstrap au redémarrage.
    """
    if value is None:
        logger.warning("Timestamp manquant en base pour un raid actif, replanification immédiate")
        return now_paris()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _raid_hours(raid) -> list[int]:
    """Heures proposées au sondage d'un raid : choisies par le créateur (colonne
    `poll_hours`), fallback sur `RAID_HOURS` (anciens raids migrés / défaut)."""
    raw = raid["poll_hours"] if raid else None
    return parse_poll_hours(raw, RAID_HOURS)


_RAID_SLUGS = {name: _slugify(name) for name in RAID_NAMES}

# Le message de rappel posté dans le salon est auto-supprimé après ce délai.
REMINDER_DELETE_AFTER = timedelta(hours=REMINDER_DELETE_HOURS)


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


class _UnregisterButton(discord.ui.Button):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(
            label="❌ Me désinscrire",
            style=discord.ButtonStyle.secondary,
            custom_id=f"bebraid:unreg:{raid_id}",
        )
        self.cog = cog
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_unregister(interaction, self.raid_id)


class _ClosePollButton(discord.ui.Button):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(
            label="🔒 Clôturer (admin)",
            style=discord.ButtonStyle.danger,
            custom_id=f"bebraid:close:{raid_id}",
        )
        self.cog = cog
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_close_poll(interaction, self.raid_id)


class _ParticipantsButton(discord.ui.Button):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(
            label="👥 Participants",
            style=discord.ButtonStyle.secondary,
            custom_id=f"bebraid:participants:{raid_id}",
        )
        self.cog = cog
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_view_participants(interaction, self.raid_id)


class _AdminRemoveButton(discord.ui.Button):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(
            label="🧹 Retirer (admin)",
            style=discord.ButtonStyle.danger,
            custom_id=f"bebraid:adminrm:{raid_id}",
        )
        self.cog = cog
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.prompt_admin_remove(interaction, self.raid_id)


class _AdminCancelButton(discord.ui.Button):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(
            label="❌ Annuler (admin)",
            style=discord.ButtonStyle.danger,
            custom_id=f"bebraid:cancel:{raid_id}",
        )
        self.cog = cog
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.prompt_cancel_raid(interaction, self.raid_id)


class _RemoveMemberSelect(discord.ui.UserSelect):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(
            placeholder="Sélectionne le(s) participant(s) à retirer",
            min_values=1,
            max_values=25,
        )
        self.cog = cog
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.admin_remove_members(interaction, self.raid_id, self.values)


class RemoveMemberView(discord.ui.View):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(timeout=300)
        self.add_item(_RemoveMemberSelect(cog, raid_id))


class _ConfirmCancelView(discord.ui.View):
    """Confirmation éphémère avant d'annuler un raid (Oui / Non)."""

    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.raid_id = raid_id

    @discord.ui.button(label="✅ Oui, annuler", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        ok = await self.cog._apply_cancel(self.raid_id)
        self.stop()
        await interaction.response.edit_message(
            content=(f"Raid **#{self.raid_id}** annulé." if ok else "Raid introuvable ou déjà annulé."),
            view=None,
        )

    @discord.ui.button(label="❌ Non", style=discord.ButtonStyle.secondary)
    async def abort(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Annulation abandonnée.", view=None)


class HourPollView(discord.ui.View):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(timeout=None)
        raid = db.get_raid(raid_id)
        now = now_paris()
        is_today = raid is not None and date.fromisoformat(raid["date"]) == now.date()
        for hour in _raid_hours(raid):
            btn = _HourVoteButton(cog, raid_id, hour)
            # Un raid prévu aujourd'hui : on désactive les créneaux déjà passés.
            if is_today and hour <= now.hour:
                btn.disabled = True
            self.add_item(btn)
        self.add_item(_ClosePollButton(cog, raid_id))
        self.add_item(_ParticipantsButton(cog, raid_id))
        self.add_item(_AdminCancelButton(cog, raid_id))


class RaidChoiceView(discord.ui.View):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(timeout=None)
        for name in RAID_NAMES:
            self.add_item(_RaidChoiceButton(cog, raid_id, name))
        self.add_item(_ClosePollButton(cog, raid_id))
        self.add_item(_ParticipantsButton(cog, raid_id))
        self.add_item(_AdminCancelButton(cog, raid_id))


class ScheduledRaidView(discord.ui.View):
    def __init__(self, cog: "RaidCog", raid_id: int):
        super().__init__(timeout=None)
        self.add_item(_RegisterButton(cog, raid_id))
        self.add_item(_UnregisterButton(cog, raid_id))
        self.add_item(_ParticipantsButton(cog, raid_id))
        self.add_item(_AdminRemoveButton(cog, raid_id))
        self.add_item(_AdminCancelButton(cog, raid_id))


class _HourChoiceSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choisis les heures à proposer au sondage",
            min_values=2,
            max_values=22,  # 22 h + boutons (close/participants/annuler) = 25 composants max Discord
            options=[discord.SelectOption(label=f"{h}h", value=str(h)) for h in range(24)],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.selected = sorted(int(v) for v in self.values)
        await interaction.response.defer()


class _ConfirmHoursButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✅ Confirmer", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.confirm(interaction)


class HourChoiceView(discord.ui.View):
    """Menu éphémère : le créateur choisit les créneaux du sondage d'heure, puis
    confirme pour créer le raid. Expiration (timeout) -> création annulée."""

    def __init__(self, cog: "RaidCog", guild, channel, user, raid_name, date_text, note):
        super().__init__(timeout=300)
        self.cog = cog
        self.selected: list[int] = []
        self.guild = guild
        self.channel = channel
        self.user = user
        self.raid_name = raid_name
        self.date_text = date_text
        self.note = note
        self.message: Optional[discord.Message] = None
        self.add_item(_HourChoiceSelect())
        self.add_item(_ConfirmHoursButton())

    async def confirm(self, interaction: discord.Interaction) -> None:
        if not self.selected:
            await interaction.response.send_message(
                "Sélectionne au moins 2 heures dans le menu, puis Confirmer.",
                ephemeral=True,
            )
            return
        try:
            raid_id = await self.cog.create_raid(
                self.guild, self.channel, self.user, self.raid_name,
                self.date_text, self.note, poll_hours=self.selected,
            )
        except dates_utils.InvalidRaidDate as exc:
            await interaction.response.edit_message(content=f"❌ Date invalide : {exc}", view=None)
            self.stop()
            return
        self.stop()
        await interaction.response.edit_message(
            content=f"✅ Raid **#{raid_id}** créé — sondage posté dans {self.channel.mention}.",
            view=None,
        )

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(
                    content="❌ Création annulée : tu n'as pas choisi les heures à temps.",
                    view=None,
                )
            except discord.DiscordException:
                pass
        self.stop()


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
            self._reschedule_reminder_cleanup()
            self._reschedule_raid_message_cleanup()
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
        # 1) réglage /setchannel (DB, par guilde) ; 2) variable d'env ; 3) salon courant.
        cid = db.get_guild_setting_int(guild.id, db.SETTING_RAIDS_CHANNEL)
        if cid:
            ch = guild.get_channel(cid)
            if ch is not None:
                return ch
        if RAIDS_CHANNEL_ID:
            ch = guild.get_channel(RAIDS_CHANNEL_ID)
            if ch is not None:
                return ch
        return fallback

    async def _prompt_hour_choice(
        self,
        interaction: discord.Interaction,
        guild,
        channel,
        user,
        raid_name,
        date_text,
        note,
    ) -> None:
        """Présente le menu de choix des heures (la création du raid est différée
        au clic sur Confirmer dans la view)."""
        view = HourChoiceView(self, guild, channel, user, raid_name, date_text, note)
        content = "🕐 Choisis les heures à proposer au sondage, puis clique sur **✅ Confirmer**."
        if interaction.response.is_done():
            view.message = await interaction.followup.send(content, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(content, view=view, ephemeral=True)
            view.message = await interaction.original_response()

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

    async def _edit_message(self, channel_id: int, message_id: int, *, embed=discord.utils.MISSING, view=discord.utils.MISSING) -> None:
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
        note: Optional[str] = None,
        poll_hours: Optional[list[int]] = None,
    ) -> int:
        """Crée un raid (cœur métier partagé par /raid et le ticket). Lève InvalidRaidDate.

        Si une heure est fournie dans date_text (ex: "15h", "demain 15h"), elle est
        imposée : pas de sondage d'heure. Le raid est planifié directement (ou après
        le sondage de choix du raid si aucun nom n'était donné).
        """
        raid_date = dates_utils.parse_raid_date(date_text)
        fixed_time = dates_utils.parse_time(date_text)
        now = now_paris()
        fixed_label = f"{fixed_time:%Hh%M}" if fixed_time else None
        # Rôle mentionné à l'annonce du raid (1er message seulement) — None si non configuré.
        notify_role_id = db.get_guild_setting_int(guild.id, db.SETTING_RAID_NOTIFY_ROLE)

        # Heure imposée ET raid connu -> planification directe, sans aucun sondage.
        if fixed_time is not None and raid_name:
            scheduled_at = dates_utils.combine_date_time(raid_date, fixed_time)
            if scheduled_at <= now:
                raise dates_utils.InvalidRaidDate(f"l'heure {fixed_label} est déjà passée")
            raid_id = db.create_raid(
                name=raid_name,
                date_iso=raid_date.isoformat(),
                created_by=user.id,
                guild_id=guild.id,
                channel_id=channel.id,
                state=STATE_SCHEDULED,
                scheduled_at=scheduled_at,
                note=note,
                fixed_time=f"{fixed_time:%H:%M}",
                poll_hours=poll_hours,
            )
            logger.info("Raid #%d créé par %s (heure fixée %s)", raid_id, user, fixed_label)
            await self._post_scheduled(raid_id, notify_role_id=notify_role_id)
            self._schedule_reminder(raid_id, scheduled_at)
            return raid_id

        # Clôture automatique des sondages : le jour du raid à RAID_POLL_CLOSE_HOUR
        # (plus de paramètre « durée » : tout découle de la date du raid).
        closes_at = dates_utils.poll_closes_at(raid_date, RAID_POLL_CLOSE_HOUR, now)

        if raid_name:
            # Raid connu -> on sonde directement l'heure, jusqu'à la clôture finale.
            state = STATE_VOTING_HOUR
            raid_closes = None
            hour_closes = closes_at
        else:
            # Raid inconnu -> sondage du choix, puis sondage de l'heure. Le choix se
            # clôture à mi-parcours pour laisser du temps au sondage d'heure jusqu'à
            # la clôture finale (jour du raid).
            state = STATE_CHOOSING_RAID
            raid_closes = now + (closes_at - now) / 2
            hour_closes = None

        raid_id = db.create_raid(
            name=raid_name,
            date_iso=raid_date.isoformat(),
            created_by=user.id,
            guild_id=guild.id,
            channel_id=channel.id,
            state=state,
            raid_poll_closes_at=raid_closes,
            hour_poll_closes_at=hour_closes,
            note=note,
            fixed_time=f"{fixed_time:%H:%M}" if fixed_time else None,
            poll_hours=poll_hours,
        )
        logger.info("Raid #%d créé par %s (state=%s, clôture %s)", raid_id, user, state, closes_at.isoformat())

        if state == STATE_VOTING_HOUR:
            await self._send_hour_poll(channel, raid_id, notify_role_id=notify_role_id)
            self._schedule(raid_id, "hour_close", hour_closes, self._close_hour_poll)
        else:
            await self._send_raid_choice(channel, raid_id, notify_role_id=notify_role_id)
            self._schedule(raid_id, "raid_close", raid_closes, self._close_raid_choice)

        return raid_id

    @staticmethod
    def _announce_content(notify_role_id) -> Optional[str]:
        """Contenu de mention pour l'annonce d'un raid (None si aucun rôle configuré)."""
        return f"<@&{notify_role_id}>" if notify_role_id else None

    async def _send_raid_choice(self, channel, raid_id: int, notify_role_id=None) -> None:
        raid = db.get_raid(raid_id)
        counts = db.get_vote_counts(raid_id, "raid")
        creator = await self._creator_display(raid["created_by"])
        embed = embeds.raid_choice_embed(raid, counts, creator)
        view = RaidChoiceView(self, raid_id)
        msg = await channel.send(content=self._announce_content(notify_role_id), embed=embed, view=view)
        db.update_raid(raid_id, raid_poll_message_id=msg.id)

    async def _send_hour_poll(self, channel, raid_id: int, notify_role_id=None) -> None:
        raid = db.get_raid(raid_id)
        counts = db.get_vote_counts(raid_id, "hour")
        creator = await self._creator_display(raid["created_by"])
        participants = db.count_participants(raid_id)
        embed = embeds.hour_poll_embed(raid, counts, creator, participants, _raid_hours(raid))
        view = HourPollView(self, raid_id)
        msg = await channel.send(content=self._announce_content(notify_role_id), embed=embed, view=view)
        db.update_raid(raid_id, hour_poll_message_id=msg.id)

    async def _post_scheduled(self, raid_id: int, notify_role_id=None) -> None:
        raid = db.get_raid(raid_id)
        creator = await self._creator_display(raid["created_by"])
        participants = db.count_participants(raid_id)
        embed = embeds.scheduled_embed(raid, participants, creator)
        view = ScheduledRaidView(self, raid_id)
        channel = await self._get_channel(raid["channel_id"])
        if channel is None:
            logger.warning("Salon introuvable pour le raid #%d", raid_id)
            return
        msg = await channel.send(content=self._announce_content(notify_role_id), embed=embed, view=view)
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
        # Raid prévu aujourd'hui : on refuse les créneaux déjà passés.
        if date.fromisoformat(raid["date"]) == now_paris().date() and hour <= now_paris().hour:
            await interaction.response.send_message("⏰ Ce créneau est déjà passé.", ephemeral=True)
            return
        already = db.is_participant(raid_id, interaction.user.id)
        will_add = str(hour) not in db.get_user_votes(raid_id, interaction.user.id, "hour")
        # Inscription comme participant au premier créneau voté (sous réserve du cap).
        if will_add and not already:
            cap = raid_cap(raid["name"])
            if cap is not None and db.count_participants(raid_id) >= cap:
                await interaction.response.send_message(
                    f"⛔ Ce raid est complet ({cap}/{cap}). Impossible de s'inscrire.", ephemeral=True
                )
                return
        added = db.toggle_vote(raid_id, interaction.user.id, "hour", str(hour))
        if added and not already:
            db.add_participant(raid_id, interaction.user.id)
        counts = db.get_vote_counts(raid_id, "hour")
        participants = db.count_participants(raid_id)
        creator = await self._creator_display(raid["created_by"])
        user_hours = sorted(int(h) for h in db.get_user_votes(raid_id, interaction.user.id, "hour"))
        votes_str = ", ".join(f"{h}h" for h in user_hours) or "aucun"
        msg = f"{'✅' if added else '🚫'} **{hour}h** {'ajouté' if added else 'retiré'}. Tes créneaux : {votes_str}."
        await interaction.response.send_message(msg, ephemeral=True)
        await self._edit_message(
            raid["channel_id"], raid["hour_poll_message_id"],
            embed=embeds.hour_poll_embed(raid, counts, creator, participants, _raid_hours(raid)),
        )

    async def handle_register(self, interaction: discord.Interaction, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] not in (STATE_SCHEDULED, STATE_REMINDED):
            await interaction.response.send_message("Inscription impossible pour ce raid.", ephemeral=True)
            return
        cap = raid_cap(raid["name"])
        already = db.is_participant(raid_id, interaction.user.id)
        if cap is not None and not already and db.count_participants(raid_id) >= cap:
            await interaction.response.send_message(
                f"⛔ Ce raid est complet ({cap}/{cap}). Impossible de s'inscrire.", ephemeral=True
            )
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

    async def handle_unregister(self, interaction: discord.Interaction, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] not in (STATE_SCHEDULED, STATE_REMINDED):
            await interaction.response.send_message("Désinscription impossible pour ce raid.", ephemeral=True)
            return
        if not db.is_participant(raid_id, interaction.user.id):
            await interaction.response.send_message("Tu n'es pas inscrit à ce raid.", ephemeral=True)
            return
        db.remove_participant(raid_id, interaction.user.id)
        participants = db.count_participants(raid_id)
        creator = await self._creator_display(raid["created_by"])
        await interaction.response.send_message(
            f"Désinscrit du rappel MP. ({participants} participant(s))", ephemeral=True
        )
        await self._edit_message(
            raid["channel_id"], raid["scheduled_message_id"],
            embed=embeds.scheduled_embed(raid, participants, creator),
        )

    def _is_raid_manager(self, interaction: discord.Interaction, raid) -> bool:
        """Organisateur (admin/rôle) ou créateur du raid : peut gérer les participants."""
        return can_manage_raid(interaction, raid)

    async def prompt_admin_remove(self, interaction: discord.Interaction, raid_id: int) -> None:
        """Bouton admin : ouvre un sélecteur pour retirer des participants."""
        raid = db.get_raid(raid_id)
        if not self._is_raid_manager(interaction, raid):
            await interaction.response.send_message(
                "🔒 Réservé aux admins et au créateur du raid.", ephemeral=True
            )
            return
        if not raid or raid["state"] not in (STATE_SCHEDULED, STATE_REMINDED):
            await interaction.response.send_message("Aucun participant à gérer pour ce raid.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Sélectionne le(s) participant(s) à retirer du rappel :",
            view=RemoveMemberView(self, raid_id),
            ephemeral=True,
        )

    async def admin_remove_members(self, interaction: discord.Interaction, raid_id: int, users) -> None:
        raid = db.get_raid(raid_id)
        if not self._is_raid_manager(interaction, raid):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        removed: list[str] = []
        skipped: list[str] = []
        for user in users:
            if db.is_participant(raid_id, user.id):
                db.remove_participant(raid_id, user.id)
                removed.append(user.mention)
            else:
                skipped.append(user.mention)
        participants = db.count_participants(raid_id)
        creator = await self._creator_display(raid["created_by"]) if raid else "?"
        if raid:
            await self._edit_message(
                raid["channel_id"], raid["scheduled_message_id"],
                embed=embeds.scheduled_embed(raid, participants, creator),
            )
        parts: list[str] = []
        if removed:
            parts.append(f"✅ Retiré du rappel : {', '.join(removed)}")
        if skipped:
            parts.append(f"⚠️ N'était pas inscrit : {', '.join(skipped)}")
        if not parts:
            parts.append("Aucun changement.")
        await interaction.response.send_message("\n".join(parts), ephemeral=True)

    async def _member_display_name(self, guild, uid: int) -> str:
        """Nom affichable d'un participant (membre de guilde en priorité)."""
        member = guild.get_member(uid) if guild is not None else None
        if member is None and guild is not None:
            try:
                member = await guild.fetch_member(uid)
            except discord.DiscordException:
                member = None
        if member is not None:
            return member.display_name
        user = self.bot.get_user(uid)
        if user is None:
            try:
                user = await self.bot.fetch_user(uid)
            except discord.DiscordException:
                user = None
        return user.display_name if user is not None else f"utilisateur {uid}"

    async def handle_view_participants(self, interaction: discord.Interaction, raid_id: int) -> None:
        """Bouton : affiche (en éphémère) la liste des participants."""
        raid = db.get_raid(raid_id)
        if not raid:
            await interaction.response.send_message("Raid introuvable.", ephemeral=True)
            return
        uids = db.get_participants(raid_id)
        names = [await self._member_display_name(interaction.guild, uid) for uid in uids]
        await interaction.response.send_message(
            embed=embeds.participants_embed(raid, names), ephemeral=True
        )

    async def handle_close_poll(self, interaction: discord.Interaction, raid_id: int) -> None:
        """Bouton : clôture immédiatement le sondage (organisateur ou créateur du raid)."""
        raid = db.get_raid(raid_id)
        if not can_manage_raid(interaction, raid):
            await interaction.response.send_message(
                "🔒 Réservé aux organisateurs et au créateur du raid.", ephemeral=True
            )
            return
        if not raid:
            await interaction.response.send_message("Raid introuvable.", ephemeral=True)
            return

        state = raid["state"]
        if state == STATE_CHOOSING_RAID:
            self._cancel_tasks(raid_id)
            await interaction.response.send_message("Sondage choix du raid clôturé…", ephemeral=True)
            await self._close_raid_choice(raid_id)
        elif state == STATE_VOTING_HOUR:
            self._cancel_tasks(raid_id)
            await interaction.response.send_message("Sondage heure clôturé…", ephemeral=True)
            await self._close_hour_poll(raid_id)
        else:
            await interaction.response.send_message("Ce sondage est déjà terminé.", ephemeral=True)

    # --------------------------------------------------------------- clôtures

    async def _close_raid_choice(self, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] != STATE_CHOOSING_RAID:
            return
        counts = db.get_vote_counts(raid_id, "raid")
        winner = tally(counts, order=RAID_NAMES, default=RAID_NAMES[0])

        # Heure imposée dès la création : on saute le sondage d'heure et on planifie.
        t = dates_utils.parse_hhmm(raid["fixed_time"])
        if t is not None:
            raid_date = date.fromisoformat(raid["date"])
            scheduled_at = dates_utils.combine_date_time(raid_date, t)
            db.update_raid(raid_id, name=winner, state=STATE_SCHEDULED, scheduled_at=scheduled_at)
            logger.info("Raid #%d : choix=%s, heure imposée %s", raid_id, winner, t.strftime("%Hh%M"))
            await self._edit_message(
                raid["channel_id"],
                raid["raid_poll_message_id"],
                embed=embeds.raid_choice_result_embed(raid, winner, counts, t.strftime("%Hh%M")),
                view=None,
            )
            await self._post_scheduled(raid_id)
            self._schedule_reminder(raid_id, scheduled_at)
            return

        now = now_paris()
        hour_closes = dates_utils.poll_closes_at(
            date.fromisoformat(raid["date"]), RAID_POLL_CLOSE_HOUR, now
        )
        # Transition atomique : état + heure de clôture du sondage heure dans la même UPDATE,
        # pour ne jamais laisser un raid en 'voting_hour' avec hour_poll_closes_at NULL.
        db.update_raid(raid_id, name=winner, state=STATE_VOTING_HOUR, hour_poll_closes_at=hour_closes)
        logger.info("Raid #%d : choix=%s, lancement sondage heure", raid_id, winner)

        await self._edit_message(
            raid["channel_id"],
            raid["raid_poll_message_id"],
            embed=embeds.raid_choice_result_embed(raid, winner, counts),
            view=None,
        )

        channel = await self._get_channel(raid["channel_id"])
        if channel is None:
            logger.warning("Salon introuvable pour le raid #%d : sondage heure non posté", raid_id)
            return
        await self._send_hour_poll(channel, raid_id)
        self._schedule(raid_id, "hour_close", hour_closes, self._close_hour_poll)

    async def _close_hour_poll(self, raid_id: int) -> None:
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] != STATE_VOTING_HOUR:
            return
        counts = db.get_vote_counts(raid_id, "hour")
        hours = _raid_hours(raid)
        hour_order = [str(h) for h in hours]
        default_hour = str(RAID_DEFAULT_HOUR) if RAID_DEFAULT_HOUR in hours else (hour_order[0] if hour_order else str(RAID_DEFAULT_HOUR))
        winner_hour = tally(counts, order=hour_order, default=default_hour)
        raid_date = date.fromisoformat(raid["date"])
        scheduled_at = dates_utils.combine_date_hour(raid_date, int(winner_hour))
        db.update_raid(raid_id, state=STATE_SCHEDULED, scheduled_at=scheduled_at)
        logger.info("Raid #%d : heure=%sh, planifié à %s", raid_id, winner_hour, scheduled_at.isoformat())

        await self._edit_message(
            raid["channel_id"],
            raid["hour_poll_message_id"],
            embed=embeds.hour_poll_result_embed(raid, winner_hour, counts, hours),
            view=None,
        )

        await self._post_scheduled(raid_id)
        self._schedule_reminder(raid_id, scheduled_at)

    def _schedule_reminder(self, raid_id: int, scheduled_at: datetime) -> None:
        now = now_paris()
        # Suppression des messages du raid 2h après l'heure prévue (tout état confondu).
        self._schedule(
            raid_id, "del_raid_msgs", scheduled_at + REMINDER_DELETE_AFTER, self._delete_raid_messages
        )
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
                msg = await channel.send(embed=embeds.reminder_channel_embed(raid, len(participants)))
                reminder_sent_at = now_paris()
                # On mémorise le message pour pouvoir le supprimer (à 2h) et survivre à un reboot.
                db.update_raid(
                    raid_id, reminder_message_id=msg.id, reminder_sent_at=reminder_sent_at
                )
                self._schedule(
                    raid_id, "del_reminder",
                    reminder_sent_at + REMINDER_DELETE_AFTER, self._delete_reminder,
                )
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

    async def _delete_reminder(self, raid_id: int) -> None:
        """Supprime le message de rappel en salon (auto-cleanup à 2h). Idempotent."""
        raid = db.get_raid(raid_id)
        if not raid or not raid["reminder_message_id"]:
            return
        channel = await self._get_channel(raid["channel_id"])
        if channel is not None:
            try:
                msg = await channel.fetch_message(raid["reminder_message_id"])
                await msg.delete()
                logger.info("Rappel #%d : message salon supprimé", raid_id)
            except discord.NotFound:
                pass  # déjà supprimé
            except discord.DiscordException as exc:
                logger.warning("Rappel #%d : suppression message échouée: %s", raid_id, exc)
        # On marque comme nettoyé pour ne pas retenter (et sortir du pass de replanif).
        db.update_raid(raid_id, reminder_message_id=None, reminder_sent_at=None)

    async def _delete_raid_messages(self, raid_id: int) -> None:
        """Supprime les messages d'un raid (sondages + message planifié) 2h après
        l'heure prévue. Les raids annulés sont exclus : leur message « annulé »
        reste visible jusqu'à suppression manuelle. Idempotent."""
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] == STATE_CANCELLED:
            return
        channel = await self._get_channel(raid["channel_id"])
        deleted = 0
        if channel is not None:
            for col in ("raid_poll_message_id", "hour_poll_message_id", "scheduled_message_id"):
                mid = raid[col]
                if not mid:
                    continue
                try:
                    msg = await channel.fetch_message(mid)
                    await msg.delete()
                    deleted += 1
                except discord.NotFound:
                    pass  # déjà supprimé
                except discord.DiscordException as exc:
                    logger.warning("Raid #%d : suppression message %s=%s échouée: %s", raid_id, col, mid, exc)
        # Marque comme nettoyé pour sortir du pass de replanif au boot.
        db.update_raid(
            raid_id, raid_poll_message_id=None, hour_poll_message_id=None, scheduled_message_id=None
        )
        logger.info("Raid #%d : %d message(s) supprimé(s) (cleanup 2h)", raid_id, deleted)

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
        for kind in ("raid_close", "hour_close", "remind", "done", "del_reminder", "del_raid_msgs"):
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
                when = _parse_when(raid["raid_poll_closes_at"])
                self._schedule(raid_id, "raid_close", when, self._close_raid_choice)
            elif state == STATE_VOTING_HOUR:
                when = _parse_when(raid["hour_poll_closes_at"])
                self._schedule(raid_id, "hour_close", when, self._close_hour_poll)
            elif state in (STATE_SCHEDULED, STATE_REMINDED):
                scheduled_at = _parse_when(raid["scheduled_at"])
                now = now_paris()
                if now >= scheduled_at:
                    db.set_raid_state(raid_id, STATE_DONE)
                    logger.info("Raid #%d déjà dépassé au reload -> terminé", raid_id)
                else:
                    remind_at = scheduled_at - timedelta(minutes=REMINDER_MINUTES)
                    if state == STATE_SCHEDULED:
                        self._schedule(raid_id, "remind", remind_at, self._remind)
                    self._schedule(raid_id, "done", scheduled_at, self._mark_done)

    def _reschedule_reminder_cleanup(self) -> None:
        """Replanifie la suppression (à 2h) des messages de rappel en salon, y compris
        pour les raids déjà terminés. `_schedule` à une date passée => déclenchement
        immédiat, donc un rappel oublié pendant un reboot est nettoyé au redémarrage.
        """
        for raid in db.list_raids_with_reminder_message():
            raid_id = raid["id"]
            sent_at = _parse_when(raid["reminder_sent_at"])
            self._schedule(
                raid_id, "del_reminder",
                sent_at + REMINDER_DELETE_AFTER, self._delete_reminder,
            )

    def _reschedule_raid_message_cleanup(self) -> None:
        """Replanifie la suppression (à 2h) des messages de raid (sondages + planifié)
        pour tous les raids non annulés dont l'heure est connue et qui ont encore des
        messages. `_schedule` à une date passée => déclenchement immédiat, donc un
        raid oublié pendant un reboot est nettoyé au redémarrage.
        """
        for raid in db.list_raids_with_messages():
            raid_id = raid["id"]
            scheduled_at = _parse_when(raid["scheduled_at"])
            self._schedule(
                raid_id, "del_raid_msgs",
                scheduled_at + REMINDER_DELETE_AFTER, self._delete_raid_messages,
            )

    # --------------------------------------------------------------- commandes

    @app_commands.command(name="raid", description="Crée un raid : fixe l'heure toi-même ou laisse un sondage")
    @app_commands.describe(
        date="Date et/ou heure (ex: ce soir, demain 19h30, 28/06, 21h). Une heure précise fixe l'heure sans sondage.",
        raid="Nom du raid (laisser vide = sondage pour choisir le raid d'abord)",
        note="Note optionnelle affichée sur le sondage",
    )
    @app_commands.choices(
        raid=[app_commands.Choice(name=name, value=name) for name in RAID_NAMES],
    )
    async def raid(
        self,
        interaction: discord.Interaction,
        date: str,
        raid: Optional[app_commands.Choice[str]] = None,
        note: Optional[str] = None,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message(
                "🔒 Tu dois avoir le rôle organisateur (ou être admin) pour créer un raid.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        if interaction.guild is None:
            await interaction.followup.send("À utiliser dans un serveur.", ephemeral=True)
            return
        raid_name = raid.value if raid else None
        channel = self._resolve_raids_channel(interaction.guild, interaction.channel)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            await interaction.followup.send("Impossible de trouver un salon pour poster le sondage.", ephemeral=True)
            return

        # Validation précoce de la date (avant de présenter le menu d'heures).
        try:
            dates_utils.parse_raid_date(date)
        except dates_utils.InvalidRaidDate as exc:
            await interaction.followup.send(f"❌ Date invalide : {exc}", ephemeral=True)
            return

        # Heure fixée dans `date` (ex: "demain 21h") -> création directe, pas de sondage.
        # Sinon -> menu de choix des créneaux (création différée au Confirm).
        if dates_utils.parse_time(date) is not None:
            try:
                raid_id = await self.create_raid(
                    interaction.guild, channel, interaction.user, raid_name, date, note,
                )
            except dates_utils.InvalidRaidDate as exc:
                await interaction.followup.send(f"❌ Date invalide : {exc}", ephemeral=True)
                return
            await interaction.followup.send(
                f"✅ Raid **#{raid_id}** créé — sondage posté dans {channel.mention}.",
                ephemeral=True,
            )
            return

        await self._prompt_hour_choice(
            interaction, interaction.guild, channel, interaction.user, raid_name, date, note,
        )

    @app_commands.command(name="list_raids", description="Liste les raids actifs")
    async def list_raids(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        rows = db.list_active_raids()
        await interaction.followup.send(embed=embeds.list_embed(rows), ephemeral=True)

    async def _apply_cancel(self, raid_id: int) -> bool:
        """Annule un raid (sans interaction) : annule les tâches planifiées, passe en
        CANCELLED et édite les messages visibles en embed « annulé ». Retourne False si
        le raid est introuvable ou déjà annulé. Réutilisée par /cancel_raid et le bouton.
        """
        raid = db.get_raid(raid_id)
        if not raid or raid["state"] == STATE_CANCELLED:
            return False
        self._cancel_tasks(raid_id)
        db.set_raid_state(raid_id, STATE_CANCELLED)
        cancelled = embeds.cancelled_embed(raid)
        for column in ("raid_poll_message_id", "hour_poll_message_id", "scheduled_message_id"):
            if raid[column]:
                await self._edit_message(raid["channel_id"], raid[column], embed=cancelled, view=None)
        return True

    async def prompt_cancel_raid(self, interaction: discord.Interaction, raid_id: int) -> None:
        """Bouton admin « Annuler » : vérifie la permission puis demande confirmation."""
        raid = db.get_raid(raid_id)
        if not raid:
            await interaction.response.send_message("Raid introuvable.", ephemeral=True)
            return
        if not can_manage_raid(interaction, raid):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"⚠️ Confirmer l'annulation du raid **#{raid_id}** ? Cette action est irréversible.",
            view=_ConfirmCancelView(self, raid_id),
            ephemeral=True,
        )

    @app_commands.command(name="cancel_raid", description="Annule un raid (créateur ou admin)")
    @app_commands.describe(raid_id="Identifiant du raid (visible via /list_raids)")
    async def cancel_raid(self, interaction: discord.Interaction, raid_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        raid = db.get_raid(raid_id)
        if not raid:
            await interaction.followup.send("Raid introuvable.", ephemeral=True)
            return
        if not can_manage_raid(interaction, raid):
            await interaction.followup.send("Permission refusée.", ephemeral=True)
            return
        ok = await self._apply_cancel(raid_id)
        await interaction.followup.send(
            f"Raid **#{raid_id}** annulé." if ok else f"Raid **#{raid_id}** introuvable ou déjà annulé.",
            ephemeral=True,
        )

    @app_commands.command(name="force_close", description="Clôture immédiatement le sondage d'un raid (organisateur)")
    @app_commands.describe(raid_id="Identifiant du raid")
    async def force_close(self, interaction: discord.Interaction, raid_id: int) -> None:
        if not is_raid_organizer(interaction):
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
