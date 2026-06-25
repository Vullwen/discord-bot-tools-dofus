from datetime import datetime
from zoneinfo import ZoneInfo

import db

PARIS = ZoneInfo("Europe/Paris")


def _fresh(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))


def test_create_and_get(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon",
        date_iso="2026-06-28",
        poll_duration_seconds=3600,
        created_by=1,
        guild_id=2,
        channel_id=3,
        state="voting_hour",
        hour_poll_closes_at=datetime(2026, 6, 25, 13, 0, tzinfo=PARIS),
    )
    raid = db.get_raid(rid)
    assert raid["name"] == "Gigalodon"
    assert raid["state"] == "voting_hour"
    assert raid["poll_duration_seconds"] == 3600


def test_votes_changeable_and_counts(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name=None, date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="choosing_raid",
    )
    db.cast_vote(rid, 100, "raid", "Gigalodon")
    db.cast_vote(rid, 100, "raid", "Jardins Éternels")  # changement
    db.cast_vote(rid, 200, "raid", "Gigalodon")
    counts = db.get_vote_counts(rid, "raid")
    assert counts["Gigalodon"] == 1
    assert counts["Jardins Éternels"] == 1
    assert db.get_voters(rid, "raid", "Gigalodon") == [200]


def test_participants(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    db.add_participant(rid, 10)
    db.add_participant(rid, 10)  # doublon ignoré
    db.add_participant(rid, 20)
    assert db.count_participants(rid) == 2
    assert set(db.get_participants(rid)) == {10, 20}


def test_update_and_state_serializes_datetime(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    db.update_raid(
        rid, state="scheduled",
        scheduled_at=datetime(2026, 6, 28, 21, 0, tzinfo=PARIS),
    )
    raid = db.get_raid(rid)
    assert raid["state"] == "scheduled"
    assert raid["scheduled_at"] == "2026-06-28T21:00:00+02:00"


def test_tickets(tmp_path):
    _fresh(tmp_path)
    db.create_ticket(channel_id=111, guild_id=2, opener_id=5)
    ticket = db.get_ticket_by_channel(111)
    assert ticket["opener_id"] == 5
    assert ticket["closed"] == 0
    db.close_ticket(111)
    assert db.get_ticket_by_channel(111)["closed"] == 1


def test_list_active_excludes_terminal(tmp_path):
    _fresh(tmp_path)
    db.create_raid(
        name="A", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    db.create_raid(
        name="B", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="done",
    )
    assert len(db.list_active_raids()) == 1
