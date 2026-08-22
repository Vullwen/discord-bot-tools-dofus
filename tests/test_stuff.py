from PIL import Image
import pytest

from cogs import stuff
from cogs.stuff import StuffCloseView, StuffCog
from utils.stuff_card import build_stuff_fallback_card, parse_dofusbook_url


class FakeBot:
    def __init__(self):
        self.views = []

    def add_view(self, view):
        self.views.append(view)


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.deferred = False
        self.defer_kwargs = None

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))

    async def defer(self, **kwargs):
        self.deferred = True
        self.defer_kwargs = kwargs


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


class FakeMessage:
    def __init__(self):
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeThread:
    def __init__(self):
        self.edits = []
        self.archived = False
        self.locked = False

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        self.archived = kwargs.get("archived", self.archived)
        self.locked = kwargs.get("locked", self.locked)


class FakeInteraction:
    def __init__(self, *, channel=None, message=None, user_id=10):
        self.channel = channel
        self.message = message
        self.guild = type("Guild", (), {"owner_id": 99, "id": 1})()
        self.user = type("User", (), {"id": user_id})()
        self.response = FakeResponse()
        self.followup = FakeFollowup()


def test_parse_private_dofusbook_url():
    link = parse_dofusbook_url(
        "https://www.dofusbook.net/fr/equipement/private/"
        "22758146-eau-air-ret-pm-dist/objets"
    )

    assert link.host == "www.dofusbook.net"
    assert link.reference == "22758146"
    assert link.label == "Eau Air Ret Pm Dist"


def test_parse_short_dofusbook_url_without_scheme():
    link = parse_dofusbook_url("d-bk.net/fr/d/1XUQs")

    assert link.url == "https://d-bk.net/fr/d/1XUQs"
    assert link.reference == "1XUQs"
    assert link.label == "Stuff 1XUQs"


def test_rejects_other_hosts():
    try:
        parse_dofusbook_url("https://example.com/stuff")
    except ValueError as exc:
        assert "dofusbook.net" in str(exc)
    else:
        raise AssertionError("invalid host should fail")


def test_build_fallback_card_is_png():
    link = parse_dofusbook_url("https://d-bk.net/fr/d/1XUQs")

    card = build_stuff_fallback_card(link, "test")

    with Image.open(card) as image:
        assert image.format == "PNG"
        assert image.size == (900, 420)


def test_stuff_close_view_has_admin_button():
    view = StuffCloseView(StuffCog(FakeBot()))

    assert [item.label for item in view.children] == ["🔒 Clôture admin"]


@pytest.mark.asyncio
async def test_stuff_cog_registers_persistent_close_view():
    bot = FakeBot()
    cog = StuffCog(bot)

    await cog.cog_load()

    assert len(bot.views) == 1
    assert isinstance(bot.views[0], StuffCloseView)


@pytest.mark.asyncio
async def test_close_stuff_denies_non_admin(monkeypatch):
    cog = StuffCog(FakeBot())
    interaction = FakeInteraction(channel=FakeThread())
    monkeypatch.setattr(stuff, "is_bot_admin", lambda _interaction: False)
    monkeypatch.setattr(stuff.discord, "Thread", FakeThread)

    await cog.close_stuff(interaction)

    assert interaction.response.messages[0][0] == "Seuls les admins peuvent utiliser cette clôture."


@pytest.mark.asyncio
async def test_close_stuff_archives_thread_for_admin(monkeypatch):
    thread = FakeThread()
    cog = StuffCog(FakeBot())
    interaction = FakeInteraction(channel=thread)
    monkeypatch.setattr(stuff, "is_bot_admin", lambda _interaction: True)
    monkeypatch.setattr(stuff.discord, "Thread", FakeThread)

    await cog.close_stuff(interaction)

    assert interaction.response.deferred is True
    assert thread.archived is True
    assert thread.locked is True
    assert interaction.followup.messages[0][0] == "Stuff clôturé."


@pytest.mark.asyncio
async def test_close_stuff_deletes_message_outside_thread_for_admin(monkeypatch):
    message = FakeMessage()
    cog = StuffCog(FakeBot())
    interaction = FakeInteraction(channel=object(), message=message)
    monkeypatch.setattr(stuff, "is_bot_admin", lambda _interaction: True)
    monkeypatch.setattr(stuff.discord, "Thread", FakeThread)

    await cog.close_stuff(interaction)

    assert interaction.response.deferred is True
    assert message.deleted is True
    assert interaction.followup.messages[0][0] == "Message stuff supprimé."
