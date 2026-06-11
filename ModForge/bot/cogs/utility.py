# -*- coding: utf-8 -*-
"""ModForge Utility Cog – UserInfo, ServerInfo, Poll, Snipe, History, etc."""
import asyncio
import datetime
import io
import json
import time
from typing import Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands

from bot.config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_INFO, E, BADGES, log,
)
from bot.utils import create_embed
from bot.bot import (
    _BOT_DEV_ID, _snipe_cache,
    SetupView, HelpView, ReactionRoleView,
)


class SetupWizardView(discord.ui.View):
    """Drei schnelle Setup-Profile direkt in Discord."""

    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot

    async def _apply_profile(self, interaction: discord.Interaction, profile: str) -> None:
        cfg = self.bot.db.get_config(interaction.guild.id)
        presets = {
            "easy": {"level": 1, "spam": True, "nuke": True, "raid": False, "automod": True},
            "safe": {"level": 2, "spam": True, "nuke": True, "raid": True, "automod": True},
            "hardcore": {"level": 3, "spam": True, "nuke": True, "raid": True, "automod": True},
        }
        p = presets[profile]
        cfg["security_level"] = p["level"]
        cfg.setdefault("anti_spam", {})["enabled"] = p["spam"]
        cfg.setdefault("anti_nuke", {})["enabled"] = p["nuke"]
        cfg.setdefault("anti_raid", {})["enabled"] = p["raid"]
        cfg.setdefault("automod", {})["enabled"] = p["automod"]
        if profile == "hardcore":
            cfg.setdefault("anti_raid", {})["lockdown"] = True
            cfg.setdefault("nuke_protection", {})["auto_backup_on_nuke"] = True
            cfg.setdefault("nuke_protection", {})["freeze_perms_on_nuke"] = True
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.edit_message(embed=create_embed(
            f"{E.OK} Setup-Profil aktiviert",
            f"Profil **{profile}** wurde gespeichert. Nutze `/doctor` für den finalen Check.",
            COLOR_SUCCESS,
            [("Security-Level", str(p["level"]), True), ("AutoMod", "aktiv", True)],
        ), view=None)

    @discord.ui.button(label="Einfach", style=discord.ButtonStyle.secondary, emoji="🟢")
    async def easy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply_profile(interaction, "easy")

    @discord.ui.button(label="Sicher", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def safe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply_profile(interaction, "safe")

    @discord.ui.button(label="Hardcore", style=discord.ButtonStyle.danger, emoji="🚨")
    async def hardcore(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply_profile(interaction, "hardcore")


class UtilityCog(commands.Cog):
    """Utility-Commands: Info, Setup, Help, Poll, Snipe, etc."""

    def __init__(self, bot):
        self.bot = bot
        self.warn_decay_loop.start()

    def cog_unload(self):
        self.warn_decay_loop.cancel()

    # ── USERINFO ──
    async def _userinfo_logic(self, guild, target, requester):
        member = guild.get_member(target.id) if guild else None
        if not member:
            return create_embed(f"{E.FAIL}", "User nicht gefunden.", COLOR_DANGER)
        cfg = self.bot.db.get_config(guild.id)
        warns = cfg.get("warns", {}).get(str(member.id), [])
        cases = await self.bot.db.aget_recent_cases(guild.id, limit=100)
        user_cases = [c for c in cases if c.get("user_id") == member.id]
        account_age = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).days
        join_age = (discord.utils.utcnow() - member.joined_at.replace(tzinfo=None)).days if member.joined_at else 0
        roles = ", ".join(r.mention for r in member.roles[1:][:15]) or "Keine"
        fields = [
            ("Account erstellt", f"<t:{int(member.created_at.timestamp())}:R> ({account_age} Tage)", True),
            ("Beigetreten", f"<t:{int(member.joined_at.timestamp())}:R> ({join_age} Tage)" if member.joined_at else "?", True),
            ("Verwarnungen", str(len(warns)), True),
            ("Cases", str(len(user_cases)), True),
            ("Rollen", roles, False),
        ]
        return create_embed(f"{E.USER} {member}", f"ID: `{member.id}`", COLOR_PRIMARY, fields,
                           thumbnail=member.display_avatar.url)

    @app_commands.command(name="userinfo", description="Zeigt User-Infos")
    @app_commands.describe(member="Der Nutzer")
    async def slash_userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        embed = await self._userinfo_logic(interaction.guild, target, interaction.user)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="userinfo", aliases=["ui", "whois"])
    async def prefix_userinfo(self, ctx, member: discord.Member = None):
        embed = await self._userinfo_logic(ctx.guild, member or ctx.author, ctx.author)
        await ctx.send(embed=embed)

    # ── SERVERINFO ──
    @app_commands.command(name="serverinfo", description="Server-Statistiken")
    async def slash_serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        fields = [
            ("Owner", g.owner.mention if g.owner else "?", True),
            ("Mitglieder", str(g.member_count), True),
            ("Rollen", str(len(g.roles)), True),
            ("Kanäle", f"{len(g.text_channels)} Text / {len(g.voice_channels)} Voice", True),
            ("Erstellt", f"<t:{int(g.created_at.timestamp())}:R>", True),
            ("Boost-Level", str(g.premium_tier), True),
        ]
        embed = create_embed(f"{E.SERVER} {g.name}", f"ID: `{g.id}`", COLOR_PRIMARY, fields,
                            thumbnail=g.icon.url if g.icon else None)
        await interaction.response.send_message(embed=embed)

    @commands.command(name="serverinfo", aliases=["si"])
    async def prefix_serverinfo(self, ctx):
        g = ctx.guild
        fields = [
            ("Mitglieder", str(g.member_count), True),
            ("Rollen", str(len(g.roles)), True),
            ("Kanäle", f"{len(g.text_channels)}T/{len(g.voice_channels)}V", True),
        ]
        await ctx.send(embed=create_embed(f"{E.SERVER} {g.name}", f"ID: `{g.id}`", COLOR_PRIMARY, fields))

    # ── SETUP ──
    @app_commands.command(name="setup", description="Interaktives Setup-Panel")
    @app_commands.default_permissions(administrator=True)
    async def slash_setup(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=create_embed(
            f"{E.GEAR} ModForge Setup", "Wähle ein Modul aus dem Dropdown.", COLOR_PRIMARY),
            view=SetupView(), ephemeral=True)

    # ── HELP ──
    @app_commands.command(name="setup-wizard", description="Schnelles Server-Setup mit Profilen")
    @app_commands.default_permissions(administrator=True)
    async def slash_setup_wizard(self, interaction: discord.Interaction):
        embed = create_embed(
            f"{E.GEAR} Setup-Wizard",
            "Wähle ein Profil. Du kannst alles danach im Dashboard fein einstellen.",
            COLOR_PRIMARY,
            [("Einfach", "Basis-Schutz für kleine Server", True),
             ("Sicher", "Empfohlen für die meisten Server", True),
             ("Hardcore", "Maximaler Schutz bei Raid-Gefahr", True)]
        )
        await interaction.response.send_message(embed=embed, view=SetupWizardView(self.bot), ephemeral=True)

    @app_commands.command(name="doctor", description="Prüft Bot-Rechte, Logs, DB und Security-Konfiguration")
    @app_commands.default_permissions(manage_guild=True)
    async def slash_doctor(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        me = guild.me
        cfg = self.bot.db.get_config(guild.id)
        checks = []
        def add(ok, name, tip):
            checks.append(("✅" if ok else "❌", name, "OK" if ok else tip, not ok))
        perms = me.guild_permissions
        add(perms.manage_roles, "Manage Roles", "Bot-Rolle höher setzen und Recht geben")
        add(perms.ban_members, "Ban Members", "Recht `Mitglieder bannen` geben")
        add(perms.kick_members, "Kick Members", "Recht `Mitglieder kicken` geben")
        add(perms.manage_channels, "Manage Channels", "Für Lockdown/TempVoice nötig")
        add(perms.manage_messages, "Manage Messages", "Für AutoMod-Löschung nötig")
        add(bool(cfg.get("log_channel") or cfg.get("log_channels")), "Logs", "Mit `/log #kanal` setzen")
        add(cfg.get("anti_nuke", {}).get("enabled"), "Anti-Nuke", "Im Dashboard oder `/setup-wizard` aktivieren")
        add(cfg.get("automod", {}).get("enabled"), "AutoMod", "AutoMod aktivieren")
        db_ok = await self.bot.db.test_connection()
        add(db_ok, "Datenbank", "MongoDB-Verbindung prüfen")
        fields = [(f"{icon} {name}", tip, False) for icon, name, tip, _bad in checks[:25]]
        bad = sum(1 for *_rest, b in checks if b)
        color = COLOR_SUCCESS if bad == 0 else COLOR_WARNING if bad <= 3 else COLOR_DANGER
        await interaction.followup.send(embed=create_embed(
            f"{E.SHIELD} Doctor Ergebnis",
            f"**{len(checks)-bad}/{len(checks)} Checks OK**",
            color, fields
        ))

    @app_commands.command(name="case_export", description="Exportiert Cases als JSON oder HTML")
    @app_commands.describe(format="json/html", limit="Anzahl der Cases")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_case_export(self, interaction: discord.Interaction, format: str = "html", limit: int = 100):
        await interaction.response.defer(ephemeral=True)
        fmt = format.lower()
        cases = await self.bot.db.aget_recent_cases(interaction.guild.id, limit=max(1, min(limit, 500)))
        serializable = []
        for c in cases:
            c = dict(c); c.pop("_id", None)
            for k, v in list(c.items()):
                if hasattr(v, "isoformat"): c[k] = v.isoformat()
            serializable.append(c)
        if fmt == "json":
            data = json.dumps(serializable, ensure_ascii=False, indent=2).encode("utf-8")
            file = discord.File(io.BytesIO(data), filename=f"cases-{interaction.guild.id}.json")
        else:
            rows = "".join(f"<tr><td>#{c.get('case_id')}</td><td>{c.get('action')}</td><td>{c.get('user_id')}</td><td>{c.get('reason','')}</td></tr>" for c in serializable)
            html = f"<html><meta charset='utf-8'><body><h1>Cases – {interaction.guild.name}</h1><table border='1' cellspacing='0' cellpadding='6'><tr><th>ID</th><th>Aktion</th><th>User</th><th>Grund</th></tr>{rows}</table></body></html>"
            file = discord.File(io.BytesIO(html.encode("utf-8")), filename=f"cases-{interaction.guild.id}.html")
        await interaction.followup.send(content=f"{E.OK} Export fertig: {len(serializable)} Cases", file=file, ephemeral=True)

    @app_commands.command(name="help", description="Zeigt die Hilfe")
    async def slash_help(self, interaction: discord.Interaction):
        embed = create_embed(
            f"{E.HELP} ModForge Hilfe",
            "Wähle eine Kategorie aus dem Dropdown um Commands zu sehen.",
            COLOR_PRIMARY)
        await interaction.response.send_message(embed=embed, view=HelpView(), ephemeral=True)

    # ── STATUS ──
    @app_commands.command(name="status", description="Zeigt den Bot-Status")
    async def slash_status(self, interaction: discord.Interaction):
        from bot.config import get_uptime
        uptime = get_uptime()
        h, m = divmod(uptime // 60, 60)
        d, h = divmod(h, 24)
        fields = [
            ("Ping", f"{round(self.bot.latency * 1000)}ms", True),
            ("Server", str(len(self.bot.guilds)), True),
            ("Mitglieder", str(sum(g.member_count or 0 for g in self.bot.guilds)), True),
            ("Uptime", f"{d}d {h}h {m}m", True),
        ]
        await interaction.response.send_message(embed=create_embed(
            f"{E.BOT} ModForge Status", "", COLOR_PRIMARY, fields))

    # ── SNIPE ──
    @app_commands.command(name="snipe", description="Letzte gelöschte Nachricht")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_snipe(self, interaction: discord.Interaction):
        d = _snipe_cache.get(interaction.guild.id, {}).get(interaction.channel.id)
        if not d or time.time() - d["ts"] > 300:
            return await interaction.response.send_message(embed=create_embed(
                "ℹ️", "Nichts zu snipen.", COLOR_INFO), ephemeral=True)
        e = create_embed(f"{E.SHIELD} Snipe", d["content"] or "*Leer*", COLOR_WARNING)
        e.set_author(name=str(d["author"]), icon_url=d["author"].display_avatar.url)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @commands.command(name="snipe")
    @commands.has_permissions(manage_messages=True)
    async def prefix_snipe(self, ctx):
        d = _snipe_cache.get(ctx.guild.id, {}).get(ctx.channel.id)
        if not d or time.time() - d["ts"] > 300:
            return await ctx.send("Nichts zu snipen.")
        e = create_embed(f"{E.SHIELD}", d["content"] or "*Leer*", COLOR_WARNING)
        e.set_author(name=str(d["author"]), icon_url=d["author"].display_avatar.url)
        await ctx.send(embed=e)

    # ── POLL ──
    @app_commands.command(name="poll", description="Abstimmung erstellen")
    @app_commands.describe(frage="Die Frage", opt1="Option 1", opt2="Option 2", opt3="Option 3", opt4="Option 4")
    async def slash_poll(self, interaction: discord.Interaction, frage: str,
                         opt1: str, opt2: str, opt3: str = None, opt4: str = None):
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
        options = [opt1, opt2]
        if opt3:
            options.append(opt3)
        if opt4:
            options.append(opt4)
        desc = "\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(options))
        embed = create_embed(f"{E.STATS} {frage}", desc, COLOR_PRIMARY)
        embed.set_footer(text=f"Abstimmung von {interaction.user}")
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        for i in range(len(options)):
            await msg.add_reaction(emojis[i])

    # ── HISTORY ──
    @app_commands.command(name="history", description="Komplette Mod-History eines Users")
    @app_commands.describe(member="Der Nutzer")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_history(self, interaction: discord.Interaction, member: discord.Member):
        cases = await self.bot.db.aget_recent_cases(interaction.guild.id, limit=100)
        user_cases = [c for c in cases if c.get("user_id") == member.id]
        if not user_cases:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", f"{member.mention} hat keine Cases.", COLOR_SUCCESS))
        lines = [f"#{c.get('case_id', '?')} {c.get('action', '?')} – {c.get('reason', '—')[:40]}"
                 for c in user_cases[:20]]
        await interaction.response.send_message(embed=create_embed(
            f"{E.CASE} History ({len(user_cases)})", "\n".join(lines), COLOR_INFO))

    # ── ROLEINFO ──
    @app_commands.command(name="roleinfo", description="Rollen-Info")
    @app_commands.describe(role="Die Rolle")
    async def slash_roleinfo(self, interaction: discord.Interaction, role: discord.Role):
        fields = [
            ("Mitglieder", str(len(role.members)), True),
            ("Farbe", str(role.color), True),
            ("Position", str(role.position), True),
            ("Hoisted", "Ja" if role.hoist else "Nein", True),
            ("Mentionable", "Ja" if role.mentionable else "Nein", True),
        ]
        await interaction.response.send_message(embed=create_embed(
            f"{E.ROLE} {role.name}", f"ID: `{role.id}`", role.color.value or COLOR_PRIMARY, fields))

    # ── LOCKALL / UNLOCKALL ──
    @app_commands.command(name="lockall", description="Sperrt ALLE Kanäle")
    @app_commands.describe(reason="Grund")
    @app_commands.default_permissions(administrator=True)
    async def slash_lockall(self, interaction: discord.Interaction, reason: str = "Lockdown"):
        await interaction.response.defer()
        locked = 0
        for ch in interaction.guild.text_channels:
            try:
                await ch.set_permissions(interaction.guild.default_role, send_messages=False, reason=reason)
                locked += 1
                await asyncio.sleep(0.3)
            except (discord.Forbidden, discord.HTTPException):
                pass
        await interaction.followup.send(embed=create_embed(
            f"{E.LOCK} Lockdown", f"{locked} Kanäle gesperrt.\nGrund: {reason}", COLOR_DANGER))

    @app_commands.command(name="unlockall", description="Entsperrt ALLE Kanäle")
    @app_commands.default_permissions(administrator=True)
    async def slash_unlockall(self, interaction: discord.Interaction):
        await interaction.response.defer()
        unlocked = 0
        for ch in interaction.guild.text_channels:
            try:
                await ch.set_permissions(interaction.guild.default_role, send_messages=None, reason="Lockdown aufgehoben")
                unlocked += 1
                await asyncio.sleep(0.3)
            except (discord.Forbidden, discord.HTTPException):
                pass
        await interaction.followup.send(embed=create_embed(
            f"{E.UNLOCK} Lockdown aufgehoben", f"{unlocked} Kanäle entsperrt.", COLOR_SUCCESS))

    # ── RAIDMODE ──
    @app_commands.command(name="raidmode", description="Manueller Raid-Modus")
    @app_commands.describe(enabled="Aktivieren/Deaktivieren", dauer="Auto-Off nach X Minuten (0=manuell)")
    @app_commands.default_permissions(administrator=True)
    async def slash_raidmode(self, interaction: discord.Interaction, enabled: bool, dauer: int = 0):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["raidmode_active"] = enabled
        await self.bot.db.set_config(interaction.guild.id, cfg)
        if enabled:
            await interaction.response.send_message(embed=create_embed(
                f"{E.RAID} Raid-Modus AKTIVIERT",
                f"Neue Mitglieder werden benachrichtigt.\n{'Auto-Off in ' + str(dauer) + ' Min.' if dauer else 'Manuell deaktivieren mit /raidmode false'}",
                COLOR_DANGER))
            if dauer > 0:
                await asyncio.sleep(dauer * 60)
                cfg["raidmode_active"] = False
                await self.bot.db.set_config(interaction.guild.id, cfg)
                try:
                    await interaction.channel.send(embed=create_embed(
                        "✅ Raid-Modus deaktiviert", "Automatisch nach Timer.", COLOR_SUCCESS))
                except Exception:
                    pass
        else:
            await interaction.response.send_message(embed=create_embed(
                "✅ Raid-Modus deaktiviert", "", COLOR_SUCCESS))

    # ── REACTIONROLE ──
    @app_commands.command(name="reactionrole", description="Erstellt eine Reaction-Role Nachricht")
    @app_commands.describe(channel="Kanal", title="Titel", description="Beschreibung")
    @app_commands.default_permissions(administrator=True)
    async def slash_reactionrole(self, interaction: discord.Interaction,
                                  channel: discord.TextChannel,
                                  title: str = "🎭 Wähle deine Rollen",
                                  description: str = "Nutze das Dropdown um Rollen zu togglen."):
        embed = create_embed(title, description, COLOR_PRIMARY)
        view = ReactionRoleView()
        try:
            msg = await channel.send(embed=embed, view=view)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Reaction-Role erstellt", f"In {channel.mention}: [Link]({msg.jump_url})", COLOR_SUCCESS))
        except discord.Forbidden:
            await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Keine Berechtigung.", COLOR_DANGER), ephemeral=True)

    # ── BADGE SYSTEM ──
    @app_commands.command(name="badge", description="Badges verwalten")
    @app_commands.describe(action="view/add/remove", user="Der Nutzer", badge="Badge-ID")
    async def slash_badge(self, interaction: discord.Interaction, action: str,
                          user: Optional[discord.Member] = None, badge: Optional[str] = None):
        if action == "view":
            target = user or interaction.user
            badges = await self.bot.db.badge_get_all(interaction.guild.id, target.id)
            if not badges:
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.USER} Badges", f"{target.mention} hat keine Badges.", COLOR_INFO))
            badge_strs = []
            for b_id in badges:
                bd = BADGES.get(b_id, {"name": b_id, "emoji": "🏷️"})
                badge_strs.append(f"{bd['emoji']} **{bd['name']}**")
            await interaction.response.send_message(embed=create_embed(
                f"{E.USER} Badges von {target}", "\n".join(badge_strs), COLOR_PRIMARY))
        elif action in ("add", "remove") and interaction.user.id != _BOT_DEV_ID:
            await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Nur der Bot-Developer kann Badges verwalten.", COLOR_DANGER), ephemeral=True)
        elif action == "add" and user and badge:
            if badge not in BADGES:
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.FAIL}", f"Badge `{badge}` existiert nicht.", COLOR_DANGER), ephemeral=True)
            await self.bot.db.badge_add(interaction.guild.id, user.id, badge, interaction.user.id)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", f"Badge `{badge}` an {user.mention} vergeben.", COLOR_SUCCESS))
        elif action == "remove" and user and badge:
            await self.bot.db.badge_remove(interaction.guild.id, user.id, badge)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", f"Badge `{badge}` von {user.mention} entfernt.", COLOR_SUCCESS))

    # ── NOTE SYSTEM ──
    @app_commands.command(name="note", description="Moderator-Notizen verwalten")
    @app_commands.describe(action="add/list/delete", user="Der Nutzer", text="Notiz-Text", note_id="Notiz-ID", priority="low/medium/high", pinned="Notiz anpinnen")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_note(self, interaction: discord.Interaction, action: str,
                         user: Optional[discord.Member] = None, text: Optional[str] = None,
                         note_id: Optional[str] = None, priority: str = "medium", pinned: bool = False):
        if action == "add" and user and text:
            nid = await self.bot.db.add_note(interaction.guild.id, user.id, interaction.user.id, text, priority, pinned)
            await interaction.response.send_message(embed=create_embed(
                f"{E.NOTE} Notiz gespeichert",
                f"Für {user.mention}: {text[:100]}\nPriorität: **{priority}** · Pin: **{'Ja' if pinned else 'Nein'}**\nID: `{nid}`",
                COLOR_SUCCESS))
        elif action == "list" and user:
            notes = await self.bot.db.get_notes(interaction.guild.id, user.id)
            if not notes:
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.NOTE}", f"Keine Notizen für {user.mention}.", COLOR_INFO))
            lines = [f"{'📌 ' if n.get('pinned') else ''}`{n.get('_id', '?')}` **{n.get('priority','medium')}** – {n.get('text', '—')[:70]}" for n in notes[:15]]
            await interaction.response.send_message(embed=create_embed(
                f"{E.NOTE} Notizen ({len(notes)})", "\n".join(lines), COLOR_PRIMARY))
        elif action == "delete" and note_id:
            await self.bot.db.delete_note(interaction.guild.id, note_id)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", "Notiz gelöscht.", COLOR_SUCCESS))
        else:
            await interaction.response.send_message(embed=create_embed(
                f"{E.HELP}", "Nutzung: `/note add @user Text priority:high pinned:true` oder `/note list @user` oder `/note delete note_id:...`",
                COLOR_INFO), ephemeral=True)

    # ── WARN DECAY ──
    @app_commands.command(name="warndecay", description="Warn-Verfall konfigurieren")
    @app_commands.describe(action="enable/disable/status", days="Tage bis Verfall")
    @app_commands.default_permissions(administrator=True)
    async def slash_warndecay(self, interaction: discord.Interaction, action: str,
                               days: Optional[int] = None):
        cfg = self.bot.db.get_config(interaction.guild.id)
        wd = cfg.get("warn_decay", {"enabled": False, "decay_days": 30})
        if action == "enable":
            wd["enabled"] = True
            if days:
                wd["decay_days"] = max(1, min(days, 365))
            cfg["warn_decay"] = wd
            await self.bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Warn-Decay aktiviert", f"Warns verfallen nach {wd['decay_days']} Tagen.", COLOR_SUCCESS))
        elif action == "disable":
            wd["enabled"] = False
            cfg["warn_decay"] = wd
            await self.bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Warn-Decay deaktiviert", "", COLOR_SUCCESS))
        else:
            status = "aktiviert" if wd.get("enabled") else "deaktiviert"
            await interaction.response.send_message(embed=create_embed(
                f"{E.WARN} Warn-Decay", f"Status: **{status}**\nTage: {wd.get('decay_days', 30)}", COLOR_INFO))

    @tasks.loop(hours=24)
    async def warn_decay_loop(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                cfg = self.bot.db.get_config(guild.id)
                wd = cfg.get("warn_decay", {})
                if not wd.get("enabled"):
                    continue
                decay_days = wd.get("decay_days", 30)
                warns = cfg.get("warns", {})
                changed = False
                cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=decay_days)
                for uid, user_warns in list(warns.items()):
                    original = len(user_warns)
                    warns[uid] = [w for w in user_warns if
                                  datetime.datetime.fromisoformat(w.get("time", "2000-01-01")) > cutoff]
                    if len(warns[uid]) < original:
                        changed = True
                if changed:
                    cfg["warns"] = warns
                    await self.bot.db.set_config(guild.id, cfg)
            except Exception as e:
                log.debug(f"Warn-Decay error {guild.id}: {e}")

    # ── ERROR HANDLING ──
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=create_embed(f"{E.FAIL} Keine Berechtigung",
                "Dir fehlen die nötigen Rechte.", COLOR_DANGER), delete_after=10)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=create_embed(f"{E.FAIL} Fehlender Parameter",
                f"Parameter `{error.param.name}` fehlt.", COLOR_DANGER), delete_after=10)
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=create_embed(f"{E.FAIL} Ungültiger Parameter",
                str(error), COLOR_DANGER), delete_after=10)
        else:
            log.error(f"Command-Fehler: {error}")


async def setup(bot):
    await bot.add_cog(UtilityCog(bot))
