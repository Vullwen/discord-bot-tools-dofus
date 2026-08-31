# Dofus Raid Bot

Dofus Raid Bot est un bot Discord pour organiser des raids Dofus sur un serveur
de guilde.

Il sert surtout à éviter les tableaux bricolés à la main : on crée un raid, les
gens votent pour l'heure, le bot inscrit les participants, envoie les rappels,
garde une trace des absences et range les messages quand le raid est passé.

Le projet tourne en Python 3.12 avec discord.py, SQLite et Docker.

## Ce que le bot gère

- Création de raids avec choix du raid, vote d'heure ou horaire fixé directement.
- Inscriptions, désinscriptions, liste d'attente et limite de places par raid.
- Rappels avant le raid, en MP et dans le salon.
- Warns et bans raid pour les personnes qui s'inscrivent puis ne viennent pas.
- Absences, kick AFK et remise du rôle de base.
- Vérification Dofus par screenshot.
- Forum marché avec prix, clôture et archivage.
- Menus de rôles persistants.
- Cartes de stuff à partir des liens Dofusbook.

## Cycle d'un raid

La commande de départ est `/raid start`.

- Avec une heure dans la date, par exemple `vendredi 21h`, le raid est planifié
  directement.
- Avec un raid mais sans heure, le bot propose les créneaux à mettre au vote.
- Sans raid précis, les membres votent d'abord pour le raid, puis pour l'heure.

Ensuite, le bot ferme les sondages le jour du raid, à midi par défaut. Les
votants du créneau gagnant sont inscrits automatiquement. Quand le raid est plein,
les nouveaux inscrits passent en liste d'attente, et le premier en attente est
promu si quelqu'un se désinscrit.

Les joueurs choisissent aussi leur palier `199-` ou `200+`, parce que certains
raids limitent les places ouvertes aux personnages 199-.

## Commandes utiles

### Général

- `/help` : affiche l'aide dans Discord.
- `/ping` : vérifie que le bot répond.

### Raids

- `/raid start date [raid] [cloture] [note]` : crée un raid.
- `/raid list` : affiche les raids actifs.
- `/raid cancel raid_id` : annule un raid.
- `/raid close raid_id` : ferme le sondage en cours tout de suite.
- `/raid warn user [raison]` : note un avertissement raid dans le salon admin raids,
  affiche son nombre total de warns, sans envoyer de MP au membre.
- `/raid warns [user]` : affiche le récap des warns raid, ou le détail d'un membre.
- `/raid ban user jours [raison]` : bloque temporairement les votes et inscriptions.
- `/raid unban user` : retire le ban raid d'un membre.
- `/raid bans` : liste les bans raid actifs.

Sur les messages de raid, les boutons permettent de voter, s'inscrire, se
désinscrire et voir les participants. Le bouton **Admin** ouvre un panneau
éphémère pour clôturer/annuler, retirer quelqu'un, enlever des places
disponibles et bloquer le raid aux niveaux 200+.

### Configuration

Tout passe par `/config`, pour éviter les anciennes commandes éparpillées.

- `/config channel usage channel` : configure un salon ou forum.
- `/config role usage [role]` : configure un rôle, ou le désactive si aucun rôle
  n'est donné.
- `/config guild nom` : règle uniquement le nom de guilde Dofus attendu dans les
  screenshots.
- `/config dofus guilde serveur` : règle la guilde et le serveur attendus pour la
  vérification Dofus. Le serveur est optionnel si tu veux seulement changer la
  guilde.
- `/config show` : affiche la configuration du serveur.

Usages de `/config channel` :

- `raids`
- `raid_admin`
- `absence_panel`
- `absence`
- `absence_admin`
- `market_forum`

Usages de `/config role` :

- `bot_admin`
- `raid_manager`
- `raid_notify`
- `base`
- `verified_member`
- `unverified_member`

### Absences

- `/absence declare` : ouvre le formulaire d'absence.
- `/absence panel` : poste le bouton public de déclaration.
- `/absence search [member]` : cherche les absences actives ou à venir, affiche
  leur ID et le décompte jusqu'au retour prévu. Si un membre est filtré, affiche
  aussi sa dernière absence passée avec le délai depuis le retour prévu sous la
  forme `Jours d'inactivité non déclarée depuis la date de retour : XX`.
- `/absence add member debut fin [motif]` : ajoute une absence pour quelqu'un.
- `/absence stop member [absence_id]` : stoppe une absence. Si plusieurs absences
  existent pour le membre, l'ID est obligatoire.
- `/absence kick user` : prévient qu'un membre est kick AFK, envoie le MP et remet
  le rôle de base configuré.

Les motifs restent dans le salon admin absences. Le message public ne montre que
le pseudo et les dates.

### Vérification Dofus

- `/mychars` : liste tes personnages vérifiés.
- `/chars membre` : liste les personnages vérifiés d'un membre.
- `/find personnage` : retrouve le compte Discord lié à un personnage.

Quand le screenshot contient le bon code, le bon serveur, la bonne guilde et le
message en chat guilde, le bot valide automatiquement. Sinon, les organisateurs
peuvent valider ou refuser dans le salon privé.

### Accueil Discord

Poste le règlement et son bouton d'acceptation avec `/ticket reglement`. Sans
option `texte`, le bot publie un embed structuré avec le nom du serveur Discord
en titre/header, l'icône du serveur en image, et une section par règle.
Quand un nouveau membre clique sur `J'accepte le règlement`, le bot ouvre un salon
privé avec deux choix : rejoindre la guilde ou demander seulement l'accès au
marché.
Un membre qui a déjà le rôle `guild_member`, `verified_member` ou `visitor` ne
peut pas rouvrir un ticket avec ce bouton.

Si tu veux garder un texte custom dans la commande, écris `\n` là où tu veux
forcer un retour ligne.

- choix guilde : le bot demande la présentation, puis les admins bot peuvent
  accepter ou refuser avec les boutons du ticket.
- choix marché : les admins bot doivent aussi accepter ou refuser la demande
  avant attribution du rôle visiteur.
- tant qu'une demande n'est pas acceptée/refusée, le membre peut changer entre
  guilde et marché. Les admins bot peuvent aussi rediriger le ticket vers guilde
  ou marché avec les boutons dédiés.
- accepter une candidature guilde : donne le rôle `guild_member` configuré, ou `verified_member` en
  repli si `guild_member` n'est pas défini.
- accepter une demande marché : donne le rôle `visitor`.
- refuser : kick le membre du serveur.

Les tickets d'accueil restent ouverts après une décision. Un admin bot les ferme
avec le bouton `Clôturer le ticket`.
Une ancienne demande déjà traitée ne bloque pas une nouvelle ouverture de ticket
si la personne quitte puis revient sans rôle d'accueil.
Seuls les admins bot (`bot_admin`, owner, admin Discord ou `ADMIN_IDS`) gèrent
le panneau règlement et les demandes d'accueil ; le rôle `raid_manager` reste
réservé aux raids.

### Autres modules

- `/stuff refresh` : régénère le dernier stuff Dofusbook trouvé dans le salon.
- `/event nom preset` : ouvre un formulaire de configuration, puis crée un
  event avec clôture d'inscriptions, compteur d'inscrits, rôle `event_<id>` et
  salon privé.
- `/event_submissions event_id` : publie les dépôts anonymes d'un concours de
  skin pour ouvrir le vote des admins event.
  Le salon event contient aussi un panneau admin pour fermer les inscriptions,
  bannir un membre de l'event ou annuler l'event.
- `/rolemenu ...` : crée et maintient les panneaux de rôles.
- `/sync` : resynchronise les commandes Discord.
- `/reload cog` : recharge un cog à chaud.
- `/health` : affiche l'état technique du bot (latence Discord, uptime, DB,
  migrations, raids actifs).

Le forum marché n'a pas besoin de commande au quotidien : les boutons apparaissent
sur les posts du forum configuré.

## Rôles

- `raid_manager` : rôle organisateur. Il peut créer et gérer les raids, configurer
  le bot, fermer les sondages, annuler et gérer les tickets.
- `raid_notify` : rôle mentionné à l'annonce d'un nouveau raid.
- `base` : rôle remis après `/absence kick`.
- `verified_member` : rôle donné après une vérification Dofus validée.
- `unverified_member` : rôle retiré après une vérification validée.
- `guild_member` : rôle donné après acceptation d'une candidature guilde.
- `visitor` : rôle donné pour l'accès visiteur au marché.
- `bot_admin` : rôle qui donne les droits admin du bot.
- `event_<id>` : rôle créé automatiquement pour accéder au salon privé d'un
  event.
- `admin_event` : rôle créé automatiquement pour voter sur les participations
  anonymes des concours de skin.

Si aucun rôle organisateur n'est configuré, les membres avec la permission
Administrateur Discord gardent la main.

## Configuration `.env`

Les valeurs complètes sont dans `.env.example`. Les plus importantes :

- `DISCORD_TOKEN` : token du bot.
- `DISCORD_GUILD_ID` : serveur utilisé pour une sync rapide des commandes. Vide =
  sync globale.
- `ADMIN_IDS` : IDs Discord des admins, séparés par des virgules.
- `BOT_NAME` : nom affiché côté bot. Par défaut : `Dofus Raid Bot`.
- `RAID_NAMES` : raids proposés dans les menus.
- `RAID_CAPS` : nombre de places par raid, par exemple `Gigalodon:12`.
- `RAID_LOW_LEVEL_CAPS` : places réservées aux personnages 199-.
- `RAID_HOURS` : créneaux proposés par défaut.
- `RAID_DEFAULT_HOUR` : heure utilisée si personne ne vote.
- `RAID_POLL_CLOSE_HOUR` : heure de fermeture auto des sondages.
- `REMINDER_MINUTES` : délai du rappel avant le raid.
- `REMINDER_DELETE_HOURS` : délai avant suppression des messages de rappel/raid.
- `MARKET_FORUM_CHANNEL_ID` : forum marché de secours, si `/config channel` n'est
  pas encore renseigné.
- `DOFUS_GUILD_NAME` et `DOFUS_SERVER` : valeurs attendues pour la vérification.
- `DB_PATH` : chemin SQLite.

La lecture automatique des screenshots demande l'intent Discord **Message
Content** dans le Developer Portal.

## Lancer le bot

En production, depuis le compose des bots (`~/server/bot`) :

```bash
cd ~/server/bot
docker compose up -d --build beb-raid
docker compose ps
docker compose logs --tail=100 beb-raid
```

En local :

```bash
cp .env.example .env
pip install -r requirements.txt
python main.py
```

## Tests

```bash
pytest -q
ruff check .
```

Avec le venv du serveur :

```bash
.venv/bin/python -m pytest
```

Dans Docker :

```bash
docker compose run --rm --no-deps --entrypoint pytest beb-raid -q
```

Une CI GitHub Actions lance `ruff check .` et `pytest -q` sur `dev` et les pull
requests vers `dev`.
