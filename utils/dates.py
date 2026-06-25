"""Parsing de dates et helpers temporels (Europe/Paris), sans dépendance Discord."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from config import PARIS

JOURS_FR = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


class InvalidRaidDate(ValueError):
    """Date de raid invalide ou dans le passé."""


def parse_raid_date(text: str, now: Optional[datetime] = None) -> date:
    """Convertit un texte libre en date de raid (Paris).

    Accepte : YYYY-MM-DD, DD/MM/YYYY, DD/MM (année courante ou suivante),
    DD-MM, et les mots 'aujourd'hui', 'demain', 'après-demain', et les jours
    de la semaine en français ('lundi' ... 'dimanche' = prochain occurence).

    Lève InvalidRaidDate si le format est inconnu ou si la date est passée.
    """
    if not text:
        raise InvalidRaidDate("date vide")

    raw = text.strip().lower().replace("’", "'")
    now = now or datetime.now(PARIS)
    today = now.date()

    # Mots-clés relatifs
    relatifs = {
        "aujourdhui": 0,
        "aujourd'hui": 0,
        "today": 0,
        "demain": 1,
        "tomorrow": 1,
        "apres-demain": 2,
        "après-demain": 2,
    }
    compact = raw.replace(" ", "")
    if compact in relatifs:
        return today + timedelta(days=relatifs[compact])

    # Jour de la semaine
    if raw in JOURS_FR:
        target = JOURS_FR[raw]
        delta = (target - today.weekday()) % 7
        if delta == 0:  # aujourd'hui -> on pousse à la semaine suivante
            delta = 7
        return today + timedelta(days=delta)

    # Formats numériques
    cleaned = raw.replace("-", "/")
    parts = [p for p in cleaned.split("/") if p != ""]
    try:
        if len(parts) == 3:
            if len(parts[0]) == 4:  # YYYY-MM-DD
                y, m, d = parts
            else:  # DD/MM/YYYY
                d, m, y = parts
            result = date(int(y), int(m), int(d))
        elif len(parts) == 2:
            d, m = parts
            candidate = date(today.year, int(m), int(d))
            # DD/MM déjà passé cette année -> on prend l'année suivante
            result = candidate if candidate >= today else date(today.year + 1, int(m), int(d))
        else:
            raise InvalidRaidDate(f"format non reconnu : {text!r}")
    except ValueError as exc:
        raise InvalidRaidDate(f"date invalide : {text!r} ({exc})")

    if result < today:
        raise InvalidRaidDate(f"date dans le passé : {result.isoformat()}")
    return result


def combine_date_hour(day: date, hour: int) -> datetime:
    """Combine une date et une heure en datetime aware Paris."""
    return datetime.combine(day, time(hour=hour, minute=0), tzinfo=PARIS)


def format_date_fr(day: date) -> str:
    """Ex: 'mercredi 25/06'."""
    noms = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    return f"{noms[day.weekday()]} {day.strftime('%d/%m')}"


def format_dt_fr(dt: datetime) -> str:
    """Ex: 'mercredi 25/06 à 21h00'."""
    return f"{format_date_fr(dt.date())} à {dt.strftime('%Hh%M')}"


def countdown_fr(closes_at: datetime, now: Optional[datetime] = None) -> str:
    """Durée humaine avant closes_at : 'dans 2h', 'dans 35min', 'clôturé'."""
    now = now or datetime.now(PARIS)
    delta = closes_at - now
    if delta.total_seconds() <= 0:
        return "clôturé"
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return f"dans {mins} min"
    hours = mins // 60
    rest = mins % 60
    if rest:
        return f"dans {hours}h{rest:02d}"
    return f"dans {hours}h"
