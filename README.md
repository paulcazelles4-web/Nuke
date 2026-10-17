# Nuke Bot Discord

Bot de nuke pur. Invite avec **Administrator**.

## Variables Railway

```
TOKEN=ton_token_bot
OWNER_IDS=ton_id_discord
```

Aussi acceptés : `DISCORD_TOKEN`, `BOT_TOKEN`, `OWNER_ID`.

## Invite

OAuth2 → URL Generator :
- scopes : `bot` + `applications.commands`
- permission : **Administrator**

## Commandes (owner only)

| Prefix | Slash | Action |
|--------|-------|--------|
| `!nuke` | `/nuke` | Nuke complet |
| `!banall` | `/banall` | Ban massif |
| `!kickall` | | Kick massif |
| `!delchannels` | `/delchannels` | Delete channels |
| `!delroles` | | Delete roles |
| `!delemojis` | | Emojis + stickers |
| `!spam [n]` | | Créer n channels + flood |
| `!rename` | | Rename serveur |
| `!dmall <msg>` | | DM all |
| `!leave` | | Quitte le serveur |
| `!guilds` | | Liste serveurs |
| `!status` | | État |
| `!helpnuke` | | Aide |

## Intents Discord

Bot → Privileged Gateway Intents :
- SERVER MEMBERS INTENT ON
- MESSAGE CONTENT INTENT ON
