# Nuke Bot — external + full

## Mode external (pas d'admin)

Invite le bot avec seulement **Send Messages** (+ optional Mention Everyone).

Slash commands (owner only) :

| Commande | Effet |
|----------|--------|
| `/spam message:texte count:25` | Flood **tous** les salons où le bot peut écrire |
| `/spam message:texte only_here:True` | Flood ce salon seulement |
| `/spamhere message:texte` | Idem salon actuel |

Permissions minimales invite : `Send Messages`, `Use Application Commands`.

## Mode full nuke (admin)

`/nuke` ou `!nuke` — nécessite Administrator / Manage Channels / Ban…

## Variables Railway

```
TOKEN=...
OWNER_IDS=ton_id
EXTERNAL_SPAM_COUNT=25
```

Aussi acceptés : `DISCORD_TOKEN`, `BOT_TOKEN`, `OWNER_ID`.

Après deploy, attend 1 min que les slash sync (`Slash commands synced` dans les logs), puis tape `/spam` dans Discord.
