# Nuke Bot

## Variables Railway (mets-en UNE pour le token)

N'importe lequel de ces noms marche :

```
TOKEN
DISCORD_TOKEN
BOT_TOKEN
DISCORD_BOT_TOKEN
```

Owners (un de ceux-là) :

```
OWNER_IDS=123456789
OWNER_ID=123456789
```

Valeur **sans guillemets**, sans espace avant/après.

Après redeploy, dans les logs cherche :

```
ENV KEYS (...): ...
TOKEN found=True
===== BOT ONLINE as ...
```

Si `TOKEN found=False`, regarde la ligne `ENV KEYS` : ton nom de variable n'y est pas → elle n'est pas injectée dans ce service.
