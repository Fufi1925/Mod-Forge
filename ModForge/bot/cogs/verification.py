# -*- coding: utf-8 -*-
"""
ModForge Verification Cog – Erweitert mit Features 51-110
Math-CAPTCHA, Quiz, Multi-Step, Timer, Trust-Score, Anti-Alt, etc.
"""
import asyncio
import datetime
import random
import time
from typing import Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands

from bot.config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_INFO, E, VERIFY_BANNER_URL, log,
)
from bot.utils import create_embed, generate_captcha
from bot.bot import VerifyView, CaptchaEntryView, safe_dm, _BOT_DEV_ID

# ═══════════════════════════════════════════════════════════════
# PENDING VERIFICATIONS (in-memory)
# ═══════════════════════════════════════════════════════════════
_pending_verify: dict = {}  # guild_id -> {user_id: {"started": ts, "step": int, ...}}
_failed_counter: dict = {}  # guild_id -> {user_id: int}


class MathCaptchaModal(discord.ui.Modal, title="Math-CAPTCHA"):
    """Feature 55: Math-CAPTCHA."""
    answer = discord.ui.TextInput(label="Löse die Aufgabe", placeholder="Ergebnis eingeben",
                                  min_length=1, max_length=10)

    def __init__(self, correct: int, bot_ref, add_roles, remove_roles):
        super().__init__()
        self.correct = correct
        self.bot = bot_ref
        self.add_roles = add_roles
        self.remove_roles = remove_roles

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_answer = int(self.answer.value.strip())
        except ValueError:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Ungültige Zahl!", COLOR_DANGER), ephemeral=True)
        if user_answer == self.correct:
            for r_id in self.add_roles:
                role = interaction.guild.get_role(r_id)
                if role:
                    await interaction.user.add_roles(role, reason="Math-CAPTCHA gelöst")
            for r_id in self.remove_roles:
                role = interaction.guild.get_role(r_id)
                if role:
                    await interaction.user.remove_roles(role, reason="Math-CAPTCHA gelöst")
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Verifiziert!", "Math-CAPTCHA korrekt gelöst.", COLOR_SUCCESS), ephemeral=True)
            await self.bot.log_action(interaction.guild, f"{E.VERIFY} Math-CAPTCHA gelöst",
                f"{interaction.user.mention}", COLOR_SUCCESS, user=interaction.user, module="verify")
        else:
            gid = interaction.guild.id
            uid = interaction.user.id
            _failed_counter.setdefault(gid, {})[uid] = _failed_counter.get(gid, {}).get(uid, 0) + 1
            await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", f"Falsch! Richtige Antwort: {self.correct}", COLOR_DANGER), ephemeral=True)


class QuizModal(discord.ui.Modal, title="Verifizierungs-Quiz"):
    """Feature 69: Quiz-System."""
    answer = discord.ui.TextInput(label="Deine Antwort", placeholder="Antwort eingeben",
                                  min_length=1, max_length=200)

    def __init__(self, correct: str, bot_ref, add_roles, remove_roles, question: str):
        super().__init__()
        self.correct = correct.lower().strip()
        self.bot = bot_ref
        self.add_roles = add_roles
        self.remove_roles = remove_roles

    async def on_submit(self, interaction: discord.Interaction):
        if self.answer.value.lower().strip() == self.correct:
            for r_id in self.add_roles:
                role = interaction.guild.get_role(r_id)
                if role:
                    await interaction.user.add_roles(role, reason="Quiz gelöst")
            for r_id in self.remove_roles:
                role = interaction.guild.get_role(r_id)
                if role:
                    await interaction.user.remove_roles(role, reason="Quiz gelöst")
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Verifiziert!", "Quiz korrekt beantwortet.", COLOR_SUCCESS), ephemeral=True)
        else:
            await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Falsche Antwort!", COLOR_DANGER), ephemeral=True)


class ExtendedVerifyView(discord.ui.View):
    """Erweiterte Verify-View mit verschiedenen Modi."""
    def __init__(self, bot_ref):
        super().__init__(timeout=None)
        self.bot = bot_ref

    @discord.ui.button(label="Verifizieren", style=discord.ButtonStyle.green,
                       custom_id="modforge:verify_ext", emoji="✅")
    async def verify_button(self, interaction: discord.Interaction, button):
        cfg = self.bot.db.get_config(interaction.guild.id)
        vs = cfg.get("verify_system", {})
        ve = cfg.get("verify_extended", {})
        add_roles = vs.get("add_roles", [])
        remove_roles = vs.get("remove_roles", [])

        # Already verified check
        if add_roles:
            if any(discord.utils.get(interaction.user.roles, id=r_id) for r_id in add_roles):
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.OK}", "Du bist bereits verifiziert.", COLOR_SUCCESS), ephemeral=True)

        # Rate-Limiting (Feature 83)
        rate_limit = ve.get("rate_limit_per_minute", 3)
        uid = interaction.user.id
        gid = interaction.guild.id
        key = f"verify_rate:{gid}:{uid}"
        # Simple in-memory rate limit
        _pending_verify.setdefault(gid, {})
        user_data = _pending_verify[gid].get(uid, {})
        last_attempt = user_data.get("last_attempt", 0)
        if time.time() - last_attempt < 60 / max(rate_limit, 1):
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Zu viele Versuche. Bitte warte einen Moment.", COLOR_DANGER), ephemeral=True)
        _pending_verify[gid][uid] = {"last_attempt": time.time(), "started": time.time()}

        # Anti-Alt-Account (Feature 85)
        if ve.get("anti_alt_account"):
            min_hours = ve.get("anti_alt_min_age_hours", 24)
            age_hours = (discord.utils.utcnow() - interaction.user.created_at.replace(tzinfo=None)).total_seconds() / 3600
            if age_hours < min_hours:
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.FAIL} Account zu jung",
                    f"Dein Account muss mindestens {min_hours}h alt sein.\n"
                    f"Aktuelles Alter: {int(age_hours)}h", COLOR_DANGER), ephemeral=True)

        # Trust-Score (Feature 98)
        trust_score = 50  # Base
        if ve.get("trust_score_enabled"):
            age_days = (discord.utils.utcnow() - interaction.user.created_at.replace(tzinfo=None)).days
            if age_days > 365:
                trust_score += 30
            elif age_days > 90:
                trust_score += 20
            elif age_days > 30:
                trust_score += 10
            if interaction.user.avatar:
                trust_score += 10
            if interaction.user.discriminator != "0":
                trust_score += 5
            # Failed attempts reduce score
            fails = _failed_counter.get(gid, {}).get(uid, 0)
            trust_score -= fails * 10
            min_score = ve.get("trust_score_min", 30)
            if trust_score < min_score:
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.FAIL} Trust-Score zu niedrig",
                    f"Dein Trust-Score ({trust_score}) ist unter dem Minimum ({min_score}).",
                    COLOR_DANGER), ephemeral=True)

        # Blacklist check (Feature 96)
        if uid in ve.get("blacklist_ids", []):
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Du bist auf der Blacklist.", COLOR_DANGER), ephemeral=True)

        # Bypass for trusted (Feature 66, 67, 97)
        if uid in ve.get("whitelist_ids", []):
            for r_id in add_roles:
                role = interaction.guild.get_role(r_id)
                if role:
                    await interaction.user.add_roles(role, reason="Verify-Bypass (Whitelist)")
            return await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Verifiziert!", "Bypass (Whitelist).", COLOR_SUCCESS), ephemeral=True)

        # Bypass for old accounts (Feature 67)
        bypass_age = ve.get("bypass_account_age_days", 90)
        if bypass_age > 0:
            age_days = (discord.utils.utcnow() - interaction.user.created_at.replace(tzinfo=None)).days
            if age_days >= bypass_age:
                for r_id in add_roles:
                    role = interaction.guild.get_role(r_id)
                    if role:
                        await interaction.user.add_roles(role, reason=f"Auto-Verify (Account {age_days}d alt)")
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.OK} Auto-Verifiziert!", f"Account-Alter: {age_days} Tage.", COLOR_SUCCESS), ephemeral=True)

        # Admin-Approval (Feature 101)
        if ve.get("admin_approval_required"):
            approval_ch = interaction.guild.get_channel(ve.get("admin_approval_channel"))
            if approval_ch:
                embed = create_embed(f"📋 Verifizierungs-Antrag",
                    f"**User:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                    f"**Account-Alter:** {(discord.utils.utcnow() - interaction.user.created_at.replace(tzinfo=None)).days} Tage\n"
                    f"**Trust-Score:** {trust_score}",
                    COLOR_INFO, user=interaction.user)
                await approval_ch.send(embed=embed)
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.OK} Antrag gesendet", "Ein Moderator wird deinen Antrag prüfen.", COLOR_INFO), ephemeral=True)

        # ── VERIFICATION MODE ──
        mode = vs.get("mode", "one_click")

        # Math-CAPTCHA (Feature 55)
        if ve.get("math_captcha") or mode == "math":
            a, b = random.randint(10, 99), random.randint(10, 99)
            op = random.choice(["+", "-"])
            correct = a + b if op == "+" else a - b
            await interaction.response.send_modal(
                MathCaptchaModal(correct, self.bot, add_roles, remove_roles))
            await interaction.followup.send(
                embed=create_embed("🔢 Math-CAPTCHA", f"Löse: **{a} {op} {b} = ?**", COLOR_PRIMARY),
                ephemeral=True)
            return

        # Quiz (Feature 69)
        if ve.get("quiz_mode"):
            questions = ve.get("quiz_questions", [])
            if questions:
                q = random.choice(questions)
                await interaction.response.send_modal(
                    QuizModal(q.get("answer", ""), self.bot, add_roles, remove_roles, q.get("question", "")))
                return

        # Standard CAPTCHA
        if mode == "captcha":
            code, img_buf = generate_captcha(vs.get("captcha_difficulty", "medium"))
            file = discord.File(img_buf, filename="captcha.png")
            await interaction.response.send_message(
                "Gib den Code aus dem Bild ein:", file=file, ephemeral=True,
                view=CaptchaEntryView(code, self.bot, add_roles, remove_roles))
            return

        # One-Click
        try:
            for r_id in add_roles:
                role = interaction.guild.get_role(r_id)
                if role:
                    await interaction.user.add_roles(role, reason="One-Click Verifizierung")
            for r_id in remove_roles:
                role = interaction.guild.get_role(r_id)
                if role:
                    await interaction.user.remove_roles(role, reason="One-Click Verifizierung")
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Verifiziert!", "Willkommen!", COLOR_SUCCESS), ephemeral=True)
            await self.bot.log_action(interaction.guild, f"{E.VERIFY} Verifiziert",
                f"{interaction.user.mention}", COLOR_SUCCESS, user=interaction.user, module="verify")
        except discord.Forbidden:
            await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Keine Berechtigung.", COLOR_DANGER), ephemeral=True)


class VerificationCog(commands.Cog):
    """Erweitertes Verifizierungs-System."""

    def __init__(self, bot):
        self.bot = bot
        self.verify_timer_loop.start()

    def cog_unload(self):
        self.verify_timer_loop.cancel()

    @app_commands.command(name="setup_verify", description="Richtet das Verifizierungssystem ein")
    @app_commands.describe(channel="Kanal", mode="one_click/captcha/math/quiz")
    @app_commands.default_permissions(administrator=True)
    async def setup_verify(self, interaction: discord.Interaction,
                           channel: discord.TextChannel, mode: str = "one_click"):
        if mode not in ("one_click", "captcha", "math", "quiz"):
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Mode: one_click, captcha, math, quiz", COLOR_DANGER), ephemeral=True)
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["verify_system"]["enabled"] = True
        cfg["verify_system"]["mode"] = mode
        cfg["verify_system"]["verify_channel"] = channel.id
        if mode == "math":
            cfg["verify_extended"]["math_captcha"] = True
        elif mode == "quiz":
            cfg["verify_extended"]["quiz_mode"] = True
        await self.bot.db.set_config(interaction.guild.id, cfg)

        ve = cfg.get("verify_extended", {})
        embed_title = ve.get("embed_title", f"{E.VERIFY} Verifizierung")
        embed_desc = ve.get("embed_description", "Klicke den Button um dich zu verifizieren.")
        try:
            embed_color = int(ve.get("embed_color", "#4169E1").lstrip("#"), 16)
        except ValueError:
            embed_color = COLOR_PRIMARY

        embed = discord.Embed(title=embed_title, description=embed_desc, color=embed_color)
        embed.set_image(url=VERIFY_BANNER_URL)
        view = ExtendedVerifyView(self.bot)
        msg = await channel.send(embed=embed, view=view)
        cfg["verify_system"]["message_id"] = msg.id
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Verify eingerichtet", f"Modus: **{mode}** in {channel.mention}", COLOR_SUCCESS))

    @app_commands.command(name="verify_roles", description="Verify-Rollen einstellen")
    @app_commands.describe(add_role="Rolle nach Verify", remove_role="Rolle entfernen nach Verify")
    @app_commands.default_permissions(administrator=True)
    async def verify_roles(self, interaction: discord.Interaction,
                           add_role: discord.Role = None, remove_role: discord.Role = None):
        cfg = self.bot.db.get_config(interaction.guild.id)
        if add_role:
            add_list = cfg["verify_system"].get("add_roles", [])
            if add_role.id not in add_list:
                add_list.append(add_role.id)
            cfg["verify_system"]["add_roles"] = add_list
        if remove_role:
            rem_list = cfg["verify_system"].get("remove_roles", [])
            if remove_role.id not in rem_list:
                rem_list.append(remove_role.id)
            cfg["verify_system"]["remove_roles"] = rem_list
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Rollen aktualisiert",
            f"Add: {add_role.mention if add_role else '—'}\nRemove: {remove_role.mention if remove_role else '—'}",
            COLOR_SUCCESS))

    @app_commands.command(name="verify_quiz_add", description="Quiz-Frage hinzufügen")
    @app_commands.describe(question="Die Frage", answer="Die richtige Antwort")
    @app_commands.default_permissions(administrator=True)
    async def verify_quiz_add(self, interaction: discord.Interaction, question: str, answer: str):
        """Feature 69: Quiz-System Fragen verwalten."""
        cfg = self.bot.db.get_config(interaction.guild.id)
        ve = cfg.get("verify_extended", {})
        questions = ve.get("quiz_questions", [])
        questions.append({"question": question, "answer": answer})
        ve["quiz_questions"] = questions
        cfg["verify_extended"] = ve
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Frage hinzugefügt", f"**Q:** {question}\n**A:** ||{answer}||", COLOR_SUCCESS))

    @app_commands.command(name="verify_timer", description="Auto-Kick Timer für unverifizierte User")
    @app_commands.describe(minutes="Minuten bis Auto-Kick (0=deaktiviert)", action="kick/ban")
    @app_commands.default_permissions(administrator=True)
    async def verify_timer(self, interaction: discord.Interaction, minutes: int = 10, action: str = "kick"):
        """Feature 62: Verification-Timer."""
        cfg = self.bot.db.get_config(interaction.guild.id)
        ve = cfg.get("verify_extended", {})
        ve["timer_enabled"] = minutes > 0
        ve["timer_minutes"] = max(0, minutes)
        ve["timer_action"] = action if action in ("kick", "ban") else "kick"
        cfg["verify_extended"] = ve
        await self.bot.db.set_config(interaction.guild.id, cfg)
        if minutes > 0:
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Timer aktiviert",
                f"Unverifizierte User werden nach **{minutes} Minuten** ge{action}t.", COLOR_SUCCESS))
        else:
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Timer deaktiviert", "", COLOR_SUCCESS))

    @app_commands.command(name="verify_stats", description="Verifizierungs-Statistiken")
    @app_commands.default_permissions(manage_messages=True)
    async def verify_stats(self, interaction: discord.Interaction):
        """Feature 64, 65: Verification-Stats + Failed-Counter."""
        gid = interaction.guild.id
        fails = _failed_counter.get(gid, {})
        total_fails = sum(fails.values())
        pending = len(_pending_verify.get(gid, {}))
        cfg = self.bot.db.get_config(gid)
        vs = cfg.get("verify_system", {})
        mode = vs.get("mode", "one_click")
        fields = [
            ("Modus", mode, True),
            ("Aktiv ausstehend", str(pending), True),
            ("Fehlversuche (gesamt)", str(total_fails), True),
        ]
        if fails:
            top_fails = sorted(fails.items(), key=lambda x: -x[1])[:5]
            fields.append(("Top Fehlversuche",
                          "\n".join(f"<@{uid}>: {count}" for uid, count in top_fails), False))
        await interaction.response.send_message(embed=create_embed(
            f"📊 Verify-Statistiken", "", COLOR_PRIMARY, fields))

    @tasks.loop(minutes=5)
    async def verify_timer_loop(self):
        """Feature 62: Auto-Kick bei Verify-Timer-Ablauf."""
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            try:
                cfg = self.bot.db.get_config(guild.id)
                ve = cfg.get("verify_extended", {})
                if not ve.get("timer_enabled"):
                    continue
                vs = cfg.get("verify_system", {})
                if not vs.get("enabled"):
                    continue
                add_roles = vs.get("add_roles", [])
                if not add_roles:
                    continue
                timer_minutes = ve.get("timer_minutes", 10)
                action = ve.get("timer_action", "kick")
                cutoff = discord.utils.utcnow() - datetime.timedelta(minutes=timer_minutes)
                for member in guild.members:
                    if member.bot:
                        continue
                    if member.joined_at and member.joined_at.replace(tzinfo=None) < cutoff:
                        has_verify_role = any(discord.utils.get(member.roles, id=r_id) for r_id in add_roles)
                        if not has_verify_role:
                            try:
                                reason = f"Verify-Timer: Nicht verifiziert nach {timer_minutes}min"
                                if action == "ban":
                                    await member.ban(reason=reason)
                                else:
                                    await member.kick(reason=reason)
                                await self.bot.log_action(guild, f"⏰ Verify-Timer",
                                    f"{member.mention} ({action}) – nicht verifiziert nach {timer_minutes}min",
                                    COLOR_WARNING, user=member, module="verify")
                            except (discord.Forbidden, discord.HTTPException):
                                pass
                            await asyncio.sleep(0.5)
            except Exception as e:
                log.debug(f"Verify-Timer error {guild.id}: {e}")


async def setup(bot):
    cog = VerificationCog(bot)
    await bot.add_cog(cog)
    # Register persistent view
    bot.add_view(ExtendedVerifyView(bot))
