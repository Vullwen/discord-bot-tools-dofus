# Discord bot Raids Dofus

Bot Discord pour organiser des raids Dofus (Gigalodon, Jardins Éternels). On crée
un raid pour une date, les votants choisissent l'heure (et le raid si besoin), un
rappel part avant, puis les messages du raid se nettoient tout seuls après le raid.

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
- Les votants choisissent leur palier (**199-** ou **200+**) avant de voter ou de
  s'inscrire. Les places 199- sont limitées par raid.
- Dans un sondage d'heure, les votants du créneau gagnant sont inscrits
  automatiquement. Le bouton **Dispo toutes les heures** permet de voter tous les
  créneaux proposés d'un coup, et **Annuler mes heures** retire tous tes votes.
- Une fois l'heure fixée, les participants peuvent s'inscrire, se désinscrire,
  voir la liste des participants et rejoindre la liste d'attente si le raid est plein.
- En cas d'égalité sur l'heure, le créateur reçoit un MP pour départager.
- Un rappel part en MP aux confirmés quelques minutes avant l'heure prévue, avec
  un rappel dans le salon.
- Les messages de rappel et de raid sont supprimés automatiquement après le délai
  configuré.

Le nombre de places par raid est limité (`RAID_CAPS`). Une fois complet, les
nouvelles inscriptions passent en liste d'attente. Si un confirmé se désinscrit,
le premier joueur en attente est promu automatiquement et reçoit un MP.

## Commandes

Général :

- `/help` — affiche l'aide du bot (admin).
- `/ping` — vérifie que le bot répond.

Raids :

- `/raid date [raid] [cloture] [note]` — crée un raid. `cloture` choisit
  l'heure de fermeture le jour du raid (ex. `12h` = midi le jour du raid).
- `/list_raids` — raids actifs.
- `/ban_raid user jours [raison]` — interdit temporairement à un membre de voter
  ou de s'inscrire aux raids, avec notification dans le salon admin raids configuré.
- `/unban_raid user` — retire le ban raid d'un membre.
- `/show_bans` — liste les bans raid actifs.
- `/cancel_raid raid_id` — annule un raid (créateur ou organisateur).
- `/force_close raid_id` — clôture tout de suite le sondage en cours.

Sur chaque message de raid, les boutons permettent de voter, s'inscrire, se
désinscrire, voir les participants, retirer un participant (admin/créateur) et
annuler le raid avec confirmation.

Absences :

- `/absence declare` — ouvre le formulaire de déclaration d'absence.
- `/absence panel` — poste le bouton de déclaration dans le salon panel absences configuré.
- `/absence search [member]` — liste les absences actives ou à venir, sans afficher les motifs.
- `/absence add member debut fin [motif]` — ajoute une absence pour un membre.
- `/absence stop member [absence_id]` — stoppe une absence active ou à venir.
- `/absence kick user` — prévient dans le salon absence et en MP qu'un membre a été
  kick de la guilde pour AFK, retire ses rôles et remet le rôle de base configuré.

Le panel et les messages d'absence utilisent deux salons différents : le bouton
est posté dans le salon panel absences, puis les absences déclarées publient un
embed public avec pseudo + dates dans le salon absence. Le motif, s'il est
renseigné, part uniquement dans le salon admin absences. Le message public est
supprimé automatiquement à minuit après la date de fin ; le message admin est
conservé.

Tickets :

- Les anciens salons privés de ticket peuvent encore utiliser les boutons
  persistants **Créer ce raid**, **Ajouter un membre** et **Fermer**.
- Le créateur du ticket et les organisateurs peuvent ajouter des membres ou fermer
  le salon.

Vérification Dofus :

- `/link personnage` — crée un salon privé avec le membre, le bot et les
  organisateurs. Le bot donne un code à recopier en chat guilde après `/whoami`
  et `/time`, puis analyse le screenshot.
- `/mychars` — liste tes personnages Dofus vérifiés.
- `/chars membre` — liste les personnages Dofus vérifiés d'un compte Discord.
- `/find personnage` — retrouve le Discord lié à un personnage.
- Si l'analyse reconnaît le code, le pseudo, le serveur, la guilde et le message en
  chat guilde, le bot valide automatiquement. Sinon les organisateurs ont des
  boutons **Valider** / **Refuser** dans le salon privé.
- Après validation, le bot ajoute le rôle membre vérifié, retire le rôle à vérifier
  si configuré, et renomme le membre Discord avec le pseudo de son personnage main.

Configuration (organisateur) :

- `/setchannel` — salons des raids, de l'admin raids, des absences et des motifs admin.
- `/setraidrole` — rôle autorisé à créer et gérer les raids : ID, mention copiée
  ou nom exact (vide = permission Administrateur Discord).
- `/setraidnotifyrole` — rôle mentionné à chaque nouveau raid : ID, mention copiée
  ou nom exact (vide = pas de mention).
- `/setmemberrole` — rôle donné automatiquement après une vérification Dofus réussie.
- `/setunverifiedrole` — rôle "à vérifier" retiré automatiquement après une vérification réussie.
- `/setdofusconfig` — nom de guilde et serveur attendus dans les screenshots `/link`.
- `/showconfig` — affiche la config du serveur.

## Rôles

- **Organisateur** (défini par `/setraidrole`) : crée et gère les raids,
  configure le bot, clôture les sondages, annule, gère les participants et les
  tickets. Si aucun rôle n'est défini, les membres avec la permission
  Administrateur Discord sont organisateurs.
- **Notif raids** (défini par `/setraidnotifyrole`) : mentionné quand un raid est
  annoncé. L'attribution aux membres est manuelle (côté Discord).
- **Créateur du raid** : peut gérer son raid même sans rôle organisateur.
- **Opener du ticket** : peut gérer son ticket même sans rôle organisateur.

## Variables d'environnement (`.env`)

Voir `.env.example` pour la liste complète. Les principales :

- `DISCORD_TOKEN` — token du bot (requis).
- `DISCORD_GUILD_ID` — guilde pour la sync instantanée des commandes (vide =
  global ; les anciennes copies de guilde sont nettoyées pour éviter les doublons).
- `ADMIN_IDS` — IDs des admins, séparés par des virgules.
- `RAID_NAMES` — raids possibles.
- `RAID_CAPS` — places max par raid (ex. `Gigalodon:12`).
- `RAID_LOW_LEVEL_CAPS` — places réservées aux personnages 199- par raid
  (ex. `Gigalodon:2,Jardins Éternels:0`).
- `RAID_HOURS` — créneaux proposés par défaut dans le sondage d'heure.
- `RAID_DEFAULT_HOUR` — heure choisie si aucun vote n'est exprimé.
- `RAID_POLL_CLOSE_HOUR` — heure de clôture auto des sondages, le jour du raid
  (12 = midi par défaut).
- `REMINDER_MINUTES` — minutes avant le raid pour le rappel (10 par défaut).
- `REMINDER_DELETE_HOURS` — délai de suppression des messages de rappel/raid
  après publication ou heure prévue (2 par défaut).
- `DOFUS_GUILD_NAME` — guilde Dofus attendue par défaut pour `/link`
  (`Bagarres et Belettes` par défaut, surchargeable par `/setdofusconfig`).
- `DOFUS_SERVER` — serveur Dofus par défaut (`Dakal` par défaut, surchargeable par
  `/setdofusconfig`).
- `VERIFICATION_CODE_PREFIX` — préfixe des codes de vérification (`BEB` par défaut).
- `VERIFICATION_EXPIRES_MINUTES` — durée de validité d'un code `/link` (15 par défaut).
- `RAIDS_CHANNEL_ID` — salon des sondages (surchargeable par `/setchannel`).
- `DB_PATH` — chemin SQLite (par défaut `/app/data/beb_raid.db` en Docker).

La lecture automatique des screenshots nécessite l'intent Discord **Message
Content** activé pour le bot dans le Developer Portal.

## Lancement

Docker en production, depuis le dossier parent `server/bot` :

```bash
docker compose up -d --build beb-raid
docker compose ps beb-raid
docker compose logs --tail=100 beb-raid
```

Le fichier `docker-compose.yml` présent dans ce dossier peut construire l'image,
mais le conteneur de production `beb-raid` est géré par le Compose parent. Utilise
donc le dossier parent pour redémarrer le service existant.

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

Tests dans l'image Docker :

```bash
cd /home/vullwen/server/bot
docker compose run --rm --no-deps --entrypoint pytest beb-raid -q
```

Contrôles utiles :

```bash
python -m compileall -q .
ruff check .
```

Le projet n'a pas encore de configuration `mypy` officielle.
