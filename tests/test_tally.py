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


def test_tally_no_votes():
    assert poll.tally({}, ["14", "15"], "21") == "21"


def test_tally_all_zero():
    assert poll.tally({"20": 0}, ["20", "21"], "21") == "21"


def test_reminder_time():
    scheduled = datetime(2026, 6, 28, 21, 0, tzinfo=PARIS)
    assert poll.reminder_time(scheduled, 10) == datetime(2026, 6, 28, 20, 50, tzinfo=PARIS)


def test_parse_duree():
    assert poll.parse_duree("1h") == "1h"
    assert poll.parse_duree("24h") == "24h"
    assert poll.parse_duree(" 12 ") == "12h"
    assert poll.parse_duree(None) == "12h"
    assert poll.parse_duree("nonsense") == "12h"


def test_is_active_and_states():
    assert poll.is_active("voting_hour")
    assert poll.is_active("scheduled")
    assert not poll.is_active("done")
    assert not poll.is_active("cancelled")


def test_format_counts_bold_leader():
    out = poll.format_counts({"14": 0, "20": 3, "21": 1}, ["14", "20", "21"], suffix="h")
    assert "**20h: 3**" in out
    assert "14h: 0" in out
