from datetime import date

from cogs.absence import _format_absence_period


def test_format_absence_period_one_day():
    assert _format_absence_period(date(2026, 7, 10), date(2026, 7, 10)) == "Le vendredi 10/07"


def test_format_absence_period_range():
    assert (
        _format_absence_period(date(2026, 7, 10), date(2026, 7, 12))
        == "Du vendredi 10/07 au dimanche 12/07"
    )
