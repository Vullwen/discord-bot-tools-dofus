from types import SimpleNamespace

import db
from cogs.settings import _CHANNEL_LABEL, _load_job_role_names, _resolve_role


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


def test_base_role_setting_exists():
    assert db.SETTING_BASE_ROLE == "base_member_role"


def test_bot_admin_role_setting_exists():
    assert db.SETTING_BOT_ADMIN_ROLE == "bot_admin_role"


def test_unverified_role_setting_exists():
    assert db.SETTING_UNVERIFIED_MEMBER_ROLE == "unverified_member_role"


def test_load_job_role_names_from_manifest():
    names = _load_job_role_names()
    assert len(names) == 22
    assert "Bûcheron" in names
    assert "Éleveur" in names
    assert _load_job_role_names("Métier - ")[0] == "Métier - Bûcheron"
