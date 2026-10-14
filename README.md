# Nuke Bot — Discord (Railway-ready)

Bot de nuke ultra-complet, concurrent, anti-crash Railway.

## Deploy Railway

1. New Project → GitHub → `paulcazelles4-web/Nuke`
2. **Variables** (voir tableau)
3. Settings → **Start Command** : `python bot.py` (ou laisse `railway.toml`)
4. Service type : n'importe (le process est un worker long-running)
5. Deploy

Si ça crash encore : regarde les logs. Les causes #1 sont `TOKEN` invalide ou intents non activés.

## Variables obligatoires

| Variable | Exemple |
|----------|---------|
| `TOKEN` | `MTIx...` token bot |
| `OWNER_IDS` | `123456789012345678` (virgules si plusieurs) |

## Variables optionnelles

| Variable | Défaut | Description |
|----------|--------|-------------|
| `PREFIX` | `!` | Préfixe |
| `NUKE_NAME` | `NUKED` | Nom serveur après nuke |
| `SPAM_CHANNELS` | `50` | Channels spam |
| `SPAM_MESSAGES` | `15` | Msgs / channel |
| `SPAM_TEXT` | `@everyone NUKED` | Texte spam |
| `WEBHOOK_SPAM` | `true` | Webhooks pour spam |
| `BAN_REASON` | `nuked` | Raison ban |
| `DELETE_ROLES` | `true` | Delete roles |
| `DELETE_EMOJIS` | `true` | Delete emojis |
| `DELETE_STICKERS` | `true` | Delete stickers |
| `DELETE_WEBHOOKS` | `true` | Delete webhooks |
| `BAN_ALL` | `true` | Ban massif |
| `KICK_INSTEAD` | `false` | Kick au lieu de ban |
| `SKIP_BOTS` | `false` | Skip bots |
| `SKIP_OWNER` | `true` | Skip owner serveur |
| `CHANGE_ICON` | `false` | Change icône |
| `ICON_URL` | | URL image icône |
| `CHANGE_BANNER` | `false` | Change bannière |
| `BANNER_URL` | | URL bannière |
| `CREATE_ROLES` | `10` | Rôles spam |
| `ROLE_NAME` | `nuked` | Base nom rôles |
| `CHANNEL_NAME` | `nuked` | Base nom channels |
| `CREATE_CATEGORIES` | `5` | Catégories spam |
| `CREATE_VOICE` | `10` | Voice channels spam |
| `DM_MESSAGE` | | DM avant ban |
| `LOG_WEBHOOK` | | URL webhook de log externe |
| `AUTO_NUKE_GUILD` | | Guild ID → nuke au boot |
| `CONCURRENCY` | `8` | Actions parallèles |
| `RATE_LIMIT_DELAY` | `0.15` | Délai de base (s) |
| `PRUNE_DAYS` | `0` | Prune inactifs (0=off) |
| `VANITY` | | Tente vanity code |
| `KEEPALIVE_SEC` | `60` | Log keepalive Railway |

## Intents Discord Developer Portal

Bot → Privileged Gateway Intents :
- **SERVER MEMBERS INTENT** ✅
- **MESSAGE CONTENT INTENT** ✅

Invite URL scopes : `bot` + permissions **Administrator**.

## Commandes (owner only)

`!nuke` `!banall` `!kickall` `!delchannels` `!delroles` `!delemojis` `!spam` `!webhookspam` `!rename` `!createchannels` `!createroles` `!dmall` `!prune` `!vanity` `!leave` `!guilds` `!status` `!helpnuke`
