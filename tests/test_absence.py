from datetime import date

from cogs.absence import _cleanup_when, _format_absence_period


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
