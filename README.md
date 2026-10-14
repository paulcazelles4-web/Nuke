# Nuke Bot

## Railway variables (obligatoire)

```
TOKEN=coller_le_token_SANS_guillemets
OWNER_IDS=ton_id_discord_numerique
```

Aussi accepté : `DISCORD_TOKEN` et `OWNER_ID`.

## Checklist Discord

1. https://discord.com/developers/applications → ton app → Bot
2. Reset Token → copier → coller dans Railway `TOKEN` **sans guillemets**
3. Privileged Gateway Intents :
   - SERVER MEMBERS INTENT = ON
   - MESSAGE CONTENT INTENT = ON
4. OAuth2 → URL Generator → scopes `bot` → permission Administrator → invite

## Logs à chercher après redeploy

```
=== NUKE BOT BOOT ===
TOKEN present=True length=70…
Health OK on 0.0.0.0:…
Connecting to Discord…
===== BOT ONLINE as Name#0000 =====
```

Si `TOKEN present=False` → variable pas sur le bon service.
Si `LOGIN FAILED` → token mort, régénère.
