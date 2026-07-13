from cogs.core import _help_embed


def test_help_embed_lists_main_commands():
    embed = _help_embed()
    text = "\n".join(field.value for field in embed.fields)

    for command in (
        "/help",
        "/ping",
        "/raid",
        "/list_raids",
        "/absence_panel",
        "/search_abs",
        "/kick_abs",
        "/setchannel",
        "/showconfig",
    ):
        assert command in text
