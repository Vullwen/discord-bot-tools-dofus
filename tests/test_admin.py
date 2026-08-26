from types import SimpleNamespace

import pytest

import db
from cogs import admin
from cogs.admin import AdminCog


class _FakeResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


@pytest.mark.asyncio
async def test_health_reports_runtime_and_database(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr(admin, "is_bot_admin", lambda _interaction: True)
    bot = SimpleNamespace(latency=0.042, guilds=[object()], cogs={"AdminCog": object()})
    cog = AdminCog(bot)
    interaction = SimpleNamespace(response=_FakeResponse())

    await AdminCog.health.callback(cog, interaction)

    content, kwargs = interaction.response.messages[0]
    embed = kwargs["embed"]
    field_values = {field.name: field.value for field in embed.fields}
    assert content is None
    assert kwargs["ephemeral"] is True
    assert embed.title == "Health OK"
    assert field_values["Discord"] == "42 ms"
    assert field_values["Guildes"] == "1"
    assert field_values["Cogs"] == "1"
    assert "migrations" in field_values["DB"]
