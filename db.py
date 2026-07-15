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
            poll_close_hour          INTEGER,
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

        CREATE TABLE IF NOT EXISTS absences (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id            INTEGER NOT NULL,
            user_id             INTEGER NOT NULL,
            user_display        TEXT NOT NULL,
            start_date          TEXT NOT NULL,
            end_date            TEXT NOT NULL,
            public_channel_id   INTEGER NOT NULL,
            public_message_id   INTEGER NOT NULL,
            admin_channel_id    INTEGER,
            admin_message_id    INTEGER,
            public_deleted_at   TEXT,
            created_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS raid_bans (
            guild_id      INTEGER NOT NULL,
            user_id       INTEGER NOT NULL,
            banned_until  TEXT NOT NULL,
            reason        TEXT NOT NULL,
            created_by    INTEGER NOT NULL,
            created_at    TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS verification_requests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id        INTEGER NOT NULL,
            discord_id      INTEGER NOT NULL,
            channel_id      INTEGER NOT NULL UNIQUE,
            character_name  TEXT NOT NULL,
            server          TEXT NOT NULL,
            code            TEXT NOT NULL,
            status          TEXT NOT NULL,
            expires_at      TEXT NOT NULL,
            ocr_text        TEXT,
            reviewed_by     INTEGER,
            verified_at     TEXT,
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dofus_characters (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id        INTEGER NOT NULL,
            discord_id      INTEGER NOT NULL,
            character_name  TEXT NOT NULL,
            server          TEXT NOT NULL,
            is_main         INTEGER NOT NULL DEFAULT 0,
            active          INTEGER NOT NULL DEFAULT 1,
            verified_at     TEXT NOT NULL,
            verified_by     INTEGER,
            UNIQUE (guild_id, server, character_name)
        );
        """
    )
    # Migrations : colonnes ajoutées a posteriori (idempotent).
    _migrate("ALTER TABLE raids ADD COLUMN fixed_hour INTEGER")
    _migrate("ALTER TABLE raids ADD COLUMN fixed_time TEXT")
    _migrate("ALTER TABLE raids ADD COLUMN reminder_message_id INTEGER")
    _migrate("ALTER TABLE raids ADD COLUMN reminder_sent_at TEXT")
    _migrate("ALTER TABLE raids ADD COLUMN poll_hours TEXT")
    _migrate("ALTER TABLE raids ADD COLUMN poll_close_hour INTEGER")
    _migrate("ALTER TABLE participants ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'")
    _migrate("ALTER TABLE participants ADD COLUMN joined_at TEXT")
    _migrate("ALTER TABLE participants ADD COLUMN level_group TEXT NOT NULL DEFAULT '200_plus'")
    # Backfill : convertit l'ancien fixed_hour (heure entière) en fixed_time 'HH:MM'.
    _conn.execute(
        "UPDATE raids SET fixed_time = printf('%02d:00', fixed_hour) "
        "WHERE fixed_hour IS NOT NULL AND fixed_time IS NULL"
    )
    # Backfill : joined_at des anciens participants (ordre FIFO arbitraire entre eux).
    _conn.execute("UPDATE participants SET joined_at = ? WHERE joined_at IS NULL", (_now_iso(),))
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
    poll_close_hour: Optional[int] = None,
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
            (name, date, poll_duration_seconds, poll_close_hour, created_by, guild_id, channel_id,
             state, raid_poll_closes_at, hour_poll_closes_at, scheduled_at,
             fixed_time, poll_hours, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            date_iso,
            poll_duration_seconds,
            poll_close_hour,
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
        "SELECT * FROM raids WHERE state IN "
        "('choosing_raid','voting_hour','breaking_hour_tie','scheduled','reminded') "
        "ORDER BY id"
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


def toggle_vote(raid_id: int, user_id: int, kind: str, choice: str) -> bool:
    """Vote multi-choix : bascule un choix pour (raid, user, kind) sans toucher aux
    autres choix déjà votés. Retourne True si le vote a été ajouté, False s'il a été
    retiré. Conçu pour le sondage d'heure (plusieurs créneaux possibles)."""
    conn = _db()
    existing = conn.execute(
        "SELECT 1 FROM votes WHERE raid_id = ? AND user_id = ? AND kind = ? AND choice = ?",
        (raid_id, user_id, kind, choice),
    ).fetchone()
    if existing:
        conn.execute(
            "DELETE FROM votes WHERE raid_id = ? AND user_id = ? AND kind = ? AND choice = ?",
            (raid_id, user_id, kind, choice),
        )
        conn.commit()
        return False
    conn.execute(
        "INSERT OR IGNORE INTO votes (raid_id, user_id, kind, choice) VALUES (?, ?, ?, ?)",
        (raid_id, user_id, kind, choice),
    )
    conn.commit()
    return True


def replace_votes(raid_id: int, user_id: int, kind: str, choices: list[str]) -> None:
    """Remplace tous les votes d'un user pour un type donné par `choices`."""
    conn = _db()
    conn.execute(
        "DELETE FROM votes WHERE raid_id = ? AND user_id = ? AND kind = ?",
        (raid_id, user_id, kind),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO votes (raid_id, user_id, kind, choice) VALUES (?, ?, ?, ?)",
        [(raid_id, user_id, kind, choice) for choice in choices],
    )
    conn.commit()


def get_user_votes(raid_id: int, user_id: int, kind: str) -> list[str]:
    """Liste les choix votés par un utilisateur pour un type donné."""
    rows = _db().execute(
        "SELECT choice FROM votes WHERE raid_id = ? AND user_id = ? AND kind = ?",
        (raid_id, user_id, kind),
    ).fetchall()
    return [row["choice"] for row in rows]


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


def set_level_choice(raid_id: int, user_id: int, level_group: str) -> None:
    cast_vote(raid_id, user_id, "level", level_group)


def get_level_choice(raid_id: int, user_id: int) -> Optional[str]:
    choices = get_user_votes(raid_id, user_id, "level")
    return choices[0] if choices else None


def count_active_level_choices(raid_id: int, level_group: str) -> int:
    row = _db().execute(
        """
        SELECT COUNT(DISTINCT level.user_id) AS n
        FROM votes AS level
        WHERE level.raid_id = ?
          AND level.kind = 'level'
          AND level.choice = ?
          AND EXISTS (
              SELECT 1
              FROM votes AS hour
              WHERE hour.raid_id = level.raid_id
                AND hour.user_id = level.user_id
                AND hour.kind = 'hour'
          )
        """,
        (raid_id, level_group),
    ).fetchone()
    return row["n"] if row else 0


# --------------------------------------------------------------------- participants


def add_participant(
    raid_id: int,
    user_id: int,
    status: str = "confirmed",
    level_group: str = "200_plus",
) -> None:
    _db().execute(
        "INSERT OR IGNORE INTO participants (raid_id, user_id, status, joined_at, level_group) "
        "VALUES (?, ?, ?, ?, ?)",
        (raid_id, user_id, status, _now_iso(), level_group),
    )
    _db().commit()


def get_participants(raid_id: int) -> list[tuple[int, str, str]]:
    """Liste (user_id, status, level_group) : confirmés d'abord (ordre d'arrivée),
    puis liste d'attente (ordre d'arrivée)."""
    rows = _db().execute(
        "SELECT user_id, status, level_group FROM participants WHERE raid_id = ? "
        "ORDER BY (status = 'confirmed') DESC, joined_at ASC",
        (raid_id,),
    ).fetchall()
    return [(row["user_id"], row["status"], row["level_group"]) for row in rows]


def get_participant_status(raid_id: int, user_id: int) -> Optional[str]:
    row = _db().execute(
        "SELECT status FROM participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    ).fetchone()
    return row["status"] if row else None


def get_participant_level_group(raid_id: int, user_id: int) -> Optional[str]:
    row = _db().execute(
        "SELECT level_group FROM participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    ).fetchone()
    return row["level_group"] if row else None


def count_participants(raid_id: int) -> int:
    row = _db().execute(
        "SELECT COUNT(*) AS n FROM participants WHERE raid_id = ?", (raid_id,)
    ).fetchone()
    return row["n"] if row else 0


def count_confirmed(raid_id: int) -> int:
    row = _db().execute(
        "SELECT COUNT(*) AS n FROM participants WHERE raid_id = ? AND status = 'confirmed'",
        (raid_id,),
    ).fetchone()
    return row["n"] if row else 0


def count_waitlist(raid_id: int) -> int:
    row = _db().execute(
        "SELECT COUNT(*) AS n FROM participants WHERE raid_id = ? AND status = 'waitlist'",
        (raid_id,),
    ).fetchone()
    return row["n"] if row else 0


def count_level_group(raid_id: int, level_group: str) -> int:
    row = _db().execute(
        "SELECT COUNT(*) AS n FROM participants WHERE raid_id = ? AND level_group = ?",
        (raid_id, level_group),
    ).fetchone()
    return row["n"] if row else 0


def waitlist_position(raid_id: int, user_id: int) -> Optional[int]:
    """Position 1-based d'un utilisateur dans la liste d'attente, ou None s'il n'y
    est pas."""
    rows = _db().execute(
        "SELECT user_id FROM participants WHERE raid_id = ? AND status = 'waitlist' "
        "ORDER BY joined_at ASC",
        (raid_id,),
    ).fetchall()
    for i, row in enumerate(rows, start=1):
        if row["user_id"] == user_id:
            return i
    return None


def is_participant(raid_id: int, user_id: int) -> bool:
    row = _db().execute(
        "SELECT 1 FROM participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    ).fetchone()
    return row is not None


def remove_participant(raid_id: int, user_id: int) -> Optional[int]:
    """Retire un participant. S'il était confirmé et qu'une file d'attente existe,
    promeut le plus ancien en attente et retourne son user_id ; sinon None."""
    conn = _db()
    row = conn.execute(
        "SELECT status FROM participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    ).fetchone()
    if not row:
        conn.commit()
        return None
    was_confirmed = row["status"] == "confirmed"
    conn.execute(
        "DELETE FROM participants WHERE raid_id = ? AND user_id = ?",
        (raid_id, user_id),
    )
    promoted: Optional[int] = None
    if was_confirmed:
        nxt = conn.execute(
            "SELECT user_id FROM participants WHERE raid_id = ? AND status = 'waitlist' "
            "ORDER BY joined_at ASC LIMIT 1",
            (raid_id,),
        ).fetchone()
        if nxt:
            conn.execute(
                "UPDATE participants SET status = 'confirmed' "
                "WHERE raid_id = ? AND user_id = ?",
                (raid_id, nxt["user_id"]),
            )
            promoted = nxt["user_id"]
    conn.commit()
    return promoted


# --------------------------------------------------------------------------- bans


def set_raid_ban(
    *,
    guild_id: int,
    user_id: int,
    banned_until: datetime,
    reason: str,
    created_by: int,
) -> None:
    _db().execute(
        """
        INSERT OR REPLACE INTO raid_bans
            (guild_id, user_id, banned_until, reason, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (guild_id, user_id, banned_until.isoformat(), reason, created_by, _now_iso()),
    )
    _db().commit()


def get_active_raid_ban(
    *,
    guild_id: int,
    user_id: int,
    now: Optional[datetime] = None,
) -> Optional[sqlite3.Row]:
    now_iso = (now.isoformat() if now is not None else _now_iso())
    return _db().execute(
        """
        SELECT * FROM raid_bans
        WHERE guild_id = ?
          AND user_id = ?
          AND banned_until > ?
        """,
        (guild_id, user_id, now_iso),
    ).fetchone()


def list_active_raid_bans(
    *,
    guild_id: int,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> list[sqlite3.Row]:
    now_iso = (now.isoformat() if now is not None else _now_iso())
    rows = _db().execute(
        """
        SELECT * FROM raid_bans
        WHERE guild_id = ?
          AND banned_until > ?
        ORDER BY banned_until ASC, user_id ASC
        LIMIT ?
        """,
        (guild_id, now_iso, limit),
    ).fetchall()
    return list(rows)


def clear_raid_ban(*, guild_id: int, user_id: int) -> None:
    _db().execute(
        "DELETE FROM raid_bans WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    _db().commit()


# --------------------------------------------------------------- vérifications


def create_verification_request(
    *,
    guild_id: int,
    discord_id: int,
    channel_id: int,
    character_name: str,
    server: str,
    code: str,
    expires_at: datetime,
) -> int:
    cur = _db().execute(
        """
        INSERT INTO verification_requests
            (guild_id, discord_id, channel_id, character_name, server, code,
             status, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            guild_id,
            discord_id,
            channel_id,
            character_name,
            server,
            code,
            expires_at.isoformat(),
            _now_iso(),
        ),
    )
    _db().commit()
    return cur.lastrowid


def get_verification_request(request_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM verification_requests WHERE id = ?", (request_id,)
    ).fetchone()


def get_verification_by_channel(channel_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM verification_requests WHERE channel_id = ?", (channel_id,)
    ).fetchone()


def get_pending_verification_for_user(
    *,
    guild_id: int,
    discord_id: int,
    now: Optional[datetime] = None,
) -> Optional[sqlite3.Row]:
    now_iso = (now.isoformat() if now is not None else _now_iso())
    return _db().execute(
        """
        SELECT * FROM verification_requests
        WHERE guild_id = ?
          AND discord_id = ?
          AND status IN ('pending', 'needs_review')
          AND expires_at > ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (guild_id, discord_id, now_iso),
    ).fetchone()


def update_verification_request(request_id: int, **fields: Any) -> None:
    if not fields:
        return
    serialized = {}
    for key, value in fields.items():
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value
    assignments = ", ".join(f"{col} = ?" for col in serialized)
    _db().execute(
        f"UPDATE verification_requests SET {assignments} WHERE id = ?",
        (*serialized.values(), request_id),
    )
    _db().commit()


def save_verified_character(
    *,
    guild_id: int,
    discord_id: int,
    character_name: str,
    server: str,
    verified_by: Optional[int],
    is_main: bool = False,
) -> int:
    conn = _db()
    if is_main:
        conn.execute(
            "UPDATE dofus_characters SET is_main = 0 WHERE guild_id = ? AND discord_id = ?",
            (guild_id, discord_id),
        )
    cur = conn.execute(
        """
        INSERT INTO dofus_characters
            (guild_id, discord_id, character_name, server, is_main, active, verified_at, verified_by)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(guild_id, server, character_name) DO UPDATE SET
            discord_id = excluded.discord_id,
            is_main = excluded.is_main,
            active = 1,
            verified_at = excluded.verified_at,
            verified_by = excluded.verified_by
        """,
        (
            guild_id,
            discord_id,
            character_name,
            server,
            1 if is_main else 0,
            _now_iso(),
            verified_by,
        ),
    )
    conn.commit()
    return cur.lastrowid


def list_user_characters(*, guild_id: int, discord_id: int) -> list[sqlite3.Row]:
    rows = _db().execute(
        """
        SELECT * FROM dofus_characters
        WHERE guild_id = ? AND discord_id = ? AND active = 1
        ORDER BY is_main DESC, character_name COLLATE NOCASE ASC
        """,
        (guild_id, discord_id),
    ).fetchall()
    return list(rows)


def find_character(*, guild_id: int, character_name: str) -> Optional[sqlite3.Row]:
    return _db().execute(
        """
        SELECT * FROM dofus_characters
        WHERE guild_id = ?
          AND active = 1
          AND lower(character_name) = lower(?)
        LIMIT 1
        """,
        (guild_id, character_name),
    ).fetchone()


def delete_user_characters(*, guild_id: int, discord_id: int) -> int:
    cur = _db().execute(
        "DELETE FROM dofus_characters WHERE guild_id = ? AND discord_id = ?",
        (guild_id, discord_id),
    )
    _db().commit()
    return cur.rowcount


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


# ------------------------------------------------------------------------- absences


def create_absence(
    *,
    guild_id: int,
    user_id: int,
    user_display: str,
    start_date: str,
    end_date: str,
    public_channel_id: int,
    public_message_id: int,
    admin_channel_id: Optional[int] = None,
    admin_message_id: Optional[int] = None,
) -> int:
    cur = _db().execute(
        """
        INSERT INTO absences
            (guild_id, user_id, user_display, start_date, end_date,
             public_channel_id, public_message_id, admin_channel_id, admin_message_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            guild_id,
            user_id,
            user_display,
            start_date,
            end_date,
            public_channel_id,
            public_message_id,
            admin_channel_id,
            admin_message_id,
            _now_iso(),
        ),
    )
    _db().commit()
    return cur.lastrowid


def get_absence(absence_id: int) -> Optional[sqlite3.Row]:
    return _db().execute("SELECT * FROM absences WHERE id = ?", (absence_id,)).fetchone()


def list_absences_for_cleanup() -> list[sqlite3.Row]:
    rows = _db().execute(
        """
        SELECT * FROM absences
        WHERE public_deleted_at IS NULL
          AND public_message_id IS NOT NULL
        ORDER BY end_date, id
        """
    ).fetchall()
    return list(rows)


def mark_absence_public_deleted(absence_id: int) -> None:
    _db().execute(
        "UPDATE absences SET public_deleted_at = ? WHERE id = ?",
        (_now_iso(), absence_id),
    )
    _db().commit()


def search_absences(
    *,
    guild_id: int,
    user_id: Optional[int] = None,
    today_iso: Optional[str] = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    today_iso = today_iso or _now_iso()[:10]
    where = [
        "guild_id = ?",
        "public_deleted_at IS NULL",
        "end_date >= ?",
    ]
    params: list[Any] = [guild_id, today_iso]
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    rows = _db().execute(
        f"""
        SELECT * FROM absences
        WHERE {" AND ".join(where)}
        ORDER BY start_date, end_date, id
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return list(rows)


# ---------------------------------------------------------------------- settings


SETTING_RAIDS_CHANNEL = "raids_channel"
# Salon admin où sont envoyées les actions de gestion des raids.
SETTING_RAID_ADMIN_CHANNEL = "raid_admin_channel"
# Salon où est posté le bouton de déclaration d'absence.
SETTING_ABSENCE_PANEL_CHANNEL = "absence_panel_channel"
# Salon public où sont publiées les absences.
SETTING_ABSENCE_CHANNEL = "absence_channel"
# Salon admin où sont envoyés les motifs d'absence.
SETTING_ABSENCE_ADMIN_CHANNEL = "absence_admin_channel"
# Rôle Discord autorisé à créer/gérer les raids (et tickets). Vide = admins seulement.
SETTING_RAID_MANAGER_ROLE = "raid_manager_role"
# Rôle Discord mentionné à l'annonce d'un nouveau raid (1er message). Vide = aucune mention.
SETTING_RAID_NOTIFY_ROLE = "raid_notify_role"
# Rôle de base remis après /absence kick. Vide = aucun changement de rôles.
SETTING_BASE_ROLE = "base_member_role"
# Rôle remis après vérification Dofus réussie. Vide = aucun rôle automatique.
SETTING_VERIFIED_MEMBER_ROLE = "verified_member_role"
# Rôle retiré après vérification Dofus réussie. Vide = aucun retrait automatique.
SETTING_UNVERIFIED_MEMBER_ROLE = "unverified_member_role"
# Nom de guilde Dofus attendu dans le /whoami OCR.
SETTING_DOFUS_GUILD_NAME = "dofus_guild_name"
# Serveur Dofus attendu par défaut pour /link.
SETTING_DOFUS_SERVER = "dofus_server"


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
