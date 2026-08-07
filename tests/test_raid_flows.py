from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

import db
from config import PARIS
from cogs import raid as raid_module
from cogs.raid import LEVEL_199_MINUS, LEVEL_200_PLUS, RaidCog
from tests.fakes import FakeBot, FakeChannel, FakeInteraction, FakeUser


NOW = datetime(2026, 6, 25, 12, 0, tzinfo=PARIS)


def _guild(guild_id: int = 2):
    return SimpleNamespace(id=guild_id, get_channel=lambda _channel_id: None)


def _cog(channel=None, users=()):
    bot = FakeBot(channel=channel, users=users)
    cog = RaidCog(bot)
    scheduled = []

    def fake_schedule(raid_id, kind, when, coro_fn):
        scheduled.append((raid_id, kind, when, coro_fn.__name__))

    cog._schedule = fake_schedule
    cog.scheduled = scheduled
    return cog


def _allowed_role_ids(message) -> set[int]:
    assert message.allowed_mentions is not None
    data = message.allowed_mentions.to_dict()
    assert "everyone" not in data.get("parse", [])
    assert "users" not in data.get("parse", [])
    return {int(role_id) for role_id in data.get("roles", [])}


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    monkeypatch.setattr(raid_module, "now_paris", lambda: NOW)


@pytest.mark.asyncio
async def test_create_fixed_raid_posts_scheduled_and_persists_contract(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = FakeChannel(300)
    creator = FakeUser(10, "Creator")
    cog = _cog(channel=channel, users=[creator])
    db.set_guild_setting(2, db.SETTING_RAID_NOTIFY_ROLE, "555")

    raid_id = await cog.create_raid(
        _guild(),
        channel,
        creator,
        "Gigalodon",
        "28/08/2026 19h30",
        note="Clefs prêtes",
    )

    raid = db.get_raid(raid_id)
    assert raid["state"] == "scheduled"
    assert raid["name"] == "Gigalodon"
    assert raid["fixed_time"] == "19:30"
    assert raid["scheduled_at"] == "2026-08-28T19:30:00+02:00"
    assert raid["scheduled_message_id"] == channel.sent[0].id
    assert db.get_participant_status(raid_id, creator.id) == "confirmed"
    assert db.get_participant_level_group(raid_id, creator.id) == LEVEL_200_PLUS
    assert db.count_confirmed(raid_id) == 1
    assert channel.sent[0].content == "<@&555>"
    assert _allowed_role_ids(channel.sent[0]) == {555}
    assert [kind for _rid, kind, _when, _fn in cog.scheduled] == [
        "del_raid_msgs",
        "remind",
        "done",
    ]


@pytest.mark.asyncio
async def test_create_known_raid_without_time_opens_hour_poll(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = FakeChannel(300)
    creator = FakeUser(10, "Creator")
    cog = _cog(channel=channel, users=[creator])

    raid_id = await cog.create_raid(
        _guild(),
        channel,
        creator,
        "Gigalodon",
        "28/08/2026",
        poll_hours=[19, 20, 21],
        poll_close_hour=18,
    )

    raid = db.get_raid(raid_id)
    assert raid["state"] == "voting_hour"
    assert raid["poll_hours"] == "19,20,21"
    assert raid["poll_close_hour"] == 18
    assert raid["hour_poll_message_id"] == channel.sent[0].id
    assert db.get_participant_status(raid_id, creator.id) == "confirmed"
    assert db.get_participant_level_group(raid_id, creator.id) == LEVEL_200_PLUS
    assert db.count_confirmed(raid_id) == 1
    assert [(kind, fn) for _rid, kind, _when, fn in cog.scheduled] == [
        ("hour_close", "_close_hour_poll")
    ]


@pytest.mark.asyncio
async def test_raid_choice_with_fixed_time_transitions_to_scheduled(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = FakeChannel(300)
    creator = FakeUser(10, "Creator")
    cog = _cog(channel=channel, users=[creator])
    db.set_guild_setting(2, db.SETTING_RAID_NOTIFY_ROLE, "555")

    raid_id = await cog.create_raid(_guild(), channel, creator, None, "28/08/2026 20h")
    db.cast_vote(raid_id, 100, "raid", "Jardins Éternels")

    await cog._close_raid_choice(raid_id)

    raid = db.get_raid(raid_id)
    assert raid["state"] == "scheduled"
    assert raid["name"] == "Jardins Éternels"
    assert raid["scheduled_at"] == "2026-08-28T20:00:00+02:00"
    assert raid["raid_poll_message_id"] is None
    assert raid["scheduled_message_id"] == channel.sent[-1].id
    assert db.get_participant_status(raid_id, creator.id) == "confirmed"
    assert db.count_confirmed(raid_id) == 1
    assert channel.sent[-1].content == "<@&555>"
    assert _allowed_role_ids(channel.sent[-1]) == {555}


@pytest.mark.asyncio
async def test_remind_sends_only_confirmed_users_and_marks_state(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = FakeChannel(300)
    users = [FakeUser(10), FakeUser(20), FakeUser(30)]
    cog = _cog(channel=channel, users=users)
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-08-28",
        created_by=1,
        guild_id=2,
        channel_id=channel.id,
        state="scheduled",
        scheduled_at=datetime(2026, 6, 28, 21, 0, tzinfo=PARIS),
    )
    db.add_participant(raid_id, 10, "confirmed", LEVEL_200_PLUS)
    db.add_participant(raid_id, 20, "waitlist", LEVEL_200_PLUS)
    db.add_participant(raid_id, 30, "confirmed", LEVEL_199_MINUS)

    await cog._remind(raid_id)

    assert len(users[0].dms) == 1
    assert len(users[1].dms) == 0
    assert len(users[2].dms) == 1
    raid = db.get_raid(raid_id)
    assert raid["state"] == "reminded"
    assert raid["reminder_message_id"] == channel.sent[0].id
    assert [kind for _rid, kind, _when, _fn in cog.scheduled] == ["del_reminder"]


@pytest.mark.asyncio
async def test_unregister_confirmed_promotes_waitlist_and_updates_message(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = FakeChannel(300)
    users = [FakeUser(10), FakeUser(20), FakeUser(30)]
    cog = _cog(channel=channel, users=users)
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-08-28",
        created_by=1,
        guild_id=2,
        channel_id=channel.id,
        state="scheduled",
        scheduled_at=datetime(2026, 6, 28, 21, 0, tzinfo=PARIS),
    )
    scheduled = await channel.send(embed=None)
    db.update_raid(raid_id, scheduled_message_id=scheduled.id)
    db.add_participant(raid_id, 10, "confirmed", LEVEL_200_PLUS)
    db.add_participant(raid_id, 20, "waitlist", LEVEL_200_PLUS)

    interaction = FakeInteraction(user=users[0], guild=_guild(), channel=channel)
    await cog.handle_unregister(interaction, raid_id)

    assert db.is_participant(raid_id, 10) is False
    assert db.get_participant_status(raid_id, 20) == "confirmed"
    assert len(users[1].dms) == 1
    assert interaction.response.messages[0][0] == "Désinscrit du rappel MP."
    assert scheduled.edits


@pytest.mark.asyncio
async def test_unregister_200_skips_low_level_waitlist_when_low_cap_full(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = FakeChannel(300)
    users = [FakeUser(uid) for uid in (10, 11, 20, 30, 40)]
    cog = _cog(channel=channel, users=users)
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-08-28",
        created_by=1,
        guild_id=2,
        channel_id=channel.id,
        state="scheduled",
        scheduled_at=datetime(2026, 6, 28, 21, 0, tzinfo=PARIS),
    )
    scheduled = await channel.send(embed=None)
    db.update_raid(raid_id, scheduled_message_id=scheduled.id)
    db.add_participant(raid_id, 10, "confirmed", LEVEL_199_MINUS)
    db.add_participant(raid_id, 11, "confirmed", LEVEL_199_MINUS)
    db.add_participant(raid_id, 20, "confirmed", LEVEL_200_PLUS)
    db.add_participant(raid_id, 30, "waitlist", LEVEL_199_MINUS)
    db.add_participant(raid_id, 40, "waitlist", LEVEL_200_PLUS)

    interaction = FakeInteraction(user=users[2], guild=_guild(), channel=channel)
    await cog.handle_unregister(interaction, raid_id)

    assert db.is_participant(raid_id, 20) is False
    assert db.get_participant_status(raid_id, 30) == "waitlist"
    assert db.get_participant_status(raid_id, 40) == "confirmed"
    assert len(users[3].dms) == 0
    assert len(users[4].dms) == 1


@pytest.mark.asyncio
async def test_unregister_low_level_can_promote_low_level_waitlist(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = FakeChannel(300)
    users = [FakeUser(uid) for uid in (10, 11, 20)]
    cog = _cog(channel=channel, users=users)
    raid_id = db.create_raid(
        name="Gigalodon",
        date_iso="2026-08-28",
        created_by=1,
        guild_id=2,
        channel_id=channel.id,
        state="scheduled",
        scheduled_at=datetime(2026, 6, 28, 21, 0, tzinfo=PARIS),
    )
    scheduled = await channel.send(embed=None)
    db.update_raid(raid_id, scheduled_message_id=scheduled.id)
    db.add_participant(raid_id, 10, "confirmed", LEVEL_199_MINUS)
    db.add_participant(raid_id, 11, "confirmed", LEVEL_199_MINUS)
    db.add_participant(raid_id, 20, "waitlist", LEVEL_199_MINUS)

    interaction = FakeInteraction(user=users[0], guild=_guild(), channel=channel)
    await cog.handle_unregister(interaction, raid_id)

    assert db.is_participant(raid_id, 10) is False
    assert db.get_participant_status(raid_id, 20) == "confirmed"
    assert len(users[2].dms) == 1
