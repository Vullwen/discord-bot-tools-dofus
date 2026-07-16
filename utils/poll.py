"""Logique métier pure (dépouillement de sondage, transitions d'état, rappels).

Aucune dépendance Discord ni DB : testable unitairement.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Mapping

# États possibles du cycle de vie d'un raid.
STATE_CHOOSING_RAID = "choosing_raid"  # sondage choix du raid en cours
STATE_VOTING_HOUR = "voting_hour"      # sondage de l'heure en cours
STATE_BREAKING_HOUR_TIE = "breaking_hour_tie"  # attente du créateur pour départager
STATE_SCHEDULED = "scheduled"          # heure décidée, en attente du rappel
STATE_REMINDED = "reminded"            # rappel envoyé, en attente de fin
STATE_DONE = "done"                    # raid passé
STATE_CANCELLED = "cancelled"          # annulé

ACTIVE_STATES = frozenset(
    {
        STATE_CHOOSING_RAID,
        STATE_VOTING_HOUR,
        STATE_BREAKING_HOUR_TIE,
        STATE_SCHEDULED,
        STATE_REMINDED,
    }
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


def tied_leaders(counts: Mapping[str, int], order: Iterable[str]) -> list[str]:
    """Choix ex-aequo en tête, dans l'ordre demandé. Vide si aucun vote positif."""
    best = max(counts.values()) if counts else 0
    if best <= 0:
        return []
    ordered = [choice for choice in order if counts.get(choice, 0) == best]
    extras = [choice for choice, value in counts.items() if value == best and choice not in ordered]
    return ordered + extras


def reminder_time(scheduled_at: datetime, minutes: int) -> datetime:
    """Moment d'envoi du rappel (scheduled_at - minutes)."""
    return scheduled_at - timedelta(minutes=minutes)


def parse_poll_hours(raw, fallback: Iterable[int]) -> list[int]:
    """CSV '19,20,21' -> [19, 20, 21] (trié, dédupliqué, 0-23).

    Retourne `list(fallback)` si `raw` est vide/invalide. Utilisé pour relire les
    créneaux choisis par le créateur d'un raid (colonne `poll_hours`).
    """
    if not raw:
        return sorted(set(fallback))
    hours: set[int] = set()
    for chunk in str(raw).split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            h = int(chunk)
            if 0 <= h <= 23:
                hours.add(h)
    return sorted(hours) if hours else sorted(set(fallback))


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
