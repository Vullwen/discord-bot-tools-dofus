"""Couche de persistance SQLite synchrone (idiome monke-jukebox/db.py).

Connexion globale, row_factory=Row, CREATE TABLE IF NOT EXISTS.
Les datetimes sont stockées en ISO aware (Europe/Paris), les dates en ISO 'YYYY-MM-DD'.
"""
from __future__ import annotations

import os
import logging
import sqlite3
from datetime import datetime
from typing import Any, Collection, Optional

from config import DB_PATH

_conn: Optional[sqlite3.Connection] = None
logger = logging.getLogger(__name__)

MIGRATIONS = (
    ("001_raids_fixed_hour", "ALTER TABLE raids ADD COLUMN fixed_hour INTEGER"),
    ("002_raids_fixed_time", "ALTER TABLE raids ADD COLUMN fixed_time TEXT"),
    ("003_raids_reminder_message_id", "ALTER TABLE raids ADD COLUMN reminder_message_id INTEGER"),
    ("004_raids_reminder_sent_at", "ALTER TABLE raids ADD COLUMN reminder_sent_at TEXT"),
    ("005_raids_poll_hours", "ALTER TABLE raids ADD COLUMN poll_hours TEXT"),
    ("006_raids_poll_close_hour", "ALTER TABLE raids ADD COLUMN poll_close_hour INTEGER"),
    (
        "007_raids_capacity_removed",
        "ALTER TABLE raids ADD COLUMN capacity_removed INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "008_raids_level_200_only",
        "ALTER TABLE raids ADD COLUMN level_200_only INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "009_participants_status",
        "ALTER TABLE participants ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'",
    ),
    ("010_participants_joined_at", "ALTER TABLE participants ADD COLUMN joined_at TEXT"),
    (
        "011_participants_level_group",
        "ALTER TABLE participants ADD COLUMN level_group TEXT NOT NULL DEFAULT '200_plus'",
    ),
    (
        "012_market_posts_control_message_id",
        "ALTER TABLE market_posts ADD COLUMN control_message_id INTEGER",
    ),
    (
        "013_onboarding_application_pseudo",
        "ALTER TABLE onboarding_tickets ADD COLUMN application_pseudo TEXT",
    ),
    (
        "014_onboarding_application_classes",
        "ALTER TABLE onboarding_tickets ADD COLUMN application_classes TEXT",
    ),
    (
        "015_onboarding_application_goals",
        "ALTER TABLE onboarding_tickets ADD COLUMN application_goals TEXT",
    ),
)


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
            capacity_removed         INTEGER NOT NULL DEFAULT 0,
            level_200_only           INTEGER NOT NULL DEFAULT 0,
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

        CREATE TABLE IF NOT EXISTS onboarding_tickets (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id   INTEGER NOT NULL UNIQUE,
            guild_id     INTEGER NOT NULL,
            user_id      INTEGER NOT NULL,
            choice       TEXT,
            application_pseudo   TEXT,
            application_classes  TEXT,
            application_goals    TEXT,
            status       TEXT NOT NULL,
            close_after  TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
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

        CREATE TABLE IF NOT EXISTS raid_warns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            reason      TEXT NOT NULL,
            created_by  INTEGER NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deathnote_blacklist (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id           INTEGER NOT NULL,
            pseudo             TEXT NOT NULL,
            normalized_pseudo  TEXT NOT NULL,
            reason             TEXT NOT NULL,
            created_by         INTEGER NOT NULL,
            created_at         TEXT NOT NULL,
            UNIQUE(guild_id, normalized_pseudo)
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

        CREATE TABLE IF NOT EXISTS role_menus (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id        INTEGER NOT NULL,
            channel_id      INTEGER NOT NULL,
            message_id      INTEGER UNIQUE,
            title           TEXT NOT NULL,
            description     TEXT,
            color           INTEGER,
            footer          TEXT,
            image_url       TEXT,
            thumbnail_url   TEXT,
            created_by      INTEGER NOT NULL,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS role_menu_components (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_id         INTEGER NOT NULL,
            component_type  TEXT NOT NULL,
            label           TEXT,
            placeholder     TEXT,
            min_values      INTEGER NOT NULL DEFAULT 0,
            max_values      INTEGER NOT NULL DEFAULT 1,
            exclusive       INTEGER NOT NULL DEFAULT 0,
            style           TEXT,
            emoji           TEXT,
            role_id         INTEGER,
            position        INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(menu_id) REFERENCES role_menus(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS role_menu_options (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            component_id    INTEGER NOT NULL,
            role_id         INTEGER NOT NULL,
            label           TEXT NOT NULL,
            description     TEXT,
            emoji           TEXT,
            position        INTEGER NOT NULL DEFAULT 0,
            UNIQUE(component_id, role_id),
            FOREIGN KEY(component_id) REFERENCES role_menu_components(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS market_posts (
            thread_id           INTEGER PRIMARY KEY,
            guild_id            INTEGER NOT NULL,
            owner_id            INTEGER NOT NULL,
            last_activity_at    TEXT NOT NULL,
            control_message_id  INTEGER,
            closed_at           TEXT,
            close_status        TEXT
        );

        CREATE TABLE IF NOT EXISTS metamob_links (
            guild_id        INTEGER NOT NULL,
            user_id         INTEGER NOT NULL,
            username        TEXT,
            quest_slug      TEXT NOT NULL,
            api_key         TEXT NOT NULL,
            character_name  TEXT,
            server_name     TEXT,
            quest_type_slug TEXT,
            linked_at       TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            PRIMARY KEY (guild_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS metamob_trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id            INTEGER NOT NULL,
            thread_id           INTEGER NOT NULL UNIQUE,
            forum_channel_id    INTEGER NOT NULL,
            starter_id          INTEGER NOT NULL,
            target_id           INTEGER NOT NULL,
            status              TEXT NOT NULL,
            control_message_id  INTEGER,
            confirmed_by        INTEGER,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            closed_at           TEXT
        );

        CREATE TABLE IF NOT EXISTS metamob_trade_items (
            trade_id      INTEGER NOT NULL,
            monster_id    INTEGER NOT NULL,
            monster_name  TEXT NOT NULL,
            giver_id      INTEGER NOT NULL,
            receiver_id   INTEGER NOT NULL,
            quantity      INTEGER NOT NULL,
            PRIMARY KEY (trade_id, monster_id, giver_id),
            FOREIGN KEY(trade_id) REFERENCES metamob_trades(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at  TEXT NOT NULL
        );

        """
    )
    _run_migrations()
    _create_indexes()
    _conn.commit()


def _create_indexes() -> None:
    """Crée les index après les migrations, car certains ciblent des colonnes migrées."""
    _db().executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_raids_state_id
            ON raids(state, id);
        CREATE INDEX IF NOT EXISTS idx_raids_reminder_message
            ON raids(reminder_message_id);
        CREATE INDEX IF NOT EXISTS idx_raids_cleanup_messages
            ON raids(state, scheduled_at);

        CREATE INDEX IF NOT EXISTS idx_votes_raid_kind_choice
            ON votes(raid_id, kind, choice);
        CREATE INDEX IF NOT EXISTS idx_votes_raid_user_kind
            ON votes(raid_id, user_id, kind);

        CREATE INDEX IF NOT EXISTS idx_participants_raid_status_joined
            ON participants(raid_id, status, joined_at);
        CREATE INDEX IF NOT EXISTS idx_participants_raid_level
            ON participants(raid_id, level_group);

        CREATE INDEX IF NOT EXISTS idx_raid_bans_guild_until
            ON raid_bans(guild_id, banned_until, user_id);
        CREATE INDEX IF NOT EXISTS idx_raid_warns_user_created
            ON raid_warns(guild_id, user_id, created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_raid_warns_guild_created
            ON raid_warns(guild_id, created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_deathnote_guild_pseudo
            ON deathnote_blacklist(guild_id, normalized_pseudo);
        CREATE INDEX IF NOT EXISTS idx_verification_pending_user
            ON verification_requests(guild_id, discord_id, status, expires_at);
        CREATE INDEX IF NOT EXISTS idx_dofus_characters_user_active
            ON dofus_characters(guild_id, discord_id, active, is_main, character_name);
        CREATE INDEX IF NOT EXISTS idx_dofus_characters_lookup
            ON dofus_characters(guild_id, active, character_name);

        CREATE INDEX IF NOT EXISTS idx_role_menus_guild_id
            ON role_menus(guild_id, id);
        CREATE INDEX IF NOT EXISTS idx_role_menu_components_menu_position
            ON role_menu_components(menu_id, position, id);
        CREATE INDEX IF NOT EXISTS idx_role_menu_options_component_position
            ON role_menu_options(component_id, position, id);

        CREATE INDEX IF NOT EXISTS idx_absences_cleanup
            ON absences(public_deleted_at, end_date, id);
        CREATE INDEX IF NOT EXISTS idx_absences_search
            ON absences(guild_id, public_deleted_at, end_date, start_date, id);
        CREATE INDEX IF NOT EXISTS idx_market_posts_inactive
            ON market_posts(closed_at, last_activity_at);
        CREATE INDEX IF NOT EXISTS idx_metamob_links_guild_user
            ON metamob_links(guild_id, user_id);
        CREATE INDEX IF NOT EXISTS idx_metamob_trades_thread
            ON metamob_trades(thread_id);
        CREATE INDEX IF NOT EXISTS idx_metamob_trades_status
            ON metamob_trades(guild_id, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_metamob_trade_items_trade
            ON metamob_trade_items(trade_id, giver_id, monster_name);
        CREATE INDEX IF NOT EXISTS idx_onboarding_open_user
            ON onboarding_tickets(guild_id, user_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_onboarding_close_after
            ON onboarding_tickets(status, close_after);
        """
    )


def _run_migrations() -> None:
    conn = _db()
    applied = {
        row["version"]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, ddl in MIGRATIONS:
        if version in applied:
            continue
        _apply_add_column_migration(conn, ddl)
        conn.execute(
            "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
            (version, ddl, _now_iso()),
        )
        logger.info("Applied database migration %s", version)

    # Backfill : convertit l'ancien fixed_hour (heure entière) en fixed_time 'HH:MM'.
    conn.execute(
        "UPDATE raids SET fixed_time = printf('%02d:00', fixed_hour) "
        "WHERE fixed_hour IS NOT NULL AND fixed_time IS NULL"
    )
    # Backfill : joined_at des anciens participants (ordre FIFO arbitraire entre eux).
    conn.execute("UPDATE participants SET joined_at = ? WHERE joined_at IS NULL", (_now_iso(),))


def _apply_add_column_migration(conn: sqlite3.Connection, ddl: str) -> None:
    """Applique un ADD COLUMN en tolérant les bases déjà mises à jour."""
    parts = ddl.split()
    if len(parts) < 6 or parts[:4] != ["ALTER", "TABLE", parts[2], "ADD"]:
        conn.execute(ddl)
        return
    table = parts[2]
    column = parts[5]
    existing_columns = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in existing_columns:
        return
    conn.execute(ddl)


def list_schema_migrations() -> list[sqlite3.Row]:
    rows = _db().execute(
        "SELECT * FROM schema_migrations ORDER BY version"
    ).fetchall()
    return list(rows)


def health_check() -> dict[str, Any]:
    conn = _db()
    quick_check = conn.execute("PRAGMA quick_check").fetchone()[0]
    migration_count = conn.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()["n"]
    active_raid_count = conn.execute(
        "SELECT COUNT(*) AS n FROM raids WHERE state IN "
        "('choosing_raid','voting_hour','breaking_hour_tie','scheduled','reminded')"
    ).fetchone()["n"]
    return {
        "db_path": DB_PATH,
        "quick_check": quick_check,
        "migration_count": migration_count,
        "expected_migration_count": len(MIGRATIONS),
        "active_raid_count": active_raid_count,
    }


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


def _promote_waitlist(
    conn: sqlite3.Connection,
    raid_id: int,
    eligible_waitlist_user_ids: Optional[Collection[int]] = None,
) -> Optional[int]:
    eligible = set(eligible_waitlist_user_ids) if eligible_waitlist_user_ids is not None else None
    rows = conn.execute(
        "SELECT user_id FROM participants WHERE raid_id = ? AND status = 'waitlist' "
        "ORDER BY joined_at ASC",
        (raid_id,),
    ).fetchall()
    for row in rows:
        user_id = row["user_id"]
        if eligible is not None and user_id not in eligible:
            continue
        conn.execute(
            "UPDATE participants SET status = 'confirmed' "
            "WHERE raid_id = ? AND user_id = ?",
            (raid_id, user_id),
        )
        return user_id
    return None


def promote_waitlist(
    raid_id: int,
    eligible_waitlist_user_ids: Optional[Collection[int]] = None,
) -> Optional[int]:
    promoted = _promote_waitlist(_db(), raid_id, eligible_waitlist_user_ids)
    _db().commit()
    return promoted


def remove_participant(
    raid_id: int,
    user_id: int,
    *,
    eligible_waitlist_user_ids: Optional[Collection[int]] = None,
) -> Optional[int]:
    """Retire un participant. S'il était confirmé et qu'une file d'attente existe,
    promeut le plus ancien en attente éligible et retourne son user_id ; sinon None."""
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
        promoted = _promote_waitlist(conn, raid_id, eligible_waitlist_user_ids)
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


# -------------------------------------------------------------------------- warns


def add_raid_warn(
    *,
    guild_id: int,
    user_id: int,
    reason: str,
    created_by: int,
) -> int:
    cur = _db().execute(
        """
        INSERT INTO raid_warns
            (guild_id, user_id, reason, created_by, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (guild_id, user_id, reason, created_by, _now_iso()),
    )
    _db().commit()
    return cur.lastrowid


def count_raid_warns(*, guild_id: int, user_id: int) -> int:
    row = _db().execute(
        "SELECT COUNT(*) AS n FROM raid_warns WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ).fetchone()
    return row["n"] if row else 0


def list_raid_warns(
    *,
    guild_id: int,
    user_id: int,
    limit: int = 10,
) -> list[sqlite3.Row]:
    rows = _db().execute(
        """
        SELECT * FROM raid_warns
        WHERE guild_id = ?
          AND user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (guild_id, user_id, limit),
    ).fetchall()
    return list(rows)


def list_raid_warn_counts(*, guild_id: int, limit: int = 50) -> list[sqlite3.Row]:
    rows = _db().execute(
        """
        SELECT user_id, COUNT(*) AS warn_count, MAX(created_at) AS last_warn_at
        FROM raid_warns
        WHERE guild_id = ?
        GROUP BY user_id
        ORDER BY warn_count DESC, last_warn_at DESC, user_id ASC
        LIMIT ?
        """,
        (guild_id, limit),
    ).fetchall()
    return list(rows)


# --------------------------------------------------------------------- deathnote


def upsert_deathnote_entry(
    *,
    guild_id: int,
    pseudo: str,
    normalized_pseudo: str,
    reason: str,
    created_by: int,
) -> int:
    cur = _db().execute(
        """
        INSERT INTO deathnote_blacklist
            (guild_id, pseudo, normalized_pseudo, reason, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id, normalized_pseudo) DO UPDATE SET
            pseudo = excluded.pseudo,
            reason = excluded.reason,
            created_by = excluded.created_by,
            created_at = excluded.created_at
        """,
        (guild_id, pseudo, normalized_pseudo, reason, created_by, _now_iso()),
    )
    _db().commit()
    return cur.lastrowid


def get_deathnote_entry(*, guild_id: int, normalized_pseudo: str) -> Optional[sqlite3.Row]:
    return _db().execute(
        """
        SELECT * FROM deathnote_blacklist
        WHERE guild_id = ?
          AND normalized_pseudo = ?
        """,
        (guild_id, normalized_pseudo),
    ).fetchone()


def list_deathnote_entries(*, guild_id: int, limit: int = 50) -> list[sqlite3.Row]:
    rows = _db().execute(
        """
        SELECT * FROM deathnote_blacklist
        WHERE guild_id = ?
        ORDER BY pseudo COLLATE NOCASE ASC
        LIMIT ?
        """,
        (guild_id, limit),
    ).fetchall()
    return list(rows)


def delete_deathnote_entry(*, guild_id: int, normalized_pseudo: str) -> bool:
    cur = _db().execute(
        """
        DELETE FROM deathnote_blacklist
        WHERE guild_id = ?
          AND normalized_pseudo = ?
        """,
        (guild_id, normalized_pseudo),
    )
    _db().commit()
    return cur.rowcount > 0


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


# --------------------------------------------------------------- onboarding tickets


def create_onboarding_ticket(*, channel_id: int, guild_id: int, user_id: int) -> int:
    now = _now_iso()
    cur = _db().execute(
        """
        INSERT INTO onboarding_tickets
            (channel_id, guild_id, user_id, status, created_at, updated_at)
        VALUES (?, ?, ?, 'pending', ?, ?)
        """,
        (channel_id, guild_id, user_id, now, now),
    )
    _db().commit()
    return cur.lastrowid


def get_onboarding_ticket_by_channel(channel_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM onboarding_tickets WHERE channel_id = ?", (channel_id,)
    ).fetchone()


def get_open_onboarding_ticket_for_user(
    *, guild_id: int, user_id: int
) -> Optional[sqlite3.Row]:
    return _db().execute(
        """
        SELECT * FROM onboarding_tickets
        WHERE guild_id = ?
          AND user_id = ?
          AND status NOT IN ('closed', 'deleted')
        ORDER BY id DESC
        LIMIT 1
        """,
        (guild_id, user_id),
    ).fetchone()


def update_onboarding_ticket(channel_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = _now_iso()
    for key, value in list(fields.items()):
        if isinstance(value, datetime):
            fields[key] = value.isoformat()
    assignments = ", ".join(f"{col} = ?" for col in fields)
    _db().execute(
        f"UPDATE onboarding_tickets SET {assignments} WHERE channel_id = ?",
        (*fields.values(), channel_id),
    )
    _db().commit()


def list_onboarding_tickets_with_close_after() -> list[sqlite3.Row]:
    rows = _db().execute(
        """
        SELECT * FROM onboarding_tickets
        WHERE close_after IS NOT NULL
          AND status NOT IN ('closed', 'deleted')
        ORDER BY close_after, id
        """
    ).fetchall()
    return list(rows)


def close_onboarding_ticket(channel_id: int) -> None:
    update_onboarding_ticket(channel_id, status="closed")
    close_ticket(channel_id)


# ---------------------------------------------------------------------- role menus


def create_role_menu(
    *,
    guild_id: int,
    channel_id: int,
    title: str,
    description: Optional[str],
    color: Optional[int],
    footer: Optional[str],
    image_url: Optional[str],
    thumbnail_url: Optional[str],
    created_by: int,
) -> int:
    now = _now_iso()
    cur = _db().execute(
        """
        INSERT INTO role_menus
            (guild_id, channel_id, title, description, color, footer,
             image_url, thumbnail_url, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            guild_id,
            channel_id,
            title,
            description,
            color,
            footer,
            image_url,
            thumbnail_url,
            created_by,
            now,
            now,
        ),
    )
    _db().commit()
    return cur.lastrowid


def get_role_menu(menu_id: int) -> Optional[sqlite3.Row]:
    return _db().execute("SELECT * FROM role_menus WHERE id = ?", (menu_id,)).fetchone()


def get_role_menu_by_message(message_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM role_menus WHERE message_id = ?", (message_id,)
    ).fetchone()


def list_role_menus(guild_id: Optional[int] = None) -> list[sqlite3.Row]:
    if guild_id is None:
        rows = _db().execute("SELECT * FROM role_menus ORDER BY id DESC").fetchall()
    else:
        rows = _db().execute(
            "SELECT * FROM role_menus WHERE guild_id = ? ORDER BY id DESC",
            (guild_id,),
        ).fetchall()
    return list(rows)


def update_role_menu(menu_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = _now_iso()
    assignments = ", ".join(f"{col} = ?" for col in fields)
    _db().execute(
        f"UPDATE role_menus SET {assignments} WHERE id = ?",
        (*fields.values(), menu_id),
    )
    _db().commit()


def delete_role_menu(menu_id: int) -> None:
    _db().execute("DELETE FROM role_menus WHERE id = ?", (menu_id,))
    _db().commit()


def add_role_menu_component(
    *,
    menu_id: int,
    component_type: str,
    label: Optional[str] = None,
    placeholder: Optional[str] = None,
    min_values: int = 0,
    max_values: int = 1,
    exclusive: bool = False,
    style: Optional[str] = None,
    emoji: Optional[str] = None,
    role_id: Optional[int] = None,
) -> int:
    row = _db().execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS next_position "
        "FROM role_menu_components WHERE menu_id = ?",
        (menu_id,),
    ).fetchone()
    position = row["next_position"] if row else 0
    cur = _db().execute(
        """
        INSERT INTO role_menu_components
            (menu_id, component_type, label, placeholder, min_values, max_values,
             exclusive, style, emoji, role_id, position)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            menu_id,
            component_type,
            label,
            placeholder,
            min_values,
            max_values,
            1 if exclusive else 0,
            style,
            emoji,
            role_id,
            position,
        ),
    )
    _db().commit()
    return cur.lastrowid


def get_role_menu_component(component_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM role_menu_components WHERE id = ?", (component_id,)
    ).fetchone()


def update_role_menu_component(component_id: int, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{col} = ?" for col in fields)
    _db().execute(
        f"UPDATE role_menu_components SET {assignments} WHERE id = ?",
        (*fields.values(), component_id),
    )
    _db().commit()


def list_role_menu_components(menu_id: int) -> list[sqlite3.Row]:
    rows = _db().execute(
        "SELECT * FROM role_menu_components WHERE menu_id = ? ORDER BY position, id",
        (menu_id,),
    ).fetchall()
    return list(rows)


def delete_role_menu_component(component_id: int) -> None:
    _db().execute("DELETE FROM role_menu_components WHERE id = ?", (component_id,))
    _db().commit()


def add_role_menu_option(
    *,
    component_id: int,
    role_id: int,
    label: str,
    description: Optional[str] = None,
    emoji: Optional[str] = None,
) -> int:
    row = _db().execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS next_position "
        "FROM role_menu_options WHERE component_id = ?",
        (component_id,),
    ).fetchone()
    position = row["next_position"] if row else 0
    cur = _db().execute(
        """
        INSERT INTO role_menu_options
            (component_id, role_id, label, description, emoji, position)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(component_id, role_id) DO UPDATE SET
            label = excluded.label,
            description = excluded.description,
            emoji = excluded.emoji
        """,
        (component_id, role_id, label, description, emoji, position),
    )
    _db().commit()
    return cur.lastrowid


def get_role_menu_option(option_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM role_menu_options WHERE id = ?", (option_id,)
    ).fetchone()


def update_role_menu_option(option_id: int, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{col} = ?" for col in fields)
    _db().execute(
        f"UPDATE role_menu_options SET {assignments} WHERE id = ?",
        (*fields.values(), option_id),
    )
    _db().commit()


def list_role_menu_options(component_id: int) -> list[sqlite3.Row]:
    rows = _db().execute(
        "SELECT * FROM role_menu_options WHERE component_id = ? ORDER BY position, id",
        (component_id,),
    ).fetchall()
    return list(rows)


def delete_role_menu_option(option_id: int) -> None:
    _db().execute("DELETE FROM role_menu_options WHERE id = ?", (option_id,))
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
    if end_date < start_date:
        start_date, end_date = end_date, start_date
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
        ORDER BY
          CASE WHEN start_date <= end_date THEN end_date ELSE start_date END,
          id
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
        "CASE WHEN start_date <= end_date THEN end_date ELSE start_date END >= ?",
    ]
    params: list[Any] = [guild_id, today_iso]
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    rows = _db().execute(
        f"""
        SELECT * FROM absences
        WHERE {" AND ".join(where)}
        ORDER BY
          CASE WHEN start_date <= end_date THEN start_date ELSE end_date END,
          CASE WHEN start_date <= end_date THEN end_date ELSE start_date END,
          id
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
# Forum où sont créés les posts du marché.
SETTING_MARKET_FORUM_CHANNEL = "market_forum_channel"
# Salon de discussion où annoncer les échanges Metamob. Vide = salon de commande.
SETTING_METAMOB_TALK_CHANNEL = "metamob_talk_channel"
# Forum où créer les posts d'échange Metamob.
SETTING_METAMOB_FORUM_CHANNEL = "metamob_forum_channel"
# Active ou désactive les commandes Metamob du serveur. Absent/1 = actif, 0 = off.
SETTING_METAMOB_ENABLED = "metamob_enabled"
# Rôle Discord qui donne les droits admin bot. Vide = ADMIN_IDS/proprio/admin Discord.
SETTING_BOT_ADMIN_ROLE = "bot_admin_role"
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
# Rôle donné aux nouveaux membres acceptés en guilde via le ticket d'accueil.
SETTING_GUILD_MEMBER_ROLE = "guild_member_role"
# Rôle donné aux visiteurs qui demandent seulement l'accès au marché.
SETTING_VISITOR_ROLE = "visitor_role"
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


# ------------------------------------------------------------------------- market


def upsert_market_post(
    *,
    thread_id: int,
    guild_id: int,
    owner_id: int,
    last_activity_at: datetime,
) -> None:
    _db().execute(
        """
        INSERT INTO market_posts
            (thread_id, guild_id, owner_id, last_activity_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(thread_id) DO UPDATE SET
            guild_id = excluded.guild_id,
            owner_id = excluded.owner_id,
            last_activity_at = excluded.last_activity_at
        WHERE market_posts.closed_at IS NULL
        """,
        (thread_id, guild_id, owner_id, last_activity_at.isoformat()),
    )
    _db().commit()


def get_market_post(thread_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM market_posts WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()


def set_market_post_control_message(thread_id: int, message_id: int) -> None:
    _db().execute(
        "UPDATE market_posts SET control_message_id = ? WHERE thread_id = ? AND closed_at IS NULL",
        (message_id, thread_id),
    )
    _db().commit()


def list_inactive_market_posts(cutoff: datetime) -> list[sqlite3.Row]:
    return _db().execute(
        """
        SELECT * FROM market_posts
        WHERE closed_at IS NULL AND last_activity_at <= ?
        ORDER BY last_activity_at ASC
        """,
        (cutoff.isoformat(),),
    ).fetchall()


def mark_market_post_closed(thread_id: int, status: str, closed_at: datetime) -> None:
    _db().execute(
        """
        UPDATE market_posts
        SET closed_at = ?, close_status = ?
        WHERE thread_id = ?
        """,
        (closed_at.isoformat(), status, thread_id),
    )
    _db().commit()


# ------------------------------------------------------------------------ metamob


def upsert_metamob_link(
    *,
    guild_id: int,
    user_id: int,
    api_key: str,
    quest_slug: str,
    username: Optional[str] = None,
    character_name: Optional[str] = None,
    server_name: Optional[str] = None,
    quest_type_slug: Optional[str] = None,
) -> None:
    now = _now_iso()
    _db().execute(
        """
        INSERT INTO metamob_links
            (guild_id, user_id, username, quest_slug, api_key, character_name,
             server_name, quest_type_slug, linked_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            username = excluded.username,
            quest_slug = excluded.quest_slug,
            api_key = excluded.api_key,
            character_name = excluded.character_name,
            server_name = excluded.server_name,
            quest_type_slug = excluded.quest_type_slug,
            updated_at = excluded.updated_at
        """,
        (
            guild_id,
            user_id,
            username,
            quest_slug,
            api_key,
            character_name,
            server_name,
            quest_type_slug,
            now,
            now,
        ),
    )
    _db().commit()


def get_metamob_link(guild_id: int, user_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM metamob_links WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ).fetchone()


def list_metamob_links_for_guild(guild_id: int) -> list[sqlite3.Row]:
    rows = _db().execute(
        "SELECT * FROM metamob_links WHERE guild_id = ? ORDER BY user_id",
        (guild_id,),
    ).fetchall()
    return list(rows)


def delete_metamob_link(guild_id: int, user_id: int) -> bool:
    cur = _db().execute(
        "DELETE FROM metamob_links WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    _db().commit()
    return cur.rowcount > 0


def create_metamob_trade(
    *,
    guild_id: int,
    thread_id: int,
    forum_channel_id: int,
    starter_id: int,
    target_id: int,
    control_message_id: Optional[int] = None,
) -> int:
    now = _now_iso()
    cur = _db().execute(
        """
        INSERT INTO metamob_trades
            (guild_id, thread_id, forum_channel_id, starter_id, target_id, status,
             control_message_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)
        """,
        (
            guild_id,
            thread_id,
            forum_channel_id,
            starter_id,
            target_id,
            control_message_id,
            now,
            now,
        ),
    )
    _db().commit()
    return cur.lastrowid


def get_metamob_trade(trade_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM metamob_trades WHERE id = ?",
        (trade_id,),
    ).fetchone()


def get_metamob_trade_by_thread(thread_id: int) -> Optional[sqlite3.Row]:
    return _db().execute(
        "SELECT * FROM metamob_trades WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()


def update_metamob_trade(trade_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields.setdefault("updated_at", _now_iso())
    assignments = ", ".join(f"{col} = ?" for col in fields)
    _db().execute(
        f"UPDATE metamob_trades SET {assignments} WHERE id = ?",
        (*fields.values(), trade_id),
    )
    _db().commit()


def add_metamob_trade_item(
    *,
    trade_id: int,
    monster_id: int,
    monster_name: str,
    giver_id: int,
    receiver_id: int,
    quantity: int = 1,
) -> None:
    _db().execute(
        """
        INSERT INTO metamob_trade_items
            (trade_id, monster_id, monster_name, giver_id, receiver_id, quantity)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_id, monster_id, giver_id) DO UPDATE SET
            quantity = metamob_trade_items.quantity + excluded.quantity,
            monster_name = excluded.monster_name,
            receiver_id = excluded.receiver_id
        """,
        (trade_id, monster_id, monster_name, giver_id, receiver_id, quantity),
    )
    update_metamob_trade(trade_id)


def remove_metamob_trade_item(
    *,
    trade_id: int,
    monster_id: int,
    giver_id: int,
    quantity: int = 1,
) -> bool:
    row = _db().execute(
        """
        SELECT quantity FROM metamob_trade_items
        WHERE trade_id = ? AND monster_id = ? AND giver_id = ?
        """,
        (trade_id, monster_id, giver_id),
    ).fetchone()
    if row is None:
        return False

    next_quantity = row["quantity"] - quantity
    if next_quantity > 0:
        _db().execute(
            """
            UPDATE metamob_trade_items
            SET quantity = ?
            WHERE trade_id = ? AND monster_id = ? AND giver_id = ?
            """,
            (next_quantity, trade_id, monster_id, giver_id),
        )
    else:
        _db().execute(
            """
            DELETE FROM metamob_trade_items
            WHERE trade_id = ? AND monster_id = ? AND giver_id = ?
            """,
            (trade_id, monster_id, giver_id),
        )
    update_metamob_trade(trade_id)
    return True


def list_metamob_trade_items(trade_id: int) -> list[sqlite3.Row]:
    rows = _db().execute(
        """
        SELECT * FROM metamob_trade_items
        WHERE trade_id = ?
        ORDER BY giver_id, monster_name
        """,
        (trade_id,),
    ).fetchall()
    return list(rows)


def clear_metamob_trade_confirmation(trade_id: int) -> None:
    update_metamob_trade(trade_id, status="open", confirmed_by=None)


# ----------------------------------------------------------------- helpers tests


def reset_for_tests(db_path: str) -> None:
    """Réinitialise la connexion sur une BDD de test (chemin explicite)."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
    init(db_path)
