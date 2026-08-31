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
from utils.perms import is_bot_admin
from utils.stuff_capture import capture_barbofus_page

logger = logging.getLogger(__name__)

PRESET_SKIN = "skin_contest"
PRESET_SKIN_LABEL = "concours de skin"
EVENT_ADMIN_ROLE_NAME = "admin_event"
EVENT_OPEN = "open"
EVENT_VOTING = "voting"
EVENT_DONE = "done"
BARBOFUS_HOSTS = {"barbofus.com", "www.barbofus.com"}
BARBOFUS_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?barbofus\.com/unity-skin/\S+",
    re.IGNORECASE,
)
TRAILING_URL_PUNCTUATION = ".,;:!?)>]}"
MAX_VOTING_BUTTONS = 25
TASK_SUBMISSIONS_CLOSE = "submissions_close"
TASK_EVENT_END = "event_end"


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
    host = parsed.netloc.lower()
    if host not in BARBOFUS_HOSTS:
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
        self.end_input = discord.ui.TextInput(
            label="Fin de l'event",
            placeholder="ex: dimanche 23h, 31/08 21h, demain 20h",
            required=True,
            max_length=80,
        )
        self.add_item(self.end_input)
        self.submissions_input: Optional[discord.ui.TextInput] = None
        if preset == PRESET_SKIN:
            self.submissions_input = discord.ui.TextInput(
                label="Durée/fin des dépôts",
                placeholder="ex: 48h, 3j, demain 21h",
                required=True,
                max_length=80,
            )
            self.add_item(self.submissions_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            event_end_at = parse_event_datetime(str(self.end_input.value))
            submissions_close_at = None
            if self.submissions_input is not None:
                submissions_close_at = parse_submission_close(
                    str(self.submissions_input.value),
                    event_end_at=event_end_at,
                )
        except ValueError as exc:
            await interaction.response.send_message(f"Date invalide : {exc}", ephemeral=True)
            return

        await self.cog.create_configured_event(
            interaction,
            name=self.name,
            preset=self.preset,
            event_end_at=event_end_at,
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
        await self.cog.submit_skin_link(
            interaction,
            self.event_id,
            str(self.link_input.value),
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


class _SubmitSkinButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", event_id: int, *, disabled: bool = False):
        super().__init__(
            label="Déposer mon lien",
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


class _VoteSubmissionButton(discord.ui.Button):
    def __init__(self, cog: "EventCog", submission_id: int):
        super().__init__(
            label="Voter",
            style=discord.ButtonStyle.success,
            custom_id=f"bebraid:event:vote:{submission_id}",
        )
        self.cog = cog
        self.submission_id = submission_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.vote_submission(interaction, self.submission_id)


class EventVoteView(discord.ui.View):
    def __init__(self, cog: "EventCog", submission_id: int):
        super().__init__(timeout=None)
        self.add_item(_VoteSubmissionButton(cog, submission_id))


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
                    EventRegistrationView(self, event_id),
                    message_id=event["announcement_message_id"],
                )
            if event["state"] == EVENT_OPEN and event["control_message_id"]:
                self.bot.add_view(
                    EventSkinSubmitView(self, event_id),
                    message_id=event["control_message_id"],
                )
            if event["state"] in (EVENT_OPEN, EVENT_VOTING) and event["event_end_at"]:
                self._schedule_event_end(event)
            if event["state"] == EVENT_OPEN and event["submissions_close_at"]:
                self._schedule_submission_close(event)

        for submission in db.list_votable_event_submissions():
            self.bot.add_view(
                EventVoteView(self, submission["id"]),
                message_id=submission["message_id"],
            )

    @app_commands.command(name="event", description="Crée un événement avec inscriptions")
    @app_commands.describe(
        nom="Nom de l'événement",
        preset="Preset optionnel",
    )
    @app_commands.choices(
        preset=[app_commands.Choice(name=PRESET_SKIN_LABEL, value=PRESET_SKIN)]
    )
    async def create_event(
        self,
        interaction: discord.Interaction,
        nom: str,
        preset: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        if not is_bot_admin(interaction):
            await interaction.response.send_message(
                "Seuls les admins bot peuvent créer un event.",
                ephemeral=True,
            )
            return
        if interaction.channel is None or not hasattr(interaction.channel, "send"):
            await interaction.response.send_message("Salon de création introuvable.", ephemeral=True)
            return

        await interaction.response.send_modal(
            EventConfigModal(
                self,
                name=nom.strip(),
                preset=preset.value if preset else None,
            )
        )

    async def create_configured_event(
        self,
        interaction: discord.Interaction,
        *,
        name: str,
        preset: Optional[str],
        event_end_at: datetime,
        submissions_close_at: Optional[datetime],
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        if guild is None or interaction.channel is None:
            await interaction.followup.send("Event impossible hors serveur.", ephemeral=True)
            return
        event_preset = preset
        event_id = db.create_event(
            guild_id=guild.id,
            name=name,
            preset=event_preset,
            created_by=interaction.user.id,
            state=EVENT_OPEN,
            event_end_at=event_end_at,
            submissions_close_at=submissions_close_at,
        )

        warning = None
        try:
            participant_role = await guild.create_role(
                name=f"event_{event_id}",
                mentionable=False,
                reason=f"Event #{event_id} créé par {interaction.user}",
            )
            admin_role = await self._get_or_create_admin_role(guild)
            await self._grant_event_admin_role(interaction, admin_role)
            channel = await self._create_event_channel(
                guild,
                event_id=event_id,
                event_name=name,
                participant_role=participant_role,
                admin_role=admin_role,
                anchor_channel=interaction.channel,
            )
        except discord.Forbidden:
            db.update_event(event_id, state=EVENT_DONE)
            await interaction.followup.send(
                "Je n'ai pas les permissions pour créer les rôles/salons de cet event.",
                ephemeral=True,
            )
            return
        except discord.DiscordException as exc:
            db.update_event(event_id, state=EVENT_DONE)
            await interaction.followup.send(f"Création de l'event impossible: `{exc}`", ephemeral=True)
            return

        db.update_event(
            event_id,
            participant_role_id=participant_role.id,
            admin_role_id=admin_role.id,
            channel_id=channel.id,
            announcement_channel_id=interaction.channel.id,
        )

        announcement = await interaction.channel.send(
            embed=self._announcement_embed(
                event_id=event_id,
                name=name,
                preset=event_preset,
                participant_count=0,
                submissions_close_at=submissions_close_at,
                event_end_at=event_end_at,
            ),
            view=EventRegistrationView(self, event_id),
        )
        db.update_event(event_id, announcement_message_id=announcement.id)
        self.bot.add_view(EventRegistrationView(self, event_id), message_id=announcement.id)

        control_message_id = None
        await channel.send(embed=self._event_channel_embed(event_id, name, participant_role, event_end_at))
        if event_preset == PRESET_SKIN:
            control = await channel.send(
                embed=self._skin_submit_embed(event_id, name, submissions_close_at),
                view=EventSkinSubmitView(self, event_id),
            )
            control_message_id = control.id
            self.bot.add_view(EventSkinSubmitView(self, event_id), message_id=control.id)
            event = db.get_event(event_id)
            if event is not None:
                self._schedule_submission_close(event)

        db.update_event(event_id, control_message_id=control_message_id)
        event = db.get_event(event_id)
        if event is not None:
            self._schedule_event_end(event)
        if warning is None:
            await interaction.followup.send(
                f"Event **#{event_id}** créé: {channel.mention}. "
                f"Rôle participants: {participant_role.mention}. "
                f"Rôle vote admin: {admin_role.mention}.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Event **#{event_id}** créé: {channel.mention}. {warning}",
                ephemeral=True,
            )

    @app_commands.command(
        name="event_submissions",
        description="Publie les participations anonymes d'un event skin pour le vote admin",
    )
    @app_commands.describe(event_id="ID de l'event")
    async def event_submissions(
        self,
        interaction: discord.Interaction,
        event_id: int,
    ) -> None:
        event = db.get_event(event_id)
        if event is None or interaction.guild is None or event["guild_id"] != interaction.guild.id:
            await interaction.response.send_message("Event introuvable.", ephemeral=True)
            return
        if not self._can_event_admin(interaction, event):
            await interaction.response.send_message("Rôle admin_event requis.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        published = await self._publish_skin_submissions(event_id, force=is_bot_admin(interaction))
        if published == -1:
            await interaction.followup.send(
                "Les dépôts ne sont pas encore fermés pour cet event.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Participations publiées pour le vote admin: **{published}**.",
            ephemeral=True,
        )

    async def join_event(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_interaction_event(interaction, event_id)
        if event is None:
            return
        role = interaction.guild.get_role(event["participant_role_id"])
        if role is None:
            await interaction.response.send_message("Rôle event introuvable.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Inscription possible uniquement en serveur.", ephemeral=True)
            return

        db.add_event_member(event_id, interaction.user.id)
        try:
            await interaction.user.add_roles(role, reason=f"Inscription event #{event_id}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "Inscription enregistrée, mais je ne peux pas donner le rôle event.",
                ephemeral=True,
            )
            await self._refresh_announcement(event_id)
            return
        await interaction.response.send_message(
            f"Inscription validée. Le salon event est accessible via le rôle {role.mention}.",
            ephemeral=True,
        )
        await self._refresh_announcement(event_id)

    async def leave_event(self, interaction: discord.Interaction, event_id: int) -> None:
        event = await self._load_interaction_event(interaction, event_id)
        if event is None:
            return
        role = interaction.guild.get_role(event["participant_role_id"])
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Désinscription possible uniquement en serveur.", ephemeral=True)
            return

        db.remove_event_member(event_id, interaction.user.id)
        if role is not None:
            try:
                await interaction.user.remove_roles(role, reason=f"Désinscription event #{event_id}")
            except discord.Forbidden:
                await interaction.response.send_message(
                    "Désinscription enregistrée, mais je ne peux pas retirer le rôle event.",
                    ephemeral=True,
                )
                await self._refresh_announcement(event_id)
                return
        await interaction.response.send_message("Désinscription validée.", ephemeral=True)
        await self._refresh_announcement(event_id)

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
        if not db.is_event_member(event_id, interaction.user.id):
            await interaction.response.send_message("Inscris-toi d'abord à l'event.", ephemeral=True)
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
        if not db.is_event_member(event_id, interaction.user.id):
            await interaction.response.send_message("Inscris-toi d'abord à l'event.", ephemeral=True)
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
            "Lien reçu anonymement. Tu peux le remplacer en redéposant un lien avant la fermeture.",
            ephemeral=True,
        )

    async def vote_submission(self, interaction: discord.Interaction, submission_id: int) -> None:
        submission = db.get_event_submission(submission_id)
        if submission is None:
            await interaction.response.send_message("Participation introuvable.", ephemeral=True)
            return
        event = db.get_event(submission["event_id"])
        if event is None or interaction.guild is None or event["guild_id"] != interaction.guild.id:
            await interaction.response.send_message("Event introuvable.", ephemeral=True)
            return
        if event["state"] != EVENT_VOTING:
            await interaction.response.send_message("Le vote n'est pas ouvert.", ephemeral=True)
            return
        if not self._has_event_admin_role(interaction, event):
            await interaction.response.send_message("Rôle admin_event requis.", ephemeral=True)
            return

        db.cast_event_vote(event["id"], submission_id, interaction.user.id)
        await interaction.response.send_message("Vote enregistré.", ephemeral=True)
        await self._refresh_submission_message(submission_id)

    async def _load_interaction_event(
        self,
        interaction: discord.Interaction,
        event_id: int,
    ) -> Optional[db.sqlite3.Row]:
        event = db.get_event(event_id)
        if event is None or interaction.guild is None or event["guild_id"] != interaction.guild.id:
            await interaction.response.send_message("Event introuvable.", ephemeral=True)
            return None
        if _event_end_reached(event):
            db.update_event(event_id, state=EVENT_DONE)
            await interaction.response.send_message("Cet event est terminé.", ephemeral=True)
            return None
        if event["state"] == EVENT_DONE:
            await interaction.response.send_message("Cet event est terminé.", ephemeral=True)
            return None
        return event

    async def _get_or_create_admin_role(self, guild: discord.Guild) -> discord.Role:
        existing = discord.utils.get(guild.roles, name=EVENT_ADMIN_ROLE_NAME)
        if existing is not None:
            return existing
        return await guild.create_role(
            name=EVENT_ADMIN_ROLE_NAME,
            mentionable=False,
            reason="Rôle de vote admin event",
        )

    async def _grant_event_admin_role(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ) -> None:
        if not isinstance(interaction.user, discord.Member):
            return
        try:
            await interaction.user.add_roles(role, reason="Créateur de l'event")
        except discord.DiscordException as exc:
            logger.warning("Impossible de donner %s au créateur event: %s", role, exc)

    async def _create_event_channel(
        self,
        guild: discord.Guild,
        *,
        event_id: int,
        event_name: str,
        participant_role: discord.Role,
        admin_role: discord.Role,
        anchor_channel: discord.abc.GuildChannel,
    ) -> discord.TextChannel:
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            participant_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                read_message_history=True,
            ),
            admin_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                manage_messages=True,
                read_message_history=True,
            ),
        }
        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                manage_channels=True,
                manage_roles=True,
                read_message_history=True,
            )
        channel = await guild.create_text_channel(
            name=_safe_event_channel_name(event_id, event_name),
            overwrites=overwrites,
            category=getattr(anchor_channel, "category", None),
            reason=f"Création event #{event_id}",
        )
        anchor_position = getattr(anchor_channel, "position", None)
        if isinstance(anchor_position, int):
            try:
                await channel.edit(
                    position=anchor_position + 1,
                    reason=f"Placement event #{event_id} sous le salon de création",
                )
            except discord.DiscordException as exc:
                logger.warning("Placement salon event #%d échoué: %s", event_id, exc)
        return channel

    def _schedule_submission_close(self, event) -> None:
        event_id = event["id"]
        self._cancel_task(event_id, TASK_SUBMISSIONS_CLOSE)
        when = event["submissions_close_at"]
        if not when:
            return
        delay = max(0.0, (_parse_when(when) - now_paris()).total_seconds())
        self._tasks[(event_id, TASK_SUBMISSIONS_CLOSE)] = asyncio.create_task(
            self._run_submission_close(event_id, delay)
        )

    def _schedule_event_end(self, event) -> None:
        event_id = event["id"]
        self._cancel_task(event_id, TASK_EVENT_END)
        when = event["event_end_at"]
        if not when:
            return
        delay = max(0.0, (_parse_when(when) - now_paris()).total_seconds())
        self._tasks[(event_id, TASK_EVENT_END)] = asyncio.create_task(
            self._run_event_end(event_id, delay)
        )

    async def _run_submission_close(self, event_id: int, delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self._publish_skin_submissions(event_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Clôture dépôts event #%d échouée", event_id)
        finally:
            self._tasks.pop((event_id, TASK_SUBMISSIONS_CLOSE), None)

    async def _run_event_end(self, event_id: int, delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self._finish_event(event_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Fin event #%d échouée", event_id)
        finally:
            self._tasks.pop((event_id, TASK_EVENT_END), None)

    def _cancel_task(self, event_id: int, kind: str) -> None:
        task = self._tasks.pop((event_id, kind), None)
        if task is not None:
            task.cancel()

    async def _finish_event(self, event_id: int) -> None:
        event = db.get_event(event_id)
        if event is None or event["state"] == EVENT_DONE:
            return
        if event["state"] == EVENT_OPEN and event["preset"] == PRESET_SKIN:
            await self._publish_skin_submissions(event_id, force=True)
        event = db.get_event(event_id)
        if event is None or event["state"] == EVENT_DONE:
            return
        db.update_event(event_id, state=EVENT_DONE)
        self._cancel_task(event_id, TASK_SUBMISSIONS_CLOSE)
        await self._disable_submit_button(event)
        await self._disable_registration_buttons(event)
        channel = await self._get_channel(event["channel_id"])
        if channel is not None:
            await channel.send(f"Event **{event['name']}** terminé.")

    async def _publish_skin_submissions(self, event_id: int, *, force: bool = False) -> int:
        event = db.get_event(event_id)
        if event is None or event["preset"] != PRESET_SKIN:
            return 0
        if event["state"] == EVENT_DONE:
            return 0
        if event["state"] == EVENT_OPEN and not force and not _event_close_reached(event):
            return -1
        channel = await self._get_channel(event["channel_id"])
        if channel is None:
            logger.warning("Salon event #%d introuvable: %s", event_id, event["channel_id"])
            return 0

        if event["state"] == EVENT_OPEN:
            db.update_event(event_id, state=EVENT_VOTING)
            await self._disable_submit_button(event)
        submissions = db.list_event_submissions(event_id)
        if not submissions:
            await channel.send("Dépôts fermés: aucune participation reçue.")
            return 0

        await channel.send(
            f"Dépôts fermés pour **{event['name']}**. Vote admin ouvert pour "
            f"{min(len(submissions), MAX_VOTING_BUTTONS)} participation(s)."
        )
        published = 0
        for number, submission in enumerate(submissions[:MAX_VOTING_BUTTONS], start=1):
            if submission["message_id"]:
                self.bot.add_view(EventVoteView(self, submission["id"]), message_id=submission["message_id"])
                published += 1
                continue
            message = await channel.send(
                embed=self._submission_embed(event, submission, number),
                file=_submission_file(submission),
                view=EventVoteView(self, submission["id"]),
            )
            db.set_event_submission_message(submission["id"], message.id)
            self.bot.add_view(EventVoteView(self, submission["id"]), message_id=message.id)
            published += 1
        if len(submissions) > MAX_VOTING_BUTTONS:
            await channel.send(
                f"{len(submissions) - MAX_VOTING_BUTTONS} participation(s) non publiées: limite Discord de "
                f"{MAX_VOTING_BUTTONS} boutons par vague."
            )
        return published

    async def _disable_submit_button(self, event) -> None:
        if not event["control_message_id"]:
            return
        channel = await self._get_channel(event["channel_id"])
        if channel is None:
            return
        try:
            message = await channel.fetch_message(event["control_message_id"])
            await message.edit(view=EventSkinSubmitView(self, event["id"], disabled=True))
        except discord.DiscordException as exc:
            logger.warning("Désactivation bouton dépôt event #%d échouée: %s", event["id"], exc)

    async def _disable_registration_buttons(self, event) -> None:
        if not event["announcement_message_id"]:
            return
        channel = await self._get_channel(event["announcement_channel_id"])
        if channel is None:
            return
        try:
            message = await channel.fetch_message(event["announcement_message_id"])
            await message.edit(
                embed=self._announcement_embed(
                    event_id=event["id"],
                    name=event["name"],
                    preset=event["preset"],
                    participant_count=db.count_event_members(event["id"]),
                    submissions_close_at=_parse_optional_when(event["submissions_close_at"]),
                    event_end_at=_parse_optional_when(event["event_end_at"]),
                    ended=True,
                ),
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
                embed=self._announcement_embed(
                    event_id=event_id,
                    name=event["name"],
                    preset=event["preset"],
                    participant_count=db.count_event_members(event_id),
                    submissions_close_at=_parse_optional_when(event["submissions_close_at"]),
                    event_end_at=_parse_optional_when(event["event_end_at"]),
                    ended=event["state"] == EVENT_DONE,
                ),
                view=EventRegistrationView(self, event_id, disabled=event["state"] == EVENT_DONE),
            )
        except discord.DiscordException as exc:
            logger.warning("Refresh annonce event #%d échoué: %s", event_id, exc)

    async def _refresh_submission_message(self, submission_id: int) -> None:
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
        number = next(
            (idx for idx, item in enumerate(submissions, start=1) if item["id"] == submission_id),
            submission_id,
        )
        try:
            message = await channel.fetch_message(submission["message_id"])
            await message.edit(embed=self._submission_embed(event, submission, number))
        except discord.DiscordException as exc:
            logger.warning("Refresh vote event submission #%d échoué: %s", submission_id, exc)

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

    def _can_event_admin(self, interaction: discord.Interaction, event) -> bool:
        if is_bot_admin(interaction):
            return True
        return self._has_event_admin_role(interaction, event)

    def _has_event_admin_role(self, interaction: discord.Interaction, event) -> bool:
        admin_role_id = event["admin_role_id"]
        roles = getattr(interaction.user, "roles", None) or []
        return any(getattr(role, "id", None) == admin_role_id for role in roles)

    def _announcement_embed(
        self,
        *,
        event_id: int,
        name: str,
        preset: Optional[str],
        participant_count: int,
        submissions_close_at,
        event_end_at,
        ended: bool = False,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"Event #{event_id} · {name}",
            color=0x95A5A6 if ended else 0x2ECC71,
        )
        embed.add_field(name="Participants", value=str(participant_count), inline=True)
        embed.add_field(name="Preset", value=_preset_label(preset), inline=True)
        if event_end_at:
            embed.add_field(
                name="Fin de l'event",
                value=discord.utils.format_dt(event_end_at, style="F"),
                inline=False,
            )
        if submissions_close_at:
            embed.add_field(
                name="Dépôts jusqu'à",
                value=discord.utils.format_dt(submissions_close_at, style="F"),
                inline=False,
            )
        footer = "Event terminé." if ended else "Inscription via les boutons ci-dessous."
        embed.set_footer(text=footer)
        return embed

    def _event_channel_embed(
        self,
        event_id: int,
        name: str,
        participant_role: discord.Role,
        event_end_at: datetime,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"Salon event #{event_id}",
            description=(
                f"Event: **{name}**\n"
                f"Accès participants: {participant_role.mention}\n"
                f"Fin: {discord.utils.format_dt(event_end_at, style='F')}"
            ),
            color=0x3498DB,
        )
        return embed

    def _skin_submit_embed(self, event_id: int, name: str, submissions_close_at) -> discord.Embed:
        embed = discord.Embed(
            title="Concours de skin",
            description=(
                f"Event: **{name}**\n"
                "Dépose ton lien Barbofus ici. Le bot garde le dépôt anonyme pour l'affichage du vote."
            ),
            color=0x9B59B6,
        )
        if submissions_close_at:
            embed.add_field(
                name="Fermeture des dépôts",
                value=discord.utils.format_dt(submissions_close_at, style="F"),
                inline=False,
            )
        embed.set_footer(text=f"Event #{event_id}")
        return embed

    def _submission_embed(self, event, submission, number: int) -> discord.Embed:
        count = db.count_event_votes(submission["id"])
        embed = discord.Embed(
            title=f"Participation #{number}",
            description=f"[Ouvrir le skin Barbofus]({submission['url']})",
            color=0xF1C40F,
        )
        embed.add_field(name="Référence", value=submission["reference"], inline=True)
        embed.add_field(name="Votes", value=str(count), inline=True)
        embed.set_footer(text=f"Event #{event['id']} · vote anonyme côté participants")
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


def _submission_file(submission) -> Optional[discord.File]:
    image = submission["image"]
    if image is None:
        return None
    return discord.File(BytesIO(image), filename=f"event-skin-{submission['id']}.png")


def _safe_event_channel_name(event_id: int, event_name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", event_name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:42] or "event"
    return f"event-{event_id}-{slug}"


def _preset_label(preset: Optional[str]) -> str:
    if preset == PRESET_SKIN:
        return PRESET_SKIN_LABEL
    return "aucun"


def parse_event_datetime(raw: str, *, now: Optional[datetime] = None) -> datetime:
    current = now or now_paris()
    value = (raw or "").strip()
    if not value:
        raise ValueError("fin de l'event vide")
    if _parse_duration(value.lower()) is not None:
        raise ValueError("la fin de l'event doit être une date, pas une durée")
    day = dates_utils.parse_raid_date(value, current)
    parsed_time = dates_utils.parse_time(value) or time(hour=23, minute=59)
    result = datetime.combine(day, parsed_time, tzinfo=current.tzinfo)
    if result <= current:
        raise ValueError("la fin de l'event doit être dans le futur")
    return result


def parse_submission_close(
    raw: str,
    *,
    event_end_at: datetime,
    now: Optional[datetime] = None,
) -> datetime:
    current = now or now_paris()
    value = (raw or "").strip().lower()
    if not value:
        raise ValueError("durée/fin des dépôts vide")

    duration = _parse_duration(value)
    if duration is not None:
        result = current + duration
    else:
        result = parse_event_datetime(value, now=current)

    if result >= event_end_at:
        raise ValueError("les dépôts doivent fermer avant la fin de l'event")
    return result


def _parse_duration(value: str) -> Optional[timedelta]:
    match = re.fullmatch(r"(\d+)\s*([a-z]*)", value)
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2) or "h"
    if amount <= 0:
        raise ValueError("la durée des dépôts doit être positive")
    if unit in {"h", "heure", "heures"}:
        return timedelta(hours=amount)
    if unit in {"j", "d", "jour", "jours", "day", "days"}:
        return timedelta(days=amount)
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return timedelta(minutes=amount)
    return None


def _event_close_reached(event) -> bool:
    when = _parse_optional_when(event["submissions_close_at"])
    return bool(when and now_paris() >= when)


def _event_end_reached(event) -> bool:
    when = _parse_optional_when(event["event_end_at"])
    return bool(when and now_paris() >= when)


def _parse_optional_when(value: Optional[str]):
    return _parse_when(value) if value else None


def _parse_when(value: str):
    return datetime.fromisoformat(value)


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


def _rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str,
    radius: int,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)


def _ellipsize(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


async def setup(bot: commands.Bot):
    await bot.add_cog(EventCog(bot))
