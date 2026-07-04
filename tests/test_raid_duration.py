from datetime import date, datetime, time

from config import PARIS
from cogs.raid import RaidCog


def _cog():
    return RaidCog.__new__(RaidCog)


def test_poll_closes_after_selected_duration():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_duration_seconds=6 * 60 * 60,
        poll_hours=[14, 21],
    )
    assert closes == datetime(2026, 6, 26, 0, 0, tzinfo=PARIS)


def test_poll_duration_is_capped_before_first_hour():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_duration_seconds=48 * 60 * 60,
        poll_hours=[14, 21],
    )
    assert closes == datetime(2026, 6, 26, 14, 0, tzinfo=PARIS)


def test_auto_poll_close_uses_configured_hour():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_duration_seconds=0,
        poll_hours=[14, 21],
    )
    assert closes == datetime(2026, 6, 26, 12, 0, tzinfo=PARIS)


def test_poll_duration_is_capped_before_fixed_time():
    now = datetime(2026, 6, 25, 18, 0, tzinfo=PARIS)
    closes = _cog()._poll_closes_at(
        date(2026, 6, 26),
        now,
        poll_duration_seconds=48 * 60 * 60,
        fixed_time=time(20, 30),
    )
    assert closes == datetime(2026, 6, 26, 20, 30, tzinfo=PARIS)
