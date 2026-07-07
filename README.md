# Discord bot Raids Dofus

Bot Discord pour organiser des raids Dofus (Gigalodon, Jardins Éternels). On crée
un raid pour une date, les votants choisissent l'heure (et le raid si besoin), un
rappel part avant, puis le salon se nettoie tout seul une fois le raid passé.

Python 3.12, discord.py 2.x, SQLite, Docker.

## Cycle d'un raid

Tout dépend de ce que tu donnes à la création :

- `/raid` avec **une heure** (ex. `vendredi 21h`) : le raid est planifié directement,
  pas de sondage.
- `/raid` avec **le raid mais pas d'heure** : un menu te laisse choisir les créneaux
  à proposer, puis un sondage est lancé. Chacun vote pour les heures qui lui
  conviennent (plusieurs choix possibles).
- `/raid` **sans le raid** : un sondage choisit d'abord le raid, puis l'heure.

Ensuite :

- Les sondages se ferment tout seuls le jour du raid (à midi par défaut).
- Les participants s'inscrivent via les boutons sous le message. Dans un sondage
  d'heure, les votants du créneau gagnant sont inscrits automatiquement. Le bouton
  **Dispo toutes les heures** permet de voter tous les créneaux proposés d'un coup,
  et **Annuler mes heures** retire tous tes votes.
- En cas d'égalité sur l'heure, le créateur reçoit un MP pour départager.
- Un rappel part en MP quelques minutes avant l'heure prévue.
- Deux heures après le raid, les messages le concernant sont supprimés.

Le nombre de places par raid est limité (`RAID_CAPS`). Une fois complet, les
nouvelles inscriptions sont bloquées.

## Commandes

Raids :

- `/raid date [raid] [cloture] [note]` — crée un raid. `cloture` choisit
  l'heure de fermeture le jour du raid (ex. `12h` = midi le jour du raid).
- `/list_raids` — raids actifs.
- `/cancel_raid raid_id` — annule un raid (créateur ou organisateur).
- `/force_close raid_id` — clôture tout de suite le sondage en cours.

Sur chaque message de raid, un bouton **Annuler (admin)** permet d'annuler à
n'importe quelle étape, avec demande de confirmation.

Tickets :

- `/raid_panel` — poste le panneau d'ouverture de ticket (organisateur). Un clic ouvre un
  salon privé pour préparer un raid.

Configuration (organisateur) :

- `/setchannel` — salon des raids, ou catégorie des tickets.
- `/setraidrole` — rôle autorisé à créer et gérer les raids : ID, mention copiée
  ou nom exact (vide = permission Administrateur Discord).
- `/setraidnotifyrole` — rôle mentionné à chaque nouveau raid : ID, mention copiée
  ou nom exact (vide = pas de mention).
- `/showconfig` — affiche la config du serveur.

## Rôles

- **Organisateur** (défini par `/setraidrole`) : crée et gère les raids et tickets,
  configure le bot, clôture les sondages, annule. Si aucun rôle n'est défini, les
  membres avec la permission Administrateur Discord sont organisateurs.
- **Notif raids** (défini par `/setraidnotifyrole`) : mentionné quand un raid est
  annoncé. L'attribution aux membres est manuelle (côté Discord).

## Variables d'environnement (`.env`)

Voir `.env.example` pour la liste complète. Les principales :

- `DISCORD_TOKEN` — token du bot (requis).
- `DISCORD_GUILD_ID` — guilde pour la sync instantanée des commandes (vide =
  global ; les anciennes copies de guilde sont nettoyées pour éviter les doublons).
- `ADMIN_IDS` — IDs des admins, séparés par des virgules.
- `RAID_NAMES` — raids possibles.
- `RAID_CAPS` — places max par raid (ex. `Gigalodon:12`).
- `RAID_POLL_CLOSE_HOUR` — heure de clôture auto des sondages, le jour du raid
  (12 = midi par défaut).
- `REMINDER_MINUTES` — minutes avant le raid pour le rappel (10 par défaut).
- `RAIDS_CHANNEL_ID` — salon des sondages (surchargeable par `/setchannel`).
- `TICKET_CATEGORY_ID` — catégorie des tickets.

## Lancement

Docker, depuis le dossier parent `server/bot` :

```bash
docker compose up -d --build beb-raid
docker compose logs --tail=100 beb-raid
```

Local :

```bash
cp .env.example .env   # renseigner DISCORD_TOKEN + ADMIN_IDS
pip install -r requirements.txt
python main.py
```

Tests :

```bash
pytest -q
```
