import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

_raw_guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
DISCORD_GUILD_ID = int(_raw_guild_id) if _raw_guild_id.isdigit() else 0

BOT_NAME = os.getenv("BOT_NAME", "Beb Raid")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

ADMIN_IDS = {
    int(user_id.strip())
    for user_id in os.getenv("ADMIN_IDS", "").split(",")
    if user_id.strip().isdigit()
}

# Timezone utilisée partout pour les calculs et le stockage (ISO aware).
PARIS = ZoneInfo("Europe/Paris")

DB_PATH = os.getenv("DB_PATH", "/app/data/beb_raid.db")


def _parse_channel_id(raw: str) -> int:
    raw = raw.strip()
    return int(raw) if raw.isdigit() else 0


# Salon où sont postés les sondages / messages de raid.
# Vide = on utilise le salon où la commande /raid a été invoquée.
RAIDS_CHANNEL_ID = _parse_channel_id(os.getenv("RAIDS_CHANNEL_ID", ""))

# Catégorie où créer les salons de ticket. Vide = catégorie du salon courant.
TICKET_CATEGORY_ID = _parse_channel_id(os.getenv("TICKET_CATEGORY_ID", ""))


def _parse_hours(raw: str) -> list[int]:
    hours = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            h = int(chunk)
        except ValueError:
            continue
        if 0 <= h <= 23:
            hours.append(h)
    return hours


# Créneaux horaires proposés dans le sondage de l'heure.
RAID_HOURS = _parse_hours(os.getenv("RAID_HOURS", "14,15,16,17,18,19,20,21,22,23"))
if not RAID_HOURS:
    RAID_HOURS = [14, 15, 16, 17, 18, 19, 20, 21, 22, 23]

# Heure par défaut si personne ne vote au sondage de l'heure.
try:
    RAID_DEFAULT_HOUR = int(os.getenv("RAID_DEFAULT_HOUR", "21"))
except ValueError:
    RAID_DEFAULT_HOUR = 21
if not (0 <= RAID_DEFAULT_HOUR <= 23):
    RAID_DEFAULT_HOUR = 21

# Minutes avant le raid pour envoyer le rappel MP.
try:
    REMINDER_MINUTES = int(os.getenv("REMINDER_MINUTES", "10"))
except ValueError:
    REMINDER_MINUTES = 10

# Noms de raids possibles (séparés par des virgules).
RAID_NAMES = [
    name.strip()
    for name in os.getenv("RAID_NAMES", "Gigalodon,Jardins Éternels").split(",")
    if name.strip()
]
if not RAID_NAMES:
    RAID_NAMES = ["Gigalodon", "Jardins Éternels"]


def now_paris() -> datetime:
    """Datetime-aware maintenant en Europe/Paris."""
    return datetime.now(PARIS)
