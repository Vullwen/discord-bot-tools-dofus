"""Builders d'embeds Discord pour les raids. Pas d'appel API, formatage pur."""
from __future__ import annotations

from datetime import date, datetime
from typing import Mapping, Optional

import discord

from config import RAID_HOURS, RAID_NAMES, raid_cap
from utils import dates as dates_utils
from utils.poll import format_counts

GREEN = 0x2ECC71
GOLD = 0xF1C40F
BLUE = 0x3498DB
RED = 0xE74C3C
GREY = 0x95A5A6

_HOUR_ORDER = [str(h) for h in RAID_HOURS]


def _parse_day(raid) -> date:
    return date.fromisoformat(raid["date"])


def _format_spots(participants: int, cap) -> str:
    """Affichage 'X/cap' avec marqueur COMPLET."""
    if cap:
        full = " 🟥 COMPLET" if participants >= cap else ""
        return f"{participants}/{cap}{full}"
    return str(participants)


def _scheduled_dt(raid) -> datetime | None:
    raw = raid["scheduled_at"]
    return datetime.fromisoformat(raw) if raw else None


def raid_choice_embed(raid, counts: Mapping[str, int], creator: str) -> discord.Embed:
    embed = discord.Embed(
        title="🤔 Quel raid organiser ?",
        description=(
            f"**Date visée :** {dates_utils.format_date_fr(_parse_day(raid))}\n"
            "Vote pour le raid que tu veux faire. Le sondage de l'heure suivra."
        ),
        color=GREEN,
    )
    embed.add_field(
        name="Résultats",
        value=format_counts(counts, RAID_NAMES),
        inline=False,
    )
    if raid["note"]:
        embed.add_field(name="Note", value=raid["note"], inline=False)
    embed.set_footer(text=f"Créé par {creator} • Clôture {dates_utils.countdown_fr(datetime.fromisoformat(raid['raid_poll_closes_at']))}")
    return embed


def raid_choice_result_embed(
    raid, winner: str, counts: Mapping[str, int], fixed_time_label: Optional[str] = None
) -> discord.Embed:
    embed = discord.Embed(
        title="🤔 Choix du raid — clôturé",
        description=f"**Raid choisi : {winner}** 🎯",
        color=GREY,
    )
    embed.add_field(name="Résultats finaux", value=format_counts(counts, RAID_NAMES), inline=False)
    if fixed_time_label:
        embed.set_footer(text=f"⏰ Heure fixée : {fixed_time_label} — planification…")
    else:
        embed.set_footer(text="Le sondage de l'heure arrive.")
    return embed


def hour_poll_embed(raid, counts: Mapping[str, int], creator: str, participants: int) -> discord.Embed:
    name = raid["name"] or "à définir"
    cap = raid_cap(raid["name"])
    embed = discord.Embed(
        title=f"🗓️ Sondage — heure du raid {name}",
        description=(
            f"**Date :** {dates_utils.format_date_fr(_parse_day(raid))}\n"
            "Clique sur ton créneau préféré. Tu peux changer d'avis."
        ),
        color=GREEN,
    )
    embed.add_field(
        name="Créneaux",
        value=format_counts(counts, _HOUR_ORDER, suffix="h"),
        inline=False,
    )
    embed.add_field(name="Inscriptions", value=_format_spots(participants, cap), inline=False)
    if raid["note"]:
        embed.add_field(name="Note", value=raid["note"], inline=False)
    closes = raid["hour_poll_closes_at"]
    footer_time = dates_utils.countdown_fr(datetime.fromisoformat(closes)) if closes else "—"
    embed.set_footer(text=f"Créé par {creator} • Clôture {footer_time}")
    return embed


def hour_poll_result_embed(raid, winner_hour: str, counts: Mapping[str, int]) -> discord.Embed:
    name = raid["name"] or "Raid"
    embed = discord.Embed(
        title="🗓️ Sondage heure — clôturé",
        description=f"**Heure choisie : {winner_hour}h** ⏰",
        color=GREY,
    )
    embed.add_field(name="Résultats finaux", value=format_counts(counts, _HOUR_ORDER, suffix="h"), inline=False)
    embed.set_footer(text=f"{name} — {dates_utils.format_date_fr(_parse_day(raid))}")
    return embed


def scheduled_embed(raid, participants: int, creator: str) -> discord.Embed:
    dt = _scheduled_dt(raid)
    cap = raid_cap(raid["name"])
    embed = discord.Embed(
        title=f"🎯 Raid planifié : {raid['name']}",
        description=(
            f"**Quand :** {dates_utils.format_dt_fr(dt)}\n"
            f"**Participants :** {_format_spots(participants, cap)}\n"
            "Clique sur **Je participe 📌** pour recevoir un rappel en MP 10 min avant."
        ),
        color=GOLD,
    )
    if raid["note"]:
        embed.add_field(name="Note", value=raid["note"], inline=False)
    embed.set_footer(text=f"Créé par {creator} • Rappel MP {10} min avant")
    return embed


def reminder_dm_embed(raid) -> discord.Embed:
    dt = _scheduled_dt(raid)
    embed = discord.Embed(
        title=f"⏰ Raid dans peu de temps : {raid['name']}",
        description=f"**Début prévu : {dates_utils.format_dt_fr(dt)}**\n"
        "Prépare ton stuff, le raid démarre !",
        color=BLUE,
    )
    return embed


def reminder_channel_embed(raid, participants: int) -> discord.Embed:
    dt = _scheduled_dt(raid)
    embed = discord.Embed(
        title=f"⚡ Rappel — raid {raid['name']} bientôt",
        description=(
            f"**Début prévu : {dates_utils.format_dt_fr(dt)}**\n"
            f"Inscriptions : {_format_spots(participants, raid_cap(raid['name']))}."
        ),
        color=BLUE,
    )
    return embed


def cancelled_embed(raid) -> discord.Embed:
    embed = discord.Embed(
        title=f"❌ Raid annulé (#{raid['id']})",
        description=f"**{raid['name'] or 'Raid'}** prévu le {dates_utils.format_date_fr(_parse_day(raid))} a été annulé.",
        color=RED,
    )
    return embed


def participants_embed(raid, names) -> discord.Embed:
    """Liste les participants (noms déjà résolus) d'un raid."""
    cap = raid_cap(raid["name"])
    embed = discord.Embed(
        title=f"📌 Participants — {raid['name'] or 'Raid'}",
        color=BLUE,
    )
    if names:
        embed.description = "\n".join(f"• {name}" for name in names)
    else:
        embed.description = "Aucun participant pour l'instant."
    embed.set_footer(text=f"{_format_spots(len(names), cap)} • Raid #{raid['id']}")
    return embed


def list_embed(rows) -> discord.Embed:
    embed = discord.Embed(title="📋 Raids actifs", color=GREEN)
    if not rows:
        embed.description = "Aucun raid actif pour le moment."
        return embed

    state_label = {
        "choosing_raid": "🔊 Choix du raid",
        "voting_hour": "🗓️ Sondage heure",
        "scheduled": "🎯 Planifié",
        "reminded": "⏰ Rappel envoyé",
    }
    lines = []
    for raid in rows:
        name = raid["name"] or "?"

        label = f"**#{raid['id']} — {name}** ({dates_utils.format_date_fr(_parse_day(raid))})"
        detail = state_label.get(raid["state"], raid["state"])
        dt = _scheduled_dt(raid)
        if dt:
            detail += f" • {dates_utils.format_dt_fr(dt)}"
        elif raid["state"] == "voting_hour" and raid["hour_poll_closes_at"]:
            detail += f" • clôture {dates_utils.countdown_fr(datetime.fromisoformat(raid['hour_poll_closes_at']))}"
        lines.append(f"{label}\n{detail}")
    embed.description = "\n\n".join(lines)
    return embed
