# Nomenclature des commandes

Ce fichier sert de reference pour garder les slash commands lisibles.

## Regles de nommage

- Grouper par domaine quand un domaine a plusieurs actions : `raid`, `absence`,
  `rolemenu`, `stuff`, `config`, `admin`.
- Utiliser des verbes courts et stables : `start`, `list`, `show`, `add`,
  `edit`, `remove`, `refresh`, `export`, `import`, `copy`, `cancel`, `close`.
- Eviter les underscores dans les nouvelles commandes : preferer un groupe et un
  sous-nom clair.
- Garder les actions destructives explicites : `cancel`, `close`, `remove`,
  `kick`, `ban`.

## Commandes actuelles

### General

| Commande | Usage |
| --- | --- |
| `/help` | Affiche l'aide du bot. |
| `/ping` | Verifie la latence du bot. |

### Raids

| Commande | Usage |
| --- | --- |
| `/raid start date [raid] [cloture] [note]` | Cree un raid, directement ou via sondage. |
| `/raid list` | Liste les raids actifs. |
| `/raid cancel raid_id` | Annule un raid. |
| `/raid close raid_id` | Cloture le sondage d'un raid. |
| `/raid warn user [raison]` | Envoie un avertissement raid au membre et le journalise. |
| `/raid ban user jours [raison]` | Bloque temporairement les votes/inscriptions raid. |
| `/raid unban user` | Retire un ban raid. |
| `/raid bans` | Liste les bans raid actifs. |

### Absences

| Commande | Usage |
| --- | --- |
| `/absence declare` | Ouvre le formulaire utilisateur. |
| `/absence panel` | Poste le bouton public de declaration. |
| `/absence search [member]` | Recherche les absences actives ou a venir. |
| `/absence add member debut fin [motif]` | Ajoute une absence pour un membre. |
| `/absence stop member [absence_id]` | Stoppe une absence. |
| `/absence kick user` | Notifie un kick AFK et remet le role de base. |

### Stuff Dofusbook

| Commande | Usage |
| --- | --- |
| `/stuff refresh` | Regenere le dernier stuff Dofusbook recent du salon. |
| Lien Dofusbook poste | Genere automatiquement une image du stuff. |

### Verification Dofus

| Commande | Usage |
| --- | --- |
| `/mychars` | Liste ses personnages verifies. |
| `/chars membre` | Liste les personnages verifies d'un membre. |
| `/find personnage` | Retrouve le compte Discord lie a un personnage. |

### Configuration

| Commande | Usage |
| --- | --- |
| `/config channel usage channel` | Configure les salons et le forum marche. |
| `/config role usage [role]` | Configure les roles du bot. |
| `/config guild nom` | Configure le nom de guilde Dofus attendu. |
| `/config dofus guilde [serveur]` | Configure guilde et serveur Dofus attendus. |
| `/config show` | Affiche la configuration serveur. |

Valeurs `usage` de `/config channel` :

| Usage | Configure |
| --- | --- |
| `raids` | Salon des raids. |
| `raid_admin` | Salon admin raids. |
| `absence_panel` | Salon panel absences. |
| `absence` | Salon absence. |
| `absence_admin` | Salon admin absences. |
| `market_forum` | Forum marche. |

Valeurs `usage` de `/config role` :

| Usage | Configure |
| --- | --- |
| `bot_admin` | Role donnant les droits admin bot. |
| `raid_manager` | Role organisateur raid/ticket. |
| `raid_notify` | Role mentionne aux annonces raid. |
| `base` | Role remis avec `/absence kick`. |
| `verified_member` | Role donne apres verification. |
| `unverified_member` | Role retire apres verification. |

### Menus de roles

| Commande | Usage |
| --- | --- |
| `/rolemenu create` | Cree un panneau de roles. |
| `/rolemenu edit_embed` | Modifie titre, couleur, footer ou images. |
| `/rolemenu edit_description` | Modifie la description via formulaire multiline. |
| `/rolemenu add_button` | Ajoute un bouton de role. |
| `/rolemenu edit_button` | Modifie un bouton de role. |
| `/rolemenu add_select` | Ajoute un menu select. |
| `/rolemenu edit_select` | Modifie un menu select. |
| `/rolemenu add_option` | Ajoute une option de role dans un select. |
| `/rolemenu edit_option` | Modifie une option de select. |
| `/rolemenu move_option` | Deplace une option vers un autre select. |
| `/rolemenu remove_component` | Supprime un bouton ou un select. |
| `/rolemenu remove_option` | Supprime une option de select. |
| `/rolemenu refresh` | Reposte la vue persistante d'un menu. |
| `/rolemenu list` | Liste les menus du serveur. |
| `/rolemenu inspect` | Affiche les IDs techniques a utiliser. |
| `/rolemenu export` | Exporte un panneau en JSON. |
| `/rolemenu copy` | Copie un panneau dans un autre salon. |
| `/rolemenu import_config` | Cree un panneau depuis un JSON. |

### Admin technique

| Commande | Usage |
| --- | --- |
| `/sync` | Resynchronise les slash commands. |
| `/reload` | Recharge un cog. |

## Optimisations prioritaires

- Extraire `cogs/raid.py` en modules plus petits : vues Discord, service de
  planification, service participants, commandes slash.
- Generer `/help` depuis un catalogue partage pour eviter les ecarts avec la doc.
- Garder les index SQLite ajoutes dans `db.py` et mesurer les requetes lentes si
  la base grossit.
- Envisager `aiosqlite` ou `asyncio.to_thread` si les operations DB deviennent
  visibles dans la latence Discord.
