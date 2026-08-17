from types import SimpleNamespace

import pytest

import db
from cogs.deathnote import DeathnoteCog, normalize_pseudo


class _FakeChannel:
    def __init__(self, channel_id: int):
        self.id = channel_id
        self.mention = f"<#{channel_id}>"
        self.sent = []

    async def send(self, *, content=None, **kwargs):
        self.sent.append(SimpleNamespace(content=content, kwargs=kwargs))


class _FakeBot:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, channel_id: int):
        return self.channel if self.channel.id == channel_id else None

    async def fetch_channel(self, channel_id: int):
        return self.get_channel(channel_id)


class _FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


def _interaction(*, user_id=1, guild_id=2):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        guild=SimpleNamespace(id=guild_id),
        response=_FakeResponse(),
    )


def test_normalize_pseudo_is_case_and_accent_insensitive():
    assert normalize_pseudo("  Éni   Bob  ") == "eni bob"


@pytest.mark.asyncio
async def test_blacklist_command_persists_entry(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr("cogs.deathnote.is_raid_organizer", lambda _interaction: True)
    cog = DeathnoteCog(SimpleNamespace())
    interaction = _interaction()

    await DeathnoteCog.blacklist.callback(cog, interaction, "Éni-Bob", "reroll suspect")

    row = db.get_deathnote_entry(guild_id=2, normalized_pseudo="eni-bob")
    assert row is not None
    assert row["pseudo"] == "Éni-Bob"
    assert row["reason"] == "reroll suspect"
    assert "ajouté à la deathnote" in interaction.response.messages[0][0]


@pytest.mark.asyncio
async def test_blacklisted_message_notifies_admin_channel(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    admin_channel = _FakeChannel(500)
    db.set_guild_setting(2, db.SETTING_RAID_ADMIN_CHANNEL, str(admin_channel.id))
    db.upsert_deathnote_entry(
        guild_id=2,
        pseudo="Éni-Bob",
        normalized_pseudo="eni-bob",
        reason="reroll suspect",
        created_by=1,
    )
    cog = DeathnoteCog(_FakeBot(admin_channel))
    author = SimpleNamespace(
        id=10,
        mention="<@10>",
        display_name="Random",
        name="random",
        bot=False,
    )
    channel = SimpleNamespace(mention="<#123>")
    message = SimpleNamespace(
        guild=SimpleNamespace(id=2),
        author=author,
        channel=channel,
        content="Salut, mon pseudo c'est eni-bob.",
        jump_url="https://discord.test/message",
    )

    await cog.on_message(message)

    assert len(admin_channel.sent) == 1
    content = admin_channel.sent[0].content
    assert "Pseudo blacklisté détecté" in content
    assert "Éni-Bob" in content
    assert "reroll suspect" in content
    assert "<@10>" in content
    assert "https://discord.test/message" in content


@pytest.mark.asyncio
async def test_blacklisted_member_join_notifies_admin_channel(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    admin_channel = _FakeChannel(500)
    db.set_guild_setting(2, db.SETTING_RAID_ADMIN_CHANNEL, str(admin_channel.id))
    db.upsert_deathnote_entry(
        guild_id=2,
        pseudo="Éni-Bob",
        normalized_pseudo="eni-bob",
        reason="reroll suspect",
        created_by=1,
    )
    cog = DeathnoteCog(_FakeBot(admin_channel))
    member = SimpleNamespace(
        id=10,
        mention="<@10>",
        display_name="Éni-Bob",
        name="random",
        guild=SimpleNamespace(id=2),
    )

    await cog.on_member_join(member)

    assert len(admin_channel.sent) == 1
    assert "Membre blacklisté détecté à l'arrivée" in admin_channel.sent[0].content
