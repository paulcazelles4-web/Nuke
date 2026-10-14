# Nuke Bot — Discord (Railway)

## Variables obligatoires

```
TOKEN=ton_token_bot
OWNER_IDS=ton_id_discord
```

## Si ça crash encore

1. Ouvre **Deployments → Logs** (pas le build log).
2. Cherche les lignes `=== NUKE BOT BOOT ===` et `TOKEN set=`.
3. Causes fréquentes :
   - `TOKEN set=False` → variable pas ajoutée ou mal nommée
   - `TOKEN INVALIDE` → régénère le token
   - Bot offline Discord → intents Members + Message Content pas activés

## Healthcheck

Le bot écoute sur `PORT` (fourni par Railway) → `GET /` retourne `200 ok`.

## Commandes

`!nuke` `!banall` `!kickall` `!delchannels` `!delroles` `!delemojis` `!spam` `!webhookspam` `!rename` `!dmall` `!prune` `!vanity` `!leave` `!guilds` `!status` `!helpnuke`
