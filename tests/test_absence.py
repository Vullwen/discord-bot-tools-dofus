from datetime import date
from types import SimpleNamespace

import pytest

from cogs.absence import AbsenceCog, _cleanup_when, _format_absence_period


def test_format_absence_period_one_day():
    assert _format_absence_period(date(2026, 7, 10), date(2026, 7, 10)) == "Le vendredi 10/07"


def test_format_absence_period_range():
    assert (
        _format_absence_period(date(2026, 7, 10), date(2026, 7, 12))
        == "Du vendredi 10/07 au dimanche 12/07"
    )


def test_cleanup_when_is_day_after_end_at_midnight():
    cleanup = _cleanup_when(date(2026, 7, 12))
    assert cleanup.isoformat() == "2026-07-13T00:00:00+02:00"


class _FakeResponse:
    def __init__(self):
        self.deferred = False
        self.defer_kwargs = None
        self.messages = []

    async def defer(self, **kwargs):
        self.deferred = True
        self.defer_kwargs = kwargs

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


class _FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


class _FakeChannel:
    id = 100
    mention = "<#100>"

    def __init__(self):
        self.sent = []

    async def send(self, *, content=None, embed=None, view=None):
        self.sent.append(SimpleNamespace(content=content, embed=embed, view=view))


class _FakeUser:
    def __init__(self, user_id):
        self.id = user_id
        self.mention = f"<@{user_id}>"
        self.dms = []

    async def send(self, *, content=None, embed=None, view=None):
        self.dms.append(SimpleNamespace(content=content, embed=embed, view=view))


@pytest.mark.asyncio
async def test_absence_channel_falls_back_to_interaction_channel():
    panel_channel = _FakeChannel()
    cog = AbsenceCog(SimpleNamespace())

    async def configured_channel(_guild, _key):
        return None

    cog._configured_channel = configured_channel
    interaction = SimpleNamespace(guild=SimpleNamespace(id=2), channel=panel_channel)

    assert await cog._absence_channel(interaction) is panel_channel


@pytest.mark.asyncio
async def test_kick_abs_notifies_absence_channel_and_member_dm(monkeypatch):
    monkeypatch.setattr("cogs.absence.is_raid_organizer", lambda _interaction: True)
    public_channel = _FakeChannel()
    cog = AbsenceCog(SimpleNamespace())

    async def absence_channel(_interaction):
        return public_channel

    cog._absence_channel = absence_channel
    member = _FakeUser(20)
    interaction = SimpleNamespace(
        user=_FakeUser(10),
        guild=SimpleNamespace(id=2),
        response=_FakeResponse(),
        followup=_FakeFollowup(),
    )

    await AbsenceCog.kick_abs.callback(cog, interaction, member)

    expected = (
        "<@20>, tu as été kick de la guilde pour afk, "
        "n'hésite pas à repostuler quand tu recommences à jouer."
    )
    assert public_channel.sent[0].content == expected
    assert member.dms[0].content == expected
    assert interaction.response.deferred is True
    assert interaction.response.defer_kwargs == {"ephemeral": True, "thinking": True}
    assert interaction.followup.messages[0] == ("Message envoyé dans <#100>.", {"ephemeral": True})
