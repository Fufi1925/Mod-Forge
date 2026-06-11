# -*- coding: utf-8 -*-
"""ModForge Events Cog – Alle Event-Handler."""
import asyncio
import datetime
import re
import time
import traceback
import unicodedata
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple, Union

import discord
from discord.ext import commands, tasks
from discord import app_commands

from bot.config import (
    ACTIVITY, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_INFO, FOOTER_TEXT, FOOTER_ICON, E, URL_REGEX, INVITE_REGEX,
    ZALGO_REGEX, SUSPICIOUS_NAME_REGEX, SCAM_DOMAINS, URL_SHORTENERS,
    DEFAULT_CONFIG, log, BADGES,
)
from bot.utils import create_embed, check_phishing_url, can_moderate, parse_duration
from bot.bot import safe_dm, _BOT_DEV_ID, _snipe_cache


# ══════════════════════════════════════════════════
# APPEAL STATE (module-level)
# ══════════════════════════════════════════════════
appeal_sessions: dict = {}
APPEAL_QUESTIONS = [
    "**Frage 1/5** – Warum glaubst du, wurdest du gebannt?",
    "**Frage 2/5** – Siehst du deinen Fehler ein? *(Bitte antworte mit `ja` oder `nein`)*",
    "**Frage 3/5** – Was möchtest du dem Moderationsteam zu deinem Ban sagen?",
    "**Frage 4/5** – Versprichst du, die Serverregeln in Zukunft zu befolgen? *(ja/nein)*",
    "**Frage 5/5** – Gibt es noch etwas, das du hinzufügen möchtest? *(Wenn nein, schreibe `nein`)*"
]
APPEAL_KEYS = ["ban_grund", "fehler_eingesehen", "statement", "regeln_versprechen", "zusatz"]


class EventsCog(commands.Cog):
    """Alle Discord-Events (on_message, on_member_join, etc.)"""
    
    def __init__(self, bot):
        self.bot = bot

    # ── LOCKDOWN HELPERS ──
    async def _activate_lockdown(self, guild: discord.Guild) -> None:
        for channel in guild.text_channels:
            try:
                await channel.set_permissions(guild.default_role, send_messages=False, reason="Anti-Raid Lockdown")
            except (discord.Forbidden, discord.HTTPException):
                pass
        await self.bot.log_action(guild, f"{E.LOCK} LOCKDOWN AKTIVIERT", "Alle Kanäle gesperrt.", COLOR_DANGER, module="antiraid")

    async def _deactivate_lockdown(self, guild: discord.Guild) -> None:
        self.bot.tracker.lockdown_active[guild.id] = False
        for channel in guild.text_channels:
            try:
                await channel.set_permissions(guild.default_role, send_messages=None, reason="Lockdown aufgehoben")
            except (discord.Forbidden, discord.HTTPException):
                pass
        await self.bot.log_action(guild, f"{E.UNLOCK} LOCKDOWN DEAKTIVIERT", "Alle Kanäle entsperrt.", COLOR_SUCCESS, module="antiraid")

    async def _nuke_check(self, guild: discord.Guild, user_id: int, action: str) -> None:
        cfg = self.bot.db.get_config(guild.id)
        nuke_cfg = cfg.get("anti_nuke", {})
        if not nuke_cfg.get("enabled"):
            return
        member = guild.get_member(user_id)
        if member and self.bot.is_whitelisted(member, "bypass_antinuke"):
            return
        now = time.time()
        dq = self.bot.tracker.nuke_tracker[guild.id][user_id]
        dq.append(now)
        self.bot.tracker.clean_old(dq, nuke_cfg.get("window", 10))
        if len(dq) >= nuke_cfg.get("threshold", 5):
            dq.clear()
            if member:
                punishment = nuke_cfg.get("punishment", "ban")
                try:
                    if punishment == "ban":
                        await member.ban(reason=f"Anti-Nuke: {action}")
                    elif punishment == "kick":
                        await member.kick(reason=f"Anti-Nuke: {action}")
                    if nuke_cfg.get("remove_roles"):
                        for role in member.roles[1:]:
                            try:
                                await member.remove_roles(role, reason="Anti-Nuke: Rollen entfernt")
                            except (discord.Forbidden, discord.HTTPException):
                                pass
                except (discord.Forbidden, discord.HTTPException):
                    pass
            await self.bot.log_action(guild, f"{E.NUKE} NUKE ERKANNT",
                f"**User:** <@{user_id}>\n**Aktion:** {action}\n**Maßnahme:** {nuke_cfg.get('punishment', 'ban')}",
                COLOR_DANGER, module="antinuke")
            # Notify owner
            if guild.owner:
                try:
                    embed = create_embed(f"{E.NUKE} NUKE-VERSUCH ERKANNT",
                        f"**Server:** {guild.name}\n**Verdächtig:** <@{user_id}>\n**Aktion:** {action}",
                        COLOR_DANGER)
                    await safe_dm(guild.owner, embed, cooldown_key=f"nuke:{guild.id}:{user_id}")
                except Exception:
                    pass

    # ── ON_MEMBER_JOIN ──
    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        cfg = self.bot.db.get_config(guild.id)
        sec_level = cfg.get("security_level", 0)
        raid_cfg = cfg.get("anti_raid", {})
        ACTIVITY.push("join", f"{member} ist **{guild.name}** beigetreten ({guild.member_count} Member).",
                      guild_id=guild.id, guild_name=guild.name, user_id=member.id, user_name=str(member))
        if self.bot.is_whitelisted(member, "bypass_antinuke"):
            await self.bot.log_action(guild, f"{E.PLUS} Mitglied beigetreten", f"{member.mention}", COLOR_SUCCESS, user=member, module="members")
            return
        # Anti-VPN
        vpn_cfg = cfg.get("anti_vpn", {})
        if vpn_cfg.get("enabled") and not member.bot:
            vpn_wl = vpn_cfg.get("whitelist_ids", [])
            if str(member.id) not in [str(w) for w in vpn_wl]:
                account_age_hours = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).total_seconds() / 3600
                suspicious_vpn = (account_age_hours < 24 and not member.avatar and
                    (member.name.startswith("user") or len(member.name) < 4 or any(c.isdigit() for c in member.name[-4:])))
                if suspicious_vpn:
                    action = vpn_cfg.get("action", "kick")
                    try:
                        if action == "ban":
                            await member.ban(reason="Anti-VPN: Verdächtiger Account")
                        elif action == "kick":
                            await member.kick(reason="Anti-VPN: Verdächtiger Account")
                        await self.bot.log_action(guild, f"{E.SHIELD} Anti-VPN",
                            f"{member.mention} verdächtig erkannt.\n**Account-Alter:** {int(account_age_hours)}h",
                            COLOR_WARNING, user=member, module="antiraid")
                    except discord.Forbidden:
                        pass

        # Raid-Mode
        if cfg.get("raidmode_active") and not member.bot:
            try:
                dm_embed = create_embed("🚨 Server im Raid-Modus",
                    f"**{guild.name}** ist aktuell im Raid-Modus.", COLOR_DANGER)
                await safe_dm(member, dm_embed, cooldown_key=f"raidmode_dm:{guild.id}:{member.id}")
            except Exception:
                pass

        # Security levels
        if sec_level >= 2:
            account_age = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).days
            if account_age < 5:
                try:
                    await member.kick(reason="Sicherheitsstufe 2: Account zu jung")
                    await self.bot.log_action(guild, f"{E.SHIELD} Sicherheitsstufe 2: Kick",
                        f"{member.mention} (Account-Alter: {account_age} Tage).", COLOR_DANGER, user=member, module="antiraid")
                    return
                except discord.Forbidden:
                    pass
        if sec_level >= 3:
            try:
                await member.ban(reason="Sicherheitsstufe 3: BLACKOUT aktiv")
                return
            except discord.Forbidden:
                pass

        # Anti-Raid
        if raid_cfg.get("enabled"):
            now = time.time()
            dq = self.bot.tracker.raid_tracker[guild.id]
            dq.append(now)
            self.bot.tracker.clean_old(dq, raid_cfg.get("window", 20))
            min_age_days = raid_cfg.get("min_account_age", 7)
            account_age = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).days
            if account_age < min_age_days and raid_cfg.get("auto_kick"):
                try:
                    await member.kick(reason=f"Anti-Raid: Account zu jung ({account_age} Tage)")
                    await self.bot.log_action(guild, f"{E.NEWACC} Neuer Account gekickt",
                        f"{member.mention} ({account_age} Tage).", COLOR_DANGER, user=member, module="antiraid")
                    return
                except discord.Forbidden:
                    pass
            if raid_cfg.get("suspicious_name_check") and SUSPICIOUS_NAME_REGEX.match(member.name):
                await self.bot.log_action(guild, f"{E.RAID} Verdächtiger Username",
                    f"{member.mention} (`{member.name}`).", COLOR_WARNING, user=member, module="antiraid")
            if len(dq) >= raid_cfg.get("join_threshold", 10):
                dq.clear()
                if not self.bot.tracker.lockdown_active[guild.id] and raid_cfg.get("lockdown"):
                    self.bot.tracker.lockdown_active[guild.id] = True
                    await self._activate_lockdown(guild)
                await self.bot.log_action(guild, f"{E.NUKE} RAID ERKANNT", "Zu viele Beitritte!", COLOR_DANGER, module="antiraid")

        # Bot-Add nuke check
        if member.bot:
            nuke_cfg = cfg.get("anti_nuke", {})
            if nuke_cfg.get("enabled"):
                try:
                    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
                        await self._nuke_check(guild, entry.user.id, "Bot hinzugefügt")
                except discord.Forbidden:
                    pass
            await self.bot.log_action(guild, f"{E.BOT} Bot hinzugefügt", f"Bot **{member.mention}**", COLOR_WARNING, user=member, module="members")
            return

        await self.bot.log_action(guild, f"{E.JOIN} Mitglied beigetreten", f"{member.mention}", COLOR_SUCCESS, user=member, module="members")

        # Welcome + Sticky Roles
        try:
            welcome_cog = self.bot.get_cog("WelcomeCog")
            if welcome_cog:
                await welcome_cog.send_welcome(member)
                await welcome_cog.restore_sticky_roles(member)
        except Exception as ex:
            log.debug(f"Welcome/Sticky-Roles Fehler: {ex}")

    # ── ON_MESSAGE ──
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            # Handle DM appeals
            if not message.guild and not message.author.bot:
                handled = await self._handle_appeal_dm(message)
                if handled:
                    return
            return

        guild = message.guild
        member = message.author
        cfg = self.bot.db.get_config(guild.id)
        content = message.content or ""

        # Message archive
        archive_cfg = cfg.get("message_archive", {})
        if archive_cfg.get("enabled"):
            try:
                await self.bot.db.arecord_message(guild.id, message.channel.id, message.id, member.id,
                    content, [a.url for a in message.attachments][:10])
            except Exception:
                pass

        # Ghost-Ping tracking
        if message.mentions:
            ghost_cfg = cfg.get("anti_ghost_ping", {})
            if ghost_cfg.get("enabled"):
                real_mentions = [m for m in message.mentions if not m.bot and m.id != member.id]
                if real_mentions:
                    self.bot.tracker.ghost_tracker[guild.id][message.id] = (member.id, [m.id for m in real_mentions])

        # Whitelist check
        if self.bot.is_whitelisted(member, "bypass_antispam"):
            return

        # Anti-Spam
        spam_cfg = cfg.get("anti_spam", {})
        if spam_cfg.get("enabled"):
            now = time.time()
            dq = self.bot.tracker.spam_tracker[guild.id][member.id]
            dq.append(now)
            self.bot.tracker.clean_old(dq, spam_cfg.get("msg_window", 10))
            if len(dq) > spam_cfg.get("msg_limit", 5):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await self.bot.punish(member, spam_cfg.get("punishment", "timeout"),
                    "Anti-Spam: Nachrichtenflut", spam_cfg.get("timeout_duration", 30))
                await self.bot.log_action(guild, f"{E.SPAM} Spam erkannt",
                    f"{member.mention} hat zu schnell geschrieben.", COLOR_WARNING, user=member, module="antispam")
                return

            # CAPS check
            if len(content) > 10:
                caps_ratio = sum(1 for c in content if c.isupper()) / max(1, len(content)) * 100
                if caps_ratio > spam_cfg.get("caps_pct", 70):
                    try:
                        await message.delete()
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    await self.bot.punish(member, spam_cfg.get("punishment", "timeout"),
                        "Anti-Spam: Übermäßige Großschreibung", spam_cfg.get("timeout_duration", 30))
                    await self.bot.log_action(guild, f"{E.CAPS} CAPS-Spam erkannt",
                        f"{member.mention} – {caps_ratio:.0f}% Großbuchstaben.", COLOR_WARNING, user=member, module="antispam")
                    return

            # Emoji flood
            emoji_count = len(re.findall(r"<a?:\w+:\d+>|[\U0001F000-\U0001FFFF]", content))
            if emoji_count > spam_cfg.get("emoji_max", 10):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await self.bot.punish(member, spam_cfg.get("punishment", "timeout"),
                    "Anti-Spam: Emoji-Spam", spam_cfg.get("timeout_duration", 30))
                await self.bot.log_action(guild, f"{E.EMOJI} Emoji-Spam erkannt",
                    f"{member.mention} – {emoji_count} Emojis.", COLOR_WARNING, user=member, module="antispam")
                return

            # Duplicate messages
            dup_list = self.bot.tracker.dup_tracker[guild.id][member.id]
            dup_list.append(content.lower().strip())
            if len(dup_list) > 10:
                dup_list.pop(0)
            if dup_list.count(content.lower().strip()) > spam_cfg.get("duplicate_max", 3):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await self.bot.punish(member, spam_cfg.get("punishment", "timeout"),
                    "Anti-Spam: Doppelte Nachrichten", spam_cfg.get("timeout_duration", 30))
                await self.bot.log_action(guild, f"{E.DUP} Duplikat-Spam erkannt",
                    f"{member.mention} hat dieselbe Nachricht zu oft gesendet.", COLOR_WARNING, user=member, module="antispam")
                return

        # AutoMod
        automod_cfg = cfg.get("automod", {})
        if automod_cfg.get("enabled"):
            # Bad words
            for word in automod_cfg.get("bad_words", []):
                try:
                    if re.search(rf"\b{re.escape(word)}\b", content, re.IGNORECASE):
                        try:
                            await message.delete()
                        except (discord.Forbidden, discord.NotFound):
                            pass
                        await self.bot.punish(member, automod_cfg.get("punishment", "warn"), f"AutoMod: Verbotenes Wort")
                        await self.bot.log_action(guild, f"{E.BADWORD} Verbotenes Wort",
                            f"{member.mention}", COLOR_DANGER, user=member, module="automod")
                        return
                except re.error:
                    continue

            # Regex rules
            for pattern in automod_cfg.get("regex_rules", []):
                try:
                    if re.search(pattern, content):
                        try:
                            await message.delete()
                        except (discord.Forbidden, discord.NotFound):
                            pass
                        await self.bot.punish(member, automod_cfg.get("punishment", "warn"), f"AutoMod: Regex-Regel")
                        await self.bot.log_action(guild, f"{E.BADWORD} AutoMod Regex",
                            f"{member.mention}", COLOR_DANGER, user=member, module="automod")
                        return
                except re.error:
                    continue

            # Invite filter
            if automod_cfg.get("invite_filter") and INVITE_REGEX.search(content):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await self.bot.punish(member, automod_cfg.get("punishment", "warn"), "AutoMod: Discord-Einladungslink")
                await self.bot.log_action(guild, f"{E.BADWORD} Invite-Link erkannt",
                    f"{member.mention}", COLOR_DANGER, user=member, module="automod")
                return

            # Link filter
            if automod_cfg.get("link_filter"):
                urls = URL_REGEX.findall(content)
                allowed = automod_cfg.get("allowed_domains", [])
                for url in urls:
                    domain = re.sub(r"https?://([^/]+).*", r"\1", url).lower()
                    if not any(domain.endswith(d.lower()) for d in allowed):
                        try:
                            await message.delete()
                        except (discord.Forbidden, discord.NotFound):
                            pass
                        await self.bot.punish(member, automod_cfg.get("punishment", "warn"), "AutoMod: Nicht erlaubter Link")
                        await self.bot.log_action(guild, f"{E.BADWORD} Link-Filter",
                            f"{member.mention}", COLOR_WARNING, user=member, module="automod")
                        return

            # Zalgo
            if automod_cfg.get("zalgo_filter") and ZALGO_REGEX.search(content):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await self.bot.punish(member, automod_cfg.get("punishment", "warn"), "AutoMod: Zalgo-Text")
                return

            # Phishing
            if automod_cfg.get("phishing_check") and URL_REGEX.search(content):
                if await check_phishing_url(content):
                    try:
                        await message.delete()
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    await self.bot.punish(member, automod_cfg.get("punishment", "warn"), "AutoMod: Phishing-Link")
                    await self.bot.log_action(guild, f"{E.NUKE} Phishing erkannt",
                        f"Link von {member.mention} gelöscht.", COLOR_DANGER, user=member, module="automod")
                    return

        # Anti-Scam
        scam_cfg = cfg.get("anti_scam", {})
        if scam_cfg.get("enabled"):
            for domain in SCAM_DOMAINS:
                if domain.lower() in content.lower():
                    try:
                        await message.delete()
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    await self.bot.punish(member, scam_cfg.get("punishment", "ban"), f"Anti-Scam: Scam-Domain '{domain}'")
                    await self.bot.log_action(guild, f"{E.BADWORD} Scam-Link",
                        f"{member.mention}", COLOR_DANGER, user=member, module="antiscam")
                    return

        # Anti-URL-Shortener
        short_cfg = cfg.get("anti_url_shortener", {})
        if short_cfg.get("enabled"):
            for shortener in URL_SHORTENERS:
                if shortener.lower() in content.lower():
                    try:
                        await message.delete()
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    await self.bot.punish(member, short_cfg.get("punishment", "warn"), f"Anti-URL-Shortener")
                    return

        # Anti-Mention
        mention_cfg = cfg.get("anti_mention", {})
        if mention_cfg.get("enabled") and (message.mentions or message.role_mentions):
            total_mentions = len(message.mentions) + len(message.role_mentions)
            now = time.time()
            dq = self.bot.tracker.mention_tracker[guild.id][member.id]
            for _ in range(total_mentions):
                dq.append(now)
            self.bot.tracker.clean_old(dq, mention_cfg.get("window", 10))
            if len(dq) > mention_cfg.get("mention_limit", 5):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await self.bot.punish(member, mention_cfg.get("punishment", "timeout"),
                    "Anti-Mention: Mention-Spam", mention_cfg.get("timeout_duration", 60))
                await self.bot.log_action(guild, f"{E.MENTION} Mention-Spam",
                    f"{member.mention}", COLOR_DANGER, user=member, module="antimention")
                return

    # ── ON_MESSAGE_DELETE ──
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        guild = message.guild
        cfg = self.bot.db.get_config(guild.id)
        ghost_cfg = cfg.get("anti_ghost_ping", {})
        if ghost_cfg.get("enabled") and message.id in self.bot.tracker.ghost_tracker.get(guild.id, {}):
            data = self.bot.tracker.ghost_tracker[guild.id].pop(message.id)
            author = guild.get_member(data[0])
            mentions = [guild.get_member(uid) for uid in data[1] if guild.get_member(uid)]
            mention_str = ", ".join(m.mention for m in mentions if m) or "Unbekannt"
            await self.bot.log_action(guild, f"{E.GHOST} Ghost-Ping erkannt",
                f"**{author.mention if author else 'Unbekannt'}** hat eine Nachricht mit Mentions gelöscht.",
                COLOR_WARNING, [("Gepingte User", mention_str, False)], user=author, module="ghostping")
            return
        try:
            await self.bot.db.amark_message_deleted(guild.id, message.id)
        except Exception:
            pass
        await self.bot.log_action(guild, f"{E.DELETE} Nachricht gelöscht",
            f"Nachricht von {message.author.mention} in {message.channel.mention} wurde gelöscht.",
            COLOR_INFO, [("Inhalt", message.content[:1000] or "*(Kein Text)*", False)],
            user=message.author, module="messages")
        # Snipe cache
        _snipe_cache.setdefault(guild.id, {})[message.channel.id] = {
            "content": message.content[:1500], "author": message.author,
            "ts": time.time(), "attachments": [a.url for a in message.attachments][:3]}

    # ── ON_MESSAGE_EDIT ──
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if not before.guild or before.author.bot or before.content == after.content:
            return
        try:
            await self.bot.db.aappend_message_edit(before.guild.id, before.id, before.content or "")
        except Exception:
            pass
        await self.bot.log_action(before.guild, f"{E.EDIT} Nachricht bearbeitet",
            f"Von {before.author.mention} in {before.channel.mention}",
            COLOR_INFO, [("Vorher", before.content[:500] or "*(leer)*", False),
                         ("Nachher", after.content[:500] or "*(leer)*", False)],
            user=before.author, module="messages")

    # ── ON_MEMBER_UPDATE ──
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.bot:
            return
        guild = after.guild
        cfg = self.bot.db.get_config(guild.id)
        # Nickname change
        if before.nick != after.nick:
            await self.bot.log_action(guild, f"{E.NICK} Nickname geändert",
                f"{after.mention}: `{before.nick or before.name}` → `{after.nick or after.name}`",
                COLOR_INFO, user=after, module="nicknames")
        # Role changes
        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        for role in added:
            await self.bot.log_action(guild, f"{E.ROLE_ADD} Rolle hinzugefügt",
                f"{after.mention} → {role.mention}", COLOR_SUCCESS, user=after, module="roles")
        for role in removed:
            await self.bot.log_action(guild, f"{E.ROLE_DEL} Rolle entfernt",
                f"{after.mention} ← {role.mention}", COLOR_WARNING, user=after, module="roles")

    # ── GUILD CHANNEL/ROLE EVENTS ──
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel) -> None:
        guild = channel.guild
        cfg = self.bot.db.get_config(guild.id)
        nuke_cfg = cfg.get("anti_nuke", {})
        if nuke_cfg.get("enabled"):
            try:
                async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
                    await self._nuke_check(guild, entry.user.id, "Kanal gelöscht")
                    break
            except discord.Forbidden:
                pass
        await self.bot.log_action(guild, f"{E.DELETE} Kanal gelöscht", f"**{channel.name}**", COLOR_DANGER, module="channels")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel) -> None:
        await self.bot.log_action(channel.guild, f"{E.PLUS} Kanal erstellt", f"{channel.mention}", COLOR_SUCCESS, module="channels")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role) -> None:
        guild = role.guild
        cfg = self.bot.db.get_config(guild.id)
        nuke_cfg = cfg.get("anti_nuke", {})
        if nuke_cfg.get("enabled"):
            try:
                async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
                    await self._nuke_check(guild, entry.user.id, "Rolle gelöscht")
                    break
            except discord.Forbidden:
                pass
        await self.bot.log_action(guild, f"{E.DELETE} Rolle gelöscht", f"**{role.name}**", COLOR_DANGER, module="roles")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role) -> None:
        await self.bot.log_action(role.guild, f"{E.PLUS} Rolle erstellt", f"{role.mention}", COLOR_SUCCESS, module="roles")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user) -> None:
        cfg = self.bot.db.get_config(guild.id)
        nuke_cfg = cfg.get("anti_nuke", {})
        if nuke_cfg.get("enabled"):
            try:
                async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                    if entry.user.id != self.bot.user.id:
                        await self._nuke_check(guild, entry.user.id, "Mitglied gebannt")
                    break
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member) -> None:
        guild = member.guild
        ACTIVITY.push("leave", f"{member} hat **{guild.name}** verlassen.",
                      guild_id=guild.id, guild_name=guild.name, user_id=member.id, user_name=str(member))
        await self.bot.log_action(guild, f"{E.KICK} Mitglied verlassen", f"{member.mention}", COLOR_WARNING, user=member, module="members")
        # Save sticky roles
        try:
            cfg = self.bot.db.get_config(guild.id)
            sticky = cfg.get("sticky_roles", [])
            if sticky:
                member_roles = [r.id for r in member.roles if r.id in sticky]
                if member_roles:
                    await self.bot.db.data.update_one(
                        {"guild_id": guild.id, "user_id": member.id, "type": "sticky_roles"},
                        {"$set": {"roles": member_roles, "updated_at": discord.utils.utcnow()}},
                        upsert=True)
        except Exception:
            pass
        # Leave message
        try:
            welcome_cog = self.bot.get_cog("WelcomeCog")
            if welcome_cog:
                await welcome_cog.send_leave(member)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild) -> None:
        ACTIVITY.push("guild_join", f"Bot zu **{guild.name}** hinzugefügt ({guild.member_count} Member).",
                      guild_id=guild.id, guild_name=guild.name)
        await self.bot.db.arecord_guild_event(guild.id, guild.name, guild.member_count or 0, "join")
        log.info(f"Guild beigetreten: {guild.name} ({guild.id}) – {guild.member_count} Mitglieder")
        # Invite caching
        try:
            if guild.me.guild_permissions.manage_guild:
                invites = await guild.invites()
                self.bot.tracker.invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            pass
        # Welcome embed to first text channel
        try:
            target = guild.system_channel or next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages), None)
            if target:
                embed = create_embed(
                    "🛡️ ModForge – Security Bot",
                    f"Danke für die Einladung zu **{guild.name}**!\n\n"
                    f"Nutze `/setup` um mich zu konfigurieren.\n"
                    f"Nutze `/help` für alle Commands.",
                    COLOR_PRIMARY)
                await target.send(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_remove(self, guild) -> None:
        ACTIVITY.push("guild_leave", f"Bot von **{guild.name}** entfernt.",
                      guild_id=guild.id, guild_name=guild.name)
        await self.bot.db.arecord_guild_event(guild.id, guild.name, guild.member_count or 0, "leave")
        log.info(f"Guild verlassen: {guild.name} ({guild.id})")

    # ── VOICE STATE UPDATE ──
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after) -> None:
        guild = member.guild
        cfg = self.bot.db.get_config(guild.id)
        # Log voice events
        if before.channel is None and after.channel is not None:
            await self.bot.log_action(guild, f"{E.VOICE_IN} Voice beigetreten",
                f"{member.mention} → {after.channel.mention}", COLOR_SUCCESS, user=member, module="voice")
        elif before.channel is not None and after.channel is None:
            await self.bot.log_action(guild, f"{E.VOICE_OUT} Voice verlassen",
                f"{member.mention} ← {before.channel.mention}", COLOR_WARNING, user=member, module="voice")
        elif before.channel != after.channel and before.channel and after.channel:
            await self.bot.log_action(guild, f"{E.VOICE_SW} Voice gewechselt",
                f"{member.mention}: {before.channel.mention} → {after.channel.mention}", COLOR_INFO, user=member, module="voice")

        # TempVoice: Auto-create
        tv_cfg = cfg.get("temp_voice", {})
        if tv_cfg.get("enabled") and after.channel:
            hub_id = tv_cfg.get("hub_channel_id")
            if hub_id and after.channel.id == hub_id:
                try:
                    category = after.channel.category
                    name_template = tv_cfg.get("name_template", "🔊 {user}'s Kanal")
                    ch_name = name_template.format(user=member.display_name)[:100]
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(connect=True),
                        member: discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True),
                        guild.me: discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True)
                    }
                    new_ch = await guild.create_voice_channel(ch_name, category=category, overwrites=overwrites,
                        reason=f"Temp-Voice für {member}")
                    await member.move_to(new_ch, reason="Temp-Voice erstellt")
                    await self.bot.db.tempvoice_channels.update_one(
                        {"guild_id": guild.id, "user_id": member.id},
                        {"$set": {"channel_id": new_ch.id, "created_at": discord.utils.utcnow()}},
                        upsert=True)
                except (discord.Forbidden, discord.HTTPException) as e:
                    log.debug(f"TempVoice create error: {e}")

        # TempVoice: Auto-delete when empty
        if before.channel and before.channel != after.channel:
            try:
                doc = await self.bot.db.tempvoice_channels.find_one(
                    {"guild_id": guild.id, "channel_id": before.channel.id})
                if doc and len(before.channel.members) == 0:
                    await before.channel.delete(reason="Temp-Voice: Leerer Kanal")
                    await self.bot.db.tempvoice_channels.delete_one(
                        {"guild_id": guild.id, "channel_id": before.channel.id})
            except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                pass

    # ── APPEAL DM HANDLER ──
    async def _handle_appeal_dm(self, message: discord.Message) -> bool:
        user_id = message.author.id
        content = message.content.strip()
        if user_id in appeal_sessions:
            session = appeal_sessions[user_id]
            if content.lower() == "!abbruch":
                del appeal_sessions[user_id]
                await message.author.send(embed=create_embed("🚫 Appeal abgebrochen", "Antrag abgebrochen.", COLOR_WARNING))
                return True
            step = session["step"]
            if step == -1:
                if content.lower() == "!start":
                    session["step"] = 0
                    await message.author.send(embed=create_embed("📋 Entbannungs-Antrag", APPEAL_QUESTIONS[0], COLOR_PRIMARY))
                return True
            session["answers"][APPEAL_KEYS[step]] = content
            session["step"] += 1
            if session["step"] < len(APPEAL_QUESTIONS):
                await message.author.send(embed=create_embed(f"{E.OK} Gespeichert", APPEAL_QUESTIONS[session["step"]], COLOR_INFO))
            else:
                await self._submit_appeal(message.author, session)
                del appeal_sessions[user_id]
            return True
        return False

    async def _submit_appeal(self, user, session):
        from bot.bot import AppealActionView
        guild = self.bot.get_guild(session["guild_id"])
        if not guild:
            await user.send(embed=create_embed(f"{E.FAIL} Fehler", "Server nicht gefunden.", COLOR_DANGER))
            return
        answers = session["answers"]
        cfg = self.bot.db.get_config(guild.id)
        log_ch_id = cfg.get("appeal_log_channel")
        if not log_ch_id:
            await user.send(embed=create_embed(f"{E.FAIL} Fehler", "Kein Appeal-Kanal konfiguriert.", COLOR_DANGER))
            return
        channel = guild.get_channel(log_ch_id)
        if not channel:
            return
        embed = create_embed(f"📋 Entbannungs-Antrag von {user}",
            f"**User:** {user.mention} (`{user.id}`)\n**Server:** {guild.name}", COLOR_PRIMARY,
            [(q.split("–")[-1].strip() if "–" in q else q, answers.get(k, "—"), False)
             for q, k in zip(APPEAL_QUESTIONS, APPEAL_KEYS)])
        embed.set_footer(text=f"UserID: {user.id} | {guild.name}", icon_url=user.display_avatar.url if user.display_avatar else None)
        appeal_data = {"user_id": user.id, "guild_id": guild.id}
        view = AppealActionView(bot_ref=self.bot, appeal_data=appeal_data)
        await channel.send(embed=embed, view=view)
        await user.send(embed=create_embed(f"{E.OK} Antrag gesendet!", "Das Team wird sich deinen Antrag ansehen.", COLOR_SUCCESS))


async def setup(bot):
    await bot.add_cog(EventsCog(bot))
