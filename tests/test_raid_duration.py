from datetime import date, datetime, time
from types import SimpleNamespace

import pytest

import db
from config import PARIS
from cogs.raid import LEVEL_199_MINUS, LEVEL_200_PLUS, RaidCog


def _cog():
    return RaidCog.__new__(RaidCog)


def test_poll_closes_at_selected_raid_day_hour():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_close_hour=12,
        poll_hours=[14, 21],
    )
    assert closes == datetime(2026, 6, 26, 11, 0, tzinfo=PARIS)


def test_poll_close_hour_is_capped_before_first_hour():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_close_hour=18,
        poll_hours=[14, 21],
    )
    assert closes == datetime(2026, 6, 26, 11, 0, tzinfo=PARIS)


def test_auto_poll_close_uses_configured_hour():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_close_hour=None,
        poll_hours=[14, 21],
    )
    assert closes == datetime(2026, 6, 26, 11, 0, tzinfo=PARIS)


def test_poll_close_hour_is_capped_before_fixed_time():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_close_hour=22,
        fixed_time=time(20, 30),
    )
    assert closes == datetime(2026, 6, 26, 17, 30, tzinfo=PARIS)


def test_today_past_close_hour_falls_back_to_short_delay():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 25),
        now,
        poll_close_hour=12,
        poll_hours=[21, 22],
    )
    assert closes == now


class _FakeChannel:
    def __init__(self, channel_id: int = 3):
        self.id = channel_id
        self.sent = []

    async def send(self, *, content=None, embed=None, view=None):
        msg = SimpleNamespace(
            id=1000 + len(self.sent),
            content=content,
            embed=embed,
            view=view,
            channel=self,
        )
        self.sent.append(msg)
        return msg


class _FakeResponse:
    def __init__(self):
        self.messages = []
        self.edits = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))

    async def edit_message(self, content=None, **kwargs):
        self.edits.append((content, kwargs))


def _async_return(value):
    async def inner(*_args, **_kwargs):
        return value

    return inner


async def _async_noop(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_hour_poll_after_raid_choice_mentions_notify_role(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = _FakeChannel()
    db.set_guild_setting(2, db.SETTING_RAID_NOTIFY_ROLE, "555")
    raid_id = db.create_raid(
        name=None,
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=channel.id,
        state="choosing_raid",
        poll_hours=[19, 20, 21],
    )
    db.update_raid(raid_id, raid_poll_message_id=42)
    db.cast_vote(raid_id, 10, "raid", "Gigalodon")
    cog = _cog()
    cog._creator_display = _async_return("Creator")
    cog._edit_message = _async_noop
    cog._get_channel = _async_return(channel)
    scheduled = []
    cog._schedule = lambda raid_id, kind, when, coro_fn: scheduled.append((raid_id, kind, when, coro_fn.__name__))

    await cog._close_raid_choice(raid_id)

    raid = db.get_raid(raid_id)
    assert raid["state"] == "voting_hour"
    assert raid["name"] == "Gigalodon"
    assert raid["hour_poll_message_id"] == channel.sent[0].id
    assert channel.sent[0].content == "<@&555>"
    assert [(kind, fn) for _rid, kind, _when, fn in scheduled] == [
        ("hour_close", "_close_hour_poll")
    ]


@pytest.mark.asyncio
async def test_ban_raid_command_persists_ban(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.raid.is_raid_organizer", lambda _interaction: True)
    monkeypatch.setattr(
        "cogs.raid.now_paris",
        lambda: datetime(2026, 6, 25, 12, 0, tzinfo=PARIS),
    )
    admin_channel = _FakeChannel(500)
    db.set_guild_setting(2, db.SETTING_RAID_ADMIN_CHANNEL, str(admin_channel.id))
    cog = _cog()
    cog._get_channel = _async_return(admin_channel)
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=1, mention="<@1>"),
        guild=SimpleNamespace(id=2),
        response=_FakeResponse(),
    )
    user = SimpleNamespace(id=10, mention="<@10>")

    await RaidCog.ban_raid.callback(cog, interaction, user, 3, None)

    ban = db.get_active_raid_ban(
        guild_id=2,
        user_id=10,
        now=datetime(2026, 6, 25, 12, 0, tzinfo=PARIS),
    )
    assert ban is not None
    assert ban["banned_until"] == "2026-06-28T12:00:00+02:00"
    assert "3 jours" in interaction.response.messages[0][0]
    assert "Ban raid" in admin_channel.sent[0].content
    assert "<@10>" in admin_channel.sent[0].content
    assert "<@1>" in admin_channel.sent[0].content


@pytest.mark.asyncio
async def test_unban_raid_command_clears_active_ban(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.raid.is_raid_organizer", lambda _interaction: True)
    monkeypatch.setattr(
        "cogs.raid.now_paris",
        lambda: datetime(2026, 6, 25, 12, 0, tzinfo=PARIS),
    )
    db.set_raid_ban(
        guild_id=2,
        user_id=10,
        banned_until=datetime(2026, 6, 28, 12, 0, tzinfo=PARIS),
        reason="absence répétée",
        created_by=1,
    )
    cog = _cog()
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=1),
        guild=SimpleNamespace(id=2),
        response=_FakeResponse(),
    )
    user = SimpleNamespace(id=10, mention="<@10>")

    await RaidCog.unban_raid.callback(cog, interaction, user)

    assert db.get_active_raid_ban(
        guild_id=2,
        user_id=10,
        now=datetime(2026, 6, 25, 12, 0, tzinfo=PARIS),
    ) is None
    assert "peut de nouveau voter" in interaction.response.messages[0][0]


@pytest.mark.asyncio
async def test_show_bans_lists_active_bans(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.raid.is_raid_organizer", lambda _interaction: True)
    monkeypatch.setattr(
        "cogs.raid.now_paris",
        lambda: datetime(2026, 6, 25, 12, 0, tzinfo=PARIS),
    )
    db.set_raid_ban(
        guild_id=2,
        user_id=10,
        banned_until=datetime(2026, 6, 27, 12, 0, tzinfo=PARIS),
        reason="absence répétée",
        created_by=1,
    )
    cog = _cog()
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=1),
        guild=SimpleNamespace(id=2),
        response=_FakeResponse(),
    )

    await RaidCog.show_bans.callback(cog, interaction)

    content, kwargs = interaction.response.messages[0]
    assert kwargs == {"ephemeral": True}
    assert "Bans raid actifs" in content
    assert "<@10>" in content
    assert "encore 2 jours" in content
    assert "absence répétée" in content


@pytest.mark.asyncio
async def test_banned_user_cannot_vote_for_raid(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr(
        "cogs.raid.now_paris",
        lambda: datetime(2026, 6, 25, 12, 0, tzinfo=PARIS),
    )
    raid_id = db.create_raid(
        name=None,
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="choosing_raid",
    )
    db.set_raid_ban(
        guild_id=2,
        user_id=10,
        banned_until=datetime(2026, 6, 27, 12, 0, tzinfo=PARIS),
        reason="tu t'es inscrit plusieurs fois à des raids sans te présenter ensuite",
        created_by=1,
    )
    cog = _cog()
    interaction = SimpleNamespace(user=SimpleNamespace(id=10), response=_FakeResponse())

    await cog.handle_raid_vote(interaction, raid_id, "Gigalodon")

    assert "Tu es banni des raids pour encore 2 jours" in interaction.response.messages[0][0]
    assert db.get_vote_counts(raid_id, "raid") == {}


def test_winning_hour_voters_are_registered(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="voting_hour",
    )
    raid = db.get_raid(raid_id)

    db.toggle_vote(raid_id, 100, "hour", "15")
    db.toggle_vote(raid_id, 200, "hour", "16")
    db.toggle_vote(raid_id, 300, "hour", "15")
    db.toggle_vote(raid_id, 300, "hour", "15")  # vote retiré

    assert _cog()._register_winning_hour_voters(raid_id, raid, "15") == (1, 0)
    assert db.is_participant(raid_id, 100)
    assert not db.is_participant(raid_id, 200)
    assert not db.is_participant(raid_id, 300)


def test_winning_hour_voters_keep_level_choice(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="voting_hour",
    )
    raid = db.get_raid(raid_id)
    db.set_level_choice(raid_id, 100, LEVEL_199_MINUS)
    db.toggle_vote(raid_id, 100, "hour", "15")

    assert _cog()._register_winning_hour_voters(raid_id, raid, "15") == (1, 0)
    assert db.get_participant_level_group(raid_id, 100) == LEVEL_199_MINUS


def test_low_level_active_hour_choices_count_against_cap(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="voting_hour",
    )
    raid = db.get_raid(raid_id)
    db.set_level_choice(raid_id, 10, LEVEL_199_MINUS)
    db.toggle_vote(raid_id, 10, "hour", "15")
    db.set_level_choice(raid_id, 20, LEVEL_199_MINUS)
    db.toggle_vote(raid_id, 20, "hour", "16")

    assert _cog()._low_level_full_message(raid, raid_id) == "Les 2 place(s) 199- sont déjà prises pour Gigalodon."


def test_register_low_level_cap_for_gigalodon(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="scheduled",
    )
    cog = _cog()

    assert cog._register_user(raid_id, 10, "Gigalodon", LEVEL_199_MINUS) == "confirmed"
    assert cog._register_user(raid_id, 20, "Gigalodon", LEVEL_199_MINUS) == "confirmed"
    assert cog._register_user(raid_id, 30, "Gigalodon", LEVEL_199_MINUS) == "waitlist"
    assert cog._register_user(raid_id, 40, "Gigalodon", LEVEL_200_PLUS) == "confirmed"
    assert db.count_level_group(raid_id, LEVEL_199_MINUS) == 3
    assert db.get_participant_status(raid_id, 30) == "waitlist"
    assert db.get_participant_level_group(raid_id, 30) == LEVEL_199_MINUS


def test_winning_hour_low_level_over_cap_goes_to_waitlist(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="voting_hour",
    )
    raid = db.get_raid(raid_id)
    for user_id in (10, 20, 30):
        db.set_level_choice(raid_id, user_id, LEVEL_199_MINUS)
        db.toggle_vote(raid_id, user_id, "hour", "15")

    assert _cog()._register_winning_hour_voters(raid_id, raid, "15") == (2, 1)
    assert db.get_participant_status(raid_id, 10) == "confirmed"
    assert db.get_participant_status(raid_id, 20) == "confirmed"
    assert db.get_participant_status(raid_id, 30) == "waitlist"
    assert db.get_participant_level_group(raid_id, 30) == LEVEL_199_MINUS


def test_register_low_level_forbidden_for_jardins(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    raid_id = db.create_raid(
        name="Jardins Éternels",
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="scheduled",
    )
    cog = _cog()

    assert cog._register_user(raid_id, 10, "Jardins Éternels", LEVEL_199_MINUS) == "low_level_full"
    assert cog._register_user(raid_id, 20, "Jardins Éternels", LEVEL_200_PLUS) == "confirmed"


def test_reminder_user_ids_excludes_waitlist(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="scheduled",
    )
    db.add_participant(raid_id, 10, "confirmed", LEVEL_200_PLUS)
    db.add_participant(raid_id, 20, "waitlist", LEVEL_200_PLUS)
    db.add_participant(raid_id, 30, "confirmed", LEVEL_199_MINUS)

    assert _cog()._reminder_user_ids(raid_id) == [10, 30]


def test_registration_allowed_after_raid_is_done(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="done",
    )

    assert _cog()._registration_allowed(db.get_raid(raid_id)) is True


def test_tied_hour_choices_only_returns_positive_ties(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="voting_hour",
    )
    db.toggle_vote(raid_id, 100, "hour", "15")
    db.toggle_vote(raid_id, 200, "hour", "16")
    assert _cog()._tied_hour_choices(raid_id, [14, 15, 16]) == [15, 16]

    db.toggle_vote(raid_id, 300, "hour", "15")
    assert _cog()._tied_hour_choices(raid_id, [14, 15, 16]) == []
