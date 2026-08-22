from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

import db
from cogs import market


@pytest.fixture(autouse=True)
def market_name_detection(monkeypatch, tmp_path):
    monkeypatch.setattr(market, "MARKET_FORUM_CHANNEL_ID", 0)
    db.reset_for_tests(str(tmp_path / "market.sqlite"))


class FakeBot:
    def __init__(self, *, channel=None, users=()):
        self.channel = channel
        self.users = {user.id: user for user in users}
        self.added_views = []

    def add_view(self, view, message_id=None):
        self.added_views.append((view, message_id))

    def get_channel(self, channel_id):
        return self.channel if getattr(self.channel, "id", None) == channel_id else None

    async def fetch_channel(self, channel_id):
        return self.get_channel(channel_id)

    def get_user(self, user_id):
        return self.users.get(user_id)

    async def fetch_user(self, user_id):
        user = self.users.get(user_id)
        if user is None:
            user = FakeUser(user_id)
            self.users[user_id] = user
        return user


class FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id
        self.display_name = f"user-{user_id}"
        self.name = self.display_name
        self.dms = []

    def __str__(self):
        return self.display_name

    async def send(self, *, content=None, embed=None, view=None):
        self.dms.append((content, {"embed": embed, "view": view}))


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.modals = []
        self.deferred = False
        self.defer_kwargs = None

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))

    async def send_modal(self, modal):
        self.modals.append(modal)

    async def defer(self, **kwargs):
        self.deferred = True
        self.defer_kwargs = kwargs


class FakeFollowup:
    def __init__(self, *, channel=None):
        self.channel = channel
        self.messages = []

    async def send(self, content=None, **kwargs):
        self.messages.append((content, kwargs))
        events = getattr(self.channel, "events", None)
        if events is not None:
            events.append(("followup", content))


class FakeInteraction:
    def __init__(self, *, user, guild, channel):
        self.user = user
        self.guild = guild
        self.channel = channel
        self.channel_id = getattr(channel, "id", None)
        self.response = FakeResponse()
        self.followup = FakeFollowup(channel=channel)


class FakeSentMessage:
    def __init__(self, *, message_id, content=None, view=None):
        self.id = message_id
        self.content = content
        self.view = view
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeThread:
    def __init__(
        self,
        *,
        thread_id=123,
        name="Gelano",
        owner_id=10,
        parent_name="le marché",
        parent_id=456,
        guild=None,
        tags=(),
    ):
        self.id = thread_id
        self.name = name
        self.owner_id = owner_id
        self.parent_id = parent_id
        self.parent = type("Parent", (), {"name": parent_name})()
        self.guild = guild
        self.applied_tags = [SimpleNamespace(name=tag) for tag in tags]
        self.jump_url = f"https://discord.test/channels/{self.id}"
        self.sent = []
        self.edits = []
        self.events = []
        self._messages = {}
        self._next_id = 1000

    async def send(self, *, content=None, view=None):
        message = FakeSentMessage(message_id=self._next_id, content=content, view=view)
        self._next_id += 1
        self.sent.append(message)
        self._messages[message.id] = message
        return message

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        self.events.append(("edit", kwargs))
        if "name" in kwargs:
            self.name = kwargs["name"]
        if "archived" in kwargs:
            self.archived = kwargs["archived"]
        if "locked" in kwargs:
            self.locked = kwargs["locked"]

    async def fetch_message(self, message_id):
        return self._messages[message_id]


class FakeMessage:
    def __init__(self, *, channel, author=None, message_id=42, components=None):
        self.channel = channel
        self.author = author or SimpleNamespace(bot=False)
        self.id = message_id
        self.components = components or []
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)


@pytest.mark.asyncio
async def test_new_market_thread_gets_control_buttons(monkeypatch):
    thread = FakeThread(guild=SimpleNamespace(id=2))
    cog = market.MarketCog(FakeBot(channel=thread))
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.on_thread_create(thread)

    assert thread.name == "[vente] Gelano"
    assert thread.edits == [{"name": "[vente] Gelano", "reason": "Présentation marché normalisée"}]
    assert len(thread.sent) == 1
    assert "Prix" in thread.sent[0].content
    assert thread.sent[0].view is not None
    labels = [item.label for item in thread.sent[0].view.children]
    assert labels == ["💰 Mettre le prix", "✅ Clôturer la vente"]
    assert db.get_market_post(thread.id)["control_message_id"] == thread.sent[0].id


@pytest.mark.asyncio
async def test_buy_thread_gets_buy_controls(monkeypatch):
    thread = FakeThread(guild=SimpleNamespace(id=2), tags=["achat"])
    cog = market.MarketCog(FakeBot(channel=thread))
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.on_thread_create(thread)

    assert thread.name == "[achat] Gelano"
    assert thread.edits == [{"name": "[achat] Gelano", "reason": "Présentation marché normalisée"}]
    labels = [item.label for item in thread.sent[0].view.children]
    assert "✅ Clôturer l'achat" in labels
    assert "gérer l'achat" in thread.sent[0].content


@pytest.mark.asyncio
async def test_market_message_backfills_missing_control_buttons(monkeypatch):
    guild = SimpleNamespace(id=2)
    thread = FakeThread(name="Bouclier", owner_id=10, guild=guild)
    cog = market.MarketCog(FakeBot(channel=thread))
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.on_message(FakeMessage(channel=thread))
    await cog.on_message(FakeMessage(channel=thread))

    assert thread.name == "Bouclier"
    assert thread.edits == []
    assert len(thread.sent) == 1
    assert db.get_market_post(thread.id)["control_message_id"] == thread.sent[0].id


@pytest.mark.asyncio
async def test_existing_market_controls_are_recorded_and_refreshed_without_duplicate(monkeypatch):
    guild = SimpleNamespace(id=2)
    thread = FakeThread(name="Cape", owner_id=10, guild=guild)
    component = SimpleNamespace(custom_id="bebraid:market:close")
    row = SimpleNamespace(children=[component])
    existing = FakeMessage(channel=thread, message_id=777, components=[row])
    thread._messages[existing.id] = existing

    async def history(*, limit):
        yield existing

    thread.history = history
    cog = market.MarketCog(FakeBot(channel=thread))
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.on_message(FakeMessage(channel=thread))

    assert thread.sent == []
    assert db.get_market_post(thread.id)["control_message_id"] == 777
    labels = [item.label for item in existing.view.children]
    assert labels == ["💰 Mettre le prix", "✅ Clôturer la vente"]


@pytest.mark.asyncio
async def test_recorded_market_control_message_is_refreshed_without_duplicate(monkeypatch):
    guild = SimpleNamespace(id=2)
    thread = FakeThread(name="Cape", owner_id=10, guild=guild)
    existing = FakeMessage(channel=thread, message_id=777)
    thread._messages[existing.id] = existing
    db.upsert_market_post(
        thread_id=thread.id,
        guild_id=guild.id,
        owner_id=thread.owner_id,
        last_activity_at=market.now_paris(),
    )
    db.set_market_post_control_message(thread.id, existing.id)
    cog = market.MarketCog(FakeBot(channel=thread))
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.on_message(FakeMessage(channel=thread))

    assert thread.sent == []
    labels = [item.label for item in existing.view.children]
    assert labels == ["💰 Mettre le prix", "✅ Clôturer la vente"]


def test_configured_market_forum_channel_takes_priority(tmp_path, monkeypatch):
    guild = SimpleNamespace(id=2)
    db.set_guild_setting(guild.id, db.SETTING_MARKET_FORUM_CHANNEL, "999")
    thread = FakeThread(parent_name="autre forum", parent_id=999, guild=guild)
    cog = market.MarketCog(FakeBot(channel=thread))
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    assert cog.is_market_thread(thread) is True


@pytest.mark.asyncio
async def test_op_can_set_price_and_thread_is_renamed(monkeypatch):
    thread = FakeThread(name="Dofus turquoise")
    cog = market.MarketCog(FakeBot(channel=thread))
    user = FakeUser(10)
    interaction = FakeInteraction(user=user, guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.set_price(interaction, 1500000, None)

    assert thread.name == "[vente] Dofus turquoise - 1 500 000 kamas"
    assert thread.edits == [{"name": "[vente] Dofus turquoise - 1 500 000 kamas", "reason": "Prix marché défini par user-10"}]
    assert interaction.response.deferred is True
    assert interaction.response.defer_kwargs == {"ephemeral": True}
    assert interaction.followup.messages[0][0] == "Prix défini : **1 500 000 kamas**."


@pytest.mark.asyncio
async def test_admin_can_set_price(monkeypatch):
    thread = FakeThread(name="Dofus turquoise", owner_id=10)
    cog = market.MarketCog(FakeBot(channel=thread))
    user = FakeUser(99)
    interaction = FakeInteraction(user=user, guild=type("Guild", (), {"owner_id": 99, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.set_price(interaction, 1500000, None)

    assert thread.name == "[vente] Dofus turquoise - 1 500 000 kamas"
    assert thread.edits == [{"name": "[vente] Dofus turquoise - 1 500 000 kamas", "reason": "Prix marché défini par user-99"}]
    assert interaction.response.deferred is True
    assert interaction.response.defer_kwargs == {"ephemeral": True}
    assert interaction.followup.messages[0][0] == "Prix défini : **1 500 000 kamas**."


@pytest.mark.asyncio
async def test_non_op_non_admin_cannot_set_price(monkeypatch):
    thread = FakeThread(owner_id=10)
    cog = market.MarketCog(FakeBot(channel=thread))
    interaction = FakeInteraction(user=FakeUser(99), guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.set_price(interaction, 1500000, None)

    assert thread.name == "Gelano"
    assert interaction.response.messages[0][0] == "Seuls l'OP et les admins peuvent utiliser ce bouton."


@pytest.mark.asyncio
async def test_op_can_prompt_close_choices(monkeypatch):
    thread = FakeThread(owner_id=10)
    cog = market.MarketCog(FakeBot(channel=thread))
    interaction = FakeInteraction(user=FakeUser(10), guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.prompt_close_sale(interaction)

    content, kwargs = interaction.response.messages[0]
    assert content == "Choisis comment clôturer cette vente :"
    assert kwargs["ephemeral"] is True
    labels = [item.label for item in kwargs["view"].children]
    custom_ids = [item.custom_id for item in kwargs["view"].children]
    assert labels == ["Vente annulée", "Vente guilde", "Vente HDV", "🔒 Clôture admin"]
    assert custom_ids[-1] == "bebraid:market:close_choice:sale:admin"


@pytest.mark.asyncio
async def test_admin_close_choice_requires_admin(monkeypatch):
    thread = FakeThread(owner_id=10)
    cog = market.MarketCog(FakeBot(channel=thread))
    interaction = FakeInteraction(user=FakeUser(10), guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.close_sale(interaction, "admin")

    assert thread.edits == []
    assert interaction.response.messages[0][0] == "Seuls les admins peuvent utiliser cette clôture."


@pytest.mark.asyncio
async def test_admin_close_choice_closes_for_admin(monkeypatch):
    thread = FakeThread(owner_id=10)
    owner = FakeUser(10)
    cog = market.MarketCog(FakeBot(channel=thread, users=[owner]))
    interaction = FakeInteraction(user=FakeUser(99), guild=type("Guild", (), {"owner_id": 99, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.close_sale(interaction, "admin")

    assert thread.archived is True
    assert thread.locked is True
    assert owner.dms
    assert "clôturé pour non-respect des règles" in owner.dms[0][0]
    assert "Gelano" in owner.dms[0][0]
    assert interaction.response.deferred is True
    assert interaction.followup.messages[0][0] == "Post marché clôturé pour non-respect des règles."


@pytest.mark.asyncio
async def test_buy_post_prompts_buy_close_choices(monkeypatch):
    thread = FakeThread(owner_id=10, tags=["achat"])
    cog = market.MarketCog(FakeBot(channel=thread))
    interaction = FakeInteraction(user=FakeUser(10), guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.prompt_close_sale(interaction)

    content, kwargs = interaction.response.messages[0]
    labels = [item.label for item in kwargs["view"].children]
    custom_ids = [item.custom_id for item in kwargs["view"].children]
    assert content == "Choisis comment clôturer cet achat :"
    assert labels == ["Achat annulé", "Achat guilde", "Achat HDV", "🔒 Clôture admin"]
    assert custom_ids[-1] == "bebraid:market:close_choice:buy:admin"


@pytest.mark.asyncio
async def test_market_cog_registers_close_choice_fallback_views(monkeypatch):
    bot = FakeBot()
    cog = market.MarketCog(bot)
    task = SimpleNamespace(cancel=lambda: None)

    def create_task(coro):
        coro.close()
        return task

    monkeypatch.setattr(market.asyncio, "create_task", create_task)

    await cog.cog_load()

    custom_ids = [
        item.custom_id
        for view, _message_id in bot.added_views
        for item in view.children
    ]
    assert "bebraid:market:close_choice:sale:admin" in custom_ids
    assert "bebraid:market:close_choice:buy:admin" in custom_ids
    assert cog._cleanup_task is task


@pytest.mark.asyncio
async def test_op_can_close_sale_as_guild_sale(monkeypatch):
    thread = FakeThread(name="[vente] Gelano - 1 500 000 kamas", owner_id=10)
    cog = market.MarketCog(FakeBot(channel=thread))
    interaction = FakeInteraction(user=FakeUser(10), guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.close_sale(interaction, "guild")

    assert thread.name == "[vente] Gelano - 1 500 000 kamas"
    assert thread.archived is True
    assert thread.locked is True
    assert thread.edits[0]["archived"] is True
    assert thread.edits[0]["locked"] is True
    assert [event[0] for event in thread.events] == ["edit"]
    assert thread.events[-1][1]["archived"] is True
    assert thread.events[-1][1]["locked"] is True
    assert interaction.response.deferred is True
    assert interaction.response.defer_kwargs == {"ephemeral": True}
    assert interaction.followup.messages == []


@pytest.mark.asyncio
async def test_buy_post_close_uses_buy_prefix(monkeypatch):
    thread = FakeThread(name="[achat] Dofus turquoise - 1 500 000 kamas", owner_id=10, tags=["achat"])
    cog = market.MarketCog(FakeBot(channel=thread))
    interaction = FakeInteraction(user=FakeUser(10), guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.close_sale(interaction, "hdv")

    assert thread.name == "[achat] Dofus turquoise - 1 500 000 kamas"
    assert thread.archived is True
    assert thread.locked is True
    assert interaction.response.deferred is True
    assert interaction.followup.messages == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    ["failed", "hdv"],
)
async def test_close_sale_statuses_archive_without_extra_thread_edits(monkeypatch, status):
    thread = FakeThread(name="Gelano", owner_id=10)
    cog = market.MarketCog(FakeBot(channel=thread))
    interaction = FakeInteraction(user=FakeUser(10), guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)

    await cog.close_sale(interaction, status)

    assert thread.name == "Gelano"
    assert thread.archived is True
    assert thread.locked is True
    assert thread.edits == [{"locked": True, "archived": True, "reason": f"{market._choice_label('sale', status)} par user-10"}]


@pytest.mark.asyncio
async def test_close_sale_ignores_duplicate_close_in_progress(monkeypatch):
    thread = FakeThread(name="Gelano", owner_id=10)
    cog = market.MarketCog(FakeBot(channel=thread))
    interaction = FakeInteraction(user=FakeUser(10), guild=type("Guild", (), {"owner_id": 1, "id": 1})(), channel=thread)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)
    cog._closing_threads.add(thread.id)

    await cog.close_sale(interaction, "guild")

    assert thread.edits == []
    assert interaction.response.messages[0][0] == "Clôture déjà en cours pour ce post."


@pytest.mark.asyncio
async def test_inactive_market_post_is_closed_and_owner_notified(monkeypatch):
    guild = SimpleNamespace(id=2)
    owner = FakeUser(10)
    thread = FakeThread(name="Anneau rare", owner_id=owner.id, guild=guild)
    bot = FakeBot(channel=thread, users=[owner])
    cog = market.MarketCog(bot)
    monkeypatch.setattr(market.discord, "Thread", FakeThread)
    db.upsert_market_post(
        thread_id=thread.id,
        guild_id=guild.id,
        owner_id=owner.id,
        last_activity_at=market.now_paris() - timedelta(days=31),
    )

    await cog._close_inactive_posts_once()

    assert thread.name == "Anneau rare"
    assert thread.archived is True
    assert thread.locked is True
    assert owner.dms
    assert "30 jours sans activité" in owner.dms[0][0]
    assert db.list_inactive_market_posts(market.now_paris()) == []
