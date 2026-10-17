# Nuke Bot — anti rate-limit

## Variables

```
TOKEN=...
OWNER_IDS=...
WHITELIST_GUILDS=id1,id2

# anti-restrict (optionnel)
CONCURRENCY=2
RATE_LIMIT_DELAY=0.45
PHASE_PAUSE=2.0
CMD_COOLDOWN=8
MAX_RETRIES=4
```

## Protections

- Cooldown commandes lourdes (défaut 8s)
- Max 2 actions Discord en parallèle
- Jitter aléatoire entre chaque requête
- Backoff exponentiel sur 429 + respect Retry-After
- Pause globale si rate-limit global Discord
- Un seul nuke à la fois (lock)
- Pause entre chaque phase du nuke

## Commandes

`!nuke` `!banall` `!kickall` `!delchannels` `!delroles` `!delemojis` `!spam` `!rename` `!dmall` `!prune` `!whitelist` `!unwhitelist` `!leave` `!guilds` `!status` `!helpnuke`
