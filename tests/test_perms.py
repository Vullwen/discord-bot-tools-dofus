"""Tests des helpers de permission (utils.perms).

On construit de fausses interactions : le helper lit interaction.user.id / .roles
et interaction.guild.id, et interroge db pour le rôle configuré. L'user est un
SimpleNamespace avec .id et .roles (duck-typing, comme un vrai Member en guilde).
"""
from types import SimpleNamespace

import db
import utils.perms as perms


def _interaction(user_id, guild_id=None, role_ids=(), administrator=False):
    user = SimpleNamespace(
        id=user_id,
        roles=[SimpleNamespace(id=rid) for rid in role_ids],
        guild_permissions=SimpleNamespace(administrator=administrator),
    )
    return SimpleNamespace(
        user=user,
        guild=SimpleNamespace(id=guild_id) if guild_id is not None else None,
    )


def _user_without_roles(user_id):
    """Simule un User hors guilde (pas de .roles)."""
    return SimpleNamespace(user=SimpleNamespace(id=user_id), guild=SimpleNamespace(id=1))


def _fresh(tmp_path, monkeypatch):
    db.reset_for_tests(str(tmp_path / "t.db"))
    monkeypatch.setattr(perms, "ADMIN_IDS", set())


# ------------------------------------------------------------------ is_raid_organizer


def test_admin_always_organizer(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(perms, "ADMIN_IDS", {42})
    assert perms.is_raid_organizer(_interaction(42, guild_id=1)) is True


def test_not_organizer_outside_guild(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    assert perms.is_raid_organizer(_interaction(42, guild_id=None, role_ids=(100,))) is False


def test_no_role_configured_denies_member_without_admin_perm(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    assert perms.is_raid_organizer(_interaction(42, guild_id=1, role_ids=(100,))) is False


def test_no_role_configured_allows_member_with_admin_perm(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    assert perms.is_raid_organizer(_interaction(42, guild_id=1, administrator=True)) is True


def test_empty_role_setting_allows_member_with_admin_perm(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "")
    assert perms.is_raid_organizer(_interaction(42, guild_id=1, administrator=True)) is True


def test_member_with_configured_role_is_organizer(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "100")
    assert perms.is_raid_organizer(_interaction(42, guild_id=1, role_ids=(7, 100))) is True


def test_member_without_configured_role_denied(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "100")
    assert perms.is_raid_organizer(_interaction(42, guild_id=1, role_ids=(7, 8))) is False


def test_role_is_per_guild(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "100")
    # Rôle configuré sur la guilde 1, mais l'interaction vient de la guilde 2.
    assert perms.is_raid_organizer(_interaction(42, guild_id=2, role_ids=(100,))) is False


def test_user_without_roles_denied(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "100")
    # User sans .roles (DM) : même avec le rôle configuré, pas organisateur.
    assert perms.is_raid_organizer(_user_without_roles(42)) is False


# -------------------------------------------------------------------- can_manage_raid


def test_can_manage_raid_creator(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "100")
    raid = {"created_by": 42}
    # Ni admin ni rôle, mais créateur du raid.
    assert perms.can_manage_raid(_interaction(42, guild_id=1), raid) is True


def test_can_manage_raid_organizer(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "100")
    raid = {"created_by": 999}
    assert perms.can_manage_raid(_interaction(42, guild_id=1, role_ids=(100,)), raid) is True


def test_can_manage_raid_denied(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "100")
    raid = {"created_by": 999}
    assert perms.can_manage_raid(_interaction(42, guild_id=1, role_ids=(7,)), raid) is False


def test_can_manage_raid_none_raid_denied_for_non_admin(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    assert perms.can_manage_raid(_interaction(42, guild_id=1, role_ids=(100,)), None) is False


# ----------------------------------------------------------------- can_manage_ticket


def test_can_manage_ticket_opener(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "100")
    ticket = {"opener_id": 42}
    assert perms.can_manage_ticket(_interaction(42, guild_id=1), ticket) is True


def test_can_manage_ticket_organizer(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "100")
    ticket = {"opener_id": 999}
    assert perms.can_manage_ticket(_interaction(42, guild_id=1, role_ids=(100,)), ticket) is True


def test_can_manage_ticket_denied(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    db.set_guild_setting(1, db.SETTING_RAID_MANAGER_ROLE, "100")
    ticket = {"opener_id": 999}
    assert perms.can_manage_ticket(_interaction(42, guild_id=1, role_ids=(7,)), ticket) is False
