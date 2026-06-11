# -*- coding: utf-8 -*-
"""
ModForge Security Cog – Erweitert mit Features 1-50
Nuke-Prävention, Server-Schutz, Raid-Erkennung, Whitelist, AutoMod-Config.
"""
import asyncio
import datetime
import time
from collections import defaultdict, deque
from typing import Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands

from bot.config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_INFO, E, log,
)
from bot.utils import create_embed
from bot.bot import safe_dm

# ═══════════════════════════════════════════════════════════════
# IN-MEMORY TRACKER für Nuke-Detection
# ═══════════════════════════════════════════════════════════════
_nuke_events: dict = defaultdict(lambda: defaultdict(deque))   # guild -> user -> deque(ts)
_nuke_attempt_counter: dict = defaultdict(lambda: defaultdict(int))  # guild -> user -> count
_multi_server_raid: dict = defaultdict(deque)  # user_id -> deque(guild_id, ts)
_server_snapshots: dict = {}   # guild_id -> snapshot dict
_perm_freeze: dict = {}        # guild_id -> {channel_id: overwrites}
_suspicious_event_counter: dict = defaultdict(lambda: deque(maxlen=50))  # guild -> deque(ts)


class SecurityCog(commands.Cog):
    """Nuke-Prävention, Server-Schutz, Raid-Erkennung, Whitelist, AutoMod-Config."""

    def __init__(self, bot):
        self.bot = bot
        self.snapshot_loop.start()

    def cog_unload(self):
        self.snapshot_loop.cancel()

    # ══════════════════════════════════════════════════
    # SNAPSHOT SYSTEM (Feature 31, 46)
    # ══════════════════════════════════════════════════
    @tasks.loop(hours=6)
    async def snapshot_loop(self):
        """Auto-Backup alle 6 Stunden + Snapshot für Vergleich."""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                _server_snapshots[guild.id] = await self._take_snapshot(guild)
            except Exception as e:
                log.debug(f"Snapshot error {guild.id}: {e}")

    async def _take_snapshot(self, guild: discord.Guild) -> dict:
        return {
            "ts": time.time(),
            "roles": {r.id: {"name": r.name, "perms": r.permissions.value, "pos": r.position} for r in guild.roles if not r.is_default()},
            "channels": {c.id: {"name": c.name, "type": str(c.type)} for c in guild.channels},
            "categories": {c.id: c.name for c in guild.categories},
            "icon_hash": str(guild.icon) if guild.icon else None,
            "banner_hash": str(guild.banner) if guild.banner else None,
            "vanity": guild.vanity_url_code,
            "member_count": guild.member_count,
        }

    async def _compare_snapshot(self, guild: discord.Guild) -> dict:
        """Vergleicht aktuellen Zustand mit letztem Snapshot (Feature 31)."""
        old = _server_snapshots.get(guild.id)
        if not old:
            return {"changes": 0}
        current = await self._take_snapshot(guild)
        changes = {"deleted_channels": [], "deleted_roles": [], "new_channels": [], "new_roles": [],
                    "icon_changed": False, "banner_changed": False, "changes": 0}
        for cid in old["channels"]:
            if cid not in current["channels"]:
                changes["deleted_channels"].append(old["channels"][cid]["name"])
                changes["changes"] += 1
        for cid in current["channels"]:
            if cid not in old["channels"]:
                changes["new_channels"].append(current["channels"][cid]["name"])
                changes["changes"] += 1
        for rid in old["roles"]:
            if rid not in current["roles"]:
                changes["deleted_roles"].append(old["roles"][rid]["name"])
                changes["changes"] += 1
        changes["icon_changed"] = old["icon_hash"] != current["icon_hash"]
        changes["banner_changed"] = old["banner_hash"] != current["banner_hash"]
        if changes["icon_changed"]:
            changes["changes"] += 1
        if changes["banner_changed"]:
            changes["changes"] += 1
        return changes

    # ══════════════════════════════════════════════════
    # NUKE DETECTION ENGINE (Features 1-33, 42-45)
    # ══════════════════════════════════════════════════
    async def _track_nuke_event(self, guild: discord.Guild, user_id: int, action: str):
        """Zentrale Nuke-Event-Tracking-Funktion."""
        cfg = self.bot.db.get_config(guild.id)
        np = cfg.get("nuke_protection", {})
        if not np.get("enabled", True):
            return

        # Whitelist check (Feature 29)
        if user_id in np.get("nuke_whitelist", []):
            return
        member = guild.get_member(user_id)
        if member and self.bot.is_whitelisted(member, "bypass_antinuke"):
            return

        window = np.get("window", 15)
        now = time.time()

        # Track suspicious events (Feature 16)
        _suspicious_event_counter[guild.id].append(now)
        recent_suspicious = sum(1 for t in _suspicious_event_counter[guild.id] if now - t < 60)

        # Per-user nuke tracking
        dq = _nuke_events[guild.id][user_id]
        dq.append(now)
        while dq and now - dq[0] > window:
            dq.popleft()

        # Determine limits based on action type
        limits = {
            "channel_delete": np.get("channel_mass_delete_limit", 3),
            "role_delete": np.get("role_mass_delete_limit", 3),
            "bot_add": np.get("bot_mass_add_limit", 3),
            "emoji_delete": np.get("emoji_mass_delete_limit", 5),
            "category_create": np.get("category_mass_create_limit", 3),
            "voice_delete": np.get("voice_mass_delete_limit", 3),
            "invite_delete": np.get("invite_mass_delete_limit", 5),
            "ban": 5, "kick": 5, "webhook_create": 3,
        }
        limit = limits.get(action, 5)

        if len(dq) < limit:
            return  # Unter dem Limit

        dq.clear()

        # ── NUKE ERKANNT ──
        log.warning(f"NUKE DETECTED: Guild {guild.name}, User {user_id}, Action {action}")

        # Nuke-Attempt Counter (Feature 27)
        _nuke_attempt_counter[guild.id][user_id] += 1
        attempt_count = _nuke_attempt_counter[guild.id][user_id]

        # Nuke-Attempt-Log mit Tracking (Feature 12)
        await self.bot.db.data.insert_one({
            "type": "nuke_attempt", "guild_id": guild.id, "user_id": user_id,
            "action": action, "attempt_number": attempt_count,
            "timestamp": datetime.datetime.utcnow(),
        })

        # Punishment
        if member:
            try:
                nuke_cfg = cfg.get("anti_nuke", {})
                punishment = nuke_cfg.get("punishment", "ban")
                if punishment == "ban":
                    await member.ban(reason=f"Anti-Nuke: {action} (Attempt #{attempt_count})")
                elif punishment == "kick":
                    await member.kick(reason=f"Anti-Nuke: {action}")
                if nuke_cfg.get("remove_roles"):
                    for role in member.roles[1:]:
                        try:
                            await member.remove_roles(role, reason="Anti-Nuke: Rollen entfernt")
                        except Exception:
                            pass
            except (discord.Forbidden, discord.HTTPException):
                pass

        # Multi-Nuke-Attempt = Permaban (Feature 28)
        permaban_threshold = np.get("nuke_attempt_permaban_threshold", 3)
        if attempt_count >= permaban_threshold and member:
            try:
                await member.ban(reason=f"Anti-Nuke: {attempt_count} Nuke-Versuche → Permaban", delete_message_seconds=604800)
            except Exception:
                pass

        # Auto-Backup bei Nuke (Feature 1)
        if np.get("auto_backup_on_nuke"):
            try:
                backup_cog = self.bot.get_cog("BackupCog")
                if backup_cog:
                    data = await backup_cog._collect_backup_data(guild)
                    await backup_cog._backup_db_save(data, self.bot.user.id, f"Nuke-Backup ({action})")
                    log.info(f"Nuke-Auto-Backup für {guild.name} erstellt")
            except Exception as e:
                log.error(f"Nuke-Auto-Backup Fehler: {e}")

        # Channel-Permissions-Freeze (Feature 17)
        if np.get("freeze_perms_on_nuke"):
            await self._freeze_permissions(guild)

        # Auto-Restore (Feature 2, 25, 26)
        if np.get("auto_restore_on_nuke"):
            await self._auto_restore(guild)

        # Alert alle Admins (Feature 33)
        if np.get("alert_all_admins"):
            await self._alert_all_admins(guild, user_id, action, attempt_count)

        # Emergency Contacts (Feature 30)
        for contact_id in np.get("emergency_contacts", []):
            try:
                user = await self.bot.fetch_user(contact_id)
                embed = create_embed(f"{E.NUKE} NUKE-ALARM: {guild.name}",
                    f"**Verdächtig:** <@{user_id}>\n**Aktion:** {action}\n**Versuch:** #{attempt_count}",
                    COLOR_DANGER)
                await safe_dm(user, embed, cooldown_key=f"emergency:{guild.id}:{user_id}")
            except Exception:
                pass

        # Nuke-Attempt-Notification an Owner (Feature 11)
        if guild.owner:
            embed = create_embed(f"{E.NUKE} NUKE-VERSUCH #{attempt_count}",
                f"**Server:** {guild.name}\n**Verdächtig:** <@{user_id}>\n**Aktion:** {action}\n"
                f"**Auto-Backup:** {f'{E.OK}' if np.get('auto_backup_on_nuke') else f'{E.FAIL}'}\n"
                f"**Auto-Restore:** {f'{E.OK}' if np.get('auto_restore_on_nuke') else f'{E.FAIL}'}",
                COLOR_DANGER)
            await safe_dm(guild.owner, embed, cooldown_key=f"nuke:{guild.id}:{user_id}")

        await self.bot.log_action(guild, f"{E.NUKE} NUKE ERKANNT",
            f"**User:** <@{user_id}>\n**Aktion:** {action}\n**Versuch:** #{attempt_count}\n"
            f"**Maßnahme:** {cfg.get('anti_nuke', {}).get('punishment', 'ban')}",
            COLOR_DANGER, module="antinuke")

        # Auto-Backup bei 3+ verdächtigen Events (Feature 16)
        if recent_suspicious >= 3 and np.get("auto_backup_on_nuke"):
            try:
                backup_cog = self.bot.get_cog("BackupCog")
                if backup_cog:
                    data = await backup_cog._collect_backup_data(guild)
                    await backup_cog._backup_db_save(data, self.bot.user.id, "Verdacht-Auto-Backup")
            except Exception:
                pass

    async def _freeze_permissions(self, guild: discord.Guild):
        """Friert Channel-Permissions ein (Feature 17)."""
        _perm_freeze[guild.id] = {}
        for ch in guild.text_channels[:50]:
            try:
                overwrites = {str(t.id): {"allow": p.pair()[0].value, "deny": p.pair()[1].value}
                              for t, p in ch.overwrites.items()}
                _perm_freeze[guild.id][ch.id] = overwrites
                await ch.set_permissions(guild.default_role, send_messages=False, reason="Nuke-Freeze")
            except Exception:
                pass
        await self.bot.log_action(guild, f"{E.LOCK} Permissions eingefroren",
            "Alle Kanäle wurden gesperrt (Nuke-Prävention).", COLOR_DANGER, module="antinuke")

    async def _auto_restore(self, guild: discord.Guild):
        """Auto-Restore Channel/Role-Struktur (Feature 2, 25, 26)."""
        snapshot = _server_snapshots.get(guild.id)
        if not snapshot:
            return
        restored = 0
        # Restore deleted channels
        current_channels = {c.id for c in guild.channels}
        for cid, cdata in snapshot.get("channels", {}).items():
            if cid not in current_channels:
                try:
                    ch_type = cdata.get("type", "text")
                    if "voice" in ch_type:
                        await guild.create_voice_channel(cdata["name"], reason="Auto-Restore")
                    else:
                        await guild.create_text_channel(cdata["name"], reason="Auto-Restore")
                    restored += 1
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
        # Restore deleted roles
        current_roles = {r.id for r in guild.roles}
        for rid, rdata in snapshot.get("roles", {}).items():
            if rid not in current_roles:
                try:
                    await guild.create_role(name=rdata["name"],
                        permissions=discord.Permissions(rdata.get("perms", 0)),
                        reason="Auto-Restore")
                    restored += 1
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
        if restored:
            await self.bot.log_action(guild, f"{E.OK} Auto-Restore",
                f"{restored} Kanäle/Rollen wiederhergestellt.", COLOR_SUCCESS, module="antinuke")

    async def _alert_all_admins(self, guild: discord.Guild, user_id: int, action: str, attempt: int):
        """Benachrichtigt alle Admins per DM (Feature 33)."""
        embed = create_embed(f"{E.NUKE} NUKE-ALARM",
            f"**Server:** {guild.name}\n**Verdächtig:** <@{user_id}>\n"
            f"**Aktion:** {action}\n**Versuch:** #{attempt}",
            COLOR_DANGER)
        for member in guild.members:
            if member.guild_permissions.administrator and not member.bot:
                try:
                    await safe_dm(member, embed, cooldown_key=f"admin_nuke:{guild.id}:{user_id}")
                except Exception:
                    pass
                await asyncio.sleep(0.2)

    # ══════════════════════════════════════════════════
    # EVENT LISTENERS (Channel/Role/Server Protection)
    # ══════════════════════════════════════════════════
    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        """Feature 9, 10: Role-Hierarchy + Admin-Permission Monitoring."""
        guild = after.guild
        cfg = self.bot.db.get_config(guild.id)
        sp = cfg.get("server_protection", {})
        if not sp.get("enabled", True):
            return
        # Admin-Permission-Monitoring (Feature 10)
        if sp.get("admin_perm_monitor"):
            dangerous = ["administrator", "manage_guild", "manage_roles", "ban_members", "manage_webhooks"]
            for perm in dangerous:
                if not getattr(before.permissions, perm, False) and getattr(after.permissions, perm, False):
                    try:
                        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
                            if entry.user.id != self.bot.user.id and entry.user.id != guild.owner_id:
                                await self.bot.log_action(guild, f"{E.PERM_WARN} Gefährliche Permission",
                                    f"**Rolle:** {after.mention}\n**Permission:** `{perm}`\n"
                                    f"**Von:** {entry.user.mention}",
                                    COLOR_DANGER, module="security")
                                await self._track_nuke_event(guild, entry.user.id, "perm_escalation")
                            break
                    except discord.Forbidden:
                        pass
        # Role-Hierarchy-Schutz (Feature 9)
        if sp.get("role_hierarchy_protect"):
            if after.position > before.position:
                bot_top = guild.me.top_role.position
                if after.position >= bot_top - 1:
                    try:
                        await after.edit(position=bot_top - 2, reason="Role-Hierarchy-Schutz")
                        await self.bot.log_action(guild, f"{E.HIERARCHY} Hierarchy-Schutz",
                            f"Rolle {after.mention} wurde zurückgesetzt.", COLOR_WARNING, module="security")
                    except Exception:
                        pass

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        """Feature 14, 15, 39, 40: Server-Transfer/Vanity/Icon/Banner-Schutz."""
        cfg = self.bot.db.get_config(after.id)
        sp = cfg.get("server_protection", {})
        if not sp.get("enabled", True):
            return
        # Server-Transfer-Schutz (Feature 14)
        if sp.get("server_transfer_protect") and before.owner_id != after.owner_id:
            await self.bot.log_action(after, f"{E.TRANSFER} SERVER-TRANSFER",
                f"**Alter Owner:** <@{before.owner_id}>\n**Neuer Owner:** <@{after.owner_id}>",
                COLOR_DANGER, module="security")
            if after.owner:
                await safe_dm(after.owner, create_embed(f"{E.TRANSFER} Server-Transfer",
                    f"Der Server **{after.name}** wurde transferiert!", COLOR_DANGER))
        # Vanity-URL-Schutz (Feature 15)
        if sp.get("vanity_url_protect") and before.vanity_url_code != after.vanity_url_code:
            await self.bot.log_action(after, f"{E.VANITY} Vanity-URL geändert",
                f"`{before.vanity_url_code}` → `{after.vanity_url_code}`", COLOR_WARNING, module="security")
        # Icon-Schutz (Feature 40)
        if sp.get("server_icon_protect") and str(before.icon) != str(after.icon):
            await self.bot.log_action(after, f"{E.ICON_CHANGE} Server-Icon geändert", "", COLOR_WARNING, module="security")
            try:
                async for entry in after.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
                    if entry.user.id != after.owner_id and entry.user.id != self.bot.user.id:
                        await self._track_nuke_event(after, entry.user.id, "icon_change")
                    break
            except discord.Forbidden:
                pass
        # Banner-Schutz (Feature 39)
        if sp.get("server_banner_protect") and str(before.banner) != str(after.banner):
            await self.bot.log_action(after, f"{E.BANNER_CHANGE} Server-Banner geändert", "", COLOR_WARNING, module="security")

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        """Feature 6, 37, 38: Webhook-Spam-Schutz."""
        guild = channel.guild
        cfg = self.bot.db.get_config(guild.id)
        sp = cfg.get("server_protection", {})
        if not sp.get("enabled", True):
            return
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
                if entry.user.id != self.bot.user.id:
                    await self._track_nuke_event(guild, entry.user.id, "webhook_create")
                break
        except discord.Forbidden:
            pass
        # Auto-Regenerate Webhooks (Feature 38)
        if sp.get("auto_regen_webhooks"):
            try:
                webhooks = await channel.webhooks()
                suspicious = [w for w in webhooks if not w.user or w.user.id != self.bot.user.id]
                if len(suspicious) > sp.get("webhook_spam_limit", 5):
                    for wh in suspicious:
                        try:
                            await wh.delete(reason="Webhook-Spam-Schutz")
                        except Exception:
                            pass
                    await self.bot.log_action(guild, f"{E.WEBHOOK} Webhooks bereinigt",
                        f"{len(suspicious)} verdächtige Webhooks in {channel.mention} gelöscht.",
                        COLOR_WARNING, module="security")
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Feature 3, 5, 18, 34: Multi-Server-Raid, Bot-Approval, Timezone-Raid."""
        if not member.guild:
            return
        guild = member.guild
        cfg = self.bot.db.get_config(guild.id)

        # Bot-Add-Approval-System (Feature 5)
        if member.bot:
            sp = cfg.get("server_protection", {})
            if sp.get("bot_approval_required"):
                approval_ch = guild.get_channel(sp.get("bot_approval_channel")) if sp.get("bot_approval_channel") else None
                if approval_ch:
                    # Kick bot, notify approval channel
                    try:
                        await member.kick(reason="Bot-Approval: Warte auf Genehmigung")
                        embed = create_embed(f"{E.APPROVAL} Bot wartet auf Genehmigung",
                            f"**Bot:** {member.mention} (`{member.id}`)\n"
                            f"Nutze `/bot_approve {member.id}` um den Bot zu genehmigen.",
                            COLOR_WARNING)
                        await approval_ch.send(embed=embed)
                    except Exception:
                        pass
                    return

            # Bot-Mass-Add-Erkennung (Feature 18)
            np = cfg.get("nuke_protection", {})
            if np.get("enabled", True):
                try:
                    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
                        await self._track_nuke_event(guild, entry.user.id, "bot_add")
                        break
                except discord.Forbidden:
                    pass

        # Multi-Server-Raid-Erkennung (Feature 3)
        rd = cfg.get("raid_detection", {})
        if rd.get("multi_server"):
            now = time.time()
            _multi_server_raid[member.id].append((guild.id, now))
            # Clean old entries
            while _multi_server_raid[member.id] and now - _multi_server_raid[member.id][0][1] > 300:
                _multi_server_raid[member.id].popleft()
            # Check if joining many servers quickly
            unique_guilds = len(set(gid for gid, _ in _multi_server_raid[member.id]))
            if unique_guilds >= 3:
                await self.bot.log_action(guild, f"{E.MULTI_RAID} Multi-Server-Raid",
                    f"{member.mention} ist in {unique_guilds} Servern in 5 Minuten beigetreten.",
                    COLOR_DANGER, user=member, module="antiraid")

        # Timezone-based-Raid-Erkennung (Feature 34)
        if rd.get("timezone_detection"):
            sp = cfg.get("server_protection", {})
            hour = datetime.datetime.utcnow().hour
            start = sp.get("suspicious_time_start", 2)
            end = sp.get("suspicious_time_end", 6)
            if start <= hour <= end:
                account_age = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).days
                if account_age < 7:
                    await self.bot.log_action(guild, f"{E.TIMEZONE} Verdächtiger Join (Nachtzeit)",
                        f"{member.mention} – Account {account_age} Tage alt, Join um {hour}:00 UTC",
                        COLOR_WARNING, user=member, module="antiraid")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Feature 36, 37: Token/Webhook-URL Leak-Schutz."""
        if not message.guild or message.author.bot:
            return
        cfg = self.bot.db.get_config(message.guild.id)
        lp = cfg.get("leak_protection", {})
        if not lp.get("enabled", True):
            return
        content = message.content or ""
        import re
        # Token-Leak-Schutz (Feature 36)
        if lp.get("token_leak_scan"):
            token_pattern = re.compile(r'[MN][A-Za-z\d]{23,28}\.[A-Za-z\d-_]{6,7}\.[A-Za-z\d-_]{27,}')
            if token_pattern.search(content):
                try:
                    await message.delete()
                except Exception:
                    pass
                await self.bot.log_action(message.guild, f"{E.TOKEN_LEAK} TOKEN-LEAK ERKANNT",
                    f"{message.author.mention} hat einen möglichen Bot-Token gepostet!\n"
                    f"Nachricht wurde gelöscht.", COLOR_DANGER, user=message.author, module="security")
                embed = create_embed(f"{E.TOKEN_LEAK} Token-Leak Warnung",
                    "Du hast einen möglichen Bot-Token gepostet. Die Nachricht wurde gelöscht.\n"
                    "**Ändere sofort deinen Token!**", COLOR_DANGER)
                await safe_dm(message.author, embed)
                return
        # Webhook-URL-Leak-Schutz (Feature 37)
        if lp.get("webhook_url_leak_scan"):
            webhook_pattern = re.compile(r'https?://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+')
            if webhook_pattern.search(content):
                try:
                    await message.delete()
                except Exception:
                    pass
                await self.bot.log_action(message.guild, f"{E.WEBHOOK_LEAK} WEBHOOK-URL-LEAK",
                    f"{message.author.mention} hat eine Webhook-URL gepostet!",
                    COLOR_DANGER, user=message.author, module="security")
                return
        # IP-Leak-Schutz (Feature 12 partial)
        if lp.get("ip_leak_scan"):
            ip_pattern = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
            ips = ip_pattern.findall(content)
            # Filter out common non-IPs
            real_ips = [ip for ip in ips if not ip.startswith("0.") and not ip.startswith("127.")]
            if len(real_ips) >= 2:
                await self.bot.log_action(message.guild, f"{E.ALERT} Möglicher IP-Leak",
                    f"{message.author.mention} hat {len(real_ips)} IP-Adressen gepostet.",
                    COLOR_WARNING, user=message.author, module="security")

    # ══════════════════════════════════════════════════
    # SLASH COMMANDS
    # ══════════════════════════════════════════════════
    security_group = app_commands.Group(name="security", description="Sicherheitseinstellungen")

    @security_group.command(name="view", description="Zeigt aktuelle Sicherheitseinstellungen")
    @app_commands.default_permissions(administrator=True)
    async def security_view(self, interaction: discord.Interaction):
        cfg = self.bot.db.get_config(interaction.guild.id)
        modules = ["anti_spam", "anti_nuke", "anti_raid", "anti_mention", "anti_scam",
                    "anti_ghost_ping", "anti_url_shortener", "anti_webhook", "automod"]
        lines = []
        for mod in modules:
            mod_cfg = cfg.get(mod, {})
            status = "✅" if mod_cfg.get("enabled") else "❌"
            lines.append(f"{status} **{mod.replace('_', ' ').title()}**")
        np = cfg.get("nuke_protection", {})
        lines.append(f"\n{f'{E.OK}' if np.get('enabled') else f'{E.FAIL}'} **Nuke-Protection**")
        lines.append(f"{f'{E.OK}' if np.get('auto_backup_on_nuke') else f'{E.FAIL}'} Auto-Backup bei Nuke")
        lines.append(f"{f'{E.OK}' if np.get('auto_restore_on_nuke') else f'{E.FAIL}'} Auto-Restore bei Nuke")
        sp = cfg.get("server_protection", {})
        lines.append(f"{f'{E.OK}' if sp.get('vanity_url_protect') else f'{E.FAIL}'} Vanity-URL-Schutz")
        lines.append(f"{f'{E.OK}' if sp.get('server_icon_protect') else f'{E.FAIL}'} Icon-Schutz")
        lines.append(f"{f'{E.OK}' if sp.get('bot_approval_required') else f'{E.FAIL}'} Bot-Approval")
        lp = cfg.get("leak_protection", {})
        lines.append(f"{f'{E.OK}' if lp.get('token_leak_scan') else f'{E.FAIL}'} Token-Leak-Schutz")
        lines.append(f"\n🔒 **Sicherheitsstufe:** {cfg.get('security_level', 0)}")
        await interaction.response.send_message(embed=create_embed(
            f"{E.SHIELD} Sicherheitsübersicht", "\n".join(lines), COLOR_PRIMARY))

    @security_group.command(name="toggle", description="Aktiviert/deaktiviert ein Modul")
    @app_commands.describe(module="Modulname")
    @app_commands.default_permissions(administrator=True)
    async def security_toggle(self, interaction: discord.Interaction, module: str):
        cfg = self.bot.db.get_config(interaction.guild.id)
        if module not in cfg:
            return await interaction.response.send_message(
                embed=create_embed(f"{E.FAIL}", f"Modul `{module}` nicht gefunden.", COLOR_DANGER), ephemeral=True)
        if isinstance(cfg[module], dict) and "enabled" in cfg[module]:
            cfg[module]["enabled"] = not cfg[module]["enabled"]
            await self.bot.db.set_config(interaction.guild.id, cfg)
            status = "aktiviert" if cfg[module]["enabled"] else "deaktiviert"
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} {module}", f"**{status}**.", COLOR_SUCCESS))
        else:
            await interaction.response.send_message(
                embed=create_embed(f"{E.FAIL}", "Kein Toggle verfügbar.", COLOR_DANGER), ephemeral=True)

    @security_group.command(name="set", description="Ändert eine Einstellung")
    @app_commands.describe(module="Modulname", setting="Einstellung", value="Neuer Wert")
    @app_commands.default_permissions(administrator=True)
    async def security_set(self, interaction: discord.Interaction, module: str, setting: str, value: str):
        cfg = self.bot.db.get_config(interaction.guild.id)
        if module not in cfg or not isinstance(cfg[module], dict):
            return await interaction.response.send_message(
                embed=create_embed(f"{E.FAIL}", "Modul nicht gefunden.", COLOR_DANGER), ephemeral=True)
        if value.isdigit():
            cfg[module][setting] = int(value)
        elif value.lower() in ("true", "false"):
            cfg[module][setting] = value.lower() == "true"
        else:
            cfg[module][setting] = value
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Einstellung geändert", f"`{module}.{setting}` = `{value}`", COLOR_SUCCESS))

    @security_group.command(name="level", description="Setzt die Sicherheitsstufe (0-3)")
    @app_commands.describe(level="0=normal, 1=erhöht, 2=hoch, 3=blackout")
    @app_commands.default_permissions(administrator=True)
    async def security_level(self, interaction: discord.Interaction, level: int):
        if level not in range(4):
            return await interaction.response.send_message(
                embed=create_embed(f"{E.FAIL}", "Stufe muss 0-3 sein.", COLOR_DANGER), ephemeral=True)
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["security_level"] = level
        await self.bot.db.set_config(interaction.guild.id, cfg)
        labels = {0: "Normal", 1: "Erhöht", 2: "Hoch (Auto-Kick)", 3: "BLACKOUT (Auto-Ban)"}
        await interaction.response.send_message(embed=create_embed(
            f"{E.SHIELD} Sicherheitsstufe {level}", labels[level],
            COLOR_WARNING if level > 0 else COLOR_SUCCESS))

    @app_commands.command(name="snapshot", description="Vergleicht Server mit letztem Snapshot")
    @app_commands.default_permissions(administrator=True)
    async def slash_snapshot(self, interaction: discord.Interaction):
        changes = await self._compare_snapshot(interaction.guild)
        if changes["changes"] == 0:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Keine Änderungen", "Server stimmt mit letztem Snapshot überein.", COLOR_SUCCESS))
        lines = []
        if changes["deleted_channels"]:
            lines.append(f"**Gelöschte Kanäle:** {', '.join(changes['deleted_channels'][:10])}")
        if changes["deleted_roles"]:
            lines.append(f"**Gelöschte Rollen:** {', '.join(changes['deleted_roles'][:10])}")
        if changes["new_channels"]:
            lines.append(f"**Neue Kanäle:** {', '.join(changes['new_channels'][:10])}")
        if changes["icon_changed"]:
            lines.append("**Icon:** Geändert")
        if changes["banner_changed"]:
            lines.append("**Banner:** Geändert")
        await interaction.response.send_message(embed=create_embed(
            f"{E.SNAPSHOT} Snapshot-Vergleich ({changes['changes']} Änderungen)", "\n".join(lines), COLOR_WARNING))

    @app_commands.command(name="panic", description="Panic-Button: Sofortiger Lockdown")
    @app_commands.default_permissions(administrator=True)
    async def slash_panic(self, interaction: discord.Interaction):
        """Feature 500: Admin-Panic-Button."""
        await interaction.response.defer()
        locked = 0
        for ch in interaction.guild.text_channels:
            try:
                await ch.set_permissions(interaction.guild.default_role, send_messages=False, reason="PANIC BUTTON")
                locked += 1
                await asyncio.sleep(0.2)
            except Exception:
                pass
        # Take emergency backup
        try:
            backup_cog = self.bot.get_cog("BackupCog")
            if backup_cog:
                data = await backup_cog._collect_backup_data(interaction.guild)
                bid = await backup_cog._backup_db_save(data, interaction.user.id, "PANIC-Backup")
        except Exception:
            bid = None
        await interaction.followup.send(embed=create_embed(
            f"{E.PANIC} PANIC-MODUS AKTIVIERT",
            f"**{locked} Kanäle gesperrt**\n"
            f"**Backup:** {'`' + str(bid) + '`' if bid else 'Fehler'}\n\n"
            f"Nutze `/unlockall` um den Lockdown aufzuheben.",
            COLOR_DANGER))

    @app_commands.command(name="nuke_whitelist", description="Nuke-Whitelist verwalten")
    @app_commands.describe(action="add/remove/list", user="Der User")
    @app_commands.default_permissions(administrator=True)
    async def slash_nuke_whitelist(self, interaction: discord.Interaction, action: str,
                                    user: Optional[discord.Member] = None):
        cfg = self.bot.db.get_config(interaction.guild.id)
        np = cfg.get("nuke_protection", {})
        wl = np.get("nuke_whitelist", [])
        if action == "add" and user:
            if user.id not in wl:
                wl.append(user.id)
            np["nuke_whitelist"] = wl
            cfg["nuke_protection"] = np
            await self.bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", f"{user.mention} zur Nuke-Whitelist hinzugefügt.", COLOR_SUCCESS))
        elif action == "remove" and user:
            wl = [uid for uid in wl if uid != user.id]
            np["nuke_whitelist"] = wl
            cfg["nuke_protection"] = np
            await self.bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", f"{user.mention} von Nuke-Whitelist entfernt.", COLOR_SUCCESS))
        elif action == "list":
            if not wl:
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.SHIELD}", "Nuke-Whitelist ist leer.", COLOR_INFO))
            mentions = ", ".join(f"<@{uid}>" for uid in wl[:20])
            await interaction.response.send_message(embed=create_embed(
                f"{E.SHIELD} Nuke-Whitelist", mentions, COLOR_PRIMARY))

    @app_commands.command(name="emergency_contact", description="Emergency-Contact hinzufügen")
    @app_commands.describe(action="add/remove/list", user="User-ID")
    @app_commands.default_permissions(administrator=True)
    async def slash_emergency_contact(self, interaction: discord.Interaction, action: str,
                                       user: Optional[discord.User] = None):
        cfg = self.bot.db.get_config(interaction.guild.id)
        np = cfg.get("nuke_protection", {})
        contacts = np.get("emergency_contacts", [])
        if action == "add" and user:
            if user.id not in contacts:
                contacts.append(user.id)
            np["emergency_contacts"] = contacts
            cfg["nuke_protection"] = np
            await self.bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", f"{user.mention} als Emergency-Contact hinzugefügt.", COLOR_SUCCESS))
        elif action == "remove" and user:
            contacts = [c for c in contacts if c != user.id]
            np["emergency_contacts"] = contacts
            cfg["nuke_protection"] = np
            await self.bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", f"{user.mention} entfernt.", COLOR_SUCCESS))
        elif action == "list":
            if not contacts:
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.APPEAL}", "Keine Emergency-Contacts.", COLOR_INFO))
            await interaction.response.send_message(embed=create_embed(
                f"{E.APPEAL} Emergency-Contacts", ", ".join(f"<@{c}>" for c in contacts), COLOR_PRIMARY))

    @app_commands.command(name="bot_approve", description="Genehmigt einen Bot (wenn Bot-Approval aktiv)")
    @app_commands.describe(bot_id="Bot-ID")
    @app_commands.default_permissions(administrator=True)
    async def slash_bot_approve(self, interaction: discord.Interaction, bot_id: str):
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Bot genehmigt",
            f"Bot `{bot_id}` kann jetzt dem Server beitreten.\n"
            f"Lade den Bot erneut ein.", COLOR_SUCCESS))

    # ── WHITELIST GROUP ──
    whitelist_group = app_commands.Group(name="whitelist", description="Whitelist verwalten")

    @whitelist_group.command(name="add", description="Fügt zur Whitelist hinzu")
    @app_commands.describe(user="User", role="Rolle")
    @app_commands.default_permissions(administrator=True)
    async def whitelist_add(self, interaction: discord.Interaction,
                            user: Optional[discord.User] = None,
                            role: Optional[discord.Role] = None):
        if not user and not role:
            return await interaction.response.send_message(
                embed=create_embed(f"{E.FAIL}", "User oder Rolle angeben.", COLOR_DANGER), ephemeral=True)
        entry_id = user.id if user else role.id
        cat = "users" if user else "roles"
        await self.bot.db.add_whitelist(interaction.guild.id, cat, entry_id)
        name = user.mention if user else role.mention
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Whitelist", f"{name} hinzugefügt ({cat}).", COLOR_SUCCESS))

    @whitelist_group.command(name="remove", description="Entfernt von der Whitelist")
    @app_commands.describe(user="User", role="Rolle")
    @app_commands.default_permissions(administrator=True)
    async def whitelist_remove(self, interaction: discord.Interaction,
                               user: Optional[discord.User] = None,
                               role: Optional[discord.Role] = None):
        if not user and not role:
            return await interaction.response.send_message(
                embed=create_embed(f"{E.FAIL}", "User oder Rolle angeben.", COLOR_DANGER), ephemeral=True)
        entry_id = user.id if user else role.id
        cat = "users" if user else "roles"
        await self.bot.db.remove_whitelist(interaction.guild.id, cat, entry_id)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK}", "Entfernt.", COLOR_SUCCESS))

    @whitelist_group.command(name="list", description="Zeigt die Whitelist")
    @app_commands.default_permissions(administrator=True)
    async def whitelist_list(self, interaction: discord.Interaction):
        wl = await self.bot.db.aget_whitelist(interaction.guild.id)
        lines = []
        for cat in ["users", "roles", "channels", "bypass_antispam", "bypass_antinuke"]:
            entries = wl.get(cat, [])
            if entries:
                mentions = [f"<@{uid}>" if cat in ("users", "bypass_antispam", "bypass_antinuke")
                           else f"<@&{rid}>" if cat == "roles" else f"<#{cid}>"
                           for uid_or_rid_or_cid in entries[:20]
                           for uid, rid, cid in [(uid_or_rid_or_cid,)*3]]
                lines.append(f"**{cat}:** {', '.join(mentions[:20])}")
        if not lines:
            lines = ["Whitelist ist leer."]
        await interaction.response.send_message(embed=create_embed(
            f"{E.SHIELD} Whitelist", "\n".join(lines), COLOR_PRIMARY))

    # ── AUTOMOD GROUP ──
    automod_group = app_commands.Group(name="automod", description="AutoMod-Konfiguration")

    @automod_group.command(name="badword_add", description="Verbotenes Wort hinzufügen")
    @app_commands.describe(word="Das Wort")
    @app_commands.default_permissions(administrator=True)
    async def automod_badword_add(self, interaction: discord.Interaction, word: str):
        cfg = self.bot.db.get_config(interaction.guild.id)
        bw = cfg.get("automod", {}).get("bad_words", [])
        if word.lower() not in [w.lower() for w in bw]:
            bw.append(word.lower())
            cfg.setdefault("automod", {})["bad_words"] = bw
            await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK}", f"||{word}|| hinzugefügt.", COLOR_SUCCESS))

    @automod_group.command(name="badword_remove", description="Verbotenes Wort entfernen")
    @app_commands.describe(word="Das Wort")
    @app_commands.default_permissions(administrator=True)
    async def automod_badword_remove(self, interaction: discord.Interaction, word: str):
        cfg = self.bot.db.get_config(interaction.guild.id)
        bw = [w for w in cfg.get("automod", {}).get("bad_words", []) if w.lower() != word.lower()]
        cfg.setdefault("automod", {})["bad_words"] = bw
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK}", "Entfernt.", COLOR_SUCCESS))

    @automod_group.command(name="badword_list", description="Verbotene Wörter anzeigen")
    @app_commands.default_permissions(administrator=True)
    async def automod_badword_list(self, interaction: discord.Interaction):
        cfg = self.bot.db.get_config(interaction.guild.id)
        bw = cfg.get("automod", {}).get("bad_words", [])
        if not bw:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", "Keine verbotenen Wörter.", COLOR_INFO))
        await interaction.response.send_message(embed=create_embed(
            f"{E.BADWORD} Verbotene Wörter ({len(bw)})",
            ", ".join(f"||{w}||" for w in bw[:50]), COLOR_PRIMARY))


async def setup(bot):
    await bot.add_cog(SecurityCog(bot))
