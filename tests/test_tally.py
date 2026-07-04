from datetime import datetime
from zoneinfo import ZoneInfo

from utils import poll

PARIS = ZoneInfo("Europe/Paris")


def test_tally_majority():
    counts = {"14": 3, "20": 5, "21": 2}
    assert poll.tally(counts, ["14", "20", "21"], "21") == "20"


def test_tally_tie_earliest_in_order():
    counts = {"20": 2, "21": 2}
    assert poll.tally(counts, ["14", "20", "21"], "21") == "20"


def test_tied_leaders_positive_votes_only():
    counts = {"20": 2, "21": 2, "22": 1}
    assert poll.tied_leaders(counts, ["14", "20", "21", "22"]) == ["20", "21"]


def test_tied_leaders_no_votes():
    assert poll.tied_leaders({}, ["20", "21"]) == []
    assert poll.tied_leaders({"20": 0, "21": 0}, ["20", "21"]) == []


def test_tally_no_votes():
    assert poll.tally({}, ["14", "15"], "21") == "21"


def test_tally_all_zero():
    assert poll.tally({"20": 0}, ["20", "21"], "21") == "21"


def test_reminder_time():
    scheduled = datetime(2026, 6, 28, 21, 0, tzinfo=PARIS)
    assert poll.reminder_time(scheduled, 10) == datetime(2026, 6, 28, 20, 50, tzinfo=PARIS)


def test_is_active_and_states():
    assert poll.is_active("voting_hour")
    assert poll.is_active("breaking_hour_tie")
    assert poll.is_active("scheduled")
    assert not poll.is_active("done")
    assert not poll.is_active("cancelled")


def test_format_counts_bold_leader():
    out = poll.format_counts({"14": 0, "20": 3, "21": 1}, ["14", "20", "21"], suffix="h")
    assert "**20h: 3**" in out
    assert "14h: 0" in out


def test_parse_poll_hours():
    assert poll.parse_poll_hours("19,20,21", [14, 15]) == [19, 20, 21]
    assert poll.parse_poll_hours("19, 20,21", [14]) == [19, 20, 21]  # espaces
    assert poll.parse_poll_hours("21,19,20", [14]) == [19, 20, 21]  # tri
    assert poll.parse_poll_hours("8,8,20", [14]) == [8, 20]          # dédoublonnage
    assert poll.parse_poll_hours("", [14, 15]) == [14, 15]           # vide -> fallback
    assert poll.parse_poll_hours(None, [14]) == [14]
    assert poll.parse_poll_hours("99,abc,-1", [14, 15]) == [14, 15]  # invalide -> fallback
