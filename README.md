# B&B Raids — Bot Dofus (Gigalodon / Jardins Éternels)

Bot Discord pour organiser des raids Dofus : on crée un raid, un **sondage à
boutons** décide de l'heure (et du raid si non précisé), puis un **rappel MP**
part 10 min avant. Un **système de ticket** permet d'organiser un raid en salon
privé.

## Stack

- Python 3.12 · discord.py 2.x · SQLite (synchrone) · Docker

## Commandes

### Raids

| Commande | Description |
|---|---|
| `/raid date duree [raid] [note]` | Crée un raid + sondage pour l'heure. |
| `/setchannel setting channel` | Définit le salon des raids / la catégorie des tickets (admin). |
| `/showconfig` | Affiche la configuration du serveur. |
| `/list_raids` | Liste les raids actifs. |
| `/cancel_raid raid_id` | Annule un raid (créateur ou admin). |
| `/force_close raid_id` | Clôture immédiatement le sondage en cours (admin). |
| `/raid_panel` | Poste le panneau de ticket (admin). |

> 💡 **Avant tout** : utilise `/setchannel setting:Salon des raids channel:#ton-salon`
> pour que les sondages/embeds arrivent au bon endroit. Puis
> `/setchannel setting:Catégorie des tickets channel:#ta-catégorie` pour les tickets.

### `/raid` en détail

- `date` : `ce soir`, `ce matin`, `21h`, `28/06`, `2026-06-28`, `demain`, `lundi`…
  (« ce soir » / une heure seule = aujourd'hui ; l'heure reste choisie par le sondage).
- `duree` : `5min` → `24h` (durée du sondage, **mini 5 min** ; l'heure est choisie par le sondage).
- `raid` (optionnel) : `Gigalodon` / `Jardins Éternels`. **Si vide** → un sondage
  choisit le raid d'abord, puis un sondage choisit l'heure.
- Chaque votant à l'heure est inscrit au rappel MP ; le message final propose
  aussi un bouton **Je participe 📌** pour s'inscrire sans voter.
- Les sondages comportent un bouton **🔒 Clôturer (admin)** : admins **et créateur
  du raid** peuvent clôturer plus tôt en un clic (équivalent `/force_close`).

### Tickets

1. Un admin poste le panneau via `/raid_panel`.
2. Un membre clique **🎟️ Ouvrir un ticket raid** → salon privé (membre + admins).
3. Dans le ticket : **🎯 Créer ce raid** (formulaire date/raid/durée) → le sondage
   est posté dans le salon des raids. **🔒 Fermer** supprime le salon.

## Variables d'environnement (`.env`)

| Var | Défaut | Rôle |
|---|---|---|
| `DISCORD_TOKEN` | — | Token du bot (requis) |
| `DISCORD_GUILD_ID` | — | Sync instantanée sur cette guilde (vide = global) |
| `ADMIN_IDS` | — | IDs Discord admins (séparés par `,`) |
| `RAID_HOURS` | `14,15,…,23` | Créneaux du sondage heure |
| `RAID_DEFAULT_HOUR` | `21` | Heure si 0 vote |
| `REMINDER_MINUTES` | `10` | Minutes avant le raid pour le rappel |
| `RAID_NAMES` | `Gigalodon,Jardins Éternels` | Raids possibles |
| `RAIDS_CHANNEL_ID` | — | Salon des sondages (surchargeable par `/setchannel`, vide = salon courant) |
| `TICKET_CATEGORY_ID` | — | Catégorie des tickets (surchargeable par `/setchannel`) |
| `DB_PATH` | `/app/data/beb_raid.db` | Base SQLite |

> ℹ️ **SERVER MEMBERS INTENT** (optionnel) : permet d'ajouter automatiquement les
> admins aux tickets depuis le cache. Sans lui, le bot utilise `fetch_member` en
> fallback. Le bot démarre dans tous les cas.

## Lancement

### Docker (depuis `server/bot`)
```bash
docker compose up -d --build beb-raid
docker compose logs --tail=100 beb-raid
```

### Local
```bash
cp .env.example .env   # renseigner DISCORD_TOKEN + ADMIN_IDS
pip install -r requirements.txt
python main.py
```

## Tests
```bash
pytest -q
```

## Structure
```text
beb_raid/
  main.py            # entry point, cogs, sync des commandes
  config.py          # variables d'env + helpers (Paris, parsing)
  db.py              # SQLite synchrone (raids, votes, participants, tickets)
  cogs/
    core.py          # /ping
    admin.py         # /sync, /reload
    settings.py      # /setchannel, /showconfig (config par serveur en DB)
    raid.py          # /raid, sondages boutons, planif, rappel MP
    ticket.py        # /raid_panel, tickets, modal de création
  utils/
    dates.py         # parsing de date flexible (Paris)
    poll.py          # dépouillement, états, rappels (pure)
    embeds.py        # builders d'embeds
  tests/             # dates, tally, db, imports
```

## Notes d'implémentation

- **Robustesse redémarrage** : sondages et rappels sont planifiés par `asyncio`
  et **replanifiés au démarrage** depuis SQLite (`cog_load` → `_reschedule_all`).
  Un `docker compose restart` n'annule aucun rappel.
- **Vues persistantes** : les boutons encodent `raid_id` + choix dans leur
  `custom_id` ; les vues sont réenregistrées au démarrage pour router les clics.
- **Fuseau** : tout est géré en `Europe/Paris` (stockage ISO aware).
