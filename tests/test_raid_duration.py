from datetime import date, datetime, time, timedelta

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
    assert closes == datetime(2026, 6, 26, 12, 0, tzinfo=PARIS)


def test_poll_close_hour_is_capped_before_first_hour():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_close_hour=18,
        poll_hours=[14, 21],
    )
    assert closes == datetime(2026, 6, 26, 14, 0, tzinfo=PARIS)


def test_auto_poll_close_uses_configured_hour():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_close_hour=None,
        poll_hours=[14, 21],
    )
    assert closes == datetime(2026, 6, 26, 12, 0, tzinfo=PARIS)


def test_poll_close_hour_is_capped_before_fixed_time():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_close_hour=22,
        fixed_time=time(20, 30),
    )
    assert closes == datetime(2026, 6, 26, 20, 30, tzinfo=PARIS)


def test_today_past_close_hour_falls_back_to_short_delay():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 25),
        now,
        poll_close_hour=12,
        poll_hours=[21, 22],
    )
    assert closes == now + timedelta(minutes=15)


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
    assert cog._register_user(raid_id, 30, "Gigalodon", LEVEL_199_MINUS) == "low_level_full"
    assert cog._register_user(raid_id, 40, "Gigalodon", LEVEL_200_PLUS) == "confirmed"
    assert db.count_level_group(raid_id, LEVEL_199_MINUS) == 2


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
