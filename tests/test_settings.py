from types import SimpleNamespace

import pytest

import db
from cogs.settings import SettingsCog, _CHANNEL_LABEL, _resolve_role


def _guild(*roles):
    return SimpleNamespace(
        roles=list(roles),
        get_role=lambda role_id: next((role for role in roles if role.id == role_id), None),
    )


def _role(role_id, name):
    return SimpleNamespace(id=role_id, name=name)


def test_resolve_role_by_id():
    role = _role(123, "Raid Admin")
    assert _resolve_role(_guild(role), "123") is role


def test_resolve_role_by_copied_mention():
    role = _role(123, "Raid Admin")
    assert _resolve_role(_guild(role), "<@&123>") is role


def test_resolve_role_by_exact_name_case_insensitive():
    role = _role(123, "Raid Admin")
    assert _resolve_role(_guild(role), "raid admin") is role


def test_resolve_role_rejects_unknown_or_ambiguous_name():
    first = _role(123, "Raid Admin")
    second = _role(456, "Raid Admin")
    assert _resolve_role(_guild(first), "Missing") is None
    assert _resolve_role(_guild(first, second), "Raid Admin") is None


def test_channel_labels_include_raid_admin_channel():
    assert _CHANNEL_LABEL[db.SETTING_RAID_ADMIN_CHANNEL] == "Salon admin raids"


def test_channel_labels_include_market_forum_channel():
    assert _CHANNEL_LABEL[db.SETTING_MARKET_FORUM_CHANNEL] == "Forum marché"


def test_base_role_setting_exists():
    assert db.SETTING_BASE_ROLE == "base_member_role"


def test_bot_admin_role_setting_exists():
    assert db.SETTING_BOT_ADMIN_ROLE == "bot_admin_role"


def test_unverified_role_setting_exists():
    assert db.SETTING_UNVERIFIED_MEMBER_ROLE == "unverified_member_role"


def test_onboarding_role_settings_exist():
    assert db.SETTING_GUILD_MEMBER_ROLE == "guild_member_role"
    assert db.SETTING_VISITOR_ROLE == "visitor_role"


class _FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


@pytest.mark.asyncio
async def test_config_guild_sets_dofus_guild_name(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.settings.is_raid_organizer", lambda _interaction: True)
    cog = SettingsCog(SimpleNamespace())
    interaction = SimpleNamespace(guild=SimpleNamespace(id=2), response=_FakeResponse())

    await SettingsCog.config_guild.callback(cog, interaction, " Les Hiboux ")

    assert db.get_guild_setting(2, db.SETTING_DOFUS_GUILD_NAME) == "Les Hiboux"
    assert "Les Hiboux" in interaction.response.messages[0][0]


@pytest.mark.asyncio
async def test_config_dofus_can_update_guild_without_overwriting_server(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.settings.is_raid_organizer", lambda _interaction: True)
    db.set_guild_setting(2, db.SETTING_DOFUS_SERVER, "Tal Kasha")
    cog = SettingsCog(SimpleNamespace())
    interaction = SimpleNamespace(guild=SimpleNamespace(id=2), response=_FakeResponse())

    await SettingsCog.config_dofus.callback(cog, interaction, "Les Hiboux", None)

    assert db.get_guild_setting(2, db.SETTING_DOFUS_GUILD_NAME) == "Les Hiboux"
    assert db.get_guild_setting(2, db.SETTING_DOFUS_SERVER) == "Tal Kasha"
    assert "Tal Kasha" in interaction.response.messages[0][0]
