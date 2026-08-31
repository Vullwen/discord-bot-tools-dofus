from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

import db
from config import now_paris
from utils import dates as dates_utils
from utils.perms import is_raid_organizer
from utils.stuff_capture import capture_barbofus_page

logger = logging.getLogger(__name__)

PRESET_SKIN = "skin_contest"
PRESET_SKIN_LABEL = "concours de skin"
EVENT_OPEN = "open"
EVENT_POPULAR_VOTE = "popular_vote"
EVENT_ADMIN_VOTE = "admin_vote"
EVENT_DONE = "done"
SUBMISSION_ACTIVE = "active"
SUBMISSION_FINALIST = "finalist"
SUBMISSION_ELIMINATED = "eliminated"
TRAILING_URL_PUNCTUATION = ".,;:!?)>]}"
BARBOFUS_HOSTS = {"barbofus.com", "www.barbofus.com"}
MAX_VOTING_BUTTONS = 25
TASK_REGISTRATION_CLOSE = "registration_close"
TASK_SUBMISSIONS_CLOSE = "submissions_close"


@dataclass(frozen=True)
class BarbofusSkinLink:
    url: str
    reference: str
    label: str


def parse_barbofus_skin_url(raw_url: str) -> BarbofusSkinLink:
    value = (raw_url or "").strip().rstrip(TRAILING_URL_PUNCTUATION)
    if not value:
        raise ValueError("Lien Barbofus vide.")
    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    if parsed.netloc.lower() not in BARBOFUS_HOSTS:
        raise ValueError("Le lien doit venir de barbofus.com.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != "unity-skin" or not parts[1].isdigit():
        raise ValueError("Le lien doit pointer vers une page /unity-skin/<id> Barbofus.")

    reference = parts[1]
    return BarbofusSkinLink(
        url=value,
        reference=reference,
        label=f"Skin Barbofus #{reference}",
    )


class EventConfigModal(discord.ui.Modal):
    def __init__(self, cog: "EventCog", *, name: str, preset: Optional[str]):
        super().__init__(title="Configuration event")
        self.cog = cog
        self.name = name
        self.preset = preset
        self.registration_input = discord.ui.TextInput(
            label="Clôture des inscriptions",
            placeholder="ex: 24h, dimanche 20h, 31/08 21h",
            required=True,
            max_length=80,
        )
        self.add_item(self.registration_input)
        self.theme_input: Optional[discord.ui.TextInput] = None
        self.submissions_input: Optional[discord.ui.TextInput] = None
        if preset == PRESET_SKIN:
            self.theme_input = discord.ui.TextInput(
                label="Thème",
                placeholder="theme",
                required=False,
                max_length=100,
            )
            self.submissions_input = discord.ui.TextInput(
                label="Fin du concours / dépôts",
                placeholder="ex: 48h, 3j, demain 21h",
                required=True,
                max_length=80,
            )
            self.add_item(self.theme_input)
            self.add_item(self.submissions_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            registration_close_at = parse_deadline(
                str(self.registration_input.value),
                field_name="clôture des inscriptions",
            )
            submissions_close_at = None
            if self.submissions_input is not None:
                submissions_close_at = parse_submission_close(str(self.submissions_input.value))
        except ValueError as exc:
            await interaction.response.send_message(f"Date invalide : {exc}", ephemeral=True)
            return

        theme = str(self.theme_input.value).strip() if self.theme_input is not None else None
        await self.cog.create_configured_event(
            interaction,
            name=self.name,
            preset=self.preset,
            theme=theme or None,
            registration_close_at=registration_close_at,
            submissions_close_at=submissions_close_at,
        )


class EventSubmitModal(discord.ui.Modal):
    def __init__(self, cog: "EventCog", event_id: int):
        super().__init__(title="Dépôt Barbofus anonyme")
        self.cog = cog
        self.event_id = event_id
        self.link_input = discord.ui.TextInput(
            label="Lien Barbofus",
            placeholder="https://barbofus.com/unity-skin/12407",
            required=True,
            max_length=300,
        )
        self.add_item(self.link_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.submit_skin_link(interaction, self.event_id, str(self.link_input.value))


class EventCancelModal(discord.ui.Modal):
    def __init__(self, cog: "EventCog", event_id: int):
        super().__init__(title="Annuler l'event")
        self.cog = cog
        self.event_id = event_id
        self.reason_input = discord.ui.TextInput(
            label="Raison",
            placeholder="Optionnel",
            required=False,
            max_length=300,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.cancel_event(
            interaction,
            self.event_id,
            str(self.reason_input.value).strip() or None,
        )


class EventBanModal(discord.ui.Modal):
    def __init__(self, cog: "EventCog", event_id: int):
        super().__init__(title="Ban event")
        self.cog = cog
        self.event_id = event_id
        self.member_input = discord.ui.TextInput(
            label="Membre",
            placeholder="@membre ou ID Discord",
            required=True,
            max_length=80,
        )
        self.reason_input = discord.ui.TextInput(
            label="Raison",
            placeholder="Optionnel",
            required=False,
            max_length=300,
        )
        self.add_item(self.member_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            user_id = parse_user_id(str(self.member_input.value))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await self.cog.ban_event_member(
            interaction,
            self.event_id,
            user_id,
            str(self.reason_input.value).strip() or None,
        )


class _JoinEventButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", event_id: int, *, disabled: bool = False):
        super().__init__(
            label="S'inscrire",
            style=discord.ButtonStyle.success,
            custom_id=f"bebraid:event:join:{event_id}",
            disabled=disabled,
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.join_event(interaction, self.event_id)


class _LeaveEventButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", event_id: int, *, disabled: bool = False):
        super().__init__(
            label="Se désinscrire",
            style=discord.ButtonStyle.secondary,
            custom_id=f"bebraid:event:leave:{event_id}",
            disabled=disabled,
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.leave_event(interaction, self.event_id)


class EventRegistrationView(discord.ui.View):
    def __init__(self, cog: "EventCog", event_id: int, *, disabled: bool = False):
        super().__init__(timeout=None)
        self.add_item(_JoinEventButton(cog, event_id, disabled=disabled))
        self.add_item(_LeaveEventButton(cog, event_id, disabled=disabled))


class _ApproveRegistrationButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", event_id: int, user_id: int):
        super().__init__(
            label="Valider cash entry",
            style=discord.ButtonStyle.success,
            custom_id=f"bebraid:event:approve:{event_id}:{user_id}",
        )
        self.cog = cog
        self.event_id = event_id
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.approve_registration(interaction, self.event_id, self.user_id)


class EventApprovalView(discord.ui.View):
    def __init__(self, cog: "EventCog", event_id: int, user_id: int):
        super().__init__(timeout=None)
        self.add_item(_ApproveRegistrationButton(cog, event_id, user_id))


class _SubmitSkinButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", event_id: int, *, disabled: bool = False):
        super().__init__(
            label="Déposer mon skin",
            style=discord.ButtonStyle.primary,
            custom_id=f"bebraid:event:skin_submit:{event_id}",
            disabled=disabled,
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.open_skin_modal(interaction, self.event_id)


class EventSkinSubmitView(discord.ui.View):
    def __init__(self, cog: "EventCog", event_id: int, *, disabled: bool = False):
        super().__init__(timeout=None)
        self.add_item(_SubmitSkinButton(cog, event_id, disabled=disabled))


class _PopularVoteButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", submission_id: int):
        super().__init__(
            label="Voter",
            style=discord.ButtonStyle.success,
            custom_id=f"bebraid:event:popular_vote:{submission_id}",
        )
        self.cog = cog
        self.submission_id = submission_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.vote_popular(interaction, self.submission_id)


class EventPopularVoteView(discord.ui.View):
    def __init__(self, cog: "EventCog", submission_id: int):
        super().__init__(timeout=None)
        self.add_item(_PopularVoteButton(cog, submission_id))


class _AdminVoteButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", submission_id: int):
        super().__init__(
            label="Vote admin",
            style=discord.ButtonStyle.primary,
            custom_id=f"bebraid:event:admin_vote:{submission_id}",
        )
        self.cog = cog
        self.submission_id = submission_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.vote_admin(interaction, self.submission_id)


class EventAdminVoteView(discord.ui.View):
    def __init__(self, cog: "EventCog", submission_id: int):
        super().__init__(timeout=None)
        self.add_item(_AdminVoteButton(cog, submission_id))


class _CloseRegistrationsButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", event_id: int):
        super().__init__(
            label="Fermer inscriptions",
            style=discord.ButtonStyle.secondary,
            custom_id=f"bebraid:event:admin_close_reg:{event_id}",
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.close_registrations_now(interaction, self.event_id)


class _ClosePopularVoteButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", event_id: int):
        super().__init__(
            label="Clore vote populaire",
            style=discord.ButtonStyle.primary,
            custom_id=f"bebraid:event:admin_close_popular:{event_id}",
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.close_popular_vote(interaction, self.event_id)


class _PublishResultsButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", event_id: int):
        super().__init__(
            label="Publier résultats",
            style=discord.ButtonStyle.success,
            custom_id=f"bebraid:event:admin_results:{event_id}",
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.publish_results(interaction, self.event_id)


class _BanEventMemberButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", event_id: int):
        super().__init__(
            label="Ban event",
            style=discord.ButtonStyle.secondary,
            custom_id=f"bebraid:event:admin_ban:{event_id}",
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.open_ban_modal(interaction, self.event_id)


class _CancelEventButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", event_id: int):
        super().__init__(
            label="Annuler event",
            style=discord.ButtonStyle.danger,
            custom_id=f"bebraid:event:admin_cancel:{event_id}",
        )
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.open_cancel_modal(interaction, self.event_id)


class EventAdminView(discord.ui.View):
    def __init__(self, cog: "EventCog", event_id: int):
        super().__init__(timeout=None)
        self.add_item(_CloseRegistrationsButton(cog, event_id))
        self.add_item(_ClosePopularVoteButton(cog, event_id))
        self.add_item(_PublishResultsButton(cog, event_id))
        self.add_item(_BanEventMemberButton(cog, event_id))
        self.add_item(_CancelEventButton(cog, event_id))


class EventCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tasks: dict[tuple[int, str], asyncio.Task] = {}

    async def cog_load(self) -> None:
        await self._reschedule_all()

    def cog_unload(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    async def _reschedule_all(self) -> None:
        for event in db.list_events_for_reschedule():
            event_id = event["id"]
            if event["announcement_message_id"]:
                self.bot.add_view(
                    EventRegistrationView(self, event_id, disabled=_registrations_closed(event)),
                    message_id=event["announcement_message_id"],
                )
            if event["admin_message_id"]:
                self.bot.add_view(EventAdminView(self, event_id), message_id=event["admin_message_id"])
            if event["state"] == EVENT_OPEN and event["control_message_id"]:
                self.bot.add_view(
                    EventSkinSubmitView(self, event_id, disabled=_event_close_reached(event)),
                    message_id=event["control_message_id"],
                )
            if event["state"] == EVENT_OPEN and event["registration_close_at"]:
                self._schedule_registration_close(event)
            if event["state"] == EVENT_OPEN and event["submissions_close_at"]:
                self._schedule_submission_close(event)

        for member in db.list_pending_event_members_with_messages():
            self.bot.add_view(
                EventApprovalView(self, member["event_id"], member["user_id"]),
                message_id=member["approval_message_id"],
            )
        for submission in db.list_votable_event_submissions():
            event = db.get_event(submission["event_id"])
            if event is None:
                continue
            if event["state"] == EVENT_POPULAR_VOTE and submission["stage"] == SUBMISSION_ACTIVE:
                self.bot.add_view(EventPopularVoteView(self, submission["id"]), message_id=submission["message_id"])
            elif event["state"] == EVENT_ADMIN_VOTE and submission["stage"] == SUBMISSION_FINALIST:
                self.bot.add_view(EventAdminVoteView(self, submission["id"]), message_id=submission["message_id"])

    @app_commands.command(name="event", description="Crée un événement avec inscriptions")
    @app_commands.describe(nom="Nom de l'événement", preset="Preset optionnel")
    @app_commands.choices(preset=[app_commands.Choice(name=PRESET_SKIN_LABEL, value=PRESET_SKIN)])
    async def create_event(
        self,
        interaction: discord.Interaction,
        nom: str,
        preset: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        missing = self._missing_event_channels(interaction.guild)
        if missing:
            await interaction.response.send_message(
                "Configure d'abord les salons event avec `/config channel`: " + ", ".join(missing),
                ephemeral=True,
            )
            return
        registration_channel_id = db.get_guild_setting_int(interaction.guild.id, db.SETTING_EVENT_REGISTRATION_CHANNEL)
        if interaction.channel_id != registration_channel_id:
            channel = interaction.guild.get_channel(registration_channel_id) if registration_channel_id else None
            where = channel.mention if channel is not None else "le salon inscriptions event configuré"
            await interaction.response.send_message(f"Crée les events dans {where}.", ephemeral=True)
            return
        await interaction.response.send_modal(
            EventConfigModal(self, name=nom.strip(), preset=preset.value if preset else None)
        )

    async def create_configured_event(
        self,
        interaction: discord.Interaction,
        *,
        name: str,
        preset: Optional[str],
        theme: Optional[str],
        registration_close_at: datetime,
        submissions_close_at: Optional[datetime],
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Event impossible hors serveur.", ephemeral=True)
            return

        registration_channel = await self._configured_channel(guild, db.SETTING_EVENT_REGISTRATION_CHANNEL)
        admin_channel = await self._configured_channel(guild, db.SETTING_EVENT_ADMIN_CHANNEL)
        event_channel = await self._configured_channel(guild, db.SETTING_EVENT_CHANNEL)
        if registration_channel is None or admin_channel is None or event_channel is None:
            await interaction.followup.send(
                "Configuration event incomplète. Utilise `/config channel` pour les trois salons event.",
                ephemeral=True,
            )
            return

        event_id = db.create_event(
            guild_id=guild.id,
            name=name,
            preset=preset,
            theme=theme,
            created_by=interaction.user.id,
            state=EVENT_OPEN,
            registration_close_at=registration_close_at,
            submissions_close_at=submissions_close_at,
        )
        db.update_event(
            event_id,
            announcement_channel_id=registration_channel.id,
            admin_channel_id=admin_channel.id,
            channel_id=event_channel.id,
        )

        announcement = await registration_channel.send(
            embed=self._announcement_embed(db.get_event(event_id)),
            view=EventRegistrationView(self, event_id),
        )
        admin = await admin_channel.send(
            embed=self._admin_embed(db.get_event(event_id)),
            view=EventAdminView(self, event_id),
        )
        control_message_id = None
        if preset == PRESET_SKIN:
            control = await event_channel.send(
                embed=self._skin_submit_embed(db.get_event(event_id)),
                view=EventSkinSubmitView(self, event_id),
            )
            control_message_id = control.id

        db.update_event(
            event_id,
            announcement_message_id=announcement.id,
            admin_message_id=admin.id,
            control_message_id=control_message_id,
        )
        event = db.get_event(event_id)
        if event is not None:
            self.bot.add_view(EventRegistrationView(self, event_id), message_id=announcement.id)
            self.bot.add_view(EventAdminView(self, event_id), message_id=admin.id)
            if control_message_id is not None:
                self.bot.add_view(EventSkinSubmitView(self, event_id), message_id=control_message_id)
            self._schedule_registration_close(event)
            self._schedule_submission_close(event)

        await interaction.followup.send(
            f"Event **#{event_id}** créé.\n"
            f"Inscriptions: {registration_channel.mention}\n"
            f"Validation cash entry: {admin_channel.mention}\n"
            f"Dépôts/votes: {event_channel.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="event_submissions",
        description="Force la publication du vote populaire d'un event skin",
    )
    @app_commands.describe(event_id="ID de l'event")
    async def event_submissions(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_admin_event(interaction, event_id)
        if event is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        published = await self._publish_popular_vote(event_id, force=True)
        await interaction.followup.send(f"Vote populaire publié: **{published}** skin(s).", ephemeral=True)

    async def join_event(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_interaction_event(interaction, event_id)
        if event is None:
            return
        if _registrations_closed(event):
            await interaction.response.send_message("Les inscriptions sont fermées.", ephemeral=True)
            return
        if db.is_event_banned(event_id, interaction.user.id):
            await interaction.response.send_message("Tu es ban de cet event.", ephemeral=True)
            return

        existing = db.get_event_member(event_id, interaction.user.id)
        if existing is not None and existing["status"] == "approved":
            await interaction.response.send_message("Tu es déjà inscrit à cet event.", ephemeral=True)
            return
        if existing is not None and existing["status"] == "pending":
            await interaction.response.send_message(self._pending_registration_message(event), ephemeral=True)
            return

        db.add_event_member(event_id, interaction.user.id, status="pending")
        await self._send_registration_review(event, interaction.user)
        await interaction.response.send_message(self._pending_registration_message(event), ephemeral=True)
        await self._refresh_announcement(event_id)

    async def leave_event(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_interaction_event(interaction, event_id)
        if event is None:
            return
        removed = db.remove_event_member(event_id, interaction.user.id)
        await interaction.response.send_message(
            "Désinscription validée." if removed else "Tu n'étais pas inscrit à cet event.",
            ephemeral=True,
        )
        await self._refresh_announcement(event_id)

    async def approve_registration(
        self,
        interaction: discord.Interaction,
        event_id: int,
        user_id: int,
    ) -> None:
        event = await self._load_admin_event(interaction, event_id)
        if event is None:
            return
        if db.is_event_banned(event_id, user_id):
            await interaction.response.send_message("Ce membre est ban de l'event.", ephemeral=True)
            return
        registration = db.get_event_member(event_id, user_id)
        if registration is None:
            await interaction.response.send_message("Aucune demande d'inscription pour ce membre.", ephemeral=True)
            return

        changed = db.approve_event_member(event_id, user_id, interaction.user.id)
        await self._refresh_announcement(event_id)
        try:
            await interaction.message.edit(view=None)
        except discord.DiscordException:
            pass
        content = "Inscription validée." if changed else "Inscription déjà validée."
        await interaction.response.send_message(f"{content} <@{user_id}> peut déposer son skin.", ephemeral=True)

    async def open_skin_modal(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_interaction_event(interaction, event_id)
        if event is None:
            return
        if event["preset"] != PRESET_SKIN:
            await interaction.response.send_message("Cet event n'attend pas de lien Barbofus.", ephemeral=True)
            return
        if event["state"] != EVENT_OPEN or _event_close_reached(event):
            await interaction.response.send_message("Les dépôts sont fermés.", ephemeral=True)
            return
        if db.is_event_banned(event_id, interaction.user.id):
            await interaction.response.send_message("Tu es ban de cet event.", ephemeral=True)
            return
        if not db.is_event_member(event_id, interaction.user.id):
            await interaction.response.send_message("Ton inscription doit d'abord être validée.", ephemeral=True)
            return
        await interaction.response.send_modal(EventSubmitModal(self, event_id))

    async def submit_skin_link(
        self,
        interaction: discord.Interaction,
        event_id: int,
        raw_url: str,
    ) -> None:
        event = db.get_event(event_id)
        if event is None or interaction.guild is None or event["guild_id"] != interaction.guild.id:
            await interaction.response.send_message("Event introuvable.", ephemeral=True)
            return
        if event["state"] != EVENT_OPEN or _event_close_reached(event):
            await interaction.response.send_message("Les dépôts sont fermés.", ephemeral=True)
            return
        if db.is_event_banned(event_id, interaction.user.id):
            await interaction.response.send_message("Tu es ban de cet event.", ephemeral=True)
            return
        if not db.is_event_member(event_id, interaction.user.id):
            await interaction.response.send_message("Ton inscription doit d'abord être validée.", ephemeral=True)
            return

        try:
            link = parse_barbofus_skin_url(raw_url)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        image, reason = await capture_barbofus_page(link.url)
        if image is None:
            image = build_skin_fallback_card(link, reason).getvalue()
        db.upsert_event_submission(
            event_id=event_id,
            user_id=interaction.user.id,
            url=link.url,
            reference=link.reference,
            label=link.label,
            image=image,
            capture_reason=reason,
        )
        await interaction.followup.send(
            "Skin reçu anonymement. Tu peux le remplacer avant la fin du concours.",
            ephemeral=True,
        )

    async def vote_popular(self, interaction: discord.Interaction, submission_id: int) -> None:
        submission = db.get_event_submission(submission_id)
        if submission is None:
            await interaction.response.send_message("Participation introuvable.", ephemeral=True)
            return
        event = db.get_event(submission["event_id"])
        if event is None or interaction.guild is None or event["guild_id"] != interaction.guild.id:
            await interaction.response.send_message("Event introuvable.", ephemeral=True)
            return
        if event["state"] != EVENT_POPULAR_VOTE or submission["stage"] != SUBMISSION_ACTIVE:
            await interaction.response.send_message("Ce vote populaire n'est plus ouvert.", ephemeral=True)
            return
        db.cast_event_vote(event["id"], submission_id, interaction.user.id)
        await interaction.response.send_message("Vote enregistré.", ephemeral=True)
        await self._refresh_submission_message(submission_id, admin_vote=False)

    async def vote_admin(self, interaction: discord.Interaction, submission_id: int) -> None:
        submission = db.get_event_submission(submission_id)
        if submission is None:
            await interaction.response.send_message("Participation introuvable.", ephemeral=True)
            return
        event = db.get_event(submission["event_id"])
        if event is None or interaction.guild is None or event["guild_id"] != interaction.guild.id:
            await interaction.response.send_message("Event introuvable.", ephemeral=True)
            return
        if event["state"] != EVENT_ADMIN_VOTE or submission["stage"] != SUBMISSION_FINALIST:
            await interaction.response.send_message("Ce vote admin n'est plus ouvert.", ephemeral=True)
            return
        if not self._can_event_admin(interaction, event):
            await interaction.response.send_message("Permission admin event requise.", ephemeral=True)
            return
        db.cast_event_admin_vote(event["id"], submission_id, interaction.user.id)
        await interaction.response.send_message("Vote admin enregistré.", ephemeral=True)
        await self._refresh_submission_message(submission_id, admin_vote=True)

    async def close_registrations_now(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_admin_event(interaction, event_id)
        if event is None:
            return
        db.update_event(event_id, registration_close_at=now_paris())
        self._cancel_task(event_id, TASK_REGISTRATION_CLOSE)
        event = db.get_event(event_id)
        if event is not None:
            await self._disable_registration_buttons(event)
        await interaction.response.send_message("Inscriptions fermées.", ephemeral=True)

    async def close_popular_vote(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_admin_event(interaction, event_id)
        if event is None:
            return
        if event["state"] != EVENT_POPULAR_VOTE:
            await interaction.response.send_message("Le vote populaire n'est pas ouvert.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self._resolve_popular_round(event_id)
        await interaction.followup.send(result, ephemeral=True)

    async def publish_results(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_admin_event(interaction, event_id)
        if event is None:
            return
        if event["state"] != EVENT_ADMIN_VOTE:
            await interaction.response.send_message("Le vote admin n'est pas ouvert.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel = await self._get_channel(event["channel_id"])
        if channel is None:
            await interaction.followup.send("Salon event introuvable.", ephemeral=True)
            return

        finalists = db.list_event_submissions_by_stage(event_id, SUBMISSION_FINALIST)
        ranked = _rank_submissions(finalists, db.get_event_admin_vote_counts(event_id))
        target = _finalist_target(len(db.list_event_submissions(event_id)))
        embed = discord.Embed(title=f"Résultats · {event['name']}", color=0xF1C40F)
        if event["theme"]:
            embed.description = f"Thème: **{event['theme']}**"
        for rank, submission in enumerate(ranked[:target], start=1):
            embed.add_field(
                name=f"#{rank} · {submission['reference']}",
                value=(
                    f"Auteur: <@{submission['user_id']}>\n"
                    f"Votes admin: {db.count_event_admin_votes(submission['id'])}\n"
                    f"[Skin Barbofus]({submission['url']})"
                ),
                inline=False,
            )
        await channel.send(embed=embed)
        db.update_event(event_id, state=EVENT_DONE)
        await self._disable_registration_buttons(db.get_event(event_id))
        await interaction.followup.send("Résultats publiés.", ephemeral=True)

    async def open_ban_modal(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_admin_event(interaction, event_id)
        if event is None:
            return
        await interaction.response.send_modal(EventBanModal(self, event_id))

    async def open_cancel_modal(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_admin_event(interaction, event_id)
        if event is None:
            return
        await interaction.response.send_modal(EventCancelModal(self, event_id))

    async def ban_event_member(
        self,
        interaction: discord.Interaction,
        event_id: int,
        user_id: int,
        reason: Optional[str],
    ) -> None:
        event = await self._load_admin_event(interaction, event_id)
        if event is None:
            return
        db.ban_event_member(event_id=event_id, user_id=user_id, banned_by=interaction.user.id, reason=reason)
        await self._refresh_announcement(event_id)
        detail = f" Raison: {reason}" if reason else ""
        await interaction.response.send_message(f"<@{user_id}> est ban de l'event.{detail}", ephemeral=True)

    async def cancel_event(
        self,
        interaction: discord.Interaction,
        event_id: int,
        reason: Optional[str],
    ) -> None:
        event = await self._load_admin_event(interaction, event_id)
        if event is None:
            return
        db.update_event(
            event_id,
            state=EVENT_DONE,
            cancelled_by=interaction.user.id,
            cancel_reason=reason,
            cancelled_at=now_paris(),
        )
        self._cancel_task(event_id, TASK_REGISTRATION_CLOSE)
        self._cancel_task(event_id, TASK_SUBMISSIONS_CLOSE)
        event = db.get_event(event_id)
        if event is not None:
            await self._disable_registration_buttons(event)
            await self._delete_or_disable_submit_button(event)
            channel = await self._get_channel(event["channel_id"])
            if channel is not None:
                detail = f"\nRaison: {reason}" if reason else ""
                await channel.send(f"Event **{event['name']}** annulé par {interaction.user.mention}.{detail}")
        await interaction.response.send_message("Event annulé.", ephemeral=True)

    async def _send_registration_review(self, event, user) -> None:
        channel = await self._get_channel(event["admin_channel_id"])
        if channel is None:
            return
        message = await channel.send(
            embed=self._registration_review_embed(event, user),
            view=EventApprovalView(self, event["id"], user.id),
        )
        db.set_event_member_approval_message(event["id"], user.id, message.id)
        self.bot.add_view(EventApprovalView(self, event["id"], user.id), message_id=message.id)

    async def _resolve_popular_round(self, event_id: int) -> str:
        submissions = db.list_event_submissions(event_id)
        finalists = db.list_event_submissions_by_stage(event_id, SUBMISSION_FINALIST)
        active = db.list_event_submissions_by_stage(event_id, SUBMISSION_ACTIVE)
        target = _finalist_target(len(submissions))
        remaining = target - len(finalists)
        if remaining <= 0:
            await self._start_admin_vote(event_id)
            return "Finalistes déjà complets. Vote admin ouvert."
        if not active:
            await self._start_admin_vote(event_id)
            return "Aucune participation restante. Vote admin ouvert avec les finalistes existants."

        ranked = _rank_submissions(active, db.get_event_vote_counts(event_id))
        if len(ranked) <= remaining:
            for submission in ranked:
                db.set_event_submission_stage(submission["id"], SUBMISSION_FINALIST)
            await self._start_admin_vote(event_id)
            return "Finalistes complets. Vote admin ouvert."

        cutoff_votes = db.count_event_votes(ranked[remaining - 1]["id"])
        above = [submission for submission in ranked if db.count_event_votes(submission["id"]) > cutoff_votes]
        tied = [submission for submission in ranked if db.count_event_votes(submission["id"]) == cutoff_votes]
        below = [submission for submission in ranked if db.count_event_votes(submission["id"]) < cutoff_votes]
        tied_slots = remaining - len(above)

        if len(tied) == tied_slots:
            for submission in above + tied:
                db.set_event_submission_stage(submission["id"], SUBMISSION_FINALIST)
            for submission in below:
                db.set_event_submission_stage(submission["id"], SUBMISSION_ELIMINATED)
            await self._start_admin_vote(event_id)
            return "Finalistes complets. Vote admin ouvert."

        for submission in above:
            db.set_event_submission_stage(submission["id"], SUBMISSION_FINALIST)
        for submission in below:
            db.set_event_submission_stage(submission["id"], SUBMISSION_ELIMINATED)
        for submission in tied:
            db.set_event_submission_stage(submission["id"], SUBMISSION_ACTIVE)
        db.clear_event_votes(event_id)
        await self._disable_submission_vote_messages(active)
        await self._publish_popular_vote(event_id, force=True, intro="Départage populaire")
        return (
            f"Départage lancé: {len(above)} déjà qualifié(s), "
            f"{tied_slots} place(s) restante(s), {len(tied)} skin(s) en vote."
        )

    async def _start_admin_vote(self, event_id: int) -> None:
        event = db.get_event(event_id)
        if event is None:
            return
        db.update_event(event_id, state=EVENT_ADMIN_VOTE)
        finalists = db.list_event_submissions_by_stage(event_id, SUBMISSION_FINALIST)
        channel = await self._get_channel(event["channel_id"])
        if channel is None:
            return
        await channel.send(f"Vote admin ouvert pour **{event['name']}**.")
        for number, submission in enumerate(finalists, start=1):
            if submission["message_id"]:
                try:
                    message = await channel.fetch_message(submission["message_id"])
                    await message.edit(
                        embed=self._submission_embed(event, submission, number, admin_vote=True),
                        view=EventAdminVoteView(self, submission["id"]),
                    )
                except discord.DiscordException:
                    pass
                self.bot.add_view(EventAdminVoteView(self, submission["id"]), message_id=submission["message_id"])

    async def _publish_popular_vote(
        self,
        event_id: int,
        *,
        force: bool = False,
        intro: str = "Vote populaire",
    ) -> int:
        event = db.get_event(event_id)
        if event is None or event["preset"] != PRESET_SKIN:
            return 0
        if event["state"] == EVENT_DONE:
            return 0
        if event["state"] == EVENT_OPEN and not force and not _event_close_reached(event):
            return 0

        channel = await self._get_channel(event["channel_id"])
        if channel is None:
            logger.warning("Salon event #%d introuvable: %s", event_id, event["channel_id"])
            return 0

        if event["state"] == EVENT_OPEN:
            db.update_event(event_id, state=EVENT_POPULAR_VOTE)
            await self._delete_or_disable_submit_button(event)

        submissions = db.list_event_submissions_by_stage(event_id, SUBMISSION_ACTIVE)
        if not submissions:
            await channel.send("Dépôts fermés: aucune participation reçue.")
            return 0

        await channel.send(f"{intro} ouvert pour **{event['name']}**.")
        published = 0
        for number, submission in enumerate(submissions[:MAX_VOTING_BUTTONS], start=1):
            message = await channel.send(
                embed=self._submission_embed(event, submission, number),
                file=_submission_file(submission),
                view=EventPopularVoteView(self, submission["id"]),
            )
            db.set_event_submission_message(submission["id"], message.id)
            self.bot.add_view(EventPopularVoteView(self, submission["id"]), message_id=message.id)
            published += 1
        if len(submissions) > MAX_VOTING_BUTTONS:
            await channel.send(f"{len(submissions) - MAX_VOTING_BUTTONS} skin(s) non publiés: limite Discord.")
        return published

    async def _disable_submission_vote_messages(self, submissions) -> None:
        for submission in submissions:
            event = db.get_event(submission["event_id"])
            if event is None or not submission["message_id"]:
                continue
            channel = await self._get_channel(event["channel_id"])
            if channel is None:
                continue
            try:
                message = await channel.fetch_message(submission["message_id"])
                await message.edit(view=None)
            except discord.DiscordException:
                pass

    def _schedule_registration_close(self, event) -> None:
        self._cancel_task(event["id"], TASK_REGISTRATION_CLOSE)
        when = event["registration_close_at"]
        if not when:
            return
        delay = max(0.0, (_parse_when(when) - now_paris()).total_seconds())
        self._tasks[(event["id"], TASK_REGISTRATION_CLOSE)] = asyncio.create_task(
            self._run_registration_close(event["id"], delay)
        )

    def _schedule_submission_close(self, event) -> None:
        self._cancel_task(event["id"], TASK_SUBMISSIONS_CLOSE)
        when = event["submissions_close_at"]
        if not when:
            return
        delay = max(0.0, (_parse_when(when) - now_paris()).total_seconds())
        self._tasks[(event["id"], TASK_SUBMISSIONS_CLOSE)] = asyncio.create_task(
            self._run_submission_close(event["id"], delay)
        )

    async def _run_registration_close(self, event_id: int, delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            event = db.get_event(event_id)
            if event is not None and event["state"] != EVENT_DONE:
                await self._disable_registration_buttons(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Clôture inscriptions event #%d échouée", event_id)
        finally:
            self._tasks.pop((event_id, TASK_REGISTRATION_CLOSE), None)

    async def _run_submission_close(self, event_id: int, delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self._publish_popular_vote(event_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Clôture dépôts event #%d échouée", event_id)
        finally:
            self._tasks.pop((event_id, TASK_SUBMISSIONS_CLOSE), None)

    def _cancel_task(self, event_id: int, kind: str) -> None:
        task = self._tasks.pop((event_id, kind), None)
        if task is not None:
            task.cancel()

    async def _delete_or_disable_submit_button(self, event) -> None:
        if not event or not event["control_message_id"]:
            return
        channel = await self._get_channel(event["channel_id"])
        if channel is None:
            return
        message = None
        try:
            message = await channel.fetch_message(event["control_message_id"])
            await message.delete()
        except discord.DiscordException:
            if message is not None:
                try:
                    await message.edit(view=EventSkinSubmitView(self, event["id"], disabled=True))
                except discord.DiscordException:
                    pass

    async def _disable_registration_buttons(self, event) -> None:
        if not event or not event["announcement_message_id"]:
            return
        channel = await self._get_channel(event["announcement_channel_id"])
        if channel is None:
            return
        try:
            message = await channel.fetch_message(event["announcement_message_id"])
            await message.edit(
                embed=self._announcement_embed(event, registrations_closed=True),
                view=EventRegistrationView(self, event["id"], disabled=True),
            )
        except discord.DiscordException as exc:
            logger.warning("Désactivation boutons event #%d échouée: %s", event["id"], exc)

    async def _refresh_announcement(self, event_id: int) -> None:
        event = db.get_event(event_id)
        if event is None or not event["announcement_message_id"]:
            return
        channel = await self._get_channel(event["announcement_channel_id"])
        if channel is None:
            return
        try:
            message = await channel.fetch_message(event["announcement_message_id"])
            await message.edit(
                embed=self._announcement_embed(event),
                view=EventRegistrationView(
                    self,
                    event_id,
                    disabled=event["state"] == EVENT_DONE or _registrations_closed(event),
                ),
            )
        except discord.DiscordException as exc:
            logger.warning("Refresh annonce event #%d échoué: %s", event_id, exc)

    async def _refresh_submission_message(self, submission_id: int, *, admin_vote: bool) -> None:
        submission = db.get_event_submission(submission_id)
        if submission is None or not submission["message_id"]:
            return
        event = db.get_event(submission["event_id"])
        if event is None:
            return
        channel = await self._get_channel(event["channel_id"])
        if channel is None:
            return
        submissions = db.list_event_submissions(event["id"])
        number = next((idx for idx, item in enumerate(submissions, start=1) if item["id"] == submission_id), 1)
        try:
            message = await channel.fetch_message(submission["message_id"])
            await message.edit(embed=self._submission_embed(event, submission, number, admin_vote=admin_vote))
        except discord.DiscordException as exc:
            logger.warning("Refresh vote event submission #%d échoué: %s", submission_id, exc)

    async def _load_interaction_event(self, interaction: discord.Interaction, event_id: int):
        event = db.get_event(event_id)
        if event is None or interaction.guild is None or event["guild_id"] != interaction.guild.id:
            await interaction.response.send_message("Event introuvable.", ephemeral=True)
            return None
        if event["state"] == EVENT_DONE:
            await interaction.response.send_message("Cet event est terminé.", ephemeral=True)
            return None
        return event

    async def _load_admin_event(self, interaction: discord.Interaction, event_id: int):
        event = await self._load_interaction_event(interaction, event_id)
        if event is None:
            return None
        if not self._can_event_admin(interaction, event):
            await interaction.response.send_message("Permission admin event requise.", ephemeral=True)
            return None
        return event

    def _can_event_admin(self, interaction: discord.Interaction, _event) -> bool:
        return is_raid_organizer(interaction)

    def _missing_event_channels(self, guild: discord.Guild) -> list[str]:
        required = (
            ("event-inscription", db.SETTING_EVENT_REGISTRATION_CHANNEL),
            ("event-admin", db.SETTING_EVENT_ADMIN_CHANNEL),
            ("event", db.SETTING_EVENT_CHANNEL),
        )
        return [label for label, key in required if self._guild_channel(guild, key) is None]

    async def _configured_channel(self, guild: discord.Guild, key: str):
        channel_id = db.get_guild_setting_int(guild.id, key)
        if not channel_id:
            return None
        channel = guild.get_channel(channel_id)
        if channel is not None:
            return channel
        return await self._get_channel(channel_id)

    def _guild_channel(self, guild: discord.Guild, key: str):
        channel_id = db.get_guild_setting_int(guild.id, key)
        return guild.get_channel(channel_id) if channel_id else None

    async def _get_channel(self, channel_id: Optional[int]):
        if not channel_id:
            return None
        channel = self.bot.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await self.bot.fetch_channel(channel_id)
        except discord.DiscordException:
            return None

    def _pending_registration_message(self, event) -> str:
        lines = [
            "Inscription prise en compte.",
            "Un admin validera ton inscription une fois la cash entry payée.",
        ]
        contest_end = _contest_end_at(event)
        if contest_end is not None:
            lines.append(f"Fin du concours : {discord.utils.format_dt(contest_end, style='F')}.")
        return "\n".join(lines)

    def _announcement_embed(self, event, *, registrations_closed: bool = False) -> discord.Embed:
        embed = discord.Embed(title=f"Event #{event['id']} · {event['name']}", color=0x2ECC71)
        embed.add_field(name="Inscrits validés", value=str(db.count_event_members(event["id"])), inline=True)
        embed.add_field(name="En attente", value=str(db.count_pending_event_members(event["id"])), inline=True)
        embed.add_field(name="Preset", value=_preset_label(event["preset"]), inline=True)
        if event["theme"]:
            embed.add_field(name="Thème", value=event["theme"], inline=False)
        registration_close_at = _parse_optional_when(event["registration_close_at"])
        if registration_close_at:
            embed.add_field(
                name="Inscriptions jusqu'à",
                value=discord.utils.format_dt(registration_close_at, style="F"),
                inline=False,
            )
        contest_end = _contest_end_at(event)
        if contest_end:
            embed.add_field(name="Fin du concours", value=discord.utils.format_dt(contest_end, style="F"), inline=False)
        if event["state"] == EVENT_DONE:
            footer = "Event annulé/terminé."
        elif registrations_closed or _registrations_closed(event):
            footer = "Inscriptions fermées."
        else:
            footer = "Inscription via les boutons ci-dessous."
        embed.set_footer(text=footer)
        return embed

    def _admin_embed(self, event) -> discord.Embed:
        embed = discord.Embed(title=f"Admin event #{event['id']}", description=f"Event: **{event['name']}**", color=0xE67E22)
        embed.set_footer(text="Validation cash entry, clôtures, ban et résultats.")
        return embed

    def _registration_review_embed(self, event, user) -> discord.Embed:
        embed = discord.Embed(
            title="Inscription event en attente",
            description=f"Membre: {user.mention}\nValider après paiement de la cash entry.",
            color=0xF1C40F,
        )
        contest_end = _contest_end_at(event)
        if contest_end:
            embed.add_field(name="Fin du concours", value=discord.utils.format_dt(contest_end, style="F"), inline=False)
        embed.set_footer(text=f"Event #{event['id']}")
        return embed

    def _skin_submit_embed(self, event) -> discord.Embed:
        embed = discord.Embed(
            title=f"Dépôt skin · {event['name']}",
            description="Dépose ton lien Barbofus validé. Les skins seront affichés anonymement au vote populaire.",
            color=0x9B59B6,
        )
        if event["theme"]:
            embed.add_field(name="Thème", value=event["theme"], inline=False)
        contest_end = _contest_end_at(event)
        if contest_end:
            embed.add_field(name="Fin du concours", value=discord.utils.format_dt(contest_end, style="F"), inline=False)
        return embed

    def _submission_embed(self, event, submission, number: int, *, admin_vote: bool = False) -> discord.Embed:
        votes = db.count_event_admin_votes(submission["id"]) if admin_vote else db.count_event_votes(submission["id"])
        title = f"Finaliste #{number}" if admin_vote else f"Participation #{number}"
        embed = discord.Embed(title=title, description=f"[Ouvrir le skin Barbofus]({submission['url']})", color=0xF1C40F)
        embed.add_field(name="Référence", value=submission["reference"], inline=True)
        embed.add_field(name="Votes", value=str(votes), inline=True)
        embed.set_footer(text=f"Event #{event['id']} · auteur masqué jusqu'aux résultats")
        return embed


def build_skin_fallback_card(link: BarbofusSkinLink, reason: str | None = None) -> BytesIO:
    width, height = 900, 420
    image = Image.new("RGB", (width, height), "#2c3336")
    draw = ImageDraw.Draw(image)
    title_font, label_font, body_font, small_font = _load_fonts()

    _rounded(draw, (18, 18, width - 18, height - 18), "#354044", "#6b7a7f", 8)
    _rounded(draw, (42, 42, width - 42, 126), "#253034", "#7e8f95", 6)
    draw.text((64, 58), link.label, fill="#ffffff", font=title_font)
    draw.text((64, 92), "Barbofus unity-skin", fill="#c7d6d9", font=small_font)

    _rounded(draw, (42, 154, width - 42, 292), "#2b363a", "#647277", 8)
    draw.text((64, 174), "Capture automatique indisponible", fill="#ffe082", font=label_font)
    draw.text((64, 216), "Le lien reste valide pour consulter la participation.", fill="#ffffff", font=body_font)
    draw.text((64, 250), _ellipsize(link.url, 92), fill="#c7d6d9", font=small_font)

    _rounded(draw, (42, 326, width - 42, 374), "#20292c", "#647277", 6)
    draw.text((64, 340), _ellipsize(reason or "Carte générée depuis le lien Barbofus.", 100), fill="#ffffff", font=small_font)

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


def parse_deadline(raw: str, *, field_name: str, now: Optional[datetime] = None) -> datetime:
    current = now or now_paris()
    value = (raw or "").strip()
    if not value:
        raise ValueError(f"{field_name} vide")
    duration = _parse_duration(value.lower())
    if duration is not None:
        result = current + duration
    else:
        day = dates_utils.parse_raid_date(value, current)
        parsed_time = dates_utils.parse_time(value) or time(hour=23, minute=59)
        result = datetime.combine(day, parsed_time, tzinfo=current.tzinfo)
    if result <= current:
        raise ValueError(f"{field_name} doit être dans le futur")
    return result


def parse_submission_close(raw: str, *, now: Optional[datetime] = None) -> datetime:
    return parse_deadline(raw, field_name="fin du concours", now=now)


def parse_user_id(raw: str) -> int:
    match = re.search(r"\d{15,25}", raw or "")
    if match is None:
        raise ValueError("Membre invalide: donne une mention ou un ID Discord.")
    return int(match.group(0))


def _parse_duration(value: str) -> Optional[timedelta]:
    match = re.fullmatch(r"(\d+)\s*([a-z]*)", value)
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2) or "h"
    if amount <= 0:
        raise ValueError("la durée doit être positive")
    if unit in {"h", "heure", "heures"}:
        return timedelta(hours=amount)
    if unit in {"j", "d", "jour", "jours", "day", "days"}:
        return timedelta(days=amount)
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return timedelta(minutes=amount)
    return None


def _submission_file(submission) -> Optional[discord.File]:
    image = submission["image"]
    if image is None:
        return None
    return discord.File(BytesIO(image), filename=f"event-skin-{submission['id']}.png")


def _rank_submissions(submissions, counts: dict[int, int]) -> list:
    return sorted(submissions, key=lambda item: (-counts.get(item["id"], 0), item["id"]))


def _finalist_target(submission_count: int) -> int:
    if submission_count <= 0:
        return 0
    if submission_count <= 5:
        return min(3, submission_count)
    if submission_count <= 10:
        return 5
    return 10


def _event_close_reached(event) -> bool:
    when = _parse_optional_when(event["submissions_close_at"])
    return bool(when and now_paris() >= when)


def _registrations_closed(event) -> bool:
    when = _parse_optional_when(event["registration_close_at"])
    return bool(when and now_paris() >= when)


def _contest_end_at(event):
    return _parse_optional_when(event["submissions_close_at"]) or _parse_optional_when(event["registration_close_at"])


def _parse_optional_when(value: Optional[str]):
    return _parse_when(value) if value else None


def _parse_when(value: str):
    return datetime.fromisoformat(value)


def _preset_label(preset: Optional[str]) -> str:
    if preset == PRESET_SKIN:
        return PRESET_SKIN_LABEL
    return "aucun"


def _load_fonts() -> tuple[ImageFont.ImageFont, ...]:
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        return (
            ImageFont.truetype(bold_path, 24),
            ImageFont.truetype(bold_path, 18),
            ImageFont.truetype(font_path, 17),
            ImageFont.truetype(font_path, 14),
        )
    except OSError:
        fallback = ImageFont.load_default()
        return fallback, fallback, fallback, fallback


def _rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str, radius: int) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)


def _ellipsize(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


async def setup(bot: commands.Bot):
    await bot.add_cog(EventCog(bot))
