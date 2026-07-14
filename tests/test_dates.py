from datetime import date, datetime, time, timedelta
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


def test_parse_absence_date_accepts_day_only():
    assert d.parse_absence_date("26", NOW).isoformat() == "2026-06-26"
    assert d.parse_absence_date("16", NOW).isoformat() == "2026-07-16"
    start = d.parse_absence_date("30", NOW)
    assert d.parse_absence_date("2", NOW, reference=start).isoformat() == "2026-07-02"


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


def test_parse_hour_extracts_hour():
    assert d.parse_hour("15h") == 15
    assert d.parse_hour("21h30") == 21
    assert d.parse_hour("9:05") == 9
    assert d.parse_hour("ce soir 21h") == 21
    assert d.parse_hour("demain 15h") == 15
    # pas d'heure détectée
    assert d.parse_hour("demain") is None
    assert d.parse_hour("28/06") is None
    assert d.parse_hour("2026-06-28") is None
    assert d.parse_hour("lundi") is None
    assert d.parse_hour("") is None
    # hors plage -> None
    assert d.parse_hour("24h") is None


def test_parse_date_with_combined_hour():
    # "demain 15h" -> date demain, heure 15
    assert d.parse_raid_date("demain 15h", NOW) == NOW.date() + timedelta(days=1)
    assert d.parse_hour("demain 15h") == 15
    # "28/06 15h30" -> date 28/06, heure 15
    assert d.parse_raid_date("28/06 15h30", NOW).isoformat() == "2026-06-28"
    assert d.parse_hour("28/06 15h30") == 15


def test_strip_hour():
    assert d.strip_hour("demain 15h") == "demain"
    assert d.strip_hour("ce soir 21h") == "ce soir"
    assert d.strip_hour("15h") == ""
    assert d.strip_hour("demain") == "demain"


def test_parse_time_with_minutes():
    assert d.parse_time("19h30") == time(19, 30)
    assert d.parse_time("9:05") == time(9, 5)
    assert d.parse_time("21h") == time(21, 0)
    assert d.parse_time("demain 15h45") == time(15, 45)
    assert d.parse_time("demain") is None
    assert d.parse_time("24h30") is None   # heure hors plage
    assert d.parse_time("21h99") is None   # minutes hors plage


def test_combine_date_time():
    day = d.parse_raid_date("28/06/2026", NOW)
    dt = d.combine_date_time(day, time(19, 30))
    assert dt.hour == 19 and dt.minute == 30
    assert dt.tzinfo is not None
    assert "à 19h30" in d.format_dt_fr(dt)


def test_parse_hhmm():
    assert d.parse_hhmm("19:30") == time(19, 30)
    assert d.parse_hhmm(None) is None
    assert d.parse_hhmm("not a time") is None


def test_poll_closes_at_noon():
    # Raid le 28/06, clôture à midi le jour J par défaut.
    closes = d.poll_closes_at(date(2026, 6, 28), 12, now=NOW)
    assert closes == datetime(2026, 6, 28, 12, 0, tzinfo=PARIS)


def test_poll_closes_at_morning():
    closes = d.poll_closes_at(date(2026, 6, 28), 9, now=NOW)
    assert closes == datetime(2026, 6, 28, 9, 0, tzinfo=PARIS)


def test_poll_closes_at_today_falls_back():
    # Raid "aujourd'hui" (25/06) à minuit : déjà passé (NOW=12h) -> repli now+15min.
    closes = d.poll_closes_at(date(2026, 6, 25), 0, now=NOW)
    assert closes == NOW + timedelta(minutes=15)
