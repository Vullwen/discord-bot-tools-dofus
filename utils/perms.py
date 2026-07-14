"""Permissions pour la création/gestion des raids et tickets.

Un « organisateur » est soit un admin bot (ADMIN_IDS, en dur dans le .env),
soit le détenteur du rôle configuré par guilde (db.SETTING_RAID_MANAGER_ROLE).
Si aucun rôle n'est configuré, les membres ayant la permission Discord
Administrateur sont aussi organisateurs.

Les helpers sont synchrones : la persistance est synchrone (sqlite3) et, pour
les interactions en guilde, Discord fournit déjà interaction.user (un Member)
avec ses roles — pas besoin d'intent privilégié ni de fetch réseau.
"""
from __future__ import annotations

from typing import Any, Optional

import discord

import db
from config import ADMIN_IDS


def _has_administrator_permission(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(getattr(permissions, "administrator", False))


def is_bot_admin(interaction: discord.Interaction) -> bool:
    """Admin bot configuré, propriétaire guilde OU Administrateur Discord."""
    guild = interaction.guild
    return (
        interaction.user.id in ADMIN_IDS
        or (guild is not None and getattr(guild, "owner_id", None) == interaction.user.id)
        or _has_administrator_permission(interaction)
    )


def is_raid_organizer(interaction: discord.Interaction) -> bool:
    """Admin bot OU détenteur du rôle configuré pour cette guilde.

    Si aucun rôle n'est configuré, la permission Discord Administrateur donne
    aussi l'accès. Peut créer/gérer n'importe quel raid ou ticket.
    """
    if is_bot_admin(interaction):
        return True
    guild = interaction.guild
    if guild is None:
        return False
    role_id = db.get_guild_setting_int(guild.id, db.SETTING_RAID_MANAGER_ROLE)
    if not role_id:
        return False
    # interaction.user est un Member en guilde (avec .roles) ; un User hors guilde
    # n'a pas .roles -> getattr retourne None -> non organisateur.
    roles = getattr(interaction.user, "roles", None)
    if not roles:
        return False
    return any(getattr(role, "id", None) == role_id for role in roles)


def can_manage_raid(interaction: discord.Interaction, raid: Optional[Any]) -> bool:
    """Organisateur OU créateur du raid : peut gérer ce raid précis."""
    return is_raid_organizer(interaction) or (
        raid is not None and interaction.user.id == raid["created_by"]
    )


def can_manage_ticket(interaction: discord.Interaction, ticket: Optional[Any]) -> bool:
    """Organisateur OU opener du ticket : peut gérer ce ticket précis."""
    return is_raid_organizer(interaction) or (
        ticket is not None and interaction.user.id == ticket["opener_id"]
    )
