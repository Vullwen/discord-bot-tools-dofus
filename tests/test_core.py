from types import SimpleNamespace

import pytest

from cogs.core import BOT_NAME, HELP_SECTIONS, CoreCog, _help_embed


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
        "/stuff refresh",
        "/event",
        "/event_submissions",
        "/raid start",
        "/raid list",
        "/raid warn",
        "/raid ban",
        "/raid unban",
        "/raid bans",
        "/deathnote add",
        "/deathnote list",
        "/deathnote remove",
        "/absence declare",
        "/absence panel",
        "/absence search",
        "/absence add",
        "/absence stop",
        "/absence kick",
        "/config channel",
        "/config role",
        "/config guild",
        "/config show",
    ):
        assert command in text


def test_help_sections_are_unique_and_rendered():
    embed = _help_embed()
    section_names = [name for name, _entries in HELP_SECTIONS]

    assert len(section_names) == len(set(section_names))
    assert [field.name for field in embed.fields] == section_names
    assert all(entries for _name, entries in HELP_SECTIONS)


@pytest.mark.asyncio
async def test_help_allows_non_admin():
    cog = CoreCog(SimpleNamespace())
    interaction = SimpleNamespace(user=SimpleNamespace(id=10), response=_FakeResponse())

    await CoreCog.help.callback(cog, interaction)

    content, kwargs = interaction.response.messages[0]
    assert content is None
    assert kwargs["ephemeral"] is True
    assert kwargs["embed"].title == f"Aide {BOT_NAME}"
