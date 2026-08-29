from datetime import date, datetime
from types import SimpleNamespace

import pytest
import discord

import db
from config import PARIS
from cogs.absence import AbsenceCog, _cleanup_when, _format_absence_period, _search_absences_embed


def test_format_absence_period_one_day():
    assert _format_absence_period(date(2026, 7, 10), date(2026, 7, 10)) == "Le vendredi 10/07"


def test_format_absence_period_range():
    assert (
        _format_absence_period(date(2026, 7, 10), date(2026, 7, 12))
        == "Du vendredi 10/07 au dimanche 12/07"
    )


def test_cleanup_when_is_day_after_end_at_midnight():
    cleanup = _cleanup_when(date(2026, 7, 12))
    assert cleanup.isoformat() == "2026-07-13T00:00:00+02:00"


def test_search_absences_embed_shows_absence_ids(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    absence_id = db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2099-08-28",
        end_date="2099-08-30",
        public_channel_id=100,
        public_message_id=1000,
    )

    embed = _search_absences_embed(
        db.search_absences(guild_id=2, today_iso="2099-08-01"),
        today=date(2099, 8, 1),
    )

    assert embed.fields[0].name == f"#{absence_id} - Bob"
    assert embed.fields[0].value == (
        "Du vendredi 28/08 au dimanche 30/08\n"
        "Retour prévu dans 29 jours"
    )


@pytest.mark.asyncio
async def test_search_abs_is_not_ephemeral(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2099-08-28",
        end_date="2099-08-30",
        public_channel_id=100,
        public_message_id=1000,
    )
    cog = AbsenceCog(SimpleNamespace())
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=2),
        response=_FakeResponse(),
    )

    await AbsenceCog.search_abs.callback(cog, interaction)

    content, kwargs = interaction.response.messages[0]
    assert content is None
    assert kwargs["ephemeral"] is False
    assert kwargs["embed"].fields[0].name == "#1 - Bob"


@pytest.mark.asyncio
async def test_search_abs_member_shows_latest_past_absence(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cogs.absence.now_paris",
        lambda: datetime(2026, 8, 14, 12, 0, tzinfo=PARIS),
    )
    db.reset_for_tests(str(tmp_path / "t.db"))
    absence_id = db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2026-07-10",
        end_date="2026-07-30",
        public_channel_id=100,
        public_message_id=1000,
    )
    db.mark_absence_public_deleted(absence_id)
    cog = AbsenceCog(SimpleNamespace())
    member = _FakeUser(20)
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=2),
        response=_FakeResponse(),
    )

    await AbsenceCog.search_abs.callback(cog, interaction, member)

    content, kwargs = interaction.response.messages[0]
    assert content is None
    assert kwargs["ephemeral"] is False
    assert kwargs["embed"].title == "Dernière absence - user-20"
    assert kwargs["embed"].fields[0].name == f"#{absence_id} - Bob"
    assert kwargs["embed"].fields[0].value == (
        "Du vendredi 10/07 au jeudi 30/07\n"
        "Jours d'inactivité non déclarée depuis la date de retour : 15"
    )


@pytest.mark.asyncio
async def test_search_abs_member_shows_active_and_latest_past_absence(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cogs.absence.now_paris",
        lambda: datetime(2026, 8, 14, 12, 0, tzinfo=PARIS),
    )
    db.reset_for_tests(str(tmp_path / "t.db"))
    old_id = db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2026-07-01",
        end_date="2026-07-05",
        public_channel_id=100,
        public_message_id=1000,
    )
    latest_past_id = db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2026-07-10",
        end_date="2026-07-30",
        public_channel_id=100,
        public_message_id=1001,
    )
    active_id = db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2026-08-10",
        end_date="2026-08-20",
        public_channel_id=100,
        public_message_id=1002,
    )
    db.mark_absence_public_deleted(old_id)
    db.mark_absence_public_deleted(latest_past_id)
    cog = AbsenceCog(SimpleNamespace())
    member = _FakeUser(20)
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=2),
        response=_FakeResponse(),
    )

    await AbsenceCog.search_abs.callback(cog, interaction, member)

    content, kwargs = interaction.response.messages[0]
    assert content is None
    assert kwargs["ephemeral"] is False
    assert kwargs["embed"].title == "Absences - user-20"
    assert [field.name for field in kwargs["embed"].fields] == [
        f"#{active_id} - Bob",
        f"#{latest_past_id} - Bob",
    ]
    assert kwargs["embed"].fields[0].value == (
        "Du lundi 10/08 au jeudi 20/08\n"
        "Retour prévu dans 6 jours"
    )
    assert kwargs["embed"].fields[1].value == (
        "Du vendredi 10/07 au jeudi 30/07\n"
        "Jours d'inactivité non déclarée depuis la date de retour : 15"
    )


class _FakeResponse:
    def __init__(self):
        self.deferred = False
        self.defer_kwargs = None
        self.messages = []

    async def defer(self, **kwargs):
        self.deferred = True
        self.defer_kwargs = kwargs

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


class _FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


class _FakeChannel:
    id = 100
    mention = "<#100>"

    def __init__(self):
        self.sent = []
        self._messages = {}

    async def send(self, *, content=None, embed=None, view=None):
        message = SimpleNamespace(id=1000 + len(self.sent), channel=self, content=content, embed=embed, view=view)
        message.deleted = False

        async def delete():
            message.deleted = True

        message.delete = delete
        self.sent.append(message)
        self._messages[message.id] = message
        return message

    async def fetch_message(self, message_id):
        return self._messages[message_id]


class _FailingChannel(_FakeChannel):
    id = 200
    mention = "<#200>"

    async def send(self, *, content=None, embed=None, view=None):
        raise discord.DiscordException("missing permissions")


class _FakeUser:
    def __init__(self, user_id):
        self.id = user_id
        self.display_name = f"user-{user_id}"
        self.name = self.display_name
        self.mention = f"<@{user_id}>"
        self.dms = []
        self.role_edits = []

    async def send(self, *, content=None, embed=None, view=None):
        self.dms.append(SimpleNamespace(content=content, embed=embed, view=view))

    async def edit(self, **kwargs):
        self.role_edits.append(kwargs)


def _fake_role(role_id: int, name: str):
    return SimpleNamespace(id=role_id, name=name, mention=f"<@&{role_id}>")


def _fake_guild(guild_id: int, *roles):
    return SimpleNamespace(
        id=guild_id,
        get_role=lambda role_id: next((role for role in roles if role.id == role_id), None),
    )


@pytest.mark.asyncio
async def test_absence_channel_falls_back_to_interaction_channel():
    panel_channel = _FakeChannel()
    cog = AbsenceCog(SimpleNamespace())

    async def configured_channel(_guild, _key):
        return None

    cog._configured_channel = configured_channel
    interaction = SimpleNamespace(guild=SimpleNamespace(id=2), channel=panel_channel)

    assert await cog._absence_channel(interaction) is panel_channel


@pytest.mark.asyncio
async def test_submit_absence_tries_panel_channel_when_configured_channel_fails(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    configured_channel = _FailingChannel()
    panel_channel = _FakeChannel()
    cog = AbsenceCog(SimpleNamespace())
    cog._schedule_cleanup = lambda _absence_id, _end: None

    async def configured(_guild, key):
        if key == db.SETTING_ABSENCE_CHANNEL:
            return configured_channel
        return None

    cog._configured_channel = configured
    interaction = SimpleNamespace(
        user=_FakeUser(10),
        guild=SimpleNamespace(id=2),
        channel=panel_channel,
        response=_FakeResponse(),
        followup=_FakeFollowup(),
    )

    await cog.submit_absence(interaction, "28/08/2099", "28/08/2099", "")

    assert len(panel_channel.sent) == 1
    assert interaction.followup.messages[0] == ("Absence publiée dans <#100>.", {"ephemeral": True})


@pytest.mark.asyncio
async def test_stop_abs_marks_member_absence_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr("cogs.absence.is_raid_organizer", lambda _interaction: True)
    db.reset_for_tests(str(tmp_path / "t.db"))
    public_channel = _FakeChannel()
    public_message = await public_channel.send(embed=None)
    absence_id = db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2026-08-28",
        end_date="2026-08-30",
        public_channel_id=public_channel.id,
        public_message_id=public_message.id,
    )
    cog = AbsenceCog(SimpleNamespace(get_channel=lambda _channel_id: public_channel))
    cog._cleanup_tasks[absence_id] = SimpleNamespace(cancel=lambda: None)
    member = _FakeUser(20)
    interaction = SimpleNamespace(
        user=_FakeUser(10),
        guild=SimpleNamespace(id=2),
        response=_FakeResponse(),
        followup=_FakeFollowup(),
    )

    await AbsenceCog.stop_abs.callback(cog, interaction, member)

    assert public_message.deleted is True
    assert db.get_absence(absence_id)["public_deleted_at"] is not None
    assert interaction.followup.messages[0] == ("1 absence(s) stoppée(s) pour user-20.", {"ephemeral": True})


@pytest.mark.asyncio
async def test_stop_abs_requires_id_when_member_has_multiple_absences(tmp_path, monkeypatch):
    monkeypatch.setattr("cogs.absence.is_raid_organizer", lambda _interaction: True)
    db.reset_for_tests(str(tmp_path / "t.db"))
    public_channel = _FakeChannel()
    first_message = await public_channel.send(embed=None)
    second_message = await public_channel.send(embed=None)
    first_absence_id = db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2099-08-28",
        end_date="2099-08-30",
        public_channel_id=public_channel.id,
        public_message_id=first_message.id,
    )
    second_absence_id = db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2099-09-05",
        end_date="2099-09-06",
        public_channel_id=public_channel.id,
        public_message_id=second_message.id,
    )
    cog = AbsenceCog(SimpleNamespace(get_channel=lambda _channel_id: public_channel))
    member = _FakeUser(20)
    interaction = SimpleNamespace(
        user=_FakeUser(10),
        guild=SimpleNamespace(id=2),
        response=_FakeResponse(),
        followup=_FakeFollowup(),
    )

    await AbsenceCog.stop_abs.callback(cog, interaction, member)

    assert first_message.deleted is False
    assert second_message.deleted is False
    assert db.get_absence(first_absence_id)["public_deleted_at"] is None
    assert db.get_absence(second_absence_id)["public_deleted_at"] is None
    content, kwargs = interaction.response.messages[0]
    assert "Plusieurs absences trouvées" in content
    assert kwargs["ephemeral"] is True
    assert [field.name for field in kwargs["embed"].fields] == [
        f"#{first_absence_id} - Bob",
        f"#{second_absence_id} - Bob",
    ]


@pytest.mark.asyncio
async def test_kick_abs_notifies_absence_channel_member_dm_and_resets_roles(tmp_path, monkeypatch):
    monkeypatch.setattr("cogs.absence.is_raid_organizer", lambda _interaction: True)
    db.reset_for_tests(str(tmp_path / "t.db"))
    base_role = _fake_role(300, "Membre")
    db.set_guild_setting(2, db.SETTING_BASE_ROLE, str(base_role.id))
    public_channel = _FakeChannel()
    cog = AbsenceCog(SimpleNamespace())

    async def absence_channel(_interaction):
        return public_channel

    cog._absence_channel = absence_channel
    member = _FakeUser(20)
    interaction = SimpleNamespace(
        user=_FakeUser(10),
        guild=_fake_guild(2, base_role),
        response=_FakeResponse(),
        followup=_FakeFollowup(),
    )

    await AbsenceCog.kick_abs.callback(cog, interaction, member)

    expected = (
        "<@20>, tu as été kick de la guilde pour afk, "
        "n'hésite pas à repostuler quand tu recommences à jouer."
    )
    assert public_channel.sent[0].content == expected
    assert member.dms[0].content == expected
    assert member.role_edits == [
        {"roles": [base_role], "reason": "/absence kick : remise au rôle de base"}
    ]
    assert interaction.response.deferred is True
    assert interaction.response.defer_kwargs == {"ephemeral": False, "thinking": True}
    assert interaction.followup.messages[0] == (
        "Message envoyé dans <#100>. Rôles retirés, rôle de base remis : <@&300>.",
        {"ephemeral": False},
    )
