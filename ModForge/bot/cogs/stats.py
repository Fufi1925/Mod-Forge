# -*- coding: utf-8 -*-
"""
ModForge Stats Cog – Features 301-350
Server-Stats, Heatmap, Command-Usage, Performance-Monitoring, Log-System.
"""
import asyncio
import datetime
import os
import time
import psutil
from typing import Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands

from bot.config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_INFO, E, log, get_uptime, ACTIVITY,
)
from bot.utils import create_embed


class StatsCog(commands.Cog):
    """Server-Statistiken, Performance-Monitoring, Logs."""

    def __init__(self, bot):
        self.bot = bot
        self._cmd_usage = {}  # {command_name: count}
        self._hourly_messages = {}  # {guild_id: {hour: count}}
        self.stats_collect_loop.start()

    def cog_unload(self):
        self.stats_collect_loop.cancel()

    @commands.Cog.listener()
    async def on_command(self, ctx):
        """Feature 318: Command-Usage-Stats."""
        name = ctx.command.qualified_name if ctx.command else "unknown"
        self._cmd_usage[name] = self._cmd_usage.get(name, 0) + 1

    @commands.Cog.listener()
    async def on_message(self, message):
        """Feature 301, 303, 304: Activity-Heatmap + Channel-Usage."""
        if not message.guild or message.author.bot:
            return
        cfg = self.bot.db.get_config(message.guild.id)
        ss = cfg.get("stats_system", {})
        if not ss.get("enabled") or not ss.get("track_messages"):
            return
        hour = datetime.datetime.utcnow().hour
        gid = message.guild.id
        self._hourly_messages.setdefault(gid, {})
        self._hourly_messages[gid][hour] = self._hourly_messages[gid].get(hour, 0) + 1

    @tasks.loop(minutes=30)
    async def stats_collect_loop(self):
        """Periodisch Stats in DB speichern."""
        await self.bot.wait_until_ready()
        for gid, hourly in self._hourly_messages.items():
            if not hourly:
                continue
            try:
                await self.bot.db.data.update_one(
                    {"type": "stats_hourly", "guild_id": gid, "date": datetime.datetime.utcnow().strftime("%Y-%m-%d")},
                    {"$inc": {f"hours.{h}": c for h, c in hourly.items()},
                     "$set": {"updated_at": datetime.datetime.utcnow()}},
                    upsert=True)
            except Exception:
                pass
        self._hourly_messages.clear()

    # ── SLASH COMMANDS ──
    @app_commands.command(name="stats", description="Server-Statistiken anzeigen")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_stats(self, interaction: discord.Interaction):
        """Feature 301-310: Umfassende Server-Statistiken."""
        guild = interaction.guild
        # Member demographics
        total = guild.member_count or 0
        bots = sum(1 for m in guild.members if m.bot)
        humans = total - bots
        online = sum(1 for m in guild.members if m.status != discord.Status.offline)
        # Role distribution
        roles_count = len(guild.roles) - 1  # exclude @everyone
        # Channel usage
        text_ch = len(guild.text_channels)
        voice_ch = len(guild.voice_channels)
        categories = len(guild.categories)
        # Cases
        cases = await self.bot.db.aget_recent_cases(guild.id, limit=1000)
        today = datetime.datetime.utcnow().date()
        cases_today = sum(1 for c in cases if c.get("created_at") and c["created_at"].date() == today)
        cases_week = sum(1 for c in cases if c.get("created_at") and
                        (datetime.datetime.utcnow() - c["created_at"]).days < 7)

        fields = [
            ("👥 Mitglieder", f"{humans} Menschen, {bots} Bots", True),
            (f"{E.OK} Online", str(online), True),
            (f"{E.ROLES} Rollen", str(roles_count), True),
            ("💬 Kanäle", f"{text_ch}T / {voice_ch}V / {categories}K", True),
            (f"{E.CASE} Cases (Heute)", str(cases_today), True),
            (f"{E.CASE} Cases (Woche)", str(cases_week), True),
            (f"{E.LOCK} Boost-Level", str(guild.premium_tier), True),
            ("📅 Erstellt", f"<t:{int(guild.created_at.timestamp())}:R>", True),
        ]
        await interaction.response.send_message(embed=create_embed(
            f"{E.STATS} Server-Statistiken – {guild.name}", "", COLOR_PRIMARY, fields,
            thumbnail=guild.icon.url if guild.icon else None))

    @app_commands.command(name="heatmap", description="Server-Aktivitäts-Heatmap")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_heatmap(self, interaction: discord.Interaction):
        """Feature 301: Server-Activity-Heatmap."""
        gid = interaction.guild.id
        # Get last 7 days of data
        docs = await self.bot.db.data.find(
            {"type": "stats_hourly", "guild_id": gid}
        ).sort("date", -1).to_list(7)

        if not docs:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.STATS}", "Noch keine Daten. Aktiviere Stats mit `/stats_enable`.", COLOR_INFO))

        # Aggregate hours
        hour_totals = {}
        for doc in docs:
            for h, count in doc.get("hours", {}).items():
                hour_totals[int(h)] = hour_totals.get(int(h), 0) + count

        # Build visual heatmap
        max_val = max(hour_totals.values()) if hour_totals else 1
        blocks = ["░", "▒", "▓", "█"]
        lines = []
        for h in range(24):
            val = hour_totals.get(h, 0)
            level = min(3, int(val / max(max_val / 4, 1)))
            bar = blocks[level] * 8
            lines.append(f"`{h:02d}:00` {bar} {val}")

        await interaction.response.send_message(embed=create_embed(
            "🔥 Aktivitäts-Heatmap (7 Tage)", "\n".join(lines), COLOR_PRIMARY))

    @app_commands.command(name="botstats", description="Bot-Performance-Statistiken")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_botstats(self, interaction: discord.Interaction):
        """Feature 323-330: Performance/Resource-Monitoring."""
        uptime = get_uptime()
        d, r = divmod(uptime, 86400)
        h, r = divmod(r, 3600)
        m, _ = divmod(r, 60)
        # System stats
        try:
            proc = psutil.Process(os.getpid())
            mem = proc.memory_info().rss / 1024 / 1024  # MB
            cpu = proc.cpu_percent(interval=0.1)
        except Exception:
            mem, cpu = 0, 0

        total_guilds = len(self.bot.guilds)
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        latency = round(self.bot.latency * 1000)

        # Command usage stats
        top_cmds = sorted(self._cmd_usage.items(), key=lambda x: -x[1])[:5]
        cmd_text = "\n".join(f"`/{name}`: {count}x" for name, count in top_cmds) if top_cmds else "Keine Daten"

        fields = [
            ("⏱️ Uptime", f"{int(d)}d {int(h)}h {int(m)}m", True),
            ("📡 Ping", f"{latency}ms", True),
            ("🏠 Server", str(total_guilds), True),
            ("👥 Mitglieder", f"{total_members:,}", True),
            ("💾 RAM", f"{mem:.1f} MB", True),
            ("🖥️ CPU", f"{cpu:.1f}%", True),
            ("🔝 Top Commands", cmd_text, False),
        ]
        await interaction.response.send_message(embed=create_embed(
            f"{E.BOT} Bot-Performance", "", COLOR_PRIMARY, fields))

    @app_commands.command(name="stats_enable", description="Aktiviert das Stats-System")
    @app_commands.default_permissions(administrator=True)
    async def slash_stats_enable(self, interaction: discord.Interaction):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg.setdefault("stats_system", {})["enabled"] = True
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Stats aktiviert", "Nachrichten, Voice und Joins werden getrackt.", COLOR_SUCCESS))

    @app_commands.command(name="cmdstats", description="Zeigt Command-Nutzungsstatistiken")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_cmdstats(self, interaction: discord.Interaction):
        """Feature 318: Command-Usage-Stats."""
        if not self._cmd_usage:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.STATS}", "Noch keine Command-Nutzung aufgezeichnet.", COLOR_INFO))
        sorted_cmds = sorted(self._cmd_usage.items(), key=lambda x: -x[1])[:20]
        lines = [f"`{name}`: {count}x" for name, count in sorted_cmds]
        await interaction.response.send_message(embed=create_embed(
            f"{E.STATS} Command-Statistiken", "\n".join(lines), COLOR_PRIMARY))

    @app_commands.command(name="rolestats", description="Zeigt Rollen-Verteilung")
    async def slash_rolestats(self, interaction: discord.Interaction):
        """Feature 315: Role-Distribution."""
        guild = interaction.guild
        role_counts = sorted(
            [(r, len(r.members)) for r in guild.roles if not r.is_default() and len(r.members) > 0],
            key=lambda x: -x[1])[:15]
        lines = [f"{r.mention}: **{count}** Mitglieder" for r, count in role_counts]
        await interaction.response.send_message(embed=create_embed(
            f"{E.STATS} Rollen-Verteilung", "\n".join(lines) or "Keine Rollen mit Mitgliedern.", COLOR_PRIMARY))

    @app_commands.command(name="growth", description="Server-Wachstum anzeigen")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_growth(self, interaction: discord.Interaction):
        """Feature 309: Growth-Rate-Tracking."""
        events = await self.bot.db.aget_recent_guild_events(limit=100)
        guild_events = [e for e in events if e.get("guild_id") == interaction.guild.id]
        joins = sum(1 for e in guild_events if e.get("event") == "member_join")
        leaves = sum(1 for e in guild_events if e.get("event") == "member_leave")
        net = joins - leaves
        fields = [
            ("Beitritte", str(joins), True),
            ("Verlassen", str(leaves), True),
            ("Netto", f"{'+' if net >= 0 else ''}{net}", True),
            ("Aktuell", str(interaction.guild.member_count), True),
        ]
        await interaction.response.send_message(embed=create_embed(
            f"{E.GROWTH} Server-Wachstum", "", COLOR_PRIMARY, fields))


async def setup(bot):
    await bot.add_cog(StatsCog(bot))
