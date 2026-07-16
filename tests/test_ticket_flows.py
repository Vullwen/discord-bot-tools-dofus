from __future__ import annotations

from types import SimpleNamespace

import pytest

import db
from cogs.ticket import TicketCog
from tests.fakes import FakeBot, FakeChannel, FakeInteraction, FakeUser


def _member(user_id: int, name: str):
    return SimpleNamespace(id=user_id, display_name=name, mention=f"<@{user_id}>")


@pytest.mark.asyncio
async def test_close_ticket_by_opener_marks_closed_and_deletes_channel(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("utils.perms.ADMIN_IDS", set())
    channel = FakeChannel(500)
    opener = FakeUser(10)
    db.create_ticket(channel_id=channel.id, guild_id=2, opener_id=opener.id)
    cog = TicketCog(FakeBot(channel=channel))
    interaction = FakeInteraction(user=opener, guild=SimpleNamespace(id=2), channel=channel)

    await cog.close_ticket(interaction)

    assert db.get_ticket_by_channel(channel.id)["closed"] == 1
    assert channel.deleted is True
    assert "Ticket fermé" in interaction.response.messages[0][0]


@pytest.mark.asyncio
async def test_close_ticket_denies_unrelated_user(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("utils.perms.ADMIN_IDS", set())
    channel = FakeChannel(500)
    db.create_ticket(channel_id=channel.id, guild_id=2, opener_id=10)
    cog = TicketCog(FakeBot(channel=channel))
    interaction = FakeInteraction(user=FakeUser(99), guild=SimpleNamespace(id=2), channel=channel)

    await cog.close_ticket(interaction)

    assert db.get_ticket_by_channel(channel.id)["closed"] == 0
    assert channel.deleted is False
    assert interaction.response.messages[0][0] == "Permission refusée."


@pytest.mark.asyncio
async def test_add_members_sets_channel_permissions_and_reports_missing(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("utils.perms.ADMIN_IDS", set())
    monkeypatch.setattr("cogs.ticket.discord.abc.GuildChannel", FakeChannel)
    channel = FakeChannel(500)
    opener = FakeUser(10)
    db.create_ticket(channel_id=channel.id, guild_id=2, opener_id=opener.id)
    alice = _member(20, "Alice")

    async def fetch_member(_user_id):
        return None

    guild = SimpleNamespace(
        id=2,
        get_member=lambda user_id: alice if user_id == alice.id else None,
        fetch_member=fetch_member,
    )
    cog = TicketCog(FakeBot(channel=channel))
    interaction = FakeInteraction(user=opener, guild=guild, channel=channel)

    await cog.add_members(interaction, [FakeUser(20), FakeUser(30)])

    assert channel.permissions[0][0] is alice
    assert channel.permissions[0][1]["view_channel"] is True
    message = interaction.response.messages[0][0]
    assert "Ajouté au salon" in message
    assert "Impossible à ajouter" in message
