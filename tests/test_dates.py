from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from utils import dates as d

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 6, 25, 12, 0, tzinfo=PARIS)  # un jeudi


def test_iso_and_eu():
    assert d.parse_raid_date("2026-06-28", NOW).isoformat() == "2026-06-28"
    assert d.parse_raid_date("28/06/2026", NOW).isoformat() == "2026-06-28"
    assert d.parse_raid_date("28-06-2026", NOW).isoformat() == "2026-06-28"


def test_short_year_rollover():
    # 28/06 cette année (dans le futur)
    assert d.parse_raid_date("28/06", NOW).isoformat() == "2026-06-28"
    # 01/01 déjà passé cette année -> année suivante
    assert d.parse_raid_date("01/01", NOW).isoformat() == "2027-01-01"


def test_relative_words():
    assert d.parse_raid_date("aujourd'hui", NOW).isoformat() == "2026-06-25"
    assert d.parse_raid_date("demain", NOW).isoformat() == "2026-06-26"
    assert d.parse_raid_date("après-demain", NOW).isoformat() == "2026-06-27"
    assert d.parse_raid_date("aujourdhui", NOW).isoformat() == "2026-06-25"


def test_weekday():
    assert NOW.weekday() == 3  # jeudi
    # vendredi = lendemain
    assert d.parse_raid_date("vendredi", NOW).isoformat() == "2026-06-26"
    # jeudi -> repoussé à la semaine suivante
    assert d.parse_raid_date("jeudi", NOW).isoformat() == "2026-07-02"


def test_past_rejected():
    with pytest.raises(d.InvalidRaidDate):
        d.parse_raid_date("20/06/2026", NOW)


def test_invalid_format():
    with pytest.raises(d.InvalidRaidDate):
        d.parse_raid_date("notadate", NOW)
    with pytest.raises(d.InvalidRaidDate):
        d.parse_raid_date("32/13/2026", NOW)


def test_combine_and_format():
    day = d.parse_raid_date("28/06/2026", NOW)
    dt = d.combine_date_hour(day, 21)
    assert dt.hour == 21
    assert dt.tzinfo is not None
    assert "à 21h00" in d.format_dt_fr(dt)


def test_ce_soir_and_time_mean_today():
    today = NOW.date()
    assert d.parse_raid_date("ce soir", NOW) == today
    assert d.parse_raid_date("ce matin", NOW) == today
    assert d.parse_raid_date("cet aprem", NOW) == today
    assert d.parse_raid_date("cette après-midi", NOW) == today
    assert d.parse_raid_date("ce soir 21h", NOW) == today
    # une heure seule est comprise comme "aujourd'hui" (l'heure est décidée par le sondage)
    assert d.parse_raid_date("21h", NOW) == today
    assert d.parse_raid_date("21h30", NOW) == today
    assert d.parse_raid_date("9:05", NOW) == today
