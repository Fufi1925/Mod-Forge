# -*- coding: utf-8 -*-
"""ModForge Events Cog – Alle Event-Handler (konsolidiert, keine Duplikate)."""
import asyncio
import datetime
import re
import time
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
    """Alle Discord-Events – zentral, keine Duplikate."""

    def __init__(self, bot):
        self.bot = bot

    async def _nuke_event(self, guild, user_id, action):
        """Leitet Nuke-Events an den SecurityCog weiter (der hat die volle Engine)."""
        sec = self.bot.get_cog("SecurityCog")
        if sec:
            await sec._track_nuke_event(guild, user_id, action)
        else:
            # Fallback: basic nuke check direkt
            cfg = self.bot.db.get_config(guild.id)
            nuke_cfg = cfg.get("anti_nuke", {})
            if not nuke_cfg.get("enabled"):
                return
            member = guild.get_member(user_id)
            if member and self.bot.is_whitelisted(member, "bypass_antinuke"):
                return
            dq = self.bot.tracker.nuke_tracker[guild.id][user_id]
            dq.append(time.time())
            self.bot.tracker.clean_old(dq, nuke_cfg.get("window", 10))
            if len(dq) >= nuke_cfg.get("threshold", 5):
                dq.clear()
                if member:
                    try:
                        await member.ban(reason=f"Anti-Nuke: {action}")
                    except Exception:
                        pass
                await self.bot.log_action(guild, f"{E.NUKE} NUKE ERKANNT",
                    f"**User:** <@{user_id}>\n**Aktion:** {action}", COLOR_DANGER, module="antinuke")

    # ── LOCKDOWN HELPERS ──
    async def _activate_lockdown(self, guild):
        for channel in guild.text_channels:
            try:
                await channel.set_permissions(guild.default_role, send_messages=False, reason="Anti-Raid Lockdown")
            except Exception:
                pass
        await self.bot.log_action(guild, f"{E.LOCK} LOCKDOWN AKTIVIERT", "Alle Kanäle gesperrt.", COLOR_DANGER, module="antiraid")

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
                age_h = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).total_seconds() / 3600
                if age_h < 24 and not member.avatar and (member.name.startswith("user") or len(member.name) < 4):
                    action = vpn_cfg.get("action", "kick")
                    try:
                        if action == "ban":
                            await member.ban(reason="Anti-VPN: Verdächtiger Account")
                        else:
                            await member.kick(reason="Anti-VPN: Verdächtiger Account")
                        await self.bot.log_action(guild, f"{E.SHIELD} Anti-VPN",
                            f"{member.mention} – {int(age_h)}h alt", COLOR_WARNING, user=member, module="antiraid")
                    except discord.Forbidden:
                        pass

        # Security levels
        if sec_level >= 2:
            age = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).days
            if age < 5:
                try:
                    await member.kick(reason="Sicherheitsstufe 2: Account zu jung")
                    await self.bot.log_action(guild, f"{E.SHIELD} Stufe 2: Kick",
                        f"{member.mention} ({age} Tage)", COLOR_DANGER, user=member, module="antiraid")
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
            min_age = raid_cfg.get("min_account_age", 7)
            age = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).days
            if age < min_age and raid_cfg.get("auto_kick"):
                try:
                    await member.kick(reason=f"Anti-Raid: Account zu jung ({age}d)")
                    await self.bot.log_action(guild, f"{E.NEWACC} Account gekickt",
                        f"{member.mention} ({age}d)", COLOR_DANGER, user=member, module="antiraid")
                    return
                except discord.Forbidden:
                    pass
            if raid_cfg.get("suspicious_name_check") and SUSPICIOUS_NAME_REGEX.match(member.name):
                await self.bot.log_action(guild, f"{E.RAID} Verdächtiger Name",
                    f"{member.mention} (`{member.name}`)", COLOR_WARNING, user=member, module="antiraid")
            if len(dq) >= raid_cfg.get("join_threshold", 10):
                dq.clear()
                if not self.bot.tracker.lockdown_active[guild.id] and raid_cfg.get("lockdown"):
                    self.bot.tracker.lockdown_active[guild.id] = True
                    await self._activate_lockdown(guild)
                await self.bot.log_action(guild, f"{E.NUKE} RAID ERKANNT", "Zu viele Beitritte!", COLOR_DANGER, module="antiraid")

        if member.bot:
            nuke_cfg = cfg.get("anti_nuke", {})
            if nuke_cfg.get("enabled"):
                try:
                    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
                        await self._nuke_event(guild, entry.user.id, "bot_add")
                except discord.Forbidden:
                    pass
            await self.bot.log_action(guild, f"{E.BOT} Bot hinzugefügt", f"{member.mention}", COLOR_WARNING, user=member, module="members")
            return

        await self.bot.log_action(guild, f"{E.JOIN} Mitglied beigetreten", f"{member.mention}", COLOR_SUCCESS, user=member, module="members")

        try:
            wc = self.bot.get_cog("WelcomeCog")
            if wc:
                await wc.send_welcome(member)
                await wc.restore_sticky_roles(member)
        except Exception:
            pass

    # ── ON_MESSAGE ──
    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            if not message.guild and not message.author.bot:
                await self._handle_appeal_dm(message)
            return

        guild = message.guild
        member = message.author
        cfg = self.bot.db.get_config(guild.id)
        content = message.content or ""

        # Message archive
        if cfg.get("message_archive", {}).get("enabled"):
            try:
                await self.bot.db.arecord_message(guild.id, message.channel.id, message.id, member.id,
                    content, [a.url for a in message.attachments][:10])
            except Exception:
                pass

        # Ghost-Ping tracking
        if message.mentions and cfg.get("anti_ghost_ping", {}).get("enabled"):
            real = [m for m in message.mentions if not m.bot and m.id != member.id]
            if real:
                self.bot.tracker.ghost_tracker[guild.id][message.id] = (member.id, [m.id for m in real])

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
                try: await message.delete()
                except Exception: pass
                await self.bot.punish(member, spam_cfg.get("punishment", "timeout"),
                    "Anti-Spam: Nachrichtenflut", spam_cfg.get("timeout_duration", 30))
                await self.bot.log_action(guild, f"{E.SPAM} Spam erkannt", f"{member.mention}", COLOR_WARNING, user=member, module="antispam")
                return
            if len(content) > 10:
                caps = sum(1 for c in content if c.isupper()) / max(1, len(content)) * 100
                if caps > spam_cfg.get("caps_pct", 70):
                    try: await message.delete()
                    except Exception: pass
                    await self.bot.punish(member, spam_cfg.get("punishment", "timeout"),
                        "Anti-Spam: CAPS", spam_cfg.get("timeout_duration", 30))
                    await self.bot.log_action(guild, f"{E.CAPS} CAPS-Spam", f"{member.mention}", COLOR_WARNING, user=member, module="antispam")
                    return
            emoji_count = len(re.findall(r"<a?:\w+:\d+>|[\U0001F000-\U0001FFFF]", content))
            if emoji_count > spam_cfg.get("emoji_max", 10):
                try: await message.delete()
                except Exception: pass
                await self.bot.punish(member, spam_cfg.get("punishment", "timeout"),
                    "Anti-Spam: Emoji-Spam", spam_cfg.get("timeout_duration", 30))
                return
            dl = self.bot.tracker.dup_tracker[guild.id][member.id]
            dl.append(content.lower().strip())
            if len(dl) > 10: dl.pop(0)
            if dl.count(content.lower().strip()) > spam_cfg.get("duplicate_max", 3):
                try: await message.delete()
                except Exception: pass
                await self.bot.punish(member, spam_cfg.get("punishment", "timeout"),
                    "Anti-Spam: Duplikate", spam_cfg.get("timeout_duration", 30))
                return

        # AutoMod (basic – erweiterte Filter im AutoModCog)
        am = cfg.get("automod", {})
        if am.get("enabled"):
            for word in am.get("bad_words", []):
                try:
                    if re.search(rf"\b{re.escape(word)}\b", content, re.IGNORECASE):
                        try: await message.delete()
                        except Exception: pass
                        await self.bot.punish(member, am.get("punishment", "warn"), "AutoMod: Verbotenes Wort")
                        await self.bot.log_action(guild, f"{E.BADWORD} Verbotenes Wort", f"{member.mention}", COLOR_DANGER, user=member, module="automod")
                        return
                except re.error: continue
            for pat in am.get("regex_rules", []):
                try:
                    if re.search(pat, content):
                        try: await message.delete()
                        except Exception: pass
                        await self.bot.punish(member, am.get("punishment", "warn"), "AutoMod: Regex")
                        return
                except re.error: continue
            if am.get("invite_filter") and INVITE_REGEX.search(content):
                try: await message.delete()
                except Exception: pass
                await self.bot.punish(member, am.get("punishment", "warn"), "AutoMod: Invite-Link")
                await self.bot.log_action(guild, f"{E.BADWORD} Invite-Link", f"{member.mention}", COLOR_DANGER, user=member, module="automod")
                return
            if am.get("link_filter"):
                urls = URL_REGEX.findall(content)
                allowed = am.get("allowed_domains", [])
                for url in urls:
                    domain = re.sub(r"https?://([^/]+).*", r"\1", url).lower()
                    if not any(domain.endswith(d.lower()) for d in allowed):
                        try: await message.delete()
                        except Exception: pass
                        await self.bot.punish(member, am.get("punishment", "warn"), "AutoMod: Link")
                        return
            if am.get("zalgo_filter") and ZALGO_REGEX.search(content):
                try: await message.delete()
                except Exception: pass
                await self.bot.punish(member, am.get("punishment", "warn"), "AutoMod: Zalgo")
                return
            if am.get("phishing_check") and URL_REGEX.search(content):
                if await check_phishing_url(content):
                    try: await message.delete()
                    except Exception: pass
                    await self.bot.punish(member, am.get("punishment", "warn"), "AutoMod: Phishing")
                    await self.bot.log_action(guild, f"{E.NUKE} Phishing", f"{member.mention}", COLOR_DANGER, user=member, module="automod")
                    return

        # Anti-Scam
        sc = cfg.get("anti_scam", {})
        if sc.get("enabled"):
            for d in SCAM_DOMAINS:
                if d.lower() in content.lower():
                    try: await message.delete()
                    except Exception: pass
                    await self.bot.punish(member, sc.get("punishment", "ban"), f"Anti-Scam: {d}")
                    await self.bot.log_action(guild, f"{E.SCAM} Scam-Link", f"{member.mention}", COLOR_DANGER, user=member, module="antiscam")
                    return

        # Anti-URL-Shortener
        sh = cfg.get("anti_url_shortener", {})
        if sh.get("enabled"):
            for s in URL_SHORTENERS:
                if s.lower() in content.lower():
                    try: await message.delete()
                    except Exception: pass
                    await self.bot.punish(member, sh.get("punishment", "warn"), "Anti-URL-Shortener")
                    return

        # Anti-Mention
        mc = cfg.get("anti_mention", {})
        if mc.get("enabled") and (message.mentions or message.role_mentions):
            total = len(message.mentions) + len(message.role_mentions)
            now = time.time()
            dq = self.bot.tracker.mention_tracker[guild.id][member.id]
            for _ in range(total): dq.append(now)
            self.bot.tracker.clean_old(dq, mc.get("window", 10))
            if len(dq) > mc.get("mention_limit", 5):
                try: await message.delete()
                except Exception: pass
                await self.bot.punish(member, mc.get("punishment", "timeout"),
                    "Anti-Mention: Spam", mc.get("timeout_duration", 60))
                await self.bot.log_action(guild, f"{E.MENTION} Mention-Spam", f"{member.mention}", COLOR_DANGER, user=member, module="antimention")
                return

    # ── ON_MESSAGE_DELETE ──
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot: return
        guild = message.guild
        cfg = self.bot.db.get_config(guild.id)
        if cfg.get("anti_ghost_ping", {}).get("enabled") and message.id in self.bot.tracker.ghost_tracker.get(guild.id, {}):
            data = self.bot.tracker.ghost_tracker[guild.id].pop(message.id)
            author = guild.get_member(data[0])
            mentions = [guild.get_member(uid) for uid in data[1] if guild.get_member(uid)]
            mention_str = ", ".join(m.mention for m in mentions if m) or "?"
            await self.bot.log_action(guild, f"{E.GHOST} Ghost-Ping",
                f"**{author.mention if author else '?'}** hat Mentions gelöscht.",
                COLOR_WARNING, [("Gepingt", mention_str, False)], user=author, module="ghostping")
            return
        try: await self.bot.db.amark_message_deleted(guild.id, message.id)
        except Exception: pass
        await self.bot.log_action(guild, f"{E.DELETE} Nachricht gelöscht",
            f"{message.author.mention} in {message.channel.mention}",
            COLOR_INFO, [("Inhalt", message.content[:1000] or "*(leer)*", False)], user=message.author, module="messages")
        _snipe_cache.setdefault(guild.id, {})[message.channel.id] = {
            "content": message.content[:1500], "author": message.author,
            "ts": time.time(), "attachments": [a.url for a in message.attachments][:3]}

    # ── ON_MESSAGE_EDIT ──
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.author.bot or before.content == after.content: return
        try: await self.bot.db.aappend_message_edit(before.guild.id, before.id, before.content or "")
        except Exception: pass
        await self.bot.log_action(before.guild, f"{E.EDIT} Nachricht bearbeitet",
            f"{before.author.mention} in {before.channel.mention}", COLOR_INFO,
            [("Vorher", before.content[:500] or "*(leer)*", False), ("Nachher", after.content[:500] or "*(leer)*", False)],
            user=before.author, module="messages")

    # ── ON_MEMBER_UPDATE ──
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.bot: return
        guild = after.guild
        if before.nick != after.nick:
            await self.bot.log_action(guild, f"{E.NICK} Nickname geändert",
                f"{after.mention}: `{before.nick or before.name}` → `{after.nick or after.name}`", COLOR_INFO, user=after, module="nicknames")
        for role in set(after.roles) - set(before.roles):
            await self.bot.log_action(guild, f"{E.ROLE_ADD} Rolle hinzugefügt", f"{after.mention} → {role.mention}", COLOR_SUCCESS, user=after, module="roles")
        for role in set(before.roles) - set(after.roles):
            await self.bot.log_action(guild, f"{E.ROLE_DEL} Rolle entfernt", f"{after.mention} ← {role.mention}", COLOR_WARNING, user=after, module="roles")

    # ── CHANNEL/ROLE EVENTS (Log + Nuke-Weiterleitung) ──
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        guild = channel.guild
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
                if entry.user.id != self.bot.user.id:
                    action = "voice_delete" if isinstance(channel, discord.VoiceChannel) else "channel_delete"
                    await self._nuke_event(guild, entry.user.id, action)
                break
        except discord.Forbidden: pass
        await self.bot.log_action(guild, f"{E.DELETE} Kanal gelöscht", f"**{channel.name}**", COLOR_DANGER, module="channels")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if isinstance(channel, discord.CategoryChannel):
            try:
                async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
                    if entry.user.id != self.bot.user.id:
                        await self._nuke_event(channel.guild, entry.user.id, "category_create")
                    break
            except discord.Forbidden: pass
        await self.bot.log_action(channel.guild, f"{E.PLUS} Kanal erstellt", f"{channel.mention}", COLOR_SUCCESS, module="channels")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        try:
            async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
                if entry.user.id != self.bot.user.id:
                    await self._nuke_event(role.guild, entry.user.id, "role_delete")
                break
        except discord.Forbidden: pass
        await self.bot.log_action(role.guild, f"{E.DELETE} Rolle gelöscht", f"**{role.name}**", COLOR_DANGER, module="roles")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.bot.log_action(role.guild, f"{E.PLUS} Rolle erstellt", f"{role.mention}", COLOR_SUCCESS, module="roles")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                if entry.user.id != self.bot.user.id:
                    await self._nuke_event(guild, entry.user.id, "ban")
                break
        except discord.Forbidden: pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        ACTIVITY.push("leave", f"{member} hat **{guild.name}** verlassen.",
                      guild_id=guild.id, guild_name=guild.name, user_id=member.id, user_name=str(member))
        await self.bot.log_action(guild, f"{E.KICK} Mitglied verlassen", f"{member.mention}", COLOR_WARNING, user=member, module="members")
        try:
            cfg = self.bot.db.get_config(guild.id)
            sticky = cfg.get("sticky_roles", [])
            if sticky:
                roles = [r.id for r in member.roles if r.id in sticky]
                if roles:
                    await self.bot.db.data.update_one(
                        {"guild_id": guild.id, "user_id": member.id, "type": "sticky_roles"},
                        {"$set": {"roles": roles, "updated_at": discord.utils.utcnow()}}, upsert=True)
        except Exception: pass
        try:
            wc = self.bot.get_cog("WelcomeCog")
            if wc: await wc.send_leave(member)
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        ACTIVITY.push("guild_join", f"Bot zu **{guild.name}** hinzugefügt.", guild_id=guild.id, guild_name=guild.name)
        await self.bot.db.arecord_guild_event(guild.id, guild.name, guild.member_count or 0, "join")
        log.info(f"Guild beigetreten: {guild.name} ({guild.id})")
        try:
            if guild.me.guild_permissions.manage_guild:
                invites = await guild.invites()
                self.bot.tracker.invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except Exception: pass
        try:
            target = guild.system_channel or next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages), None)
            if target:
                await target.send(embed=create_embed(f"{E.SHIELD} ModForge – Security Bot",
                    f"Danke für die Einladung zu **{guild.name}**!\n\nNutze `/setup` um mich zu konfigurieren.\nNutze `/help` für alle Commands.", COLOR_PRIMARY))
        except Exception: pass

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        ACTIVITY.push("guild_leave", f"Bot von **{guild.name}** entfernt.", guild_id=guild.id, guild_name=guild.name)
        await self.bot.db.arecord_guild_event(guild.id, guild.name, guild.member_count or 0, "leave")
        log.info(f"Guild verlassen: {guild.name} ({guild.id})")

    # ── VOICE STATE ──
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild
        cfg = self.bot.db.get_config(guild.id)
        if before.channel is None and after.channel is not None:
            await self.bot.log_action(guild, f"{E.VOICE_IN} Voice beigetreten", f"{member.mention} → {after.channel.mention}", COLOR_SUCCESS, user=member, module="voice")
        elif before.channel is not None and after.channel is None:
            await self.bot.log_action(guild, f"{E.VOICE_OUT} Voice verlassen", f"{member.mention} ← {before.channel.mention}", COLOR_WARNING, user=member, module="voice")
        elif before.channel != after.channel and before.channel and after.channel:
            await self.bot.log_action(guild, f"{E.VOICE_SW} Voice gewechselt", f"{member.mention}: {before.channel.mention} → {after.channel.mention}", COLOR_INFO, user=member, module="voice")
        # TempVoice
        tv = cfg.get("temp_voice", {})
        if tv.get("enabled") and after.channel and tv.get("hub_channel_id") == getattr(after.channel, "id", None):
            try:
                cat = after.channel.category
                name = tv.get("name_template", "🔊 {user}'s Kanal").format(user=member.display_name)[:100]
                ow = {guild.default_role: discord.PermissionOverwrite(connect=True),
                      member: discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True),
                      guild.me: discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True)}
                ch = await guild.create_voice_channel(name, category=cat, overwrites=ow, reason=f"Temp-Voice für {member}")
                await member.move_to(ch, reason="Temp-Voice erstellt")
                await self.bot.db.tempvoice_channels.update_one(
                    {"guild_id": guild.id, "user_id": member.id},
                    {"$set": {"channel_id": ch.id, "created_at": discord.utils.utcnow()}}, upsert=True)
            except Exception: pass
        if before.channel and before.channel != after.channel:
            try:
                doc = await self.bot.db.tempvoice_channels.find_one({"guild_id": guild.id, "channel_id": before.channel.id})
                if doc and len(before.channel.members) == 0:
                    await before.channel.delete(reason="Temp-Voice: Leer")
                    await self.bot.db.tempvoice_channels.delete_one({"guild_id": guild.id, "channel_id": before.channel.id})
            except Exception: pass

    # ── APPEAL DM ──
    async def _handle_appeal_dm(self, message):
        uid = message.author.id
        content = message.content.strip()
        if uid not in appeal_sessions: return False
        session = appeal_sessions[uid]
        if content.lower() == "!abbruch":
            del appeal_sessions[uid]
            await message.author.send(embed=create_embed(f"{E.FAIL} Abgebrochen", "Appeal abgebrochen.", COLOR_WARNING))
            return True
        step = session["step"]
        if step == -1:
            if content.lower() == "!start":
                session["step"] = 0
                await message.author.send(embed=create_embed(f"{E.APPEAL} Entbannungs-Antrag", APPEAL_QUESTIONS[0], COLOR_PRIMARY))
            return True
        session["answers"][APPEAL_KEYS[step]] = content
        session["step"] += 1
        if session["step"] < len(APPEAL_QUESTIONS):
            await message.author.send(embed=create_embed(f"{E.OK} Gespeichert", APPEAL_QUESTIONS[session["step"]], COLOR_INFO))
        else:
            await self._submit_appeal(message.author, session)
            del appeal_sessions[uid]
        return True

    async def _submit_appeal(self, user, session):
        from bot.bot import AppealActionView
        guild = self.bot.get_guild(session["guild_id"])
        if not guild:
            await user.send(embed=create_embed(f"{E.FAIL}", "Server nicht gefunden.", COLOR_DANGER))
            return
        cfg = self.bot.db.get_config(guild.id)
        ch = guild.get_channel(cfg.get("appeal_log_channel"))
        if not ch: return
        embed = create_embed(f"{E.APPEAL} Appeal von {user}",
            f"**User:** {user.mention} (`{user.id}`)\n**Server:** {guild.name}", COLOR_PRIMARY,
            [(q.split("–")[-1].strip() if "–" in q else q, session["answers"].get(k, "—"), False) for q, k in zip(APPEAL_QUESTIONS, APPEAL_KEYS)])
        embed.set_footer(text=f"UserID: {user.id} | {guild.name}", icon_url=user.display_avatar.url if user.display_avatar else None)
        view = AppealActionView(bot_ref=self.bot, appeal_data={"user_id": user.id, "guild_id": guild.id})
        await ch.send(embed=embed, view=view)
        await user.send(embed=create_embed(f"{E.OK} Gesendet!", "Das Team prüft deinen Antrag.", COLOR_SUCCESS))


async def setup(bot):
    await bot.add_cog(EventsCog(bot))
