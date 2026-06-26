"""Logique métier pure (dépouillement de sondage, transitions d'état, rappels).

Aucune dépendance Discord ni DB : testable unitairement.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Optional

# États possibles du cycle de vie d'un raid.
STATE_CHOOSING_RAID = "choosing_raid"  # sondage choix du raid en cours
STATE_VOTING_HOUR = "voting_hour"      # sondage de l'heure en cours
STATE_SCHEDULED = "scheduled"          # heure décidée, en attente du rappel
STATE_REMINDED = "reminded"            # rappel envoyé, en attente de fin
STATE_DONE = "done"                    # raid passé
STATE_CANCELLED = "cancelled"          # annulé

ACTIVE_STATES = frozenset(
    {STATE_CHOOSING_RAID, STATE_VOTING_HOUR, STATE_SCHEDULED, STATE_REMINDED}
)
TERMINAL_STATES = frozenset({STATE_DONE, STATE_CANCELLED})


def is_active(state: str) -> bool:
    return state in ACTIVE_STATES


def tally(counts: Mapping[str, int], order: Iterable[str], default: str) -> str:
    """Renvoie le choix gagnant.

    - majorité simple (plus de votes) ;
    - égalité -> premier dans `order` ;
    - aucun vote (ou que des zéros) -> `default`.
    """
    order = list(order)
    if not counts:
        return default
    best = max(counts.values())
    if best <= 0:
        return default
    for choice in order:
        if counts.get(choice, 0) == best:
            return choice
    # Fallback : première clé atteignant le max (au cas où hors de `order`).
    for choice, value in counts.items():
        if value == best:
            return choice
    return default


def reminder_time(scheduled_at: datetime, minutes: int) -> datetime:
    """Moment d'envoi du rappel (scheduled_at - minutes)."""
    return scheduled_at - timedelta(minutes=minutes)


def format_counts(counts: Mapping[str, int], order: Iterable[str], suffix: str = "") -> str:
    """Représentation texte des résultats : '14h: 2 | 15h: 0 | ...'.

    Met en gras le ou les créneaux en tête (ex-aequo).
    """
    order = list(order)
    best = max(counts.values()) if counts else 0
    parts = []
    for choice in order:
        value = counts.get(choice, 0)
        label = f"{choice}{suffix}"
        cell = f"**{label}: {value}**" if value > 0 and value == best else f"{label}: {value}"
        parts.append(cell)
    return " | ".join(parts) if parts else "—"


def parse_duration_seconds(value, minimum: int = 300) -> int:
    """Convertit une durée saisie librement en secondes (minimum appliqué).

    Accepte : '5mn', '5min', '5 m', '5 minutes', '1h', '2h', '1h30', '2h30m',
    '1.5h', '90', '90min'... Unités reconnues : h/heure(s) ; min/mn/m/minute(s).
    Une valeur seule sans unité est interprétée en minutes.
    """
    if value is None:
        return minimum
    s = str(value).strip().lower().replace(",", ".")
    if not s:
        return minimum
    # On collecte tous les couples <nombre><unité> (ex: '1h30' -> 1h + 30min).
    matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(heures|heure|hours|hour|minutes|minute|min|mn|m|h)?",
        s,
    )
    total = 0.0
    found = False
    for num, unit in matches:
        n = float(num)
        if unit.startswith("h"):
            total += n * 3600
        else:
            total += n * 60
        found = True
    if not found:
        return minimum
    return max(int(round(total)), minimum)
