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


def test_level_choice_for_hour_votes(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    db.set_level_choice(rid, 100, "199_minus")
    db.toggle_vote(rid, 100, "hour", "20")
    db.set_level_choice(rid, 200, "199_minus")
    db.set_level_choice(rid, 300, "200_plus")
    db.toggle_vote(rid, 300, "hour", "21")

    assert db.get_level_choice(rid, 100) == "199_minus"
    assert db.get_level_choice(rid, 999) is None
    assert db.count_active_level_choices(rid, "199_minus") == 1
    assert db.count_active_level_choices(rid, "200_plus") == 1


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
    assert {u for u, _, _ in db.get_participants(rid)} == {10, 20}
    assert db.get_participant_level_group(rid, 10) == "200_plus"


def test_participant_level_group(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    db.add_participant(rid, 10, "confirmed", "199_minus")
    db.add_participant(rid, 20, "waitlist", "200_plus")
    assert db.get_participant_level_group(rid, 10) == "199_minus"
    assert db.count_level_group(rid, "199_minus") == 1
    assert db.count_level_group(rid, "200_plus") == 1
    assert db.get_participants(rid) == [
        (10, "confirmed", "199_minus"),
        (20, "waitlist", "200_plus"),
    ]


def test_is_participant(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    assert db.is_participant(rid, 10) is False
    db.add_participant(rid, 10)
    assert db.is_participant(rid, 10) is True
    assert db.is_participant(rid, 99) is False


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


def test_absences_search_and_cleanup(tmp_path):
    _fresh(tmp_path)
    a1 = db.create_absence(
        guild_id=2,
        user_id=10,
        user_display="Alice",
        start_date="2026-07-10",
        end_date="2026-07-12",
        public_channel_id=100,
        public_message_id=1000,
        admin_channel_id=200,
        admin_message_id=2000,
    )
    db.create_absence(
        guild_id=2,
        user_id=20,
        user_display="Bob",
        start_date="2026-07-11",
        end_date="2026-07-13",
        public_channel_id=100,
        public_message_id=1001,
    )
    db.create_absence(
        guild_id=3,
        user_id=10,
        user_display="Alice",
        start_date="2026-07-11",
        end_date="2026-07-13",
        public_channel_id=100,
        public_message_id=1002,
    )

    assert [row["id"] for row in db.search_absences(guild_id=2, today_iso="2026-07-10")] == [a1, a1 + 1]
    assert [row["id"] for row in db.search_absences(guild_id=2, user_id=10, today_iso="2026-07-10")] == [a1]

    db.mark_absence_public_deleted(a1)
    assert [row["id"] for row in db.search_absences(guild_id=2, today_iso="2026-07-10")] == [a1 + 1]
    assert [row["id"] for row in db.list_absences_for_cleanup()] == [a1 + 1, a1 + 2]


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
    db.create_raid(
        name="C", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="breaking_hour_tie",
    )
    assert len(db.list_active_raids()) == 2


def test_create_raid_stores_poll_hours(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour", poll_hours=[19, 20, 21],
    )
    assert db.get_raid(rid)["poll_hours"] == "19,20,21"


def test_create_raid_stores_poll_close_hour(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="Gigalodon", date_iso="2026-06-28", poll_close_hour=12,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    assert db.get_raid(rid)["poll_close_hour"] == 12


def test_list_raids_with_messages(tmp_path):
    _fresh(tmp_path)
    # Scheduled avec scheduled_message_id -> inclus.
    r1 = db.create_raid(
        name="A", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    db.update_raid(r1, scheduled_at=datetime(2026, 6, 28, 21, 0, tzinfo=PARIS), scheduled_message_id=111)
    # Pas de scheduled_at ni message -> exclu.
    db.create_raid(
        name="B", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    # Cancelled avec message -> exclu (annulé, message conservé).
    r3 = db.create_raid(
        name="C", date_iso="2026-06-28", poll_duration_seconds=3600,
        created_by=1, guild_id=2, channel_id=3, state="cancelled",
    )
    db.update_raid(r3, scheduled_at=datetime(2026, 6, 28, 21, 0, tzinfo=PARIS), scheduled_message_id=333)
    assert [r["id"] for r in db.list_raids_with_messages()] == [r1]


def test_toggle_vote_multi(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="X", date_iso="2026-06-28", created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    # Multi-vote : un user peut voter plusieurs créneaux qui coexistent.
    assert db.toggle_vote(rid, 100, "hour", "20") is True   # ajout
    assert db.toggle_vote(rid, 100, "hour", "21") is True   # ajout (2e créneau)
    assert db.get_user_votes(rid, 100, "hour") == ["20", "21"]
    # Re-clic sur un créneau déjà voté -> le retire sans toucher aux autres.
    assert db.toggle_vote(rid, 100, "hour", "20") is False
    assert db.get_user_votes(rid, 100, "hour") == ["21"]
    assert db.get_vote_counts(rid, "hour") == {"21": 1}


def test_replace_votes(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="X", date_iso="2026-06-28", created_by=1, guild_id=2, channel_id=3, state="voting_hour",
    )
    db.toggle_vote(rid, 100, "hour", "20")
    db.toggle_vote(rid, 100, "hour", "21")
    db.replace_votes(rid, 100, "hour", ["14", "15", "16"])
    assert db.get_user_votes(rid, 100, "hour") == ["14", "15", "16"]
    assert db.get_vote_counts(rid, "hour") == {"14": 1, "15": 1, "16": 1}
    db.replace_votes(rid, 100, "hour", [])
    assert db.get_user_votes(rid, 100, "hour") == []
    assert db.get_vote_counts(rid, "hour") == {}


def test_waitlist_promotion(tmp_path):
    _fresh(tmp_path)
    rid = db.create_raid(
        name="X", date_iso="2026-06-28", created_by=1, guild_id=2, channel_id=3, state="scheduled",
    )
    db.add_participant(rid, 1, "confirmed")
    db.add_participant(rid, 2, "confirmed")
    db.add_participant(rid, 3, "waitlist")
    db.add_participant(rid, 4, "waitlist")
    assert db.count_confirmed(rid) == 2
    assert db.count_waitlist(rid) == 2
    # Ordre FIFO de la file d'attente.
    assert db.waitlist_position(rid, 3) == 1
    assert db.waitlist_position(rid, 4) == 2
    # Retirer un confirmé -> promeut le 1er de la file (user 3).
    assert db.remove_participant(rid, 1) == 3
    assert db.get_participant_status(rid, 3) == "confirmed"
    assert db.count_confirmed(rid) == 2
    assert db.count_waitlist(rid) == 1
    # Retirer un waitlist -> aucune promotion.
    assert db.remove_participant(rid, 4) is None
    assert db.count_waitlist(rid) == 0
    # get_participants ordonne confirmés puis liste d'attente.
    db.add_participant(rid, 5, "waitlist")
    parts = db.get_participants(rid)
    assert {u for u, _, _ in parts} == {2, 3, 5}
    assert [u for u, s, _ in parts if s == "waitlist"] == [5]
