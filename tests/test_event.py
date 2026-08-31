from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image

import db
from cogs.event import (
    EVENT_OPEN,
    PRESET_SKIN,
    build_skin_fallback_card,
    parse_event_datetime,
    parse_barbofus_skin_url,
    parse_submission_close,
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


def test_parse_event_datetime_accepts_date_and_hour():
    now = datetime(2026, 8, 31, 12, 0, tzinfo=PARIS)

    result = parse_event_datetime("demain 21h30", now=now)

    assert result.isoformat() == "2026-09-01T21:30:00+02:00"


def test_parse_event_datetime_rejects_duration():
    now = datetime(2026, 8, 31, 12, 0, tzinfo=PARIS)

    try:
        parse_event_datetime("48h", now=now)
    except ValueError as exc:
        assert "date" in str(exc)
    else:
        raise AssertionError("event end should require a date")


def test_parse_submission_close_accepts_duration_before_event_end():
    now = datetime(2026, 8, 31, 12, 0, tzinfo=PARIS)
    event_end = datetime(2026, 9, 3, 20, 0, tzinfo=PARIS)

    result = parse_submission_close("48h", event_end_at=event_end, now=now)

    assert result.isoformat() == "2026-09-02T12:00:00+02:00"


def test_parse_submission_close_rejects_after_event_end():
    now = datetime(2026, 8, 31, 12, 0, tzinfo=PARIS)
    event_end = datetime(2026, 9, 1, 12, 0, tzinfo=PARIS)

    try:
        parse_submission_close("48h", event_end_at=event_end, now=now)
    except ValueError as exc:
        assert "avant la fin" in str(exc)
    else:
        raise AssertionError("submission close after event end should fail")


def test_event_persistence_members_submissions_and_votes(tmp_path):
    _fresh(tmp_path)
    event_end_at = datetime(2026, 9, 1, 21, 0, tzinfo=PARIS)
    event_id = db.create_event(
        guild_id=1,
        name="Concours été",
        preset=PRESET_SKIN,
        created_by=10,
        state=EVENT_OPEN,
        event_end_at=event_end_at,
        submissions_close_at=datetime(2026, 8, 31, 21, 0, tzinfo=PARIS),
    )

    db.update_event(
        event_id,
        participant_role_id=101,
        admin_role_id=102,
        channel_id=201,
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

    event = db.get_event(event_id)
    submissions = db.list_event_submissions(event_id)

    assert event["participant_role_id"] == 101
    assert event["event_end_at"] == event_end_at.isoformat()
    assert db.count_event_members(event_id) == 1
    assert db.is_event_member(event_id, 42) is True
    assert submissions[0]["id"] == submission_id
    assert submissions[0]["user_id"] == 42
    assert db.get_event_vote_counts(event_id) == {submission_id: 1}
