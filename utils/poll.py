"""Logique métier pure (dépouillement de sondage, transitions d'état, rappels).

Aucune dépendance Discord ni DB : testable unitairement.
"""
from __future__ import annotations

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


def parse_duree(value: Optional[str], default: str = "12h") -> str:
    """Normalise une durée de sondage saisie librement ('1h','12h','24h')."""
    if value is None:
        return default
    cleaned = value.strip().lower().replace(" ", "")
    if cleaned in ("1h", "1"):
        return "1h"
    if cleaned in ("12h", "12"):
        return "12h"
    if cleaned in ("24h", "24"):
        return "24h"
    return default
