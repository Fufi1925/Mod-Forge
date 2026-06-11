# -*- coding: utf-8 -*-
"""ModForge Admin Cog – Owner/Admin Commands, Cases, Audit-Perms."""
import asyncio

import discord
from discord.ext import commands
from discord import app_commands

from bot.config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_INFO, E,
)
from bot.utils import create_embed


class AdminCog(commands.Cog):
    """Admin-Commands: Cases, Audit-Perms, Mass-Actions, etc."""

    def __init__(self, bot):
        self.bot = bot

    # ── CASES ──
    @app_commands.command(name="case", description="Zeigt einen Case an")
    @app_commands.describe(case_id="Case-ID")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_case(self, interaction: discord.Interaction, case_id: int):
        case = await self.bot.db.aget_case(interaction.guild.id, case_id)
        if not case:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", f"Case #{case_id} nicht gefunden.", COLOR_DANGER), ephemeral=True)
        fields = [
            ("Aktion", case.get("action", "?"), True),
            ("User", f"<@{case.get('user_id', 0)}>", True),
            ("Moderator", f"<@{case.get('mod_id', 0)}>", True),
            ("Grund", case.get("reason", "—"), False),
        ]
        if case.get("duration"):
            fields.append(("Dauer", f"{case['duration']}s", True))
        if case.get("evidence"):
            fields.append(("Beweise", str(len(case["evidence"])), True))
        if case.get("message_archive"):
            fields.append(("Archivierte Nachrichten", str(len(case["message_archive"])), True))
        await interaction.response.send_message(embed=create_embed(
            f"{E.CASE} Case #{case_id}", "", COLOR_PRIMARY, fields))

    @app_commands.command(name="cases", description="Zeigt die letzten Cases")
    @app_commands.describe(limit="Anzahl (max 50)")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_cases(self, interaction: discord.Interaction, limit: int = 20):
        cases = await self.bot.db.aget_recent_cases(interaction.guild.id, limit=min(limit, 50))
        if not cases:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", "Keine Cases vorhanden.", COLOR_INFO))
        lines = []
        for c in cases:
            action_emoji = {"ban": E.BAN, "kick": E.KICK, "warn": E.WARN, "timeout": E.MUTE, "softban": E.BAN,
                           "tempban": E.TIMER, "tempmute": E.TIMER}.get(c.get("action", ""), E.CASE)
            lines.append(f"{action_emoji} `#{c.get('case_id', '?')}` {c.get('action', '?')} – <@{c.get('user_id', 0)}> – {c.get('reason', '—')[:30]}")
        await interaction.response.send_message(embed=create_embed(
            f"{E.CASE} Cases ({len(cases)})", "\n".join(lines[:25]), COLOR_PRIMARY))

    @app_commands.command(name="case_edit", description="Ändert den Grund eines Cases")
    @app_commands.describe(case_id="Case-ID", reason="Neuer Grund")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_case_edit(self, interaction: discord.Interaction, case_id: int, reason: str):
        ok = await self.bot.db.aupdate_case_reason(interaction.guild.id, case_id, reason, interaction.user.id)
        if ok:
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Case #{case_id} aktualisiert", f"Neuer Grund: {reason}", COLOR_SUCCESS))
        else:
            await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Case nicht gefunden.", COLOR_DANGER), ephemeral=True)

    # ── AUDIT-PERMS ──
    @app_commands.command(name="audit-perms", description="Prüft gefährliche Berechtigungen")
    @app_commands.default_permissions(administrator=True)
    async def slash_audit_perms(self, interaction: discord.Interaction):
        guild = interaction.guild
        cfg = self.bot.db.get_config(guild.id)
        danger_perms = cfg.get("perms_audit", {}).get("danger_perms", [
            "administrator", "manage_guild", "manage_roles", "manage_channels",
            "ban_members", "kick_members", "manage_webhooks"])

        issues = []
        for role in guild.roles:
            if role.is_default() or role.managed:
                continue
            for perm_name in danger_perms:
                if getattr(role.permissions, perm_name, False):
                    level = f"{E.FAIL} CRITICAL" if perm_name == "administrator" else f"{E.WARN} HIGH"
                    issues.append(f"{level} {role.mention} → `{perm_name}`")

        if not issues:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Keine Probleme", "Alle Berechtigungen sehen sicher aus.", COLOR_SUCCESS))

        # Split if too long
        desc = "\n".join(issues[:30])
        if len(issues) > 30:
            desc += f"\n\n... und {len(issues) - 30} weitere"
        await interaction.response.send_message(embed=create_embed(
            f"{E.SHIELD} Berechtigungs-Audit ({len(issues)} Funde)", desc, COLOR_WARNING))

    # ── MASSUNBAN ──
    @app_commands.command(name="massunban", description="Entbannt ALLE gebannten User")
    @app_commands.default_permissions(administrator=True)
    async def slash_massunban(self, interaction: discord.Interaction):
        await interaction.response.defer()
        unbanned = 0
        try:
            async for entry in interaction.guild.bans(limit=1000):
                try:
                    await interaction.guild.unban(entry.user, reason="Mass-Unban")
                    unbanned += 1
                    if unbanned % 10 == 0:
                        await asyncio.sleep(1)
                except (discord.Forbidden, discord.HTTPException):
                    pass
        except discord.Forbidden:
            return await interaction.followup.send(embed=create_embed(
                f"{E.FAIL}", "Keine Berechtigung für Banliste.", COLOR_DANGER))
        await interaction.followup.send(embed=create_embed(
            f"{E.OK} Mass-Unban", f"{unbanned} User entbannt.", COLOR_SUCCESS))

    # ── MASSBAN ──
    @app_commands.command(name="massban", description="Bannt mehrere Nutzer gleichzeitig")
    @app_commands.describe(user_ids="User-IDs (kommagetrennt)", reason="Grund")
    @app_commands.default_permissions(ban_members=True)
    async def slash_massban(self, interaction: discord.Interaction, user_ids: str, reason: str = "Mass-Ban"):
        await interaction.response.defer()
        ids = [uid.strip() for uid in user_ids.split(",") if uid.strip().isdigit()]
        banned = 0
        for uid in ids:
            try:
                await interaction.guild.ban(discord.Object(id=int(uid)), reason=reason)
                banned += 1
                await asyncio.sleep(0.5)
            except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                pass
        await interaction.followup.send(embed=create_embed(
            f"{E.OK} Mass-Ban", f"{banned}/{len(ids)} User gebannt.\nGrund: {reason}", COLOR_SUCCESS))

    # ── MASSROLE ──
    @app_commands.command(name="massrole_remove", description="Entfernt eine Rolle von allen Mitgliedern")
    @app_commands.describe(role="Die Rolle")
    @app_commands.default_permissions(administrator=True)
    async def slash_massrole_remove(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer()
        removed = 0
        for member in role.members:
            try:
                await member.remove_roles(role, reason="Mass-Role Remove")
                removed += 1
                if removed % 5 == 0:
                    await asyncio.sleep(1)
            except (discord.Forbidden, discord.HTTPException):
                pass
        await interaction.followup.send(embed=create_embed(
            f"{E.OK} Mass-Role Remove", f"{role.mention} von {removed} Mitgliedern entfernt.", COLOR_SUCCESS))

    # ── SETARCHIVE ──
    @app_commands.command(name="setarchive", description="Setzt den Archiv-Kanal")
    @app_commands.describe(channel="Der Kanal")
    @app_commands.default_permissions(administrator=True)
    async def slash_setarchive(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["archive_channel"] = channel.id
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Archiv-Kanal", f"Gesetzt auf {channel.mention}", COLOR_SUCCESS))

    # ── APPEAL CONFIG ──
    @app_commands.command(name="banappeal", description="Ban-Appeal System konfigurieren")
    @app_commands.describe(enabled="Aktivieren/Deaktivieren")
    @app_commands.default_permissions(administrator=True)
    async def slash_banappeal(self, interaction: discord.Interaction, enabled: bool):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["auto_ban_appeal"] = {"enabled": enabled}
        await self.bot.db.set_config(interaction.guild.id, cfg)
        status = "aktiviert" if enabled else "deaktiviert"
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Ban-Appeal", f"System **{status}**.", COLOR_SUCCESS))

    @app_commands.command(name="appeal_channel", description="Setzt den Appeal-Log-Kanal")
    @app_commands.describe(channel="Der Kanal")
    @app_commands.default_permissions(administrator=True)
    async def slash_appeal_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["appeal_log_channel"] = channel.id
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Appeal-Kanal", f"Gesetzt auf {channel.mention}", COLOR_SUCCESS))

    # ── INVITES ──
    @app_commands.command(name="invites", description="Invite-Statistiken eines Users")
    @app_commands.describe(member="Der Nutzer")
    async def slash_invites(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        try:
            invites = await interaction.guild.invites()
            user_invites = [inv for inv in invites if inv.inviter and inv.inviter.id == target.id]
            total = sum(inv.uses for inv in user_invites)
            lines = [f"`{inv.code}` – {inv.uses} Nutzungen" for inv in user_invites[:10]]
            await interaction.response.send_message(embed=create_embed(
                f"{E.JOIN} Invites von {target}", f"**Gesamt:** {total} Einladungen\n\n" + "\n".join(lines),
                COLOR_PRIMARY))
        except discord.Forbidden:
            await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Keine Berechtigung für Invite-Liste.", COLOR_DANGER), ephemeral=True)

    # ── MODSTATS ──
    @app_commands.command(name="modstats", description="Moderator-Statistiken")
    @app_commands.describe(moderator="Der Moderator")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_modstats(self, interaction: discord.Interaction, moderator: discord.Member = None):
        cases = await self.bot.db.aget_recent_cases(interaction.guild.id, limit=500)
        if moderator:
            mod_cases = [c for c in cases if c.get("mod_id") == moderator.id]
            actions = {}
            for c in mod_cases:
                act = c.get("action", "?")
                actions[act] = actions.get(act, 0) + 1
            lines = [f"**{act}:** {count}" for act, count in sorted(actions.items(), key=lambda x: -x[1])]
            await interaction.response.send_message(embed=create_embed(
                f"{E.STATS} Modstats – {moderator}", f"**Gesamt:** {len(mod_cases)} Cases\n\n" + "\n".join(lines),
                COLOR_PRIMARY))
        else:
            # Ranking
            mod_counts = {}
            for c in cases:
                mid = c.get("mod_id", 0)
                mod_counts[mid] = mod_counts.get(mid, 0) + 1
            ranking = sorted(mod_counts.items(), key=lambda x: -x[1])[:10]
            lines = [f"**{i+1}.** <@{mid}> – {count} Cases" for i, (mid, count) in enumerate(ranking)]
            await interaction.response.send_message(embed=create_embed(
                f"{E.STATS} Mod-Ranking", "\n".join(lines) or "Keine Cases.", COLOR_PRIMARY))

    # ── REPORT ──
    @app_commands.command(name="report", description="Meldet einen User")
    @app_commands.describe(member="Der Nutzer", reason="Grund")
    async def slash_report(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        cfg = self.bot.db.get_config(interaction.guild.id)
        ch_id = cfg.get("report_channel")
        if not ch_id:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Kein Report-Kanal konfiguriert. Nutze `/report_setup`.", COLOR_DANGER), ephemeral=True)
        channel = interaction.guild.get_channel(ch_id)
        if not channel:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Report-Kanal nicht gefunden.", COLOR_DANGER), ephemeral=True)
        embed = create_embed(f"{E.REPORT} Report", f"**Gemeldet:** {member.mention}\n**Von:** {interaction.user.mention}\n**Grund:** {reason}",
            COLOR_DANGER, user=member)
        await channel.send(embed=embed)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Report gesendet", f"Report über {member.mention} wurde gesendet.", COLOR_SUCCESS), ephemeral=True)

    @app_commands.command(name="report_setup", description="Setzt den Report-Kanal")
    @app_commands.describe(channel="Der Kanal")
    @app_commands.default_permissions(administrator=True)
    async def slash_report_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["report_channel"] = channel.id
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Report-Kanal", f"Gesetzt auf {channel.mention}", COLOR_SUCCESS))

    # ── AUTO BACKUP SETUP ──
    @app_commands.command(name="backup_autosetup", description="Auto-Backup konfigurieren")
    @app_commands.describe(enabled="Aktivieren", interval="Intervall in Stunden", max_backups="Max Backups")
    @app_commands.default_permissions(administrator=True)
    async def slash_backup_autosetup(self, interaction: discord.Interaction,
                                      enabled: bool = True, interval: int = 24, max_backups: int = 5):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["backup_system"] = {
            "auto_enabled": enabled,
            "auto_interval_hours": max(1, min(interval, 168)),
            "auto_max_backups": max(1, min(max_backups, 20)),
            "auto_last_backup": cfg.get("backup_system", {}).get("auto_last_backup"),
        }
        await self.bot.db.set_config(interaction.guild.id, cfg)
        status = "aktiviert" if enabled else "deaktiviert"
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Auto-Backup {status}",
            f"**Intervall:** {interval}h\n**Max Backups:** {max_backups}",
            COLOR_SUCCESS))


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
