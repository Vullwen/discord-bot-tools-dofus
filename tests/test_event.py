from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image

import db
from cogs.event import (
    EVENT_OPEN,
    PRESET_SKIN,
    SUBMISSION_ACTIVE,
    _finalist_target,
    build_skin_fallback_card,
    parse_barbofus_skin_url,
    parse_deadline,
    parse_submission_close,
    parse_user_id,
)

PARIS = ZoneInfo("Europe/Paris")


def _fresh(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))


def test_parse_barbofus_skin_url():
    link = parse_barbofus_skin_url("barbofus.com/unity-skin/12407")

    assert link.url == "https://barbofus.com/unity-skin/12407"
    assert link.reference == "12407"
    assert link.label == "Skin Barbofus #12407"


def test_parse_barbofus_skin_url_rejects_other_hosts():
    try:
        parse_barbofus_skin_url("https://example.com/unity-skin/12407")
    except ValueError as exc:
        assert "barbofus.com" in str(exc)
    else:
        raise AssertionError("invalid host should fail")


def test_build_skin_fallback_card_is_png():
    link = parse_barbofus_skin_url("https://barbofus.com/unity-skin/12407")

    card = build_skin_fallback_card(link, "test")

    with Image.open(card) as image:
        assert image.format == "PNG"
        assert image.size == (900, 420)


def test_parse_deadline_accepts_date_and_hour():
    now = datetime(2026, 8, 31, 12, 0, tzinfo=PARIS)

    result = parse_deadline("demain 21h30", field_name="clôture", now=now)

    assert result.isoformat() == "2026-09-01T21:30:00+02:00"


def test_parse_deadline_accepts_duration():
    now = datetime(2026, 8, 31, 12, 0, tzinfo=PARIS)

    result = parse_deadline("48h", field_name="clôture", now=now)

    assert result.isoformat() == "2026-09-02T12:00:00+02:00"


def test_parse_submission_close_accepts_duration():
    now = datetime(2026, 8, 31, 12, 0, tzinfo=PARIS)

    result = parse_submission_close("48h", now=now)

    assert result.isoformat() == "2026-09-02T12:00:00+02:00"


def test_parse_user_id_accepts_mentions():
    assert parse_user_id("<@123456789012345678>") == 123456789012345678


def test_parse_user_id_rejects_invalid_value():
    try:
        parse_user_id("pas un membre")
    except ValueError as exc:
        assert "mention" in str(exc)
    else:
        raise AssertionError("invalid member value should fail")


def test_event_persistence_members_submissions_and_votes(tmp_path):
    _fresh(tmp_path)
    registration_close_at = datetime(2026, 9, 1, 21, 0, tzinfo=PARIS)
    event_id = db.create_event(
        guild_id=1,
        name="Concours été",
        preset=PRESET_SKIN,
        theme="Royal bouftou",
        created_by=10,
        state=EVENT_OPEN,
        registration_close_at=registration_close_at,
        submissions_close_at=datetime(2026, 8, 31, 21, 0, tzinfo=PARIS),
    )

    db.update_event(
        event_id,
        channel_id=201,
        admin_channel_id=203,
        announcement_channel_id=202,
        announcement_message_id=301,
    )
    db.add_event_member(event_id, 42)
    db.add_event_member(event_id, 42)
    submission_id = db.upsert_event_submission(
        event_id=event_id,
        user_id=42,
        url="https://barbofus.com/unity-skin/12407",
        reference="12407",
        label="Skin Barbofus #12407",
        image=b"png",
        capture_reason=None,
    )
    db.cast_event_vote(event_id, submission_id, 1000)
    db.cast_event_vote(event_id, submission_id, 1000)
    db.cast_event_admin_vote(event_id, submission_id, 2000)
    db.cast_event_admin_vote(event_id, submission_id, 2000)

    event = db.get_event(event_id)
    submissions = db.list_event_submissions(event_id)

    assert event["theme"] == "Royal bouftou"
    assert event["admin_channel_id"] == 203
    assert event["registration_close_at"] == registration_close_at.isoformat()
    assert db.count_event_members(event_id) == 1
    assert db.is_event_member(event_id, 42) is True
    assert submissions[0]["id"] == submission_id
    assert submissions[0]["user_id"] == 42
    assert submissions[0]["stage"] == SUBMISSION_ACTIVE
    assert db.get_event_vote_counts(event_id) == {submission_id: 1}
    assert db.get_event_admin_vote_counts(event_id) == {submission_id: 1}


def test_event_ban_removes_member_and_blocks_rejoin(tmp_path):
    _fresh(tmp_path)
    event_id = db.create_event(
        guild_id=1,
        name="Concours été",
        preset=None,
        created_by=10,
        state=EVENT_OPEN,
        registration_close_at=datetime(2026, 9, 1, 21, 0, tzinfo=PARIS),
    )
    db.add_event_member(event_id, 42)

    db.ban_event_member(event_id=event_id, user_id=42, banned_by=10, reason="test")

    assert db.count_event_members(event_id) == 0
    assert db.is_event_member(event_id, 42) is False
    assert db.is_event_banned(event_id, 42) is True


def test_event_pending_registration_then_approval(tmp_path):
    _fresh(tmp_path)
    event_id = db.create_event(
        guild_id=1,
        name="Concours été",
        preset=PRESET_SKIN,
        created_by=10,
        state=EVENT_OPEN,
        registration_close_at=datetime(2026, 9, 1, 21, 0, tzinfo=PARIS),
        submissions_close_at=datetime(2026, 9, 2, 21, 0, tzinfo=PARIS),
    )

    db.add_event_member(event_id, 42, status="pending")
    db.set_event_member_approval_message(event_id, 42, 1234)

    assert db.count_event_members(event_id) == 0
    assert db.count_pending_event_members(event_id) == 1
    assert db.is_event_member(event_id, 42) is False
    assert db.get_event_member(event_id, 42)["approval_message_id"] == 1234
    assert db.approve_event_member(event_id, 42, approved_by=10) is True
    assert db.count_event_members(event_id) == 1
    assert db.count_pending_event_members(event_id) == 0
    assert db.is_event_member(event_id, 42) is True


def test_finalist_target_scales_with_submission_count():
    assert _finalist_target(0) == 0
    assert _finalist_target(2) == 2
    assert _finalist_target(5) == 3
    assert _finalist_target(6) == 5
    assert _finalist_target(10) == 5
    assert _finalist_target(11) == 10
