# CODEMAP — Carte du code beb_raid

> But : en lisant ce fichier, retrouver **n'importe quel fichier / fonction / bout de logique**
> du bot sans fouiller. Pour chaque fichier : son rôle + la liste de ses fonctions/classes
> avec une ligne d'explication.
>
> Légende : `📦 fichier` → `class/def` — *à quoi ça sert*.

---

## 1. Vue d'ensemble

Bot Discord (discord.py, slash commands, cogs) pour organiser des **raids Dofus**
(Gigalodon, Jardins Éternels). Flux type :

1. `/raid` (ou ticket) → crée un raid.
2. **Sondage choix du raid** (si nom non fourni) → boutons.
3. **Sondage de l'heure** → boutons (les votants du créneau gagnant sont inscrits).
4. **Heure décidée** → message de planification + bouton « Je participe ».
5. **Rappel MP** X min avant → puis raid marqué **terminé**.

Tout est persisté en **SQLite** (`data/beb_raid.db`) et replanifié au redémarrage
(tâches `asyncio` one-shot reconstruites depuis la base → robuste aux reboot).

### Cycle de vie / états d'un raid (définis dans `utils/poll.py`)
| État | Constante | Sens |
|------|-----------|------|
| `choosing_raid` | `STATE_CHOOSING_RAID` | Sondage « quel raid » en cours |
| `voting_hour` | `STATE_VOTING_HOUR` | Sondage de l'heure en cours |
| `breaking_hour_tie` | `STATE_BREAKING_HOUR_TIE` | Égalité sur l'heure, attente du créateur |
| `scheduled` | `STATE_SCHEDULED` | Heure fixée, en attente du rappel |
| `reminded` | `STATE_REMINDED` | Rappel envoyé, en attente de fin |
| `done` | `STATE_DONE` | Raid passé (terminal) |
| `cancelled` | `STATE_CANCELLED` | Annulé (terminal) |

### Arborescence
```
beb_raid/
├── main.py              # Entry point : bot, logging, sync, load cogs
├── config.py            # Variables d'env + constantes (heures, raids, caps, tz)
├── db.py                # Persistance SQLite synchrone
├── docker-compose.yml   # Compose standalone (le prod utilise ../docker-compose.yml)
├── Dockerfile
├── requirements.txt
├── cogs/                # Modules Discord (1 responsabilité chacun)
│   ├── core.py          #   /ping
│   ├── admin.py         #   /sync /reload
│   ├── settings.py      #   /setchannel /showconfig
│   ├── raid.py          #   ★ cœur métier : sondages, planif, rappels
│   └── ticket.py        #   tickets privés pour organiser un raid
├── utils/               # Logique pure (testable sans Discord)
│   ├── dates.py         #   parsing de dates/heures (Paris)
│   ├── poll.py          #   états, dépouillement, formatage
│   ├── embeds.py        #   builders d'embeds Discord
│   └── perms.py         #   permissions : rôle organisateur (raid/ticket)
├── data/                # SQLite (monté en volume, gitignoré)
└── tests/               # pytest
```

---

## 2. `main.py` — Entry point

Configure logging (horodaté Europe/Paris), crée le `Bot` (intents défaut, pas de
préfixe), charge les cogs, sync les slash commands.

- `_no_prefix(_bot, _message)` — préfixe vide (bot 100% slash commands).
- `sync_commands()` — sync slash commands : guilde ciblée si `DISCORD_GUILD_ID`, sinon global + nettoyage des copies de guilde.
- `on_ready()` — log + `sync_commands()` + activité « watching les raids ».
- `on_app_command_error(interaction, error)` — handler centralisé : log + message user-friendly éphémère.
- `main()` — vérifie `DISCORD_TOKEN`, charge `COGS = [core, admin, settings, raid, ticket]`, démarre.
- Liste **`COGS`** = ordre de chargement des cogs.

---

## 3. `config.py` — Configuration (env + constantes)

Charge `.env` (python-dotenv). **Toutes les constantes tunables sont ici.**

Constantes globales : `DISCORD_TOKEN`, `DISCORD_GUILD_ID`, `BOT_NAME`, `LOG_LEVEL`,
`ADMIN_IDS` (set d'IDs), `PARIS` (ZoneInfo Europe/Paris), `DB_PATH`,
`RAIDS_CHANNEL_ID`, `TICKET_CATEGORY_ID`.

- `_parse_channel_id(raw)` — str → int (0 si invalide).
- `_parse_hours(raw)` — "14,15,16" → `[14,15,16]` (filtre 0-23).
- `RAID_HOURS` — créneaux du sondage heure (défaut `14..23`).
- `RAID_DEFAULT_HOUR` — heure si 0 vote (défaut 21).
- `RAID_POLL_CLOSE_HOUR` — heure de clôture auto des sondages le jour du raid (défaut 12).
- `REMINDER_MINUTES` — minutes avant le raid pour le rappel MP (défaut 10).
- `RAID_NAMES` — noms possibles (défaut `Gigalodon, Jardins Éternels`).
- `_parse_caps(raw)` — "Gigalodon:12" → dict.
- `RAID_CAPS` — caps par raid (`_DEFAULT_CAPS` ⊕ env) → `{Gigalodon:12, Jardins Éternels:16}`.
- `raid_cap(name)` — renvoie la cap d'un raid (`None` si inconnu/sans nom).
- `now_paris()` — `datetime.now(PARIS)` (maintenant aware).

---

## 4. `db.py` — Persistance SQLite (synchrone)

Connexion globale, `row_factory=Row`, `CREATE TABLE IF NOT EXISTS`, WAL, FK ON.
Datetimes stockés en **ISO aware**, dates en `YYYY-MM-DD`.

**Tables :** `raids`, `votes`, `participants`, `tickets`, `guild_settings`.

> Schéma `raids` : `id, name, date, poll_duration_seconds, poll_close_hour, created_by, guild_id,
> channel_id, state, raid_poll_message_id, hour_poll_message_id,
> scheduled_message_id, scheduled_at, raid_poll_closes_at, hour_poll_closes_at,
> note, fixed_hour, created_at`.

### Connexion / migration
- `init(db_path=DB_PATH)` — crée les tables + migrations, commit.
- `_migrate(ddl)` — applique un `ALTER TABLE` (idempotent, ignore si colonne existe). → ajoute `fixed_hour`.
- `_db()` — renvoie la connexion (auto-`init` si None).
- `_now_iso()` / `_dt(value)` — helpers ISO ↔ datetime.

### Raids
- `create_raid(*, name, date_iso, poll_duration_seconds=0, poll_close_hour=None, created_by, guild_id, channel_id, state, raid_poll_closes_at=None, hour_poll_closes_at=None, scheduled_at=None, note=None, fixed_time=None, poll_hours=None)` — INSERT, renvoie `raid_id`.
- `get_raid(raid_id)` — une ligne.
- `list_active_raids()` — états non terminaux, tri par id.
- `list_all_raids(limit=50)` — tous, récents d'abord.
- `update_raid(raid_id, **fields)` — UPDATE générique (sérialise les datetime).
- `set_raid_state(raid_id, state)` — raccourci `update_raid(state=…)`.

### Votes (`kind` ∈ `"raid"` | `"hour"`)
- `cast_vote(raid_id, user_id, kind, choice)` — vote **changeable** (1 choix par user/kind).
- `get_vote_counts(raid_id, kind)` — `{choice: nb}`.
- `get_voters(raid_id, kind, choice)` — liste d'IDs ayant voté ce choix.

### Participants
- `add_participant(raid_id, user_id)` — INSERT OR IGNORE.
- `get_participants(raid_id)` — liste d'IDs.
- `count_participants(raid_id)` — compteur.
- `is_participant(raid_id, user_id)` — booléen.

### Tickets
- `create_ticket(*, channel_id, guild_id, opener_id)` — INSERT.
- `get_ticket_by_channel(channel_id)` — une ligne.
- `close_ticket(channel_id)` — marque `closed=1`.

### Settings (par guilde)
- Constantes clés : `SETTING_RAIDS_CHANNEL = "raids_channel"`, `SETTING_TICKET_CATEGORY = "ticket_category"`.
- `set_guild_setting(guild_id, key, value)` — INSERT OR REPLACE.
- `get_guild_setting(guild_id, key)` — valeur str ou None.
- `get_guild_setting_int(guild_id, key)` — valeur int ou None.

### Tests
- `reset_for_tests(db_path)` — ferme + rouvre sur une BDD de test.

---

## 5. `utils/dates.py` — Parsing dates & heures (Paris, sans Discord)

- `InvalidRaidDate(ValueError)` — levée si date invalide/passée.
- `_HOUR_RE` — regex d'heure (`15h`, `21h30`, `9:05`…), group(1) = heure.
- `parse_hour(text)` — extrait une heure 0-23 (`None` si absente/hors plage).
- `strip_hour(text)` — retire l'heure d'un texte (`"demain 15h"` → `"demain"`).
- `parse_raid_date(text, now=None)` — texte → `date`. Accepte ISO, `DD/MM`, `DD-MM`,
  mots relatifs (`aujourd'hui`, `demain`, `après-demain`), jours FR. Heure éventuelle
  ignorée ici (extraite via `parse_hour`). Lève si passé.
- `combine_date_hour(day, hour)` — `date` + heure → datetime aware Paris.
- `format_date_fr(day)` — `"mercredi 25/06"`.
- `format_dt_fr(dt)` — `"mercredi 25/06 à 21h00"`.
- `countdown_fr(closes_at, now=None)` — `"dans 2h"`, `"dans 35 min"`, `"clôturé"`.

---

## 6. `utils/poll.py` — Logique métier pure (sans Discord ni DB)

- Constantes d'état : `STATE_*` (voir tableau §1), `ACTIVE_STATES`, `TERMINAL_STATES`.
- `is_active(state)` — booléen.
- `tally(counts, order, default)` — **gagnant** : majorité simple, puis 1er de `order` en cas d'égalité, puis `default` si aucun vote.
- `tied_leaders(counts, order)` — choix ex-aequo en tête, vide si aucun vote positif.
- `reminder_time(scheduled_at, minutes)` — `scheduled_at - minutes`.
- `format_counts(counts, order, suffix="")` — rendu texte des résultats (`"14h: 2 | 15h: 0"`), gras les leaders.

---

## 7. `utils/embeds.py` — Builders d'embeds (formatage pur)

Couleurs : `GREEN, GOLD, BLUE, RED, GREY`. `_HOUR_ORDER` = heures en str.

- `_parse_day(raid)` / `_scheduled_dt(raid)` — extraient date/datetime d'une ligne raid.
- `_format_spots(participants, cap)` — `"X/cap"` + `🟥 COMPLET` si plein.
- `raid_choice_embed(raid, counts, creator)` — sondage « quel raid ».
- `raid_choice_result_embed(raid, winner, counts)` — résultat choix du raid (gris).
- `hour_poll_embed(raid, counts, creator, participants)` — sondage de l'heure.
- `hour_poll_result_embed(raid, winner_hour, counts)` — résultat heure (gris).
- `scheduled_embed(raid, participants, creator)` — raid planifié (+ bouton Je participe).
- `reminder_dm_embed(raid)` — rappel en MP.
- `reminder_channel_embed(raid, participants)` — rappel dans le salon.
- `cancelled_embed(raid)` — raid annulé.
- `participants_embed(raid, names)` — liste des participants (bouton 👥).
- `list_embed(rows)` — embed `/list_raids`.

---

## 8. `cogs/raid.py` — ★ Cœur métier (le gros fichier)

Sondages à boutons, planification `asyncio`, rappels MP, replanif au reboot.

### Helpers module
- `_slugify(name)` — nom → slug ASCII (pour les `custom_id`).
- `_parse_when(value)` — valeur BDD (ISO/datetime/None) → datetime aware (fallback `now` si None).
- `_HOUR_ORDER`, `_RAID_SLUGS` — lookups précalculés.
- `POLL_CLOSE_HOUR_CHOICES` — heures de clôture proposées au slash (`auto`, 00h..23h).

### Boutons (custom_id entre parenthèses)
- `_HourVoteButton` (`bebraid:hour:{raid_id}:{hour}`) → `handle_hour_vote`.
- `_AllHoursButton` (`bebraid:allhours:{raid_id}`) → `handle_all_hour_votes`.
- `_ClearHourVotesButton` (`bebraid:clearhours:{raid_id}`) → `handle_clear_hour_votes`.
- `_RaidChoiceButton` (`bebraid:raid:{raid_id}:{slug}`) → `handle_raid_vote`.
- `_RegisterButton` (`bebraid:reg:{raid_id}`) → `handle_register`.
- `_ClosePollButton` (`bebraid:close:{raid_id}`) → `handle_close_poll`.
- `_ParticipantsButton` (`bebraid:participants:{raid_id}`) → `handle_view_participants`.

### Vues (regroupent les boutons ; `timeout=None` = persistantes)
- `HourPollView` — boutons heures (ceux **passés sont désactivés** si raid aujourd'hui) + Dispo toutes les heures + Annuler mes heures + Clôturer si place + Annuler.
- `RaidChoiceView` — boutons raids + Clôturer + Participants.
- `ScheduledRaidView` — Je participe + Participants.

### Classe `RaidCog`
**Cycle de vie du cog**
- `__init__` — `self._tasks` {(raid_id, kind): Task}, `_bootstrap_task`.
- `cog_load()` — `db.init()` + lance `_bootstrap`.
- `_bootstrap()` — `wait_until_ready` → `_reschedule_all`.
- `cog_unload()` — cancel toutes les tâches.

**Helpers**
- `_resolve_raids_channel(guild, fallback)` — salon raids : réglage DB → env → salon courant.
- `_creator_display(user_id)` — display name du créateur (fetch en fallback).
- `_get_channel(channel_id)` — salon (fetch en fallback).
- `_edit_message(channel_id, message_id, *, embed, view)` — édite un message stocké.

**Création**
- `create_raid(guild, channel, user, raid_name, date_text, note=None, poll_hours=None, poll_close_hour=None)` — **cœur partagé** (/raid + ticket).
  - Heure dans `date_text` + raid connu → **planification directe** (sans sondage).
  - Raid connu, pas d'heure → sondage heure (`voting_hour`).
  - Pas de raid → sondage choix (`choosing_raid`), puis heure (ou direct si `fixed_hour`).
- `_send_raid_choice(channel, raid_id)` / `_send_hour_poll(channel, raid_id)` / `_post_scheduled(raid_id)` — postent les 3 types de messages + stockent leur id.

**Handlers de boutons**
- `handle_raid_vote(interaction, raid_id, name)` — vote choix raid.
- `handle_hour_vote(interaction, raid_id, hour)` — vote heure ; **refuse les créneaux passés** (jour même).
- `handle_all_hour_votes(interaction, raid_id)` — vote tous les créneaux proposés encore valides.
- `handle_clear_hour_votes(interaction, raid_id)` — retire tous les votes d'heure de l'utilisateur.
- `_register_winning_hour_voters(raid_id, raid, winner_hour)` — inscrit les votants du créneau gagnant.
- `handle_hour_tie_break(interaction, raid_id, hour)` — bouton MP : le créateur départage une égalité.
- `handle_register(interaction, raid_id)` — inscription rappel MP ; cap.
- `handle_view_participants(interaction, raid_id)` — embed éphémère des participants.
- `handle_close_poll(interaction, raid_id)` — clôture manuelle (organisateur ou créateur).
- `_member_display_name(guild, uid)` — nom affichable d'un participant (membre guilde puis user global).

**Clôtures automatiques**
- `_close_raid_choice(raid_id)` — dépouille, fixe le raid. Si `fixed_hour` → planifie direct, sinon sondage heure.
- `_close_hour_poll(raid_id)` — dépouille l'heure ; en cas d'égalité, MP au créateur pour départage.
- `_finalize_hour_poll(raid_id, winner_hour, ...)` — planifie, poste scheduled, inscrit les votants gagnants, planifie rappel+fin.
- `_schedule_reminder(raid_id, scheduled_at)` — planifie `remind` + `done` (ou marque `done` si déjà passé).
- `_remind(raid_id)` — MP chaque participant + message salon → état `reminded`.
- `_mark_done(raid_id)` — état `done` (sauf si annulé).

**Planification `asyncio`**
- `_schedule(raid_id, kind, when, coro_fn)` — crée une tâche one-shot.
- `_run_scheduled(raid_id, kind, delay, coro_fn)` — `sleep(delay)` puis exécute (nettoie `_tasks`).
- `_cancel_tasks(raid_id)` — cancel raid_close/hour_close/remind/done.
- `_reschedule_all()` — au boot : `add_view` (routage clics) + replanif des tâches depuis la base.

**Slash commands**
- `/raid date raid? cloture? note?` — crée un raid ; `cloture` = heure le jour du raid (**organisateur** ; defer éphémère).
- `/list_raids` — embed des raids actifs.
- `/cancel_raid raid_id` — annule (créateur ou organisateur).
- `/force_close raid_id` — clôture immédiat (organisateur).

---

## 9. `cogs/ticket.py` — Tickets privés d'organisation

Salon privé (opener + organisateurs) pour discuter puis lancer `/raid`-like via modal.

- `_channel_name(name)` — pseudo → nom de salon `raid-pseudo`.
- `RaidCreateModal` (Modal) — champs Raid / Date → `on_submit` appelle `RaidCog.create_raid` en clôture auto.
- `_OpenTicketButton` (`bebraid:ticket_open`) → `open_ticket`.
- `_CreateFromTicketButton` (`bebraid:ticket_create`) → ouvre le modal.
- `_CloseTicketButton` (`bebraid:ticket_close`) → `close_ticket`.
- `_AddMemberButton` (`bebraid:ticket_add`) → `prompt_add_member`.
- `_AddMemberSelect` (UserSelect) → `add_members`.
- `AddMemberView` (timeout 300s), `TicketPanelView`, `TicketChannelView` — regroupent les composants.

### Classe `TicketCog`
- `cog_load()` — enregistre les vues persistantes (`add_view`).
- `/raid_panel` (admin) — poste le panneau « Ouvrir un ticket raid ».
- `_resolve_ticket_category(guild)` — catégorie : réglage DB → env → None.
- `open_ticket(interaction)` — crée le salon privé (overwrites) + entrée BDD (**organisateur**).
- `close_ticket(interaction)` — ferme + supprime le salon (organisateur ou opener).
- `_is_ticket_manager(interaction)` — opener ou organisateur ?
- `prompt_add_member(interaction)` / `add_members(interaction, users)` — ajoute des membres au salon.

---

## 10. Autres cogs

### `cogs/core.py` — `CoreCog`
- `/ping` — latence du bot (éphémère).

### `cogs/admin.py` — `AdminCog`
- `_is_admin(user_id)` — dans `ADMIN_IDS` ?
- `/sync` — resync slash commands (guilde ou global + nettoyage des copies de guilde).
- `/reload cog` — recharge un cog à chaud.

### `cogs/settings.py` — `SettingsCog`
- `/setchannel setting channel` — fixe salon raids **ou** catégorie tickets (admin). `setting` ∈ {raids_channel, ticket_category}.
- `/setraidrole role?` — fixe le **rôle organisateur** autorisé à créer/gérer les raids et tickets (admin). Vide = admins seulement.
- `/showconfig` — embed de la config de la guilde (salon, catégorie, rôle organisateur).

### Permissions (`utils/perms.py`)
Un **organisateur** = `ADMIN_IDS` (super-admins, en dur dans le `.env`) **OU** détenteur du rôle configuré par guilde (`SETTING_RAID_MANAGER_ROLE`, via `/setraidrole`). Si aucun rôle n'est configuré, seuls les `ADMIN_IDS` sont organisateurs.
- `is_raid_organizer(interaction)` — création de raid, `/force_close`.
- `can_manage_raid(interaction, raid)` — organisateur **ou créateur** du raid (clôture sondage, annulation, retrait de participants).
- `can_manage_ticket(interaction, ticket)` — organisateur **ou opener** du ticket (fermer, ajouter des membres).

> **Total : 11 slash commands** (core×1, admin×2, settings×3, raid×4, ticket×1).

---

## 11. Variables d'environnement (`.env`)

| Variable | Défaut | Rôle |
|----------|--------|------|
| `DISCORD_TOKEN` | — | Token du bot (requis) |
| `DISCORD_GUILD_ID` | — | Sync instantanée sur cette guilde (vide = global) |
| `BOT_NAME` | `Beb Raid` | Nom |
| `LOG_LEVEL` | `INFO` | Niveau de log |
| `ADMIN_IDS` | — | IDs séparés par virgule |
| `RAID_HOURS` | `14..23` | Créneaux du sondage heure |
| `RAID_DEFAULT_HOUR` | `21` | Heure si 0 vote |
| `RAID_POLL_CLOSE_HOUR` | `12` | Heure de clôture auto des sondages le jour du raid |
| `REMINDER_MINUTES` | `10` | Rappel MP X min avant |
| `RAID_NAMES` | `Gigalodon,Jardins Éternels` | Raids possibles |
| `RAID_CAPS` | `Gigalodon:12,Jardins Éternels:16` | Caps par raid |
| `RAIDS_CHANNEL_ID` | — | Salon des raids (vide = salon courant) |
| `TICKET_CATEGORY_ID` | — | Catégorie des tickets |
| `DB_PATH` | `/app/data/beb_raid.db` | Chemin SQLite |

---

## 12. Déploiement & tests

### Docker
- **Prod** : service `beb-raid` dans `../docker-compose.yml` (projet `bot`), `build: ./beb_raid`,
  volume `./beb_raid/data:/app/data`. → `docker compose up -d --build beb-raid` depuis `../`.
- **Standalone** : `./docker-compose.yml` local (projet `beb_raid`).
- Seul `data/` est monté : **tout changement de code nécessite un rebuild**.
- `Dockerfile` : `python:3.12-slim`, `pip install requirements.txt`, `python main.py`.

### Tests (`pytest`)
- `tests/test_dates.py` — parsing dates/heures (`parse_hour`, `strip_hour`, `parse_raid_date`…).
- `tests/test_db.py` — CRUD raids/votes/participants/tickets, (dé)sérialisation datetime.
- `tests/test_tally.py` — `tally`, `format_counts`, états.
- `tests/test_raid_duration.py` — calcul de l'heure de clôture des sondages.
- `tests/test_config.py` — caps par défaut / `raid_cap`.
- `tests/test_imports.py` — import de tous les modules (nécessite `discord` installé).

```bash
pytest                      # tout
pytest tests/test_dates.py  # ciblé
```
> Les tests `test_imports` échouent sur l'hôte si `discord.py` n'est pas installé
> (normal : la lib n'est que dans le conteneur).

---

## 13. Où chercher quand…

| Je veux… | Aller à |
|----------|---------|
| Modifier un embed | `utils/embeds.py` |
| Ajouter un créneau / raid / cap | `config.py` (`RAID_HOURS`, `RAID_NAMES`, `RAID_CAPS`) |
| Changer la logique de vote / dépouillement | `utils/poll.py` + handlers `cogs/raid.py` |
| Comprendre le parsing d'une date/heure | `utils/dates.py` (`parse_raid_date`, `parse_hour`) |
| Modifier le schéma BDD | `db.py` (`init` + `_migrate`) |
| Ajouter un bouton | `cogs/raid.py` ou `cogs/ticket.py` (classe `_*Button` + vue + handler) |
| Changer le moment du rappel | `config.py` (`REMINDER_MINUTES`) + `_schedule_reminder` |
| Debug replanif au reboot | `RaidCog._reschedule_all` / `_parse_when` |
| Routage d'un clic (custom_id) | préfixe `bebraid:` dans `cogs/raid.py` / `cogs/ticket.py` |
