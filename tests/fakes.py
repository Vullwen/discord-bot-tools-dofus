from __future__ import annotations

from types import SimpleNamespace


class FakeMessage:
    def __init__(
        self,
        channel,
        message_id: int,
        *,
        content=None,
        embed=None,
        view=None,
        file=None,
        allowed_mentions=None,
    ):
        self.channel = channel
        self.id = message_id
        self.content = content
        self.embed = embed
        self.view = view
        self.file = file
        self.allowed_mentions = allowed_mentions
        self.deleted = False
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)

    async def delete(self):
        self.deleted = True


class FakeChannel:
    def __init__(self, channel_id: int = 100):
        self.id = channel_id
        self.mention = f"<#{channel_id}>"
        self.sent = []
        self._messages = {}
        self._next_id = 1000
        self.deleted = False
        self.permissions = []

    async def send(self, *, content=None, embed=None, view=None, file=None, allowed_mentions=None):
        msg = FakeMessage(
            self,
            self._next_id,
            content=content,
            embed=embed,
            view=view,
            file=file,
            allowed_mentions=allowed_mentions,
        )
        self._next_id += 1
        self.sent.append(msg)
        self._messages[msg.id] = msg
        return msg

    async def fetch_message(self, message_id: int):
        return self._messages[message_id]

    async def delete(self, **kwargs):
        self.deleted = True
        self.delete_kwargs = kwargs

    async def set_permissions(self, member, **kwargs):
        self.permissions.append((member, kwargs))


class FakeUser:
    def __init__(self, user_id: int, display_name: str | None = None):
        self.id = user_id
        self.display_name = display_name or f"user-{user_id}"
        self.name = self.display_name
        self.mention = f"<@{user_id}>"
        self.dms = []

    async def send(self, *, content=None, embed=None, view=None):
        self.dms.append(SimpleNamespace(content=content, embed=embed, view=view))


class FakeBot:
    def __init__(self, *, channel=None, users=()):
        self.channel = channel or FakeChannel()
        self.users = {user.id: user for user in users}
        self.added_views = []
        self.latency = 0.042
        self.guilds = []
        self.cogs = {}

    def get_channel(self, channel_id: int):
        return self.channel if self.channel.id == channel_id else None

    async def fetch_channel(self, channel_id: int):
        return self.get_channel(channel_id)

    def get_user(self, user_id: int):
        return self.users.get(user_id)

    async def fetch_user(self, user_id: int):
        user = self.users.get(user_id)
        if user is None:
            user = FakeUser(user_id)
            self.users[user_id] = user
        return user

    def add_view(self, view, message_id=None):
        self.added_views.append((view, message_id))


class FakeResponse:
    def __init__(self):
        self.messages = []
        self.edits = []
        self.modals = []
        self.deferred = False

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))

    async def send_modal(self, modal):
        self.modals.append(modal)

    async def edit_message(self, content=None, **kwargs):
        self.edits.append((content, kwargs))

    async def defer(self, **kwargs):
        self.deferred = True
        self.defer_kwargs = kwargs

    def is_done(self):
        return bool(self.messages or self.edits or self.modals or self.deferred)


class FakeFollowup:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        self.messages.append((content, kwargs))
        return SimpleNamespace(id=9999)


class FakeInteraction:
    def __init__(self, *, user, guild=None, channel=None, channel_id=None):
        self.user = user
        self.guild = guild
        self.channel = channel
        self.channel_id = channel_id if channel_id is not None else getattr(channel, "id", None)
        self.response = FakeResponse()
        self.followup = FakeFollowup()
