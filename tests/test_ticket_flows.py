from __future__ import annotations

from types import SimpleNamespace

import pytest

import db
from cogs.ticket import OnboardingChoiceView, OnboardingReviewView, TicketCog, _rules_embed
from tests.fakes import FakeBot, FakeChannel, FakeInteraction, FakeUser


def _member(user_id: int, name: str):
    return SimpleNamespace(id=user_id, display_name=name, mention=f"<@{user_id}>")


def test_rules_embed_uses_fields_for_readable_sections():
    embed = _rules_embed(guild_name="Bagarres & Belettes", guild_icon_url="https://cdn.example/icon.png")

    assert embed.title == "Bagarres & Belettes"
    assert embed.author.name == "Bagarres & Belettes"
    assert embed.author.icon_url == "https://cdn.example/icon.png"
    assert embed.thumbnail.url == "https://cdn.example/icon.png"
    assert len(embed.fields) == 9
    assert embed.fields[0].name == "👤 1 — Comportement des membres"
    assert "Respect obligatoire" in embed.fields[0].value
    assert "\n- Aucune insulte" in embed.fields[0].value
    assert embed.fields[4].name == "🤝 5 — Entraide"
    assert "rang Fouine" in embed.fields[4].value
    assert "plus bas niveau" in embed.fields[4].value


def test_onboarding_views_include_admin_close_button():
    cog = TicketCog(FakeBot())

    choice_labels = [item.label for item in OnboardingChoiceView(cog).children]
    review_labels = [item.label for item in OnboardingReviewView(cog).children]

    assert "Clôturer le ticket" in choice_labels
    assert "Clôturer le ticket" in review_labels


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
async def test_onboarding_visitor_choice_waits_for_admin_review(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
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
    assert ticket["status"] == "visitor_pending"
    assert ticket["close_after"] is None
    assert visitor.roles == []
    assert "Un administrateur regardera ta demande" in interaction.response.messages[0][0]
    assert "Le bouton Accepter est réservé aux admins" in interaction.response.messages[0][0]
    assert interaction.response.messages[0][1]["view"] is not None


@pytest.mark.asyncio
async def test_onboarding_guild_choice_opens_application_form(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = FakeChannel(500)
    applicant = FakeMember(10)
    guild = FakeGuild(members=(applicant,))
    db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=applicant.id)
    db.create_onboarding_ticket(channel_id=channel.id, guild_id=guild.id, user_id=applicant.id)
    cog = TicketCog(FakeBot(channel=channel))
    interaction = FakeInteraction(user=applicant, guild=guild, channel=channel)

    await cog.choose_onboarding_path(interaction, choice="guild")

    ticket = db.get_onboarding_ticket_by_channel(channel.id)
    assert ticket["choice"] is None
    assert ticket["status"] == "pending"
    assert interaction.response.modals


@pytest.mark.asyncio
async def test_guild_application_submit_stores_answers_and_waits_for_admin_review(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = FakeChannel(500)
    applicant = FakeMember(10)
    guild = FakeGuild(members=(applicant,))
    db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=applicant.id)
    db.create_onboarding_ticket(channel_id=channel.id, guild_id=guild.id, user_id=applicant.id)
    cog = TicketCog(FakeBot(channel=channel))
    interaction = FakeInteraction(user=applicant, guild=guild, channel=channel)

    await cog.submit_guild_application(
        interaction,
        pseudo="Belette-Royale",
        classes="Eniripsa 200",
        goals="PvM, fun, opti",
    )

    ticket = db.get_onboarding_ticket_by_channel(channel.id)
    assert ticket["choice"] == "guild"
    assert ticket["status"] == "guild_pending"
    assert ticket["application_pseudo"] == "Belette-Royale"
    assert ticket["application_classes"] == "Eniripsa 200"
    assert ticket["application_goals"] == "PvM, fun, opti"
    assert "Un administrateur regardera sa demande" in interaction.response.messages[0][0]
    assert "Le bouton Accepter est réservé aux admins" in interaction.response.messages[0][0]
    embed = interaction.response.messages[0][1]["embed"]
    assert embed.title == "Candidature guilde"
    assert embed.fields[0].value == "Belette-Royale"
    assert embed.fields[1].value == "Eniripsa 200"
    assert embed.fields[2].value == "PvM, fun, opti"
    assert interaction.response.messages[0][1]["view"] is not None


@pytest.mark.asyncio
async def test_onboarding_visitor_review_accepts_and_grants_visitor_role(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.ticket.is_bot_admin", lambda _interaction: True)
    channel = FakeChannel(500)
    visitor = FakeMember(10)
    admin = FakeMember(20)
    role = FakeRole(90, "Visiteur")
    guild = FakeGuild(members=(visitor, admin), roles=(role,))
    db.set_guild_setting(guild.id, db.SETTING_VISITOR_ROLE, str(role.id))
    db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=visitor.id)
    db.create_onboarding_ticket(channel_id=channel.id, guild_id=guild.id, user_id=visitor.id)
    cog = TicketCog(FakeBot(channel=channel))

    await cog.choose_onboarding_path(
        FakeInteraction(user=visitor, guild=guild, channel=channel),
        choice="visitor",
    )
    await cog.review_onboarding_request(
        FakeInteraction(user=admin, guild=guild, channel=channel),
        accepted=True,
    )

    ticket = db.get_onboarding_ticket_by_channel(channel.id)
    assert ticket["choice"] == "visitor"
    assert ticket["status"] == "visitor_granted"
    assert ticket["close_after"] is None
    assert visitor.roles == [role]


@pytest.mark.asyncio
async def test_onboarding_guild_review_accepts_and_grants_guild_role(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.ticket.is_bot_admin", lambda _interaction: True)
    channel = FakeChannel(500)
    applicant = FakeMember(10)
    admin = FakeMember(20)
    role = FakeRole(91, "Guilde")
    guild = FakeGuild(members=(applicant, admin), roles=(role,))
    db.set_guild_setting(guild.id, db.SETTING_GUILD_MEMBER_ROLE, str(role.id))
    db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=applicant.id)
    db.create_onboarding_ticket(channel_id=channel.id, guild_id=guild.id, user_id=applicant.id)
    cog = TicketCog(FakeBot(channel=channel))

    await cog.submit_guild_application(
        FakeInteraction(user=applicant, guild=guild, channel=channel),
        pseudo="Belette-Royale",
        classes="Eniripsa 200",
        goals="PvM",
    )
    await cog.review_onboarding_request(
        FakeInteraction(user=admin, guild=guild, channel=channel),
        accepted=True,
    )

    ticket = db.get_onboarding_ticket_by_channel(channel.id)
    assert ticket["choice"] == "guild"
    assert ticket["status"] == "accepted"
    assert ticket["close_after"] is None
    assert applicant.roles == [role]


@pytest.mark.asyncio
async def test_onboarding_guild_review_rejects_and_kicks_member(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.ticket.is_bot_admin", lambda _interaction: True)
    channel = FakeChannel(500)
    applicant = FakeMember(10)
    admin = FakeMember(20)
    guild = FakeGuild(members=(applicant, admin))
    db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=applicant.id)
    db.create_onboarding_ticket(channel_id=channel.id, guild_id=guild.id, user_id=applicant.id)
    db.update_onboarding_ticket(channel.id, choice="guild", status="guild_pending")
    cog = TicketCog(FakeBot(channel=channel))

    await cog.review_onboarding_request(
        FakeInteraction(user=admin, guild=guild, channel=channel),
        accepted=False,
    )

    assert db.get_onboarding_ticket_by_channel(channel.id)["status"] == "rejected"
    assert applicant.kicked is True


@pytest.mark.asyncio
async def test_close_onboarding_ticket_requires_bot_admin_and_deletes_channel(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    channel = FakeChannel(500)
    admin = FakeMember(20)
    guild = FakeGuild(members=(admin,))
    db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=10)
    db.create_onboarding_ticket(channel_id=channel.id, guild_id=guild.id, user_id=10)
    cog = TicketCog(FakeBot(channel=channel))

    monkeypatch.setattr("cogs.ticket.is_bot_admin", lambda _interaction: False)
    denied = FakeInteraction(user=admin, guild=guild, channel=channel)
    await cog.close_onboarding_ticket(denied)
    assert denied.response.messages[0][0] == "Permission refusée."
    assert channel.deleted is False

    monkeypatch.setattr("cogs.ticket.is_bot_admin", lambda _interaction: True)
    accepted = FakeInteraction(user=admin, guild=guild, channel=channel)
    await cog.close_onboarding_ticket(accepted)

    assert db.get_onboarding_ticket_by_channel(channel.id)["status"] == "closed"
    assert db.get_ticket_by_channel(channel.id)["closed"] == 1
    assert channel.deleted is True


@pytest.mark.asyncio
async def test_accept_rules_opens_onboarding_ticket(monkeypatch):
    created_channel = FakeChannel(777)

    async def open_ticket(_self, member, *, reason):
        assert member.id == 10
        assert "clic règlement" in reason
        return created_channel

    monkeypatch.setattr("cogs.ticket.discord.Member", FakeMember)
    monkeypatch.setattr(TicketCog, "open_onboarding_ticket", open_ticket)
    cog = TicketCog(FakeBot(channel=created_channel))
    interaction = FakeInteraction(
        user=FakeMember(10),
        guild=SimpleNamespace(id=2),
        channel=FakeChannel(500),
    )

    await cog.accept_rules(interaction)

    assert interaction.response.deferred is True
    assert created_channel.mention in interaction.followup.messages[0][0]


@pytest.mark.asyncio
async def test_accept_rules_denies_member_with_existing_onboarding_role(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    role = FakeRole(90, "Visiteur")
    member = FakeMember(10)
    member.roles.append(role)
    guild = FakeGuild(members=(member,), roles=(role,))
    db.set_guild_setting(guild.id, db.SETTING_VISITOR_ROLE, str(role.id))

    async def open_ticket(*_args, **_kwargs):
        raise AssertionError("ticket should not be opened")

    monkeypatch.setattr("cogs.ticket.discord.Member", FakeMember)
    monkeypatch.setattr(TicketCog, "open_onboarding_ticket", open_ticket)
    cog = TicketCog(FakeBot(channel=FakeChannel(777)))
    interaction = FakeInteraction(
        user=member,
        guild=guild,
        channel=FakeChannel(500),
    )

    await cog.accept_rules(interaction)

    assert interaction.response.messages[0][0] == "Tu as déjà accès au serveur. Pas besoin de rouvrir un ticket."
