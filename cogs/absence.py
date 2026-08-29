"""Déclarations d'absence via bouton + formulaire."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from config import PARIS, now_paris
from utils import dates as dates_utils
from utils.perms import is_raid_organizer

logger = logging.getLogger("dofus-raid-bot.absence")


def _user_display(user: discord.abc.User) -> str:
    return getattr(user, "display_name", None) or user.name


def _format_absence_period(start: date, end: date) -> str:
    start, end = _ordered_absence_dates(start, end)
    if start == end:
        return f"Le {dates_utils.format_date_fr(start)}"
    return f"Du {dates_utils.format_date_fr(start)} au {dates_utils.format_date_fr(end)}"


def _ordered_absence_dates(start: date, end: date) -> tuple[date, date]:
    return (end, start) if end < start else (start, end)


def _cleanup_when(end: date) -> datetime:
    return datetime.combine(end + timedelta(days=1), time.min, tzinfo=PARIS)


def _channel_label(channel: discord.abc.Messageable) -> str:
    return getattr(channel, "mention", None) or f"`{getattr(channel, 'id', 'salon')}`"


def _is_messageable(channel: object) -> bool:
    return isinstance(channel, discord.abc.Messageable) or callable(getattr(channel, "send", None))


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


def _kick_abs_message(user: discord.abc.User) -> str:
    return (
        f"{user.mention}, tu as été kick de la guilde pour afk, "
        "n'hésite pas à repostuler quand tu recommences à jouer."
    )


def _role_label(role: object) -> str:
    return getattr(role, "mention", None) or getattr(role, "name", None) or f"`{getattr(role, 'id', 'rôle')}`"


def _format_return_delay(end: date, today: date) -> str:
    days = (today - end).days
    suffix = "" if abs(days) == 1 else "s"
    if days <= 0:
        return "Retour prévu aujourd'hui" if days == 0 else f"Retour prévu dans {-days} jour{suffix}"
    return f"Retour prévu dépassé depuis {days} jour{suffix}"


def _search_absences_embed(
    rows: list,
    title: str = "Absences",
    *,
    today: Optional[date] = None,
    empty_description: str = "Aucune absence active ou à venir.",
) -> discord.Embed:
    embed = discord.Embed(title=title, color=0xF1C40F)
    if not rows:
        embed.description = empty_description
        return embed

    today = today or now_paris().date()
    for row in rows[:20]:
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"])
        value = _format_absence_period(start, end)
        if end < today:
            value = f"{value}\n{_format_return_delay(end, today)}"
        embed.add_field(
            name=f"#{row['id']} - {row['user_display']}",
            value=value,
            inline=False,
        )
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
    absence = app_commands.Group(name="absence", description="Gestion des absences")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cleanup_tasks: dict[int, asyncio.Task] = {}
        self._bootstrap_task: Optional[asyncio.Task] = None

    async def cog_load(self) -> None:
        self.bot.add_view(AbsenceView(self))
        self._bootstrap_task = asyncio.create_task(self._bootstrap_cleanup())
        logger.info("AbsenceCog prêt")

    async def cog_unload(self) -> None:
        if self._bootstrap_task is not None:
            self._bootstrap_task.cancel()
        for task in self._cleanup_tasks.values():
            task.cancel()
        self._cleanup_tasks.clear()

    async def _bootstrap_cleanup(self) -> None:
        try:
            await self.bot.wait_until_ready()
            for absence in db.list_absences_for_cleanup():
                self._schedule_cleanup(absence["id"], date.fromisoformat(absence["end_date"]))
            logger.info("%d absence(s) avec cleanup rechargée(s)", len(self._cleanup_tasks))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Bootstrap cleanup absences échoué: %s", exc)

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
        return channel if _is_messageable(channel) else None

    async def _get_channel(self, channel_id: int) -> Optional[discord.abc.Messageable]:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.DiscordException as exc:
                logger.warning("Salon %s introuvable: %s", channel_id, exc)
                return None
        return channel if _is_messageable(channel) else None

    async def _absence_channel(
        self,
        interaction: discord.Interaction,
    ) -> Optional[discord.abc.Messageable]:
        channels = await self._absence_channels(interaction)
        return channels[0] if channels else None

    async def _absence_channels(
        self,
        interaction: discord.Interaction,
    ) -> list[discord.abc.Messageable]:
        if interaction.guild is None:
            return []
        channels = []
        configured = await self._configured_channel(interaction.guild, db.SETTING_ABSENCE_CHANNEL)
        if configured is not None:
            channels.append(configured)
        channel = getattr(interaction, "channel", None)
        if _is_messageable(channel) and all(
            getattr(existing, "id", None) != getattr(channel, "id", None) for existing in channels
        ):
            channels.append(channel)
        return channels

    def _schedule_cleanup(self, absence_id: int, end: date) -> None:
        previous = self._cleanup_tasks.pop(absence_id, None)
        if previous is not None:
            previous.cancel()
        when = _cleanup_when(end)
        delay = max(0, (when - now_paris()).total_seconds())
        self._cleanup_tasks[absence_id] = asyncio.create_task(
            self._run_cleanup(absence_id, delay)
        )

    async def _run_cleanup(self, absence_id: int, delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self._delete_public_absence(absence_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Cleanup absence #%d échoué: %s", absence_id, exc)
        finally:
            self._cleanup_tasks.pop(absence_id, None)

    async def _delete_public_absence(self, absence_id: int) -> bool:
        absence = db.get_absence(absence_id)
        if absence is None or absence["public_deleted_at"]:
            return False

        channel = await self._get_channel(absence["public_channel_id"])
        if channel is not None:
            try:
                message = await channel.fetch_message(absence["public_message_id"])
                await message.delete()
                logger.info("Absence #%d : message public supprimé", absence_id)
            except discord.NotFound:
                logger.info("Absence #%d : message public déjà absent", absence_id)
            except discord.DiscordException as exc:
                logger.warning("Absence #%d : suppression message public échouée: %s", absence_id, exc)
                return False

        db.mark_absence_public_deleted(absence_id)
        return True

    def _cancel_cleanup(self, absence_id: int) -> None:
        task = self._cleanup_tasks.pop(absence_id, None)
        if task is not None:
            task.cancel()

    async def _publish_absence(
        self,
        interaction: discord.Interaction,
        user: discord.abc.User,
        start: date,
        end: date,
        motif: str,
        public_channels: list[discord.abc.Messageable],
    ) -> None:
        public_channel = None
        public_message = None
        failed_channels = []
        try:
            embed = _absence_embed(user, start, end)
            for candidate in public_channels:
                try:
                    public_message = await candidate.send(embed=embed)
                    public_channel = candidate
                    break
                except discord.DiscordException as exc:
                    failed_channels.append(_channel_label(candidate))
                    logger.warning(
                        "Publication absence échouée dans %s: %s",
                        _channel_label(candidate),
                        exc,
                    )
            if public_channel is None or public_message is None:
                channels = ", ".join(failed_channels) if failed_channels else "le salon absence"
                await interaction.followup.send(
                    "Impossible de publier l'absence : le bot n'a pas la permission "
                    f"d'écrire dans {channels}.",
                    ephemeral=True,
                )
                return
        except discord.DiscordException as exc:
            logger.warning("Publication absence échouée: %s", exc)
            await interaction.followup.send(
                "Impossible de publier l'absence : vérifie les permissions du bot dans le salon absence.",
                ephemeral=True,
            )
            return

        admin_warning = ""
        admin_message = None
        admin_channel = await self._configured_channel(interaction.guild, db.SETTING_ABSENCE_ADMIN_CHANNEL)
        if admin_channel is not None:
            try:
                admin_message = await admin_channel.send(
                    embed=_absence_admin_embed(user, start, end, motif.strip())
                )
            except discord.DiscordException as exc:
                logger.warning("Publication motif absence échouée: %s", exc)
                admin_warning = " Motif non envoyé : erreur sur le salon admin."
        elif motif.strip():
            admin_warning = " Motif non envoyé : salon admin non configuré."

        absence_id = db.create_absence(
            guild_id=interaction.guild.id,
            user_id=user.id,
            user_display=_user_display(user),
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            public_channel_id=public_message.channel.id,
            public_message_id=public_message.id,
            admin_channel_id=admin_message.channel.id if admin_message is not None else None,
            admin_message_id=admin_message.id if admin_message is not None else None,
        )
        self._schedule_cleanup(absence_id, end)

        prefix = "Absence publiée" if user.id == interaction.user.id else f"Absence de {_user_display(user)} publiée"
        await interaction.followup.send(
            f"{prefix} dans {_channel_label(public_channel)}.{admin_warning}",
            ephemeral=True,
        )

    def _parse_absence_dates(self, start_raw: str, end_raw: str) -> tuple[date, date]:
        start = dates_utils.parse_absence_date(start_raw)
        end = dates_utils.parse_absence_date(end_raw, reference=start)
        return _ordered_absence_dates(start, end)

    async def _reset_member_roles_to_base(
        self,
        guild: discord.Guild,
        member: discord.Member,
    ) -> str:
        base_role_id = db.get_guild_setting_int(guild.id, db.SETTING_BASE_ROLE)
        if not base_role_id:
            return " Rôles non modifiés : rôle de base non configuré."

        base_role = guild.get_role(base_role_id)
        if base_role is None:
            return f" Rôles non modifiés : rôle de base `{base_role_id}` introuvable."

        try:
            await member.edit(
                roles=[base_role],
                reason="/absence kick : remise au rôle de base",
            )
        except discord.Forbidden:
            logger.warning("Remise rôle base refusée pour %s", member.id)
            return (
                " Rôles non modifiés : je ne peux pas modifier les rôles de ce membre. "
                "Vérifie que mon rôle est au-dessus du sien et que j'ai la permission `Gérer les rôles`."
            )
        except discord.DiscordException as exc:
            logger.warning("Remise rôle base échouée pour %s: %s", member.id, exc)
            return " Rôles non modifiés : erreur Discord."

        return f" Rôles retirés, rôle de base remis : {_role_label(base_role)}."

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
            start, end = self._parse_absence_dates(start_raw, end_raw)
        except dates_utils.InvalidRaidDate as exc:
            await interaction.response.send_message(f"Date invalide : {exc}", ephemeral=True)
            return

        public_channels = await self._absence_channels(interaction)
        if not public_channels:
            await interaction.response.send_message(
                "Aucun salon absence disponible. Configure le salon absence avec `/config channel`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._publish_absence(interaction, interaction.user, start, end, motif, public_channels)

    @absence.command(name="declare", description="Ouvre le formulaire de déclaration d'absence")
    async def declare_abs(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.send_modal(AbsenceModal(self))

    @absence.command(name="add", description="Ajoute une absence pour un membre")
    @app_commands.describe(
        member="Membre absent",
        debut="Date de début (ex: 16, 16/07, demain)",
        fin="Date de fin (ex: 17, 17/07, dimanche)",
        motif="Motif optionnel",
    )
    async def add_abs(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        debut: str,
        fin: str,
        motif: Optional[str] = None,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        try:
            start, end = self._parse_absence_dates(debut, fin)
        except dates_utils.InvalidRaidDate as exc:
            await interaction.response.send_message(f"Date invalide : {exc}", ephemeral=True)
            return

        public_channels = await self._absence_channels(interaction)
        if not public_channels:
            await interaction.response.send_message(
                "Aucun salon absence disponible. Configure le salon absence avec `/config channel`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self._publish_absence(interaction, member, start, end, motif or "", public_channels)

    @absence.command(name="stop", description="Stoppe les absences actives ou à venir d'un membre")
    @app_commands.describe(
        member="Membre dont l'absence doit être stoppée",
        absence_id="ID précis si plusieurs absences existent",
    )
    async def stop_abs(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        absence_id: Optional[int] = None,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        today_iso = now_paris().date().isoformat()
        if absence_id is not None:
            row = db.get_absence(absence_id)
            rows = [
                row
                for row in [row]
                if row is not None
                and row["guild_id"] == interaction.guild.id
                and row["user_id"] == member.id
                and not row["public_deleted_at"]
                and row["end_date"] >= today_iso
            ]
        else:
            rows = db.search_absences(
                guild_id=interaction.guild.id,
                user_id=member.id,
                today_iso=today_iso,
                limit=100,
            )
            if len(rows) > 1:
                embed = _search_absences_embed(
                    rows,
                    title=f"Absences - {_user_display(member)}",
                )
                await interaction.response.send_message(
                    "Plusieurs absences trouvées. Relance `/absence stop` avec l'`absence_id` voulu.",
                    embed=embed,
                    ephemeral=True,
                )
                return

        if not rows:
            await interaction.response.send_message(
                f"Aucune absence active ou à venir trouvée pour {_user_display(member)}.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        stopped = 0
        failed = 0
        for row in rows:
            if await self._delete_public_absence(row["id"]):
                self._cancel_cleanup(row["id"])
                stopped += 1
            else:
                failed += 1

        message = f"{stopped} absence(s) stoppée(s) pour {_user_display(member)}."
        if failed:
            message += f" {failed} suppression(s) impossible(s) : vérifie les permissions du salon."
        await interaction.followup.send(message, ephemeral=True)

    @absence.command(name="panel", description="Poste le bouton de déclaration d'absence")
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

        target = await self._configured_channel(interaction.guild, db.SETTING_ABSENCE_PANEL_CHANNEL)
        if target is None:
            await interaction.response.send_message(
                "Configure d'abord le salon panel absences avec `/config channel`.",
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

    @absence.command(
        name="search",
        description="Recherche les absences actives, à venir ou la dernière passée d'un membre",
    )
    @app_commands.describe(member="Membre à filtrer")
    async def search_abs(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        today = now_paris().date()
        rows = db.search_absences(
            guild_id=interaction.guild.id,
            user_id=member.id if member is not None else None,
            today_iso=today.isoformat(),
        )
        title = f"Absences - {member.display_name}" if member is not None else "Absences"
        empty_description = "Aucune absence active ou à venir."
        if member is not None and not rows:
            latest = db.get_latest_absence(guild_id=interaction.guild.id, user_id=member.id)
            if latest is not None:
                rows = [latest]
                title = f"Dernière absence - {member.display_name}"
            else:
                empty_description = f"Aucune absence trouvée pour {_user_display(member)}."
        await interaction.response.send_message(
            embed=_search_absences_embed(
                rows,
                title=title,
                today=today,
                empty_description=empty_description,
            ),
            ephemeral=False,
        )

    @absence.command(
        name="kick",
        description="Préviens un membre AFK, remet le rôle de base et retire les autres rôles",
    )
    @app_commands.describe(user="Membre à prévenir")
    async def kick_abs(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        public_channel = await self._absence_channel(interaction)
        if public_channel is None:
            await interaction.response.send_message("Aucun salon absence disponible.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False, thinking=True)

        message = _kick_abs_message(user)
        try:
            await public_channel.send(content=message)
        except discord.DiscordException as exc:
            logger.warning("Publication kick absence échouée: %s", exc)
            await interaction.followup.send("Impossible de publier le message d'absence.", ephemeral=False)
            return

        role_warning = await self._reset_member_roles_to_base(interaction.guild, user)

        dm_warning = ""
        try:
            await user.send(content=message)
        except discord.DiscordException as exc:
            logger.warning("MP kick absence échoué pour %s: %s", user.id, exc)
            dm_warning = " MP non envoyé : impossible de contacter la personne."

        await interaction.followup.send(
            f"Message envoyé dans {_channel_label(public_channel)}.{role_warning}{dm_warning}",
            ephemeral=False,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AbsenceCog(bot))
