from __future__ import annotations

import pytest

from cogs import market


@pytest.fixture(autouse=True)
def market_name_detection(monkeypatch):
    monkeypatch.setattr(market, "MARKET_FORUM_CHANNEL_ID", 0)


class FakeBot:
    def __init__(self, *, channel=None):
        self.channel = channel
        self.added_views = []

    def add_view(self, view, message_id=None):
        self.added_views.append((view, message_id))


class FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id
        self.display_name = f"user-{user_id}"
        self.name = self.display_name

    def __str__(self):
        return self.display_name


class FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


class FakeInteraction:
    def __init__(self, *, user, guild, channel):
        self.user = user
        self.guild = guild
        self.channel = channel
        self.channel_id = getattr(channel, "id", None)
        self.response = FakeResponse()


class FakeThread:
    def __init__(self, *, name="Gelano", owner_id=10, parent_name="le marché"):
        self.id = 123
        self.name = name
        self.owner_id = owner_id
        self.parent_id = 456
        self.parent = type("Parent", (), {"name": parent_name})()
        self.sent = []
        self.edits = []
        self._messages = {}
        self._next_id = 1000

    async def send(self, *, content=None, view=None):
        message = type("Message", (), {"id": self._next_id, "content": content, "view": view})()
        self._next_id += 1
        self.sent.append(message)
        self._messages[message.id] = message
        return message

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        if "name" in kwargs:
            self.name = kwargs["name"]
        if "archived" in kwargs:
            self.archived = kwargs["archived"]
        if "locked" in kwargs:
            self.locked = kwargs["locked"]

    async def fetch_message(self, message_id):
        return self._messages[message_id]


@pytest.mark.asyncio
async def test_new_market_thread_gets_control_buttons(monkeypatch):
    thread = FakeThread()
    cog = market.MarketCog(FakeBot(channel=thread))
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.on_thread_create(thread)

    assert len(thread.sent) == 1
    assert "Prix" in thread.sent[0].content
    assert thread.sent[0].view is not None


@pytest.mark.asyncio
async def test_op_can_set_price_and_thread_is_renamed(monkeypatch):
    thread = FakeThread(name="Dofus turquoise")
    cog = market.MarketCog(FakeBot(channel=thread))
    user = FakeUser(10)
    interaction = FakeInteraction(user=user, guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.set_price(interaction, 1500000, None)

    assert thread.name == "Dofus turquoise - 1 500 000 kamas"
    assert interaction.response.messages[0][0] == "Prix défini : **1 500 000 kamas**."


@pytest.mark.asyncio
async def test_non_op_cannot_set_price(monkeypatch):
    thread = FakeThread(owner_id=10)
    cog = market.MarketCog(FakeBot(channel=thread))
    interaction = FakeInteraction(user=FakeUser(99), guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.set_price(interaction, 1500000, None)

    assert thread.name == "Gelano"
    assert interaction.response.messages[0][0] == "Seul l'OP peut modifier le prix."


@pytest.mark.asyncio
async def test_op_can_finalize_sale(monkeypatch):
    thread = FakeThread(name="Gelano - 1 500 000 kamas", owner_id=10)
    cog = market.MarketCog(FakeBot(channel=thread))
    interaction = FakeInteraction(user=FakeUser(10), guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.finalize_sale(interaction)

    assert thread.name == "[finalisé] Gelano - 1 500 000 kamas"
    assert thread.archived is True
    assert thread.locked is True
