from __future__ import annotations

from types import SimpleNamespace

import pytest

import db
from cogs.ticket import TicketCog
from tests.fakes import FakeBot, FakeChannel, FakeInteraction, FakeUser


def _member(user_id: int, name: str):
    return SimpleNamespace(id=user_id, display_name=name, mention=f"<@{user_id}>")


class FakeRole:
    def __init__(self, role_id: int, name: str):
        self.id = role_id
        self.name = name
        self.mention = f"<@&{role_id}>"


class FakeMember(FakeUser):
    def __init__(self, user_id: int, display_name: str | None = None):
        super().__init__(user_id, display_name)
        self.roles = []
        self.kicked = False

    async def add_roles(self, role, **kwargs):
        self.roles.append(role)
        self.add_roles_kwargs = kwargs

    async def kick(self, **kwargs):
        self.kicked = True
        self.kick_kwargs = kwargs


class FakeGuild:
    def __init__(self, *, guild_id: int = 2, members=(), roles=()):
        self.id = guild_id
        self.members = {member.id: member for member in members}
        self.roles = {role.id: role for role in roles}

    def get_member(self, user_id: int):
        return self.members.get(user_id)

    async def fetch_member(self, user_id: int):
        return self.members.get(user_id)

    def get_role(self, role_id: int):
        return self.roles.get(role_id)


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


@pytest.mark.asyncio
async def test_onboarding_visitor_choice_grants_role_and_schedules_close(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    scheduled = []
    monkeypatch.setattr(
        TicketCog,
        "_schedule_onboarding_close",
        lambda _self, channel_id, close_after: scheduled.append((channel_id, close_after)),
    )
    channel = FakeChannel(500)
    visitor = FakeMember(10)
    role = FakeRole(90, "Visiteur")
    guild = FakeGuild(members=(visitor,), roles=(role,))
    db.set_guild_setting(guild.id, db.SETTING_VISITOR_ROLE, str(role.id))
    db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=visitor.id)
    db.create_onboarding_ticket(channel_id=channel.id, guild_id=guild.id, user_id=visitor.id)
    cog = TicketCog(FakeBot(channel=channel))
    interaction = FakeInteraction(user=visitor, guild=guild, channel=channel)

    await cog.choose_onboarding_path(interaction, choice="visitor")

    ticket = db.get_onboarding_ticket_by_channel(channel.id)
    assert ticket["choice"] == "visitor"
    assert ticket["status"] == "visitor_granted"
    assert ticket["close_after"] is not None
    assert visitor.roles == [role]
    assert scheduled[0][0] == channel.id
    assert "fermé dans 15 minutes" in interaction.response.messages[0][0]


@pytest.mark.asyncio
async def test_onboarding_guild_review_accepts_and_grants_guild_role(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.ticket.is_raid_organizer", lambda _interaction: True)
    monkeypatch.setattr(TicketCog, "_schedule_onboarding_close", lambda *_args: None)
    channel = FakeChannel(500)
    applicant = FakeMember(10)
    admin = FakeMember(20)
    role = FakeRole(91, "Guilde")
    guild = FakeGuild(members=(applicant, admin), roles=(role,))
    db.set_guild_setting(guild.id, db.SETTING_GUILD_MEMBER_ROLE, str(role.id))
    db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=applicant.id)
    db.create_onboarding_ticket(channel_id=channel.id, guild_id=guild.id, user_id=applicant.id)
    cog = TicketCog(FakeBot(channel=channel))

    await cog.choose_onboarding_path(
        FakeInteraction(user=applicant, guild=guild, channel=channel),
        choice="guild",
    )
    await cog.review_guild_application(
        FakeInteraction(user=admin, guild=guild, channel=channel),
        accepted=True,
    )

    ticket = db.get_onboarding_ticket_by_channel(channel.id)
    assert ticket["choice"] == "guild"
    assert ticket["status"] == "accepted"
    assert applicant.roles == [role]


@pytest.mark.asyncio
async def test_onboarding_guild_review_rejects_and_kicks_member(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.ticket.is_raid_organizer", lambda _interaction: True)
    monkeypatch.setattr(TicketCog, "_schedule_onboarding_close", lambda *_args: None)
    channel = FakeChannel(500)
    applicant = FakeMember(10)
    admin = FakeMember(20)
    guild = FakeGuild(members=(applicant, admin))
    db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=applicant.id)
    db.create_onboarding_ticket(channel_id=channel.id, guild_id=guild.id, user_id=applicant.id)
    db.update_onboarding_ticket(channel.id, choice="guild", status="guild_pending")
    cog = TicketCog(FakeBot(channel=channel))

    await cog.review_guild_application(
        FakeInteraction(user=admin, guild=guild, channel=channel),
        accepted=False,
    )

    assert db.get_onboarding_ticket_by_channel(channel.id)["status"] == "rejected"
    assert applicant.kicked is True
