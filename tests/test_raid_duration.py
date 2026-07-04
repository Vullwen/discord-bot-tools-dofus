from datetime import date, datetime, time, timedelta

from config import PARIS
from cogs.raid import RaidCog


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
