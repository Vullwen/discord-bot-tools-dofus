from types import SimpleNamespace

import pytest

from cogs.core import CoreCog, _help_embed


class _FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


def test_help_embed_lists_main_commands():
    embed = _help_embed()
    text = "\n".join(field.value for field in embed.fields)

    for command in (
        "/help",
        "/ping",
        "/stuff",
        "/raid",
        "/list_raids",
        "/ban_raid",
        "/unban_raid",
        "/show_bans",
        "/absence declare",
        "/absence panel",
        "/absence search",
        "/absence add",
        "/absence stop",
        "/absence kick",
        "/setchannel",
        "/setbaserole",
        "/showconfig",
    ):
        assert command in text


@pytest.mark.asyncio
async def test_help_allows_non_admin():
    cog = CoreCog(SimpleNamespace())
    interaction = SimpleNamespace(user=SimpleNamespace(id=10), response=_FakeResponse())

    await CoreCog.help.callback(cog, interaction)

    content, kwargs = interaction.response.messages[0]
    assert content is None
    assert kwargs["ephemeral"] is True
    assert kwargs["embed"].title == "Aide Beb Raid"
