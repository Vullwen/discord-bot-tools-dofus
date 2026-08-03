import pytest

from config import DEFAULT_BOT_COGS, parse_bot_cogs, raid_cap, raid_low_level_cap


def test_default_caps():
    assert raid_cap("Gigalodon") == 12
    assert raid_cap("Jardins Éternels") == 16


def test_unknown_returns_none():
    assert raid_cap(None) is None
    assert raid_cap("Inconnu") is None


def test_low_level_caps():
    assert raid_low_level_cap("Gigalodon") == 2
    assert raid_low_level_cap("Jardins Éternels") == 0
    assert raid_low_level_cap(None) == 0
    assert raid_low_level_cap("Inconnu") == 0


def test_parse_bot_cogs_defaults_to_everything():
    assert parse_bot_cogs("") == DEFAULT_BOT_COGS
    assert parse_bot_cogs("all") == DEFAULT_BOT_COGS


def test_parse_bot_cogs_accepts_absence_only_alias():
    assert parse_bot_cogs("absence") == ["cogs.absence"]


def test_parse_bot_cogs_accepts_comma_separated_aliases_without_duplicates():
    assert parse_bot_cogs("raid, cogs.ticket, raid") == ["cogs.raid", "cogs.ticket"]


def test_parse_bot_cogs_rejects_unknown_values():
    with pytest.raises(ValueError):
        parse_bot_cogs("absence,unknown")
