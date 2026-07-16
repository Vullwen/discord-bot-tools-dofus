from __future__ import annotations

from types import SimpleNamespace

import pytest

import db
from cogs.absence import AbsenceCog
from tests.fakes import FakeBot, FakeChannel, FakeInteraction, FakeUser


def _guild(guild_id: int = 2):
    return SimpleNamespace(id=guild_id)


@pytest.mark.asyncio
async def test_submit_absence_publishes_public_and_admin_messages_and_persists(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    public_channel = FakeChannel(100)
    admin_channel = FakeChannel(200)
    cog = AbsenceCog(FakeBot(channel=public_channel))
    scheduled = []

    async def absence_channel(_interaction):
        return public_channel

    async def configured_channel(_guild, key):
        return admin_channel if key == db.SETTING_ABSENCE_ADMIN_CHANNEL else None

    cog._absence_channel = absence_channel
    cog._configured_channel = configured_channel
    cog._schedule_cleanup = lambda absence_id, end: scheduled.append((absence_id, end))

    user = FakeUser(10, "Alice")
    interaction = FakeInteraction(user=user, guild=_guild(), channel=public_channel)

    await cog.submit_absence(interaction, "28/08/2026", "30/08/2026", "Vacances")

    rows = db.search_absences(guild_id=2, today_iso="2026-08-01")
    assert len(rows) == 1
    assert rows[0]["user_id"] == 10
    assert rows[0]["start_date"] == "2026-08-28"
    assert rows[0]["end_date"] == "2026-08-30"
    assert rows[0]["public_channel_id"] == 100
    assert rows[0]["admin_channel_id"] == 200
    assert len(public_channel.sent) == 1
    assert len(admin_channel.sent) == 1
    assert [(absence_id, end.isoformat()) for absence_id, end in scheduled] == [
        (rows[0]["id"], rows[0]["end_date"])
    ]
    assert interaction.followup.messages[0][0] == "Absence publiée dans <#100>."


@pytest.mark.asyncio
async def test_submit_absence_rejects_end_before_start(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    cog = AbsenceCog(FakeBot())
    interaction = FakeInteraction(user=FakeUser(10), guild=_guild())

    await cog.submit_absence(interaction, "30/08/2026", "28/08/2026", "")

    assert db.search_absences(guild_id=2, today_iso="2026-08-01") == []
    assert "date de fin" in interaction.response.messages[0][0]


@pytest.mark.asyncio
async def test_submit_absence_warns_when_reason_has_no_admin_channel(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    public_channel = FakeChannel(100)
    cog = AbsenceCog(FakeBot(channel=public_channel))
    async def absence_channel(_interaction):
        return public_channel

    async def configured_channel(_guild, _key):
        return None

    cog._absence_channel = absence_channel
    cog._configured_channel = configured_channel
    cog._schedule_cleanup = lambda _absence_id, _end: None
    interaction = FakeInteraction(user=FakeUser(10, "Alice"), guild=_guild(), channel=public_channel)

    await cog.submit_absence(interaction, "28/08/2026", "28/08/2026", "IRL")

    assert "Motif non envoyé" in interaction.followup.messages[0][0]
    assert len(public_channel.sent) == 1
