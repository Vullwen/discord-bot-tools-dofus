"""Couche de persistance SQLite synchrone (idiome monke-jukebox/db.py).

Connexion globale, row_factory=Row, CREATE TABLE IF NOT EXISTS.
Les datetimes sont stockées en ISO aware (Europe/Paris), les dates en ISO 'YYYY-MM-DD'.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any, Iterable, Optional

from config import DB_PATH

_conn: Optional[sqlite3.Connection] = None


def init(db_path: str = DB_PATH) -> None:
    global _conn
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    _conn = sqlite3.connect(db_path)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.execute("PRAGMA foreign_keys=ON;")
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS raids (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            name                     TEXT,
            date                     TEXT NOT NULL,
            poll_duration_seconds    INTEGER NOT NULL,
            created_by               INTEGER NOT NULL,
            guild_id                 INTEGER NOT NULL,
            channel_id               INTEGER NOT NULL,
            state                    TEXT NOT NULL,
            raid_poll_message_id     INTEGER,
            hour_poll_message_id     INTEGER,
            scheduled_message_id     INTEGER,
            scheduled_at             TEXT,
            raid_poll_closes_at      TEXT,
            hour_poll_closes_at      TEXT,
            note                     TEXT,
            fixed_hour               INTEGER,
            fixed_time               TEXT,
            reminder_message_id      INTEGER,
            reminder_sent_at         TEXT,
            created_at               TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS votes (
            raid_id   INTEGER NOT NULL,
            user_id   INTEGER NOT NULL,
            kind      TEXT NOT NULL,
            choice    TEXT NOT NULL,
            PRIMARY KEY (raid_id, user_id, kind, choice)
        );

        CREATE TABLE IF NOT EXISTS participants (
            raid_id  INTEGER NOT NULL,
            user_id  INTEGER NOT NULL,
            PRIMARY KEY (raid_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id  INTEGER NOT NULL UNIQUE,
            guild_id    INTEGER NOT NULL,
            opener_id   INTEGER NOT NULL,
            created_at  TEXT NOT NULL,
            closed      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id  INTEGER NOT NULL,
            key       TEXT NOT NULL,
            value     TEXT,
            PRIMARY KEY (guild_id, key)
        );
        """
    )
    # Migrations : colonnes ajoutées a posteriori (idempotent).
    _migrate("ALTER TABLE raids ADD COLUMN fixed_hour INTEGER")
    _migrate("ALTER TABLE raids ADD COLUMN fixed_time TEXT")
    _migrate("ALTER TABLE raids ADD COLUMN reminder_message_id INTEGER")
    _migrate("ALTER TABLE raids ADD COLUMN reminder_sent_at TEXT")
    _migrate("ALTER TABLE raids ADD COLUMN poll_hours TEXT")
    # Backfill : convertit l'ancien fixed_hour (heure entière) en fixed_time 'HH:MM'.
    _conn.execute(
        "UPDATE raids SET fixed_time = printf('%02d:00', fixed_hour) "
        "WHERE fixed_hour IS NOT NULL AND fixed_time IS NULL"
    )
    _conn.commit()


def _migrate(ddl: str) -> None:
    """Applique un DDL de migration ; ignore l'erreur si la colonne existe déjà."""
    try:
        _db().execute(ddl)
    except sqlite3.OperationalError:
        pass


def _db() -> sqlite3.Connection:
    if _conn is None:
        init()
    return _conn


def _now_iso() -> str:
    from config import now_paris
    return now_paris().isoformat()


def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


# --------------------------------------------------------------------------- raids


def create_raid(
    *,
    name: Optional[str],
    date_iso: str,
    poll_duration_seconds: int = 0,
    created_by: int,
    guild_id: int,
    channel_id: int,
    state: str,
    raid_poll_closes_at: Optional[datetime] = None,
    hour_poll_closes_at: Optional[datetime] = None,
    scheduled_at: Optional[datetime] = None,
    note: Optional[str] = None,
    fixed_time: Optional[str] = None,
    poll_hours: Optional[list[int]] = None,
) -> int:
    cur = _db().execute(
        """
        INSERT INTO raids
            (name, date, poll_duration_seconds, created_by, guild_id, channel_id,
             state, raid_poll_closes_at, hour_poll_closes_at, scheduled_at,
             fixed_time, poll_hours, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            date_iso,
            poll_duration_seconds,
            created_by,
            guild_id,
            channel_id,
            state,
            raid_poll_closes_at.isoformat() if raid_poll_closes_at else None,
            hour_poll_closes_at.isoformat() if hour_poll_closes_at else None,
            scheduled_at.isoformat() if scheduled_at else None,
            fixed_time,
            ",".join(str(h) for h in poll_hours) if poll_hours else None,
            note,
            _now_iso(),
        ),
    )
    _db().commit()
    return cur.lastrowid


def get_raid(raid_id: int) -> Optional[sqlite3.Row]:
    return _db().execute("SELECT * FROM raids WHERE id = ?", (raid_id,)).fetchone()


def list_active_raids() -> list[sqlite3.Row]:
    rows = _db().execute(
        "SELECT * FROM raids WHERE state IN ('choosing_raid','voting_hour','scheduled','reminded') ORDER BY id"
    ).fetchall()
    return list(rows)


def list_all_raids(limit: int = 50) -> list[sqlite3.Row]:
    rows = _db().execute(
        "SELECT * FROM raids ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return list(rows)


def list_raids_with_reminder_message() -> list[sqlite3.Row]:
    """Raids dont le message de rappel salon est encore à supprimer (tous états confondus)."""
    rows = _db().execute(
        "SELECT * FROM raids WHERE reminder_message_id IS NOT NULL ORDER BY id"
    ).fetchall()
    return list(rows)


def list_raids_with_messages() -> list[sqlite3.Row]:
    """Raids dont au moins un message (sondages / planifié) reste à supprimer, et dont
    l'heure prévue est connue. Les raids annulés sont exclus (leur message « annulé »
    reste visible). Sert au cleanup automatique 2h post-raid."""
    rows = _db().execute(
        """
        SELECT * FROM raids
        WHERE state != 'cancelled'
          AND scheduled_at IS NOT NULL
          AND (raid_poll_message_id IS NOT NULL
               OR hour_poll_message_id IS NOT NULL
               OR scheduled_message_id IS NOT NULL)
        ORDER BY id
        """
    ).fetchall()
    return list(rows)


def update_raid(raid_id: int, **fields: Any) -> None:
    if not fields:
        return
    # Sérialisation des datetimes en ISO.
    serialized = {}
    for key, value in fields.items():
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value
    assignments = ", ".join(f"{col} = ?" for col in serialized)
    _db().execute(
        f"UPDATE raids SET {assignments} WHERE id = ?",
        (*serialized.values(), raid_id),
    )
    _db().commit()


def set_raid_state(raid_id: int, state: str) -> None:
    update_raid(raid_id, state=state)


# --------------------------------------------------------------------------- votes


def cast_vote(raid_id: int, user_id: int, kind: str, choice: str) -> None:
    """Vote changeable : un seul choix par (raid, user, kind)."""
    conn = _db()
    conn.execute(
        "DELETE FROM votes WHERE raid_id = ? AND user_id = ? AND kind = ?",
        (raid_id, user_id, kind),
    )
    conn.execute(
        "INSERT OR IGNORE INTO votes (raid_id, user_id, kind, choice) VALUES (?, ?, ?, ?)",
        (raid_id, user_id, kind, choice),
    )
    conn.commit()


def get_vote_counts(raid_id: int, kind: str) -> dict[str, int]:
    rows = _db().execute(
        "SELECT choice, COUNT(*) AS n FROM votes WHERE raid_id = ? AND kind = ? GROUP BY choice",
        (raid_id, kind),
    ).fetchall()
    return {row["choice"]: row["n"] for row in rows}


def get_voters(raid_id: int, kind: str, choice: str) -> list[int]:
    rows = _db().execute(
        "SELECT user_id FROM votes WHERE raid_id = ? AND kind = ? AND choice = ?",
        (raid_id, kind, choice),
    ).fetchall()
    return [row["user_id"] for row in rows]


# --------------------------------------------------------------------- participants


def add_participant(raid_id: int, user_id: int) -> None:
    _db().execute(
        "INSERT OR IGNORE INTO participants (raid_id, user_id) VALUES (?, ?)",
        (raid_id, user_id),
    )
    _db().commit()


def get_participants(raid_id: int) -> list[int]:
    rows = _db().execute(
        "SELECT user_id FROM participants WHERE raid_id = ?", (raid_id,)
    ).fetchall()
    return [row["user_id"] for row in rows]


def count_participants(raid_id: int) -> int:
    row = _db().execute(
        "SELECT COUNT(*) AS n FROM participants WHERE raid_id = ?", (raid_id,)
    ).fetchone()
    return row["n"] if row else 0


def is_participant(raid_id: int, user_id: int) -> bool:
    row = _db().execute(
        "SELECT 1 FROM participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    ).fetchone()
    return row is not None


def remove_participant(raid_id: int, user_id: int) -> None:
    _db().execute(
        "DELETE FROM participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    )
    _db().commit()


# --------------------------------------------------------------------------- tickets


def create_ticket(*, channel_id: int, guild_id: int, opener_id: int) -> int:
    cur = _db().execute(
        "INSERT INTO tickets (channel_id, guild_id, opener_id, created_at) VALUES (?, ?, ?, ?)",
        (channel_id, guild_id, opener_id, _now_iso()),
    )
    _db().commit()
    return cur.lastrowid


def get_ticket_by_channel(channel_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
    ).fetchone()


def close_ticket(channel_id: int) -> None:
    _db().execute(
        "UPDATE tickets SET closed = 1 WHERE channel_id = ?", (channel_id,)
    )
    _db().commit()


# ---------------------------------------------------------------------- settings


SETTING_RAIDS_CHANNEL = "raids_channel"
SETTING_TICKET_CATEGORY = "ticket_category"
# Rôle Discord autorisé à créer/gérer les raids (et tickets). Vide = admins seulement.
SETTING_RAID_MANAGER_ROLE = "raid_manager_role"
# Rôle Discord mentionné à l'annonce d'un nouveau raid (1er message). Vide = aucune mention.
SETTING_RAID_NOTIFY_ROLE = "raid_notify_role"


def set_guild_setting(guild_id: int, key: str, value: str) -> None:
    _db().execute(
        "INSERT OR REPLACE INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?)",
        (guild_id, key, value),
    )
    _db().commit()


def get_guild_setting(guild_id: int, key: str) -> Optional[str]:
    row = _db().execute(
        "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
        (guild_id, key),
    ).fetchone()
    return row["value"] if row else None


def get_guild_setting_int(guild_id: int, key: str) -> Optional[int]:
    value = get_guild_setting(guild_id, key)
    if value and value.lstrip("-").isdigit():
        return int(value)
    return None


# ----------------------------------------------------------------- helpers tests


def reset_for_tests(db_path: str) -> None:
    """Réinitialise la connexion sur une BDD de test (chemin explicite)."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
    init(db_path)
