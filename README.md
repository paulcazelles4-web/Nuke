# Nuke Bot — Discord

Bot de nuke ultra-complet. Déployable sur Railway.

## Variables Railway (obligatoires)

| Variable | Description |
|----------|-------------|
| `TOKEN` | Token du bot Discord |
| `OWNER_IDS` | IDs Discord des owners séparés par des virgules (ex: `123,456`) |

## Variables optionnelles

| Variable | Défaut | Description |
|----------|--------|-------------|
| `PREFIX` | `!` | Préfixe des commandes |
| `NUKE_NAME` | `NUKED` | Nouveau nom du serveur après nuke |
| `SPAM_CHANNELS` | `50` | Nombre de channels spam créés |
| `SPAM_MESSAGES` | `10` | Messages par channel spam |
| `SPAM_TEXT` | `@everyone NUKED` | Texte des messages spam |
| `WEBHOOK_SPAM` | `true` | Utiliser webhooks pour le spam (plus rapide) |
| `BAN_REASON` | `nuked` | Raison des bans |
| `DELETE_ROLES` | `true` | Supprimer les rôles |
| `DELETE_EMOJIS` | `true` | Supprimer les emojis |
| `DELETE_STICKERS` | `true` | Supprimer les stickers |
| `DELETE_WEBHOOKS` | `true` | Supprimer les webhooks existants |
| `BAN_ALL` | `true` | Ban tous les membres |
| `KICK_INSTEAD` | `false` | Kick au lieu de ban |
| `SKIP_BOTS` | `false` | Ne pas ban/kick les bots |
| `SKIP_OWNER` | `true` | Ne pas ban le owner du serveur |
| `CHANGE_ICON` | `false` | Changer l'icône (nécessite ICON_URL) |
| `ICON_URL` | `` | URL d'une image pour l'icône |
| `CREATE_ROLES` | `0` | Nombre de rôles spam à créer |
| `ROLE_NAME` | `nuked` | Nom de base des rôles spam |
| `CHANNEL_NAME` | `nuked` | Nom de base des channels spam |
| `DM_MESSAGE` | `` | Message DM avant ban (vide = désactivé) |
| `LOG_CHANNEL` | `` | ID channel de log (optionnel) |
| `AUTO_NUKE_GUILD` | `` | Si défini, nuke auto ce guild_id au démarrage |
| `RATE_LIMIT_DELAY` | `0.3` | Délai entre actions (secondes) |

## Commandes

- `!nuke [guild_id]` — nuke complet (toutes options actives)
- `!banall` — ban massif uniquement
- `!kickall` — kick massif
- `!delchannels` — supprimer tous les channels
- `!delroles` — supprimer tous les rôles
- `!delemojis` — supprimer emojis + stickers
- `!spam [count]` — créer N channels + flood
- `!webhookspam [count]` — spam via webhooks
- `!rename [name]` — renommer le serveur
- `!createchannels [n]` — créer N channels
- `!createroles [n]` — créer N rôles
- `!dmall [message]` — DM tous les membres
- `!leave` — quitter le serveur
- `!guilds` — lister les serveurs
- `!status` — état du bot
- `!helpnuke` — aide complète

Owner only. Préfixe configurable.
