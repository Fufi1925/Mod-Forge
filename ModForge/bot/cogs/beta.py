# -*- coding: utf-8 -*-
"""
ModForge – BETA Features
========================
Alle Features aus Das67.txt Anforderungen:

1. 🌙 Dark Mode Toggle + Theme pro Server
2. 📡 Live Server Activity Feed (erweitert)
3. 👤 User Risk Profile
4. ⏱️ Smart Timeout Suggestions
5. 📋 Auto-Appeal System
6. 📝 Staff Application System

Diese Features sind als BETA markiert — Feedback willkommen!
"""
import asyncio
import datetime
import logging
from collections import defaultdict, deque
from typing import Dict, List, Optional, Any

import discord
from discord.ext import commands, tasks
from discord import app_commands

from bot.config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER, COLOR_INFO,
    COLOR_PURPLE, FOOTER_TEXT, FOOTER_ICON, log,
)
from bot.embed_config import get_embed, COLORS as EMBED_COLORS
from bot.utils import create_embed, safe_dm

# Farb-Aliase aus embed_config (für kürzere Verwendung)
COLOR_PINK = EMBED_COLORS["pink"]
COLOR_TEAL = EMBED_COLORS["teal"]
COLOR_DARK = EMBED_COLORS["dark"]
COLOR_GOLD = EMBED_COLORS["gold"]

# ═══════════════════════════════════════════════════════════════════
# BETA-FEATURE: Theme-System
# ═══════════════════════════════════════════════════════════════════
THEMES = {
    "dark":      {"name": "🌙 Dark",      "accent": 0x5865F2, "background": 0x1F2937},
    "light":     {"name": "☀️ Light",     "accent": 0x7C3AED, "background": 0xF3F4F6},
    "midnight":  {"name": "🌌 Midnight",  "accent": 0x8B5CF6, "background": 0x0F172A},
    "sunset":    {"name": "🌅 Sunset",    "accent": 0xEC4899, "background": 0x1E1B4B},
    "forest":    {"name": "🌲 Forest",    "accent": 0x22C55E, "background": 0x14532D},
    "neon":      {"name": "⚡ Neon",      "accent": 0xFACC15, "background": 0x000000},
    "ocean":     {"name": "🌊 Ocean",     "accent": 0x06B6D4, "background": 0x0C4A6E},
    "lavender":  {"name": "💜 Lavender",  "accent": 0xC084FC, "background": 0x2E1065},
}


# ═══════════════════════════════════════════════════════════════════
# BETA-FEATURE: Smart Timeout Suggestions
# ═══════════════════════════════════════════════════════════════════
def smart_timeout_suggestion(bot, guild_id: int, user_id: int) -> int:
    """Berechnet eine smarte Timeout-Dauer basierend auf vorherigen Cases.

    Logik:
      • 0 vorherige Cases: 5 Minuten (leichte Erinnerung)
      • 1-2 Cases: 30 Minuten
      • 3-5 Cases: 2 Stunden
      • 6+ Cases: 24 Stunden (längere Pause)
      • Maximal 28 Tage (Discord-Limit)
    """
    try:
        cases_count = 0
        if hasattr(bot, "db") and bot.db is not None:
            # Sync-Lookup im Cache
            cfg = bot.db.get_config(guild_id)
            cases_count = len(cfg.get("warns", {}).get(str(user_id), []))
        if cases_count == 0:
            return 300  # 5 min
        if cases_count <= 2:
            return 1800  # 30 min
        if cases_count <= 5:
            return 7200  # 2 h
        return 86400  # 24 h
    except Exception as ex:
        log.debug(f"smart_timeout_suggestion Fehler: {ex}")
        return 600  # Fallback: 10 min


# ═══════════════════════════════════════════════════════════════════
# BETA-FEATURE: User Risk Profile
# ═══════════════════════════════════════════════════════════════════
def compute_user_risk(member: discord.Member, cfg: dict, cases: list) -> dict:
    """Berechnet ein Risiko-Profil für einen User.

    Returns: dict mit score, flags, summary
    """
    now = datetime.datetime.utcnow()
    flags = []
    score = 0

    # Account-Alter
    if member.created_at:
        account_age_days = (now - member.created_at.replace(tzinfo=None)).days
        if account_age_days < 7:
            score += 30
            flags.append("⚠️ Neuer Account (<7 Tage)")
        elif account_age_days < 30:
            score += 10
            flags.append("Account <30 Tage alt")
    else:
        account_age_days = 0

    # Kein Avatar
    if not member.display_avatar or str(member.display_avatar.url).endswith("embed/avatars/"):
        if not member.bot:
            score += 10
            flags.append("Kein Profilbild")

    # Viele Cases
    cases_count = len(cases or [])
    if cases_count >= 10:
        score += 40
        flags.append(f"🚨 {cases_count} Cases!")
    elif cases_count >= 5:
        score += 20
        flags.append(f"{cases_count} Cases")
    elif cases_count >= 1:
        score += 5

    # Warns aus Config
    warns_count = len(cfg.get("warns", {}).get(str(member.id), []))
    if warns_count > 0:
        score += warns_count * 8
        flags.append(f"{warns_count} Warns")

    # Bot-Whitelist check
    if member.guild_permissions.administrator:
        score = 0  # Admins sind safe
        flags.insert(0, "✅ Administrator")

    score = min(score, 100)

    return {
        "score": score,
        "flags": flags,
        "account_age_days": account_age_days,
        "cases_count": cases_count,
        "warns_count": warns_count,
    }


# ═══════════════════════════════════════════════════════════════════
# BETA-FEATURE: DM-Benachrichtigungen (Auto-DM)
# ═══════════════════════════════════════════════════════════════════
async def send_punishment_dm(bot, member, punishment: str, reason: str, duration: Optional[int] = None, guild: discord.Guild = None):
    """Sendet automatisch eine DM bei Strafen.

    Aus Das67.txt:
      'mache das wenn user gestimmt wird dm user automatisch
       wenn timeout rum ist dm und wenn jemand früher timeout macht
       vei Kickt dm bei welcome dm und bei warn dm und alles'
    """
    if member is None or getattr(member, "bot", False):
        return False
    try:
        if punishment == "kick":
            embed = get_embed("kick", user=member, mod=bot.user, reason=reason, guild=guild, bot=bot)
        elif punishment == "ban":
            embed = get_embed("ban", user=member, mod=bot.user, reason=reason, guild=guild, bot=bot)
        elif punishment == "timeout":
            embed = get_embed("mute", user=member, mod=bot.user, reason=reason,
                              duration=f"{duration}s" if duration else "Unbekannt",
                              guild=guild, bot=bot)
        elif punishment == "untimeout":
            embed = get_embed("success", message="Dein Timeout wurde aufgehoben.", user=member, bot=bot)
            return await safe_dm(member, embed, cooldown_key=f"untimeout:{guild.id if guild else 0}:{member.id}")
        else:
            embed = get_embed("warn", user=member, mod=bot.user, reason=reason, guild=guild, bot=bot)

        key = f"{punishment}:{guild.id if guild else 0}:{member.id}"
        return await safe_dm(member, embed, cooldown_key=key)
    except Exception as e:
        log.debug(f"send_punishment_dm Fehler: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
# BETA-COG
# ═══════════════════════════════════════════════════════════════════
class BetaCog(commands.Cog):
    """Beta-Features (Dark Mode, Risk Profile, Smart Timeout, Appeals, Staff)"""

    def __init__(self, bot):
        self.bot = bot
        self.live_feed = deque(maxlen=200)  # erweiterter Live-Feed
        self.appeals_pending: Dict[str, dict] = {}

    # ── DARK MODE / THEME ──────────────────────────────────────
    @app_commands.command(name="theme", description="[BETA] Setze das Theme für diesen Server")
    @app_commands.describe(theme="Welches Theme?")
    @app_commands.default_permissions(administrator=True)
    @app_commands.choices(theme=[
        app_commands.Choice(name=v["name"], value=k)
        for k, v in THEMES.items()
    ])
    async def slash_theme(self, interaction: discord.Interaction, theme: str):
        if theme not in THEMES:
            return await interaction.response.send_message(embed=get_embed("error", message="Unbekanntes Theme.", user=interaction.user, bot=self.bot), ephemeral=True)
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["theme"] = theme
        await self.bot.db.set_config(interaction.guild.id, cfg)
        info = THEMES[theme]
        embed = discord.Embed(
            title=f"{info['name']} aktiviert",
            description=f"Das Theme wurde auf **{info['name']}** gesetzt.",
            color=info["accent"],
        )
        embed.add_field(name="Akzentfarbe", value=f"#{info['accent']:06X}", inline=True)
        embed.set_footer(text="🌙 Theme System • BETA", icon_url=FOOTER_ICON)
        await interaction.response.send_message(embed=embed)

    # ── USER RISK PROFILE ──────────────────────────────────────
    @app_commands.command(name="risk", description="[BETA] Zeigt das Risiko-Profil eines Users")
    @app_commands.describe(member="Welcher User?")
    async def slash_risk(self, interaction: discord.Interaction, member: discord.Member):
        cfg = self.bot.db.get_config(interaction.guild.id)
        try:
            cases = await self.bot.db.aget_recent_cases(interaction.guild.id, limit=100)
            cases = [c for c in cases if str(c.get("user_id")) == str(member.id)]
        except Exception:
            cases = []
        risk = compute_user_risk(member, cfg, cases)

        # Score-Farbe
        if risk["score"] >= 70:
            color = COLOR_DANGER
            verdict = "🚨 Hohes Risiko"
        elif risk["score"] >= 40:
            color = COLOR_WARNING
            verdict = "⚠️ Mittleres Risiko"
        elif risk["score"] >= 20:
            color = COLOR_INFO
            verdict = "ℹ️ Leicht erhöht"
        else:
            color = COLOR_SUCCESS
            verdict = "✅ Sicher"

        embed = discord.Embed(
            title=f"👤 Risiko-Profil: {member.display_name}",
            description=verdict,
            color=color,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Risk-Score", value=f"**{risk['score']}/100**", inline=True)
        embed.add_field(name="Account-Alter", value=f"{risk['account_age_days']} Tage", inline=True)
        embed.add_field(name="Cases", value=str(risk["cases_count"]), inline=True)
        embed.add_field(name="Warns", value=str(risk["warns_count"]), inline=True)
        if risk["flags"]:
            embed.add_field(name="Flags", value="\n".join(risk["flags"])[:1024], inline=False)
        embed.set_footer(text="🛡️ Risk Profile • BETA", icon_url=FOOTER_ICON)
        await interaction.response.send_message(embed=embed)

    # ── SMART TIMEOUT SUGGESTIONS ──────────────────────────────
    @app_commands.command(name="mute", description="Timeout mit Smart-Suggestion [BETA: zeigt Vorschlag]")
    @app_commands.describe(member="Welcher User?", duration="Dauer in Sekunden (leer = Vorschlag)", reason="Grund")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_mute(self, interaction: discord.Interaction, member: discord.Member, duration: Optional[int] = None, reason: str = "Kein Grund angegeben"):
        if duration is None:
            # Smart-Vorschlag
            suggestion = smart_timeout_suggestion(self.bot, interaction.guild.id, member.id)
            minutes = suggestion // 60
            hours = minutes // 60
            embed = discord.Embed(
                title="⏱️ Smart Timeout Vorschlag",
                description=f"Für **{member.mention}** basierend auf vorherigen Cases:",
                color=COLOR_PRIMARY,
            )
            embed.add_field(name="Empfehlung", value=f"**{suggestion} Sekunden** ({minutes} Min / {hours}h)", inline=False)
            embed.add_field(name="Grund", value=reason, inline=False)
            embed.add_field(name="Aktion", value="Nutze `/mute <user> <dauer>` um den Vorschlag anzuwenden.", inline=False)
            embed.set_footer(text="⏱️ Smart Timeout • BETA", icon_url=FOOTER_ICON)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # Echtes Timeout anwenden
        await interaction.response.defer()
        try:
            duration = max(60, min(int(duration), 2419200))
            until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=duration)
            await member.timeout(until, reason=f"[Dashboard/Smart] {reason}")
            # Auto-DM
            await send_punishment_dm(self.bot, member, "timeout", reason, duration=duration, guild=interaction.guild)
            embed = get_embed("mute", user=member, mod=interaction.user, reason=reason,
                              duration=f"{duration}s", guild=interaction.guild, bot=self.bot)
            await interaction.followup.send(embed=embed)
            await self.bot.log_action(interaction.guild, f"{"🔇"} Smart Timeout", f"{member.mention} ({duration}s) - {reason}",
                                       COLOR_WARNING, user=member, module="moderation")
        except discord.Forbidden:
            embed = get_embed("error", message="Keine Berechtigung.", user=interaction.user, bot=self.bot)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            embed = get_embed("error", message=f"Fehler: {e}", user=interaction.user, bot=self.bot)
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── LIVE SERVER ACTIVITY FEED ──────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Trackt Voice-Events für den Live-Feed."""
        if before.channel != after.channel:
            self.live_feed.append({
                "type": "voice_move" if (before.channel and after.channel) else ("voice_join" if after.channel else "voice_leave"),
                "user": str(member),
                "channel": after.channel.name if after.channel else (before.channel.name if before.channel else "?"),
                "guild": str(member.guild.name) if member.guild else "?",
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
            })

    # ── AUTO-APPEAL SYSTEM ─────────────────────────────────────
    @app_commands.command(name="appeal", description="[BETA] Stelle einen Entbannungs-Antrag")
    @app_commands.describe(reason="Warum möchtest du entbannt werden?")
    async def slash_appeal(self, interaction: discord.Interaction, reason: str):
        if not interaction.guild:
            return await interaction.response.send_message(embed=get_embed("error", message="Nur in Servern nutzbar.", user=interaction.user, bot=self.bot), ephemeral=True)
        try:
            appeal_id = await self.bot.db.acreate_appeal(interaction.guild.id, interaction.user.id, reason)
            if appeal_id:
                # Auto-DM an Owner
                try:
                    if interaction.guild.owner:
                        embed = get_embed("info", title="📬 Neuer Appeal", description=f"{interaction.user.mention} bittet um Entbannung:\n> {reason}", bot=self.bot)
                        await interaction.guild.owner.send(embed=embed)
                except Exception:
                    pass
                embed = get_embed("success", message=f"Dein Appeal wurde eingereicht (ID: `{appeal_id}`). Das Mod-Team wird benachrichtigt.", user=interaction.user, bot=self.bot)
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                embed = get_embed("error", message="Appeal konnte nicht erstellt werden.", user=interaction.user, bot=self.bot)
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = get_embed("error", message=f"Fehler: {e}", user=interaction.user, bot=self.bot)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── STAFF APPLICATION SYSTEM ───────────────────────────────
    @app_commands.command(name="apply", description="[BETA] Bewirb dich als Staff-Mitglied")
    @app_commands.describe(question="Deine Antwort auf die Bewerbungsfrage")
    async def slash_apply(self, interaction: discord.Interaction, question: str):
        if not interaction.guild:
            return await interaction.response.send_message(embed=get_embed("error", message="Nur in Servern nutzbar.", user=interaction.user, bot=self.bot), ephemeral=True)
        try:
            answers = {"motivation": question}
            application_id = await self.bot.db.acreate_staff_application(interaction.guild.id, interaction.user.id, answers)
            if application_id:
                embed = get_embed("success", message=f"Deine Bewerbung wurde eingereicht (ID: `{application_id}`).", user=interaction.user, bot=self.bot)
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                embed = get_embed("error", message="Bewerbung konnte nicht eingereicht werden.", user=interaction.user, bot=self.bot)
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = get_embed("error", message=f"Fehler: {e}", user=interaction.user, bot=self.bot)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── UNTIMEOUT AUTO-DM ──────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Trackt Member-Updates + sendet DM wenn Timeout endet."""
        # Live-Feed: Status-Wechsel
        try:
            if before.status != after.status:
                self.live_feed.append({
                    "type": "status_change",
                    "user": str(after),
                    "from": str(before.status),
                    "to": str(after.status),
                    "guild": str(after.guild.name) if after.guild else "?",
                    "ts": datetime.datetime.utcnow().isoformat() + "Z",
                })
        except Exception:
            pass

        # Auto-DM: Timeout endet gerade
        try:
            was_timed_out = before.timed_out_until and before.timed_out_until > datetime.datetime.now(datetime.timezone.utc)
            is_timed_out = after.timed_out_until and after.timed_out_until > datetime.datetime.now(datetime.timezone.utc)
            if was_timed_out and not is_timed_out and not after.bot:
                embed = get_embed("success", message="Dein Timeout ist abgelaufen. Du kannst wieder schreiben.", user=after, bot=self.bot)
                await safe_dm(after, embed, cooldown_key=f"timeout_end:{after.guild.id}:{after.id}")
        except Exception as ex:
            log.debug(f"untimeout-dm Fehler: {ex}")


async def setup(bot):
    await bot.add_cog(BetaCog(bot))
