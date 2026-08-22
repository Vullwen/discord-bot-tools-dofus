from PIL import Image
import pytest

from cogs import stuff
from cogs.stuff import StuffCloseView, StuffCog
from utils.stuff_card import build_stuff_fallback_card, parse_dofusbook_url


class FakeBot:
    def __init__(self, users=()):
        self.views = []
        self.users = {user.id: user for user in users}

    def add_view(self, view):
        self.views.append(view)

    def get_user(self, user_id):
        return self.users.get(user_id)

    async def fetch_user(self, user_id):
        return self.users.get(user_id)


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


class FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id
        self.bot = False
        self.dms = []

    async def send(self, *, content=None, **kwargs):
        self.dms.append((content, kwargs))


class FakeMessage:
    def __init__(self, *, author=None, content="", jump_url=None, reference=None):
        self.author = author
        self.content = content
        self.jump_url = jump_url
        self.reference = reference
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeThread:
    def __init__(self, *, owner_id=None, name="Stuff PvM"):
        self.owner_id = owner_id
        self.name = name
        self.jump_url = "https://discord.test/thread"
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
    owner = FakeUser(42)
    thread = FakeThread(owner_id=owner.id)
    cog = StuffCog(FakeBot(users=[owner]))
    interaction = FakeInteraction(channel=thread)
    monkeypatch.setattr(stuff, "is_bot_admin", lambda _interaction: True)
    monkeypatch.setattr(stuff.discord, "Thread", FakeThread)

    await cog.close_stuff(interaction)

    assert interaction.response.deferred is True
    assert thread.archived is True
    assert thread.locked is True
    assert owner.dms
    assert "Ton post stuff **Stuff PvM** a été clôturé pour non-respect des règles." in owner.dms[0][0]
    assert interaction.followup.messages[0][0] == "Stuff clôturé."


@pytest.mark.asyncio
async def test_close_stuff_deletes_message_outside_thread_for_admin(monkeypatch):
    owner = FakeUser(42)
    source = FakeMessage(
        author=owner,
        content="https://d-bk.net/fr/d/1XUQs",
        jump_url="https://discord.test/message",
    )
    message = FakeMessage(reference=type("Reference", (), {"resolved": source})())
    cog = StuffCog(FakeBot())
    interaction = FakeInteraction(channel=object(), message=message)
    monkeypatch.setattr(stuff, "is_bot_admin", lambda _interaction: True)
    monkeypatch.setattr(stuff.discord, "Thread", FakeThread)

    await cog.close_stuff(interaction)

    assert interaction.response.deferred is True
    assert message.deleted is True
    assert owner.dms
    assert "https://d-bk.net/fr/d/1XUQs" in owner.dms[0][0]
    assert "clôturé pour non-respect des règles" in owner.dms[0][0]
    assert interaction.followup.messages[0][0] == "Message stuff supprimé."
