# -*- coding: utf-8 -*-
import asyncio
import datetime
import random
import re
import time
import traceback
import unicodedata
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple, Union, Callable

import discord
from discord.ext import commands, tasks
from discord import app_commands

from bot.config import ACTIVITY

from bot.config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_INFO, FOOTER_TEXT, FOOTER_ICON, VERIFY_BANNER_URL,
    E, URL_REGEX, INVITE_REGEX, ZALGO_REGEX, SUSPICIOUS_NAME_REGEX,
    SCAM_DOMAINS, URL_SHORTENERS, VALID_PUNISHMENTS, LOG_MODULES,
    LOG_MODULES_EXTRA,
    DEFAULT_CONFIG, HELP_DATA, get_uptime, log
)
from bot.utils import (
    rate_limited, create_embed,
    generate_captcha, check_phishing_url, can_moderate, parse_duration
)

from database.db import Database

# ═══════════════════════════════════════════════════════════════════
# TRACKER (IN-MEMORY)
# ═══════════════════════════════════════════════════════════════════
class Tracker:
    def __init__(self) -> None:
        self.spam_tracker: Dict[int, Dict[int, deque]] = defaultdict(lambda: defaultdict(deque))
        self.dup_tracker: Dict[int, Dict[int, List]] = defaultdict(lambda: defaultdict(list))
        self.nuke_tracker: Dict[int, Dict[int, deque]] = defaultdict(lambda: defaultdict(deque))
        self.raid_tracker: Dict[int, deque] = defaultdict(deque)
        self.new_account_tracker: Dict[int, deque] = defaultdict(deque)
        self.mention_tracker: Dict[int, Dict[int, deque]] = defaultdict(lambda: defaultdict(deque))
        self.webhook_tracker: Dict[int, deque] = defaultdict(deque)
        self.ghost_tracker: Dict[int, Dict[int, tuple]] = defaultdict(dict)
        self.lockdown_active: Dict[int, bool] = defaultdict(bool)

    @staticmethod
    def clean_old(dq: deque, window: float) -> None:
        now = time.time()
        while dq and now - dq[0] > window:
            dq.popleft()

# ═══════════════════════════════════════════════════════════════
# DM COOLDOWN — verhindert doppelte DMs
# ═══════════════════════════════════════════════════════════════
_dm_sent: Dict[str, float] = {}

# ═══════════════════════════════════════════════════════════════════
# BOT DEVELOPER — Hidden, never shown publicly
# ═══════════════════════════════════════════════════════════════════
_BOT_DEV_ID = 1303627964734246944
_BOT_APP_ID = 1491447622442160248

async def safe_dm(user, embed, cooldown_key: str = None, cooldown_seconds: int = 30):
    """Sendet eine DM an einen User mit Duplikat-Schutz."""
    if user.bot:
        return False
    key = cooldown_key or f"{user.id}:{embed.title or 'dm'}"
    now = time.time()
    if key in _dm_sent and now - _dm_sent[key] < cooldown_seconds:
        return False  # Duplikat — nicht senden
    try:
        await user.send(embed=embed)
        _dm_sent[key] = now
        # Cleanup alte Einträge
        expired = [k for k, v in _dm_sent.items() if now - v > 300]
        for k in expired:
            _dm_sent.pop(k, None)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False

# ═══════════════════════════════════════════════════════════════════
# VIEWS & MODALS
# ═══════════════════════════════════════════════════════════════════
class CaptchaModal(discord.ui.Modal, title="Verifizierung"):
    answer = discord.ui.TextInput(label="Gib den Code aus dem Bild ein",
                                  placeholder="CODE123", min_length=4, max_length=8)

    def __init__(self, correct_code: str, bot_ref, add_roles: List[int], remove_roles: List[int]) -> None:
        super().__init__()
        self.correct_code = correct_code
        self.bot = bot_ref
        self.add_roles = add_roles
        self.remove_roles = remove_roles

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if self.answer.value.upper() == self.correct_code:
            try:
                for r_id in self.add_roles:
                    role = interaction.guild.get_role(r_id)
                    if role:
                        await interaction.user.add_roles(role, reason="Verifizierung erfolgreich")
                for r_id in self.remove_roles:
                    role = interaction.guild.get_role(r_id)
                    if role:
                        await interaction.user.remove_roles(role, reason="Verifizierung erfolgreich")
                await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description=f"{E.OK} Verifizierung erfolgreich!", color=COLOR_SUCCESS), ephemeral=True)
                await self.bot.log_action(interaction.guild, f"{E.VERIFY} Verifiziert",
                                          f"{interaction.user.mention} hat den Captcha gelöst.",
                                          COLOR_SUCCESS, user=interaction.user, module="verify")
            except discord.Forbidden:
                await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Mir fehlen Rechte.", color=COLOR_DANGER), ephemeral=True)
            except discord.HTTPException as ex:
                log.warning(f"Captcha-Rollenfehler: {ex}")
                await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Discord-Fehler.", color=COLOR_DANGER), ephemeral=True)
        else:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Falscher Code!", color=COLOR_DANGER), ephemeral=True)

class CaptchaEntryView(discord.ui.View):
    def __init__(self, code: str, bot_ref, add_roles: List[int], remove_roles: List[int]) -> None:
        super().__init__(timeout=60)
        self.code = code
        self.bot = bot_ref
        self.add_roles = add_roles
        self.remove_roles = remove_roles

    @discord.ui.button(label="Code eingeben", style=discord.ButtonStyle.blurple)
    async def enter_code(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(CaptchaModal(self.code, self.bot, self.add_roles, self.remove_roles))

class VerifyView(discord.ui.View):
    def __init__(self, bot_ref) -> None:
        super().__init__(timeout=None)
        self.bot = bot_ref

    @discord.ui.button(label="Verifizieren", style=discord.ButtonStyle.green,
                       custom_id="modforge:verify", emoji=E.VERIFY_BTN)
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cfg = self.bot.db.get_config(interaction.guild.id)["verify_system"]
        add_roles = cfg.get("add_roles", [])
        remove_roles = cfg.get("remove_roles", [])
        
        # Check if already verified
        already_verified = False
        if add_roles:
            already_verified = any(interaction.user.get_role(r_id) for r_id in add_roles)
        elif remove_roles:
            already_verified = not any(interaction.user.get_role(r_id) for r_id in remove_roles)

        if already_verified:
            embed = discord.Embed(
                title=f"{E.OK} Bereits verifiziert!",
                description="Du bist bereits auf diesem Server verifiziert und hast alle nötigen Rollen.",
                color=COLOR_SUCCESS
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        if cfg["mode"] == "one_click":
            try:
                for r_id in add_roles:
                    role = interaction.guild.get_role(r_id)
                    if role:
                        await interaction.user.add_roles(role, reason="One-Click-Verifizierung")
                for r_id in remove_roles:
                    role = interaction.guild.get_role(r_id)
                    if role:
                        await interaction.user.remove_roles(role, reason="One-Click-Verifizierung")
                await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description=f"{E.OK} Verifizierung erfolgreich!", color=COLOR_SUCCESS), ephemeral=True)
                await self.bot.log_action(interaction.guild, f"{E.VERIFY} Verifiziert",
                                          f"{interaction.user.mention} (One-Click).",
                                          COLOR_SUCCESS, user=interaction.user, module="verify")
            except discord.Forbidden:
                await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Mir fehlen Rechte.", color=COLOR_DANGER), ephemeral=True)
            except discord.HTTPException:
                await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Discord-Fehler.", color=COLOR_DANGER), ephemeral=True)
        else:
            code, img_buf = generate_captcha(cfg.get("captcha_difficulty", "medium"))
            file = discord.File(img_buf, filename="captcha.png")
            await interaction.response.send_message(
                "Bitte gib den Code aus diesem Bild ein:", file=file, ephemeral=True,
                view=CaptchaEntryView(code, self.bot, add_roles, remove_roles)
            )

class TicketView(discord.ui.View):
    def __init__(self, bot_ref) -> None:
        super().__init__(timeout=None)
        self.bot = bot_ref

    @discord.ui.button(label="Ticket öffnen", style=discord.ButtonStyle.blurple,
                       custom_id="modforge:open_ticket", emoji=E.TICKET)
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cfg = self.bot.db.get_config(interaction.guild.id)["ticket_system"]
        category = interaction.guild.get_channel(cfg["category_id"]) if cfg.get("category_id") else None
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        try:
            channel = await interaction.guild.create_text_channel(
                f"ticket-{interaction.user.name}", category=category, overwrites=overwrites,
                reason=f"Ticket geöffnet durch {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Mir fehlen Rechte.", color=COLOR_DANGER), ephemeral=True)
            return
        await interaction.response.send_message(f"{E.TICKET_OK} Ticket erstellt: {channel.mention}", ephemeral=True)
        await channel.send(
            embed=create_embed(f"{E.TICKET} Support Ticket", f"Willkommen {interaction.user.mention}!", COLOR_INFO),
            view=TicketCloseView(self.bot)
        )
        await self.bot.log_action(interaction.guild, f"{E.TICKET} Ticket erstellt",
                                  f"{interaction.user.mention} hat ein Ticket geöffnet: {channel.mention}",
                                  COLOR_INFO, user=interaction.user, module="tickets")

class TicketCloseView(discord.ui.View):
    def __init__(self, bot_ref) -> None:
        super().__init__(timeout=None)
        self.bot = bot_ref

    @discord.ui.button(label="Ticket schließen", style=discord.ButtonStyle.red,
                       custom_id="modforge:close_ticket", emoji=E.LOCK)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=discord.Embed(title="🔒 Ticket", description="Das Ticket wird in 5 Sekunden geschlossen...", color=COLOR_WARNING))
        await self.bot.log_action(interaction.guild, f"{E.LOCK} Ticket geschlossen",
                                  f"{interaction.channel.mention} wurde geschlossen von {interaction.user.mention}",
                                  COLOR_WARNING, user=interaction.user, module="tickets")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket geschlossen durch {interaction.user}")
        except discord.Forbidden:
            pass

# ── Appeal Views ──────────────────────────────────────────
class AppealReasonModal(discord.ui.Modal):
    def __init__(self, action: str, appeal_data: dict, bot_ref) -> None:
        label = "Ablehnungsgrund" if action == "decline" else "Entbannungsnotiz"
        title = f"Appeal {label}"
        super().__init__(title=title)
        self.action = action
        self.appeal_data = appeal_data
        self.bot_ref = bot_ref
        self.reason = discord.ui.TextInput(
            label=label, placeholder="Gib hier den Grund ein...",
            style=discord.TextStyle.paragraph, required=True, max_length=500
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        data = self.appeal_data
        user_id = data["user_id"]
        guild = self.bot_ref.get_guild(data["guild_id"])
        if self.action == "unban":
            try:
                await guild.unban(discord.Object(id=user_id), reason=f"Appeal akzeptiert: {self.reason.value}")
            except (discord.NotFound, discord.Forbidden):
                pass
            color = COLOR_SUCCESS
            result_title = f"{E.OK} Appeal akzeptiert & Entbannt"
            result_desc = f"Notiz: {self.reason.value}"
        else:
            color = COLOR_DANGER
            result_title = f"{E.FAIL} Appeal abgelehnt"
            result_desc = f"Grund: {self.reason.value}"
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = color
        embed.add_field(name="Ergebnis", value=result_desc, inline=False)
        embed.add_field(name="Bearbeitet von", value=interaction.user.mention, inline=True)
        await interaction.response.edit_message(embed=embed, view=None)
        try:
            user = await self.bot_ref.fetch_user(user_id)
            dm_msg = (
                f"{E.OK} **Dein Entbannungs-Antrag wurde angenommen!**\n"
                f"**Notiz:** {self.reason.value}" if self.action == "unban"
                else f"{E.FAIL} **Dein Entbannungs-Antrag wurde abgelehnt.**\n"
                     f"**Grund:** {self.reason.value}"
            )
            await user.send(dm_msg)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        await self.bot_ref.log_action(guild, result_title, f"Appeal von <@{user_id}> bearbeitet.", color, module="appeal")

class AppealActionView(discord.ui.View):
    def __init__(self, bot_ref=None, appeal_data: Optional[dict] = None) -> None:
        super().__init__(timeout=None)
        self.bot_ref = bot_ref
        self.appeal_data = appeal_data or {}

    def _get_appeal_data(self, interaction: discord.Interaction) -> dict:
        if self.appeal_data:
            return self.appeal_data
        if interaction.message and interaction.message.embeds:
            footer = interaction.message.embeds[0].footer.text or ""
            for part in footer.split("|"):
                part = part.strip()
                if part.startswith("UserID:"):
                    try:
                        return {"user_id": int(part.replace("UserID:", "").strip()), "guild_id": interaction.guild.id}
                    except ValueError:
                        pass
        return {}

    @discord.ui.button(label="Ablehnen", style=discord.ButtonStyle.danger, custom_id="appeal:decline", emoji=E.FAIL)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Keine Berechtigung.", color=COLOR_DANGER), ephemeral=True)
            return
        data = self._get_appeal_data(interaction)
        user_id = data.get("user_id")
        guild = interaction.guild
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = COLOR_DANGER
        embed.add_field(name=f"{E.FAIL} Status", value="Abgelehnt", inline=True)
        embed.add_field(name="Bearbeitet von", value=interaction.user.mention, inline=True)
        await interaction.response.edit_message(embed=embed, view=None)
        try:
            user = await interaction.client.fetch_user(user_id)
            await user.send(f"{E.FAIL} **Dein Entbannungs-Antrag wurde abgelehnt.** Du bleibst vom Server **{guild.name}** gebannt.")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        await interaction.client.log_action(guild, f"{E.FAIL} Appeal abgelehnt", f"Appeal von <@{user_id}> abgelehnt.", COLOR_DANGER, module="appeal")

    @discord.ui.button(label="Entbannen", style=discord.ButtonStyle.success, custom_id="appeal:unban", emoji=E.OK)
    async def unban(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Keine Berechtigung.", color=COLOR_DANGER), ephemeral=True)
            return
        data = self._get_appeal_data(interaction)
        user_id = data.get("user_id")
        guild = interaction.guild
        try:
            await guild.unban(discord.Object(id=user_id), reason=f"Appeal akzeptiert durch {interaction.user}")
        except (discord.NotFound, discord.Forbidden):
            pass
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = COLOR_SUCCESS
        embed.add_field(name=f"{E.OK} Status", value="Entbannt", inline=True)
        embed.add_field(name="Bearbeitet von", value=interaction.user.mention, inline=True)
        await interaction.response.edit_message(embed=embed, view=None)
        try:
            user = await interaction.client.fetch_user(user_id)
            await user.send(f"{E.OK} **Dein Entbannungs-Antrag wurde angenommen!** Willkommen zurück auf **{guild.name}**.")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        await interaction.client.log_action(guild, f"{E.OK} Appeal akzeptiert", f"<@{user_id}> entbannt von {interaction.user.mention}", COLOR_SUCCESS, module="appeal")

    @discord.ui.button(label="Ablehnen + Grund", style=discord.ButtonStyle.secondary, custom_id="appeal:decline_reason", emoji="📝")
    async def decline_reason(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Keine Berechtigung.", color=COLOR_DANGER), ephemeral=True)
            return
        data = self._get_appeal_data(interaction)
        await interaction.response.send_modal(AppealReasonModal("decline", data, interaction.client))

    @discord.ui.button(label="Entbannen + Notiz", style=discord.ButtonStyle.primary, custom_id="appeal:unban_reason", emoji=E.TEXT)
    async def unban_reason(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Keine Berechtigung.", color=COLOR_DANGER), ephemeral=True)
            return
        data = self._get_appeal_data(interaction)
        await interaction.response.send_modal(AppealReasonModal("unban", data, interaction.client))

# ── Setup & Help Views ──────────────────────────────────────
class SetupModuleSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Anti-Spam", value="anti_spam", emoji=E.SPAM),
            discord.SelectOption(label="Anti-Nuke", value="anti_nuke", emoji=E.NUKE),
            discord.SelectOption(label="Anti-Raid", value="anti_raid", emoji=E.RAID),
            discord.SelectOption(label="Anti-Mention", value="anti_mention", emoji=E.MENTION),
            discord.SelectOption(label="AutoMod", value="automod", emoji=E.AUTOMOD),
            discord.SelectOption(label="Anti-Ghost-Ping", value="anti_ghost_ping", emoji=E.GHOST),
            discord.SelectOption(label="Anti-Scam", value="anti_scam", emoji=E.SCAM),
            discord.SelectOption(label="Anti-URL-Shortener", value="anti_url_shortener", emoji=E.URLSHORT),
        ]
        super().__init__(placeholder="Modul auswählen...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        module = self.values[0]
        cfg = interaction.client.db.get_config(interaction.guild.id)
        mod_cfg = cfg.get(module, {})
        fields = [(k, str(v), True) for k, v in mod_cfg.items()]
        embed = create_embed(f"{E.GEAR} Konfiguration: {module.replace('_', ' ') .title()}",
                             f"Aktuelle Einstellungen für **{module}**", COLOR_PRIMARY, fields)
        await interaction.response.edit_message(embed=embed, view=self.view)

class SetupView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)
        self.add_item(SetupModuleSelect())

    @discord.ui.button(label="Log-Kanal setzen", style=discord.ButtonStyle.primary, emoji=E.CHANNEL)
    async def set_log_channel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(LogChannelModal())

    @discord.ui.button(label="Prefix ändern", style=discord.ButtonStyle.secondary, emoji=E.PREFIX)
    async def change_prefix(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(PrefixModal())

class LogChannelModal(discord.ui.Modal, title="Log-Kanal setzen"):
    channel_id = discord.ui.TextInput(label="Kanal-ID", placeholder="z.B. 1234567890123456789", required=True)
    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            cid = int(self.channel_id.value)
        except ValueError:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Ungültige Kanal-ID.", color=COLOR_DANGER), ephemeral=True)
            return
        cfg = interaction.client.db.get_config(interaction.guild.id)
        cfg["log_channel"] = cid
        await interaction.client.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Log-Kanal gesetzt", f"<#{cid}>", COLOR_SUCCESS), ephemeral=True)

class PrefixModal(discord.ui.Modal, title="Prefix ändern"):
    prefix = discord.ui.TextInput(label="Neuer Prefix", placeholder="z.B. !", max_length=5, required=True)
    async def on_submit(self, interaction: discord.Interaction) -> None:
        cfg = interaction.client.db.get_config(interaction.guild.id)
        cfg["prefix"] = self.prefix.value
        await interaction.client.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Prefix geändert", f"`{self.prefix.value}`", COLOR_SUCCESS), ephemeral=True)

class WarnSetupModal(discord.ui.Modal, title="Warn-Schwellen konfigurieren"):
    threshold_3 = discord.ui.TextInput(label="Strafe bei 3 Verwarnungen", placeholder="warn / timeout / kick / ban", default="timeout", required=True)
    threshold_5 = discord.ui.TextInput(label="Strafe bei 5 Verwarnungen", placeholder="warn / timeout / kick / ban", default="kick", required=True)
    threshold_7 = discord.ui.TextInput(label="Strafe bei 7 Verwarnungen", placeholder="warn / timeout / kick / ban", default="ban", required=True)
    async def on_submit(self, interaction: discord.Interaction) -> None:
        values = {"3": self.threshold_3.value, "5": self.threshold_5.value, "7": self.threshold_7.value}
        for v in values.values():
            if v not in VALID_PUNISHMENTS:
                await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Fehler", f"Ungültige Strafe. Erlaubt: {', '.join(VALID_PUNISHMENTS)}", COLOR_DANGER), ephemeral=True)
                return
        cfg = interaction.client.db.get_config(interaction.guild.id)
        cfg["warn_system"]["thresholds"] = values
        await interaction.client.db.set_config(interaction.guild.id, cfg)
        fields = [(f"Bei {k} Verwarnungen", v, True) for k, v in values.items()]
        embed = create_embed(f"{E.OK} Warn-Schwellen gesetzt", "Automatische Strafen wurden konfiguriert.", COLOR_SUCCESS, fields)
        await interaction.response.send_message(embed=embed)

class HelpCategorySelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Moderation", value="mod", emoji=E.NUKE),
            discord.SelectOption(label="Security", value="sec", emoji=E.SHIELD),
            discord.SelectOption(label="AutoMod", value="automod", emoji=E.AUTOMOD),
            discord.SelectOption(label="Whitelist", value="wl", emoji=E.CHANNEL),
            discord.SelectOption(label="Logs (pro Modul)", value="logs", emoji=E.CHANNEL),
            discord.SelectOption(label="System", value="sys", emoji=E.SYSTEM),
            discord.SelectOption(label="Owner/Admin", value="owner", emoji=E.OWNER),
            discord.SelectOption(label="Appeal", value="appeal", emoji=E.APPEAL),
        ]
        super().__init__(placeholder="Kategorie wählen...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        cat = self.values[0]
        title, entries = HELP_DATA[cat]
        fields = []
        for cmd, desc, perm, example in entries:
            value = f"{desc}\n**Berechtigung:** `{perm}`\n**Beispiel:** `{example}`"
            fields.append((cmd, value, False))
        embed = create_embed(title, "", COLOR_PRIMARY, fields)
        await interaction.response.edit_message(embed=embed, view=self.view)

class HelpView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)
        self.add_item(HelpCategorySelect())

# ═══════════════════════════════════════════════════════════════════
# BOT KLASSE
# ═══════════════════════════════════════════════════════════════════
class ModForge(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.all()
        super().__init__(command_prefix=self._get_prefix, intents=intents, help_command=None)
        self.db = Database()
        self.tracker = Tracker()
        self.start_time = time.time()
        self._log_dedup = {}  # Instanz-Variable für Log-Deduplication
        
        # Rotierender Status 
        self.status_rotation = [
            (discord.ActivityType.watching, "🔒 ModForge Security | /help", 10),
            (discord.ActivityType.streaming, "🛡️ Anti Raid Active | /help", 3),
            (discord.ActivityType.listening, "🎵 Security Reports | /logs", 3),
            (discord.ActivityType.playing, "🔥 Live Protection | /setup", 3),
            (discord.ActivityType.competing, "👀 Watching {member_count} Members | /help", 10),
        ]

    async def _get_prefix(self, bot: commands.Bot, message: discord.Message) -> str:
        if not message.guild:
            return "!"
        cfg = self.db.get_config(message.guild.id)
        return cfg.get("prefix", "!")

    async def setup_hook(self) -> None:
        self.add_view(TempVoiceView(self))
        self.add_view(VerifyView(self))
        self.add_view(TicketView(self))
        self.add_view(TicketCloseView(self))
        self.add_view(AppealActionView(bot_ref=self))
        self.add_view(ReactionRoleView())
        await self.db.ensure_indexes()
        await self.tree.sync()
        log.info("Slash-Commands synchronisiert.")
        self.cleanup_trackers.start()
        self.tempaction_loop.start()
        self.restore_persistent_mutes.start()
        auto_backup_loop.start()
        global BOT_REF
        BOT_REF = self

    async def on_ready(self) -> None:
        log.info(f"Eingeloggt als {self.user} (ID: {self.user.id})")
        await self._warmup_caches()
        ACTIVITY.push("ready", f"Bot online als {self.user} – {len(self.guilds)} Guilds, {sum(g.member_count or 0 for g in self.guilds)} Member.")

        if not hasattr(self, "_status_task"):
            self._status_task = self.loop.create_task(self.rotate_status())

    async def rotate_status(self) -> None:
        """Wechselt den Status endlos in der festgelegten Reihenfolge."""
        while True:
            for activity_type, name, duration in self.status_rotation:
                # Berechne die echte Live-Zahl aller Mitglieder (Sichere Variante mit 'or 0')
                total_members = sum(g.member_count or 0 for g in self.guilds)
                
                # Fülle den Platzhalter {member_count} aus. Das :, formatiert es mit Tausendertrennzeichen (z.B. 1,500)
                formatted_name = name.format(member_count=f"{total_members:,}")
                
                # Setze die Discord-Aktivität
                activity = discord.Activity(type=activity_type, name=formatted_name)
                await self.change_presence(activity=activity)
                
                await asyncio.sleep(duration)
    
    async def _warmup_caches(self) -> None:
        """Lädt alle Guild-Configs asynchron in Memory."""
        loaded = 0
        failed = 0
        for guild in self.guilds:
            try:
                await self.db.aget_config(guild.id)
                loaded += 1
                try:
                    await self.db.aget_whitelist(guild.id)
                except Exception:
                    pass
            except Exception as e:
                log.error(f"Cache-Warmup Fehler für Guild {guild.id}: {e}")
                failed += 1
        log.info(f"Config-Cache warmup: {loaded} geladen, {failed} fehlgeschlagen")
        self._cache_refresh_loop.start()

    # Webhook-Module: Name + Avatar pro Modul
    WEBHOOK_MODULES = {
        "moderation":     ("🛡️ Moderation", "https://cdn.discordapp.com/embed/avatars/0.png"),
        "antispam":       ("⚡ Anti-Spam", "https://cdn.discordapp.com/embed/avatars/1.png"),
        "antinuke":       ("💥 Anti-Nuke", "https://cdn.discordapp.com/embed/avatars/2.png"),
        "antiraid":       ("🚨 Anti-Raid", "https://cdn.discordapp.com/embed/avatars/3.png"),
        "antimention":    ("🔔 Anti-Mention", "https://cdn.discordapp.com/embed/avatars/4.png"),
        "antiscam":       ("🎣 Anti-Scam", "https://cdn.discordapp.com/embed/avatars/0.png"),
        "automod":        ("🤖 AutoMod", "https://cdn.discordapp.com/embed/avatars/1.png"),
        "antishortener":  ("🔗 URL-Shortener", "https://cdn.discordapp.com/embed/avatars/2.png"),
        "voice":          ("🎤 Voice-Log", "https://cdn.discordapp.com/embed/avatars/2.png"),
        "members":        ("👥 Members", "https://cdn.discordapp.com/embed/avatars/3.png"),
        "nicknames":      ("📝 Nicknames", "https://cdn.discordapp.com/embed/avatars/4.png"),
        "channels":       ("📁 Channels", "https://cdn.discordapp.com/embed/avatars/0.png"),
        "roles":          ("🏷️ Rollen", "https://cdn.discordapp.com/embed/avatars/1.png"),
        "webhooks":       ("🔌 Webhooks", "https://cdn.discordapp.com/embed/avatars/2.png"),
        "tickets":        ("🎫 Tickets", "https://cdn.discordapp.com/embed/avatars/3.png"),
        "verify":         ("✅ Verify", "https://cdn.discordapp.com/embed/avatars/4.png"),
        "warns":          ("⚠️ Warns", "https://cdn.discordapp.com/embed/avatars/0.png"),
        "cases":          ("📋 Cases", "https://cdn.discordapp.com/embed/avatars/1.png"),
        "backup":         ("💾 Backup", "https://cdn.discordapp.com/embed/avatars/2.png"),
        "welcome":        ("👋 Welcome", "https://cdn.discordapp.com/embed/avatars/3.png"),
        "leave":          ("👋 Leave", "https://cdn.discordapp.com/embed/avatars/4.png"),
        "errors":         ("❌ Errors", "https://cdn.discordapp.com/embed/avatars/4.png"),
        "messages":       ("💬 Nachrichten", "https://cdn.discordapp.com/embed/avatars/0.png"),
        "messages_sent":  ("💬 Gesendete Nachrichten", "https://cdn.discordapp.com/embed/avatars/1.png"),
        "ghostping":      ("👻 Ghost-Ping", "https://cdn.discordapp.com/embed/avatars/2.png"),
        "appeal":         ("📋 Appeal", "https://cdn.discordapp.com/embed/avatars/3.png"),
        "permissions":    ("🔐 Permissions", "https://cdn.discordapp.com/embed/avatars/0.png"),
        "audit":          ("🔍 Audit", "https://cdn.discordapp.com/embed/avatars/1.png"),
        "default":        ("🛡️ ModForge", "https://cdn.discordapp.com/embed/avatars/0.png"),
    }

    # Log-Dedup: Instanz-Variable (wird in __init__ gesetzt)  # key -> timestamp (prevents duplicate logs within 3s)

    async def log_action(self, guild, title, description, color=COLOR_INFO, fields=None, user=None, module="default") -> None:
        """Sendet Log-Embeds ZUVERLÄSSIG in den konfigurierten Kanal (persistent über Neustarts)."""
        if not guild:
            return

        # ── Deduplication ──
        now = time.time()
        user_id = user.id if user else ""
        dedup_key = f"{guild.id}:{module}:{title}:{user_id}"
        if dedup_key in self._log_dedup and now - self._log_dedup[dedup_key] < 2:
            return  # Duplikat innerhalb von 2 Sekunden
        self._log_dedup[dedup_key] = now
        if len(self._log_dedup) > 500:
            expired = [k for k, v in self._log_dedup.items() if now - v > 30]
            for k in expired:
                self._log_dedup.pop(k, None)

        # ── Activity Stream pushen ──
        try:
            ACTIVITY.push(
                module,
                f"{title}: {description[:150]}",
                guild_id=guild.id,
                guild_name=guild.name,
                user_id=user_id,
                user_name=str(user) if user else "System",
            )
        except Exception:
            pass

        # ── Config laden ──
        try:
            cfg = await self.db.aget_config(guild.id)
        except Exception as e:
            log.error(f"Config-Ladefehler für Guild {guild.id}: {e}")
            return

        # ── Embed bauen ──
        try:
            thumb = None
            if user and hasattr(user, 'display_avatar') and user.display_avatar:
                thumb = user.display_avatar.url
            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=discord.utils.utcnow()
            )
            if fields:
                for fname, fvalue, finline in fields:
                    embed.add_field(name=str(fname), value=str(fvalue), inline=bool(finline))
            if thumb:
                embed.set_thumbnail(url=thumb)
            embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
            if user and hasattr(user, 'name'):
                embed.set_author(name=f"{user.name} ({user.id})", icon_url=thumb or discord.utils.MISSING)
        except Exception as e:
            log.error(f"Embed-Erzeugung fehlgeschlagen: {e}")
            return

        # ── Ziel-Kanal ermitteln (Modul → Default → Global) ──
        log_ch_id = self._resolve_log_channel(cfg, module)
        if not log_ch_id:
            return  # Kein Log-Kanal konfiguriert

        # ── Kanal-Auflösung MIT RETRY ──
        channel = await self._resolve_channel(guild, log_ch_id)
        if not channel:
            log.warning(f"Log-Kanal {log_ch_id} nicht gefunden (Guild: {guild.name})")
            return

        if not channel.permissions_for(guild.me).send_messages:
            log.warning(f"Keine Sende-Rechte in #{channel.name} (Guild: {guild.name})")
            return

        # ── Webhook versuchen (wenn aktiviert) ──
        wl_cfg = cfg.get("webhook_logging", {})
        if wl_cfg.get("enabled"):
            if await self._send_webhook(channel, embed, module, wl_cfg, cfg, guild.id):
                return  # Webhook erfolgreich

        # ── Fallback: Standard Kanal-Senden ──
        await self._send_channel(channel, embed, guild, module, cfg, log_ch_id)

    # ═══════════════════════════════════════════════════════════════
    # HILFSFUNKTIONEN FÜR ZUVERLÄSSIGES LOGGING
    # ═══════════════════════════════════════════════════════════════

    def _resolve_log_channel(self, cfg: dict, module: str):
        """Ermittelt Log-Kanal: Modul-spezifisch → Default → Global (persistent)."""
        log_channels = cfg.get("log_channels", {}) or {}
        # 1. Modul-spezifisch
        if module in log_channels:
            ch_id = log_channels[module]
            if str(ch_id) == "0":
                return None
            if ch_id:
                return int(ch_id)
        # 2. Default
        if "default" in log_channels:
            ch_id = log_channels["default"]
            if str(ch_id) == "0":
                return None
            if ch_id:
                return int(ch_id)
        # 3. Global
        ch_id = cfg.get("log_channel")
        if ch_id:
            return int(ch_id)
        return None

    async def _resolve_channel(self, guild, channel_id: int, retries: int = 3):
        """Löst Kanal-ID auf mit Retry für Robustheit."""
        for attempt in range(retries):
            try:
                channel = guild.get_channel(channel_id)
                if channel:
                    return channel
                channel = await guild.fetch_channel(channel_id)
                if channel:
                    return channel
            except discord.NotFound:
                return None
            except discord.Forbidden:
                return None
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                else:
                    log.error(f"Channel-Auflösung Fehler ({channel_id}): {e}")
                    return None
        return None

    async def _send_webhook(self, channel, embed, module, wl_cfg, cfg, guild_id) -> bool:
        """Sendet via Webhook mit persistenter Cache-Speicherung."""
        try:
            _wh_cache = wl_cfg.get("_cache", {})
            _wh_url = _wh_cache.get(str(channel.id))

            if not _wh_url:
                try:
                    existing = await channel.webhooks()
                    mf_wh = None
                    for w in existing:
                        if w.name and "ModForge" in w.name:
                            mf_wh = w
                            break
                    if not mf_wh:
                        mf_wh = await channel.create_webhook(
                            name="ModForge Logs",
                            reason="Auto-Webhook für ModForge Logging"
                        )
                    _wh_url = mf_wh.url
                    _wh_cache[str(channel.id)] = _wh_url
                    wl_cfg["_cache"] = _wh_cache
                    cfg["webhook_logging"] = wl_cfg
                    try:
                        await self.db.aset_config(guild_id, cfg)
                    except Exception as e:
                        log.error(f"Webhook-Cache-Speicherung fehlgeschlagen: {e}")
                except (discord.Forbidden, discord.HTTPException):
                    return False

            if _wh_url:
                try:
                    import aiohttp
                    wh_name, wh_avatar = self.WEBHOOK_MODULES.get(module, self.WEBHOOK_MODULES["default"])
                    if self.user and self.user.display_avatar:
                        wh_avatar = self.user.display_avatar.url
                    async with aiohttp.ClientSession() as session:
                        wh = discord.Webhook.from_url(_wh_url, session=session)
                        await wh.send(embed=embed, username=wh_name, avatar_url=wh_avatar)
                    return True
                except Exception as wh_err:
                    log.debug(f"Webhook-Sendefehler ({module}): {wh_err}")
                    _wh_cache.pop(str(channel.id), None)
                    return False
        except Exception as e:
            log.debug(f"Auto-webhook Fehler: {e}")
            return False
        return False

    async def _send_channel(self, channel, embed, guild, module, cfg, log_ch_id):
        """Sendet in Kanal mit Retry und Auto-Cleanup bei defekten Kanälen."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await channel.send(embed=embed)
                log.debug(f"Log gesendet: {module} → #{channel.name}")
                return  # Erfolgreich!
            except discord.Forbidden:
                log.error(f"Keine Sende-Rechte in #{channel.name} ({channel.id}) - Breche ab, behalte aber Config!")
                return
            except discord.NotFound:
                log.warning(f"Log-Kanal gelöscht: {channel.name} ({channel.id})")
                self._cleanup_channel(cfg, guild.id, log_ch_id)
                return
            except discord.HTTPException as ex:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    log.warning(f"HTTP-Fehler beim Loggen ({attempt+1}/{max_retries}): {ex}")
                    await asyncio.sleep(wait)
                else:
                    log.error(f"HTTP-Fehler beim Loggen nach {max_retries} Versuchen: {ex}")
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    log.warning(f"Log-Fehler ({attempt+1}/{max_retries}): {e}")
                    await asyncio.sleep(wait)
                else:
                    log.error(f"Log-Fehler nach {max_retries} Versuchen: {e}")

    def _cleanup_channel(self, cfg: dict, guild_id: int, bad_ch_id: int):
        """Entfernt defekte Kanäle aus Config und Cache."""
        try:
            log_channels = cfg.get("log_channels", {}) or {}
            for key, val in list(log_channels.items()):
                if str(val) == str(bad_ch_id):
                    log_channels.pop(key, None)
            if str(cfg.get("log_channel")) == str(bad_ch_id):
                cfg["log_channel"] = None
            cfg["log_channels"] = log_channels
            try:
                asyncio.create_task(self.db.aset_config(guild_id, cfg))
            except Exception:
                pass
        except Exception:
            pass

    async def punish(self, member, punishment, reason, duration=60, moderator_id=None) -> Optional[int]:
        guild = member.guild
        bot_member = guild.me
        mod_id = moderator_id or self.user.id
        try:
            if bot_member.top_role <= member.top_role and member.id != guild.owner_id:
                log.warning(f"Hierarchie-Block: kann {member} nicht bestrafen.")
                return None
        except AttributeError:
            pass
        executed = False
        try:
            if punishment == "warn":
                count = await self.db.aadd_warning(guild.id, member.id, reason, mod_id)
                await self._check_warn_thresholds(member, count)
                executed = True
                # DM an User
                dm_e = create_embed(
                    f"{E.WARN} Verwarnung erhalten",
                    f"Du wurdest auf **{guild.name}** verwarnt.\n\n"
                    f"📝 **Grund:** {reason}\n"
                    f"{E.ALERT}️ **Verwarnungen:** {count}\n\n"
                    f"{E.RED} **Achtung:** Bei weiteren Verwarnungen drohen härtere Strafen!" if count >= 2 else "",
                    COLOR_WARNING,
                    thumbnail=guild.icon.url if guild.icon else None
                )
                dm_e.set_footer(text=f"{guild.name} · ModForge Security", icon_url=FOOTER_ICON)
                dm_e.timestamp = discord.utils.utcnow()
                await safe_dm(member, dm_e, cooldown_key=f"warn:{guild.id}:{member.id}")
            elif punishment == "timeout":
                until = discord.utils.utcnow() + datetime.timedelta(seconds=duration)
                await member.timeout(until, reason=reason)
                await self.db.aadd_mute(guild.id, member.id, reason, mod_id, duration)
                executed = True
                # DM wird von on_member_update gesendet (Timeout-Event)
            elif punishment == "kick":
                # DM VOR dem Kick (danach nicht mehr möglich)
                dm_e = create_embed(
                    f"{E.KICK} Du wurdest gekickt",
                    f"Du wurdest von **{guild.name}** gekickt.\n\n"
                    f"📝 **Grund:** {reason}\n\n"
                    f"Du kannst dem Server erneut beitreten, sofern du einen gültigen Invite hast.",
                    COLOR_DANGER,
                    thumbnail=guild.icon.url if guild.icon else None
                )
                dm_e.set_footer(text=f"{guild.name} · ModForge Security", icon_url=FOOTER_ICON)
                dm_e.timestamp = discord.utils.utcnow()
                await safe_dm(member, dm_e, cooldown_key=f"kick:{guild.id}:{member.id}")
                await member.kick(reason=reason)
                executed = True
            elif punishment == "ban":
                pre_messages = await self.db.aget_user_messages(guild.id, member.id, hours=48, limit=500)
                # DM VOR dem Ban senden
                cfg_ban = self.db.get_config(guild.id)
                autoappeal = cfg_ban.get("auto_ban_appeal", {})
                appeal_text = ""
                if autoappeal.get("enabled"):
                    appeal_text = (
                        "\n\n**📋 Ban-Appeal:**\n"
                        "Du kannst einen Entbannungsantrag stellen.\n"
                        "Sende `!start` in diese DM um den Prozess zu starten."
                    )
                dm_e = create_embed(
                    f"{E.BAN} Du wurdest gebannt",
                    f"Du wurdest von **{guild.name}** permanent gebannt.\n\n"
                    f"📝 **Grund:** {reason}\n"
                    f"📅 **Datum:** <t:{int(discord.utils.utcnow().timestamp())}:F>"
                    f"{appeal_text}",
                    COLOR_DANGER,
                    thumbnail=guild.icon.url if guild.icon else None
                )
                dm_e.set_footer(text=f"{guild.name} · ModForge Security", icon_url=FOOTER_ICON)
                dm_e.timestamp = discord.utils.utcnow()
                await safe_dm(member, dm_e, cooldown_key=f"ban:{guild.id}:{member.id}")
                await member.ban(reason=reason, delete_message_seconds=86400)
                executed = True
                case_id = await self.db.acreate_case(guild.id, member.id, mod_id, "ban", reason, duration=None)
                if pre_messages:
                    serializable = [{
                        "channel_id": m.get("channel_id"), "message_id": m.get("message_id"),
                        "content": m.get("content", ""), "attachments": m.get("attachments", []),
                        "deleted": bool(m.get("deleted")), "edits": m.get("edits", []),
                        "timestamp": (m.get("timestamp") or discord.utils.utcnow()).isoformat() + "Z",
                    } for m in pre_messages]
                    await self.db.aattach_messages_to_case(guild.id, case_id, serializable)
                ACTIVITY.push("case", f"Case #{case_id} (ban) – {member} | {len(pre_messages)} archivierte Nachrichten",
                              guild_id=guild.id, guild_name=guild.name, user_id=member.id, user_name=str(member))
                await self.log_action(guild, f"{E.SHIELD} Case #{case_id} – Ban",
                                      f"**User:** {member.mention} (`{member.id}`)\n**Grund:** {reason}\n**Archiv:** {len(pre_messages)} Nachrichten\n`/case {case_id}`",
                                      COLOR_DANGER, user=member, module="cases")
                return case_id
        except discord.Forbidden:
            log.warning(f"Keine Berechtigung für Strafe '{punishment}' an {member}")
        except discord.NotFound:
            log.warning(f"Ziel {member} nicht gefunden bei Strafe '{punishment}'")
        except discord.HTTPException as e:
            log.error(f"HTTP-Fehler bei Strafe '{punishment}': {e}")

        if executed and punishment in ("warn", "timeout", "kick"):
            case_id = await self.db.acreate_case(guild.id, member.id, mod_id, punishment, reason,
                                                 duration=duration if punishment == "timeout" else None)
            ACTIVITY.push("case", f"Case #{case_id} ({punishment}) – {member}", guild_id=guild.id, guild_name=guild.name,
                          user_id=member.id, user_name=str(member))
            return case_id
        return None

    async def create_mod_case(self, guild, target, moderator, action, reason, duration=None, snapshot_messages=False) -> int:
        target_id = target.id if hasattr(target, "id") else int(target)
        case_id = await self.db.acreate_case(guild.id, target_id, moderator.id, action, reason, duration=duration)
        if snapshot_messages:
            pre_messages = await self.db.aget_user_messages(guild.id, target_id, hours=48, limit=500)
            if pre_messages:
                serializable = [{
                    "channel_id": m.get("channel_id"), "message_id": m.get("message_id"),
                    "content": m.get("content", ""), "attachments": m.get("attachments", []),
                    "deleted": bool(m.get("deleted")), "edits": m.get("edits", []),
                    "timestamp": (m.get("timestamp") or discord.utils.utcnow()).isoformat() + "Z",
                } for m in pre_messages]
                await self.db.aattach_messages_to_case(guild.id, case_id, serializable)
        ACTIVITY.push("case", f"Case #{case_id} ({action}) – Target `{target_id}` von {moderator}.",
                      guild_id=guild.id, guild_name=guild.name, user_id=moderator.id, user_name=str(moderator))
        return case_id

    async def _check_warn_thresholds(self, member, warn_count: int) -> None:
        cfg = self.db.get_config(member.guild.id)
        thresholds = cfg.get("warn_system", {}).get("thresholds", {})
        for threshold_str, action in sorted(thresholds.items(), key=lambda x: int(x[0])):
            try:
                if warn_count == int(threshold_str):
                    await self.punish(member, action, f"Automatisch: {warn_count} Verwarnungen erreicht")
                    await self.log_action(member.guild, f"{E.WARN} Warn-Schwelle erreicht",
                                          f"{member.mention} hat **{warn_count} Verwarnungen** erreicht → **{action}**",
                                          COLOR_WARNING, user=member, module="warns")
            except ValueError:
                continue

    def is_whitelisted(self, member, bypass_type=None) -> bool:
        # Bot erkennt sich IMMER als whitelisted — nie gegen sich selbst handeln
        if member.id == self.user.id:
            return True
        # Server-Owner ist immer geschützt
        if member.id == member.guild.owner_id:
            return True
        wl = self.db.get_whitelist(member.guild.id)
        if member.id in wl.get("users", []):
            return True
        for role in member.roles:
            if role.id in wl.get("roles", []):
                return True
        if bypass_type and member.id in wl.get(bypass_type, []):
            return True
        return False

    # ── PERIODISCHE TASKS ──────────────────────────────────
    @tasks.loop(minutes=5)
    async def cleanup_trackers(self) -> None:
        now = time.time()
        for guild_data in self.tracker.spam_tracker.values():
            for dq in guild_data.values():
                while dq and now - dq[0] > 60:
                    dq.popleft()
        log.debug("Tracker bereinigt.")

    @tasks.loop(hours=1)
    async def _cache_refresh_loop(self) -> None:
        """Refresh Config-Cache stündlich – hält Logs persistent über Neustarts."""
        refreshed = 0
        failed = 0
        for guild in self.guilds:
            try:
                cfg = self.db.get_config(guild.id)
                self._config_cache[guild.id] = cfg
                refreshed += 1
            except Exception as e:
                log.error(f"Cache-Refresh Fehler für Guild {guild.id}: {e}")
                failed += 1
        if refreshed > 0:
            log.info(f"Config-Cache refresh: {refreshed} aktualisiert, {failed} fehlgeschlagen")

    @tasks.loop(seconds=30)
    async def tempaction_loop(self) -> None:
        try:
            due = await self.db.aget_due_tempactions()
        except Exception as e:
            log.error(f"tempaction_loop Fehler: {e}")
            return
        for entry in due:
            guild = self.get_guild(entry["guild_id"])
            if not guild:
                await self.db.adeactivate_tempaction(entry["_id"])
                continue
            try:
                if entry["action"] == "tempban":
                    try:
                        await guild.unban(discord.Object(id=entry["user_id"]), reason="Tempban abgelaufen")
                    except discord.NotFound:
                        pass
                    except discord.Forbidden:
                        pass
                    await self.log_action(guild, f"{E.OK} Tempban abgelaufen", f"<@{entry['user_id']}> entbannt.", COLOR_SUCCESS, module="moderation")
                elif entry["action"] == "tempmute":
                    member = guild.get_member(entry["user_id"])
                    if member:
                        try:
                            await member.timeout(None, reason="Tempmute abgelaufen")
                        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                            pass
                    await self.db.adeactivate_mute(guild.id, entry["user_id"])
                    await self.log_action(guild, f"{E.UNMUTE} Tempmute abgelaufen", f"<@{entry['user_id']}> entmutet.", COLOR_SUCCESS, module="moderation")
            finally:
                await self.db.adeactivate_tempaction(entry["_id"])

    @tasks.loop(count=1)
    async def restore_persistent_mutes(self) -> None:
        await self.wait_until_ready()
        active = await self.db.aget_active_mutes()
        now = discord.utils.utcnow()
        for entry in active:
            guild = self.get_guild(entry["guild_id"])
            if not guild:
                continue
            member = guild.get_member(entry["user_id"])
            if not member:
                continue
            end_time = entry.get("end_time")
            if end_time and end_time <= now:
                try:
                    await member.timeout(None, reason="Persistent-Mute abgelaufen (Recovery)")
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass
                await self.db.adeactivate_mute(guild.id, member.id)
                continue
            if end_time:
                try:
                    await member.timeout(end_time, reason="Persistent-Mute Wiederherstellung nach Neustart")
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass
        log.info(f"{len(active)} persistente Mutes geprüft.")

# ═══════════════════════════════════════════════════════════════════
# BOT EVENTS
# ═══════════════════════════════════════════════════════════════════
# (alle Events als Methoden von ModForge werden im Anschluss registriert)

# Da die Bot-Instanz später erstellt wird, müssen die Event-Handler als
# Funktionen definiert werden, die das bot-Objekt referenzieren.
# Wir definieren sie nach der Klasse und nutzen `@bot.event`.

# Erstelle die Bot-Instanz vorläufig, dann Events.
BOT_REF = None
bot = ModForge()

# Bot-Developer kann jeden Command nutzen
@bot.check
async def global_dev_check(ctx):
    if ctx.author.id == _BOT_DEV_ID:
        return True
    return True  # Normal permission check continues

@bot.event
async def on_member_join(member):
    guild = member.guild
    cfg = bot.db.get_config(guild.id)
    sec_level = cfg.get("security_level", 0)
    raid_cfg = cfg.get("anti_raid", {})
    ACTIVITY.push("join", f"{member} ist **{guild.name}** beigetreten ({guild.member_count} Member).",
                  guild_id=guild.id, guild_name=guild.name, user_id=member.id, user_name=str(member))
    if bot.is_whitelisted(member, "bypass_antinuke"):
        await bot.log_action(guild, f"{E.PLUS} Mitglied beigetreten", f"{member.mention}", COLOR_SUCCESS, user=member, module="members")
        return
    # ── Anti-VPN Check ──
    vpn_cfg = cfg.get("anti_vpn", {})
    if vpn_cfg.get("enabled") and not member.bot:
        vpn_wl = vpn_cfg.get("whitelist_ids", [])
        if str(member.id) not in [str(w) for w in vpn_wl]:
            # Note: Discord doesn't expose IP directly. We check via audit log guild join metadata
            # This is a heuristic: new accounts + no avatar + suspicious patterns
            account_age_hours = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).total_seconds() / 3600
            suspicious_vpn = (
                account_age_hours < 24 and
                not member.avatar and
                (member.name.startswith("user") or len(member.name) < 4 or any(c.isdigit() for c in member.name[-4:]))
            )
            if suspicious_vpn:
                action = vpn_cfg.get("action", "kick")
                try:
                    if action == "ban":
                        await member.ban(reason="Anti-VPN: Verdächtiger Account (VPN/Proxy-Heuristik)")
                    elif action == "kick":
                        await member.kick(reason="Anti-VPN: Verdächtiger Account (VPN/Proxy-Heuristik)")
                    await bot.log_action(guild, f"{E.SHIELD} Anti-VPN",
                        f"{member.mention} wurde als verdächtig erkannt.\n"
                        f"**Account-Alter:** {int(account_age_hours)}h\n**Aktion:** {action}\n"
                        f"Kein Avatar + neuer Account + verdächtiger Name",
                        COLOR_WARNING, user=member, module="antiraid")
                except discord.Forbidden:
                    await bot.log_action(guild, f"{E.ALERT}️ Anti-VPN", f"Kann {member.mention} nicht {action}en (fehlende Rechte).", COLOR_WARNING, module="antiraid")

    # ── Raid-Mode DM ──
    if cfg.get("raidmode_active") and not member.bot:
        try:
            dm_embed = create_embed(
                "🚨 Server im Raid-Modus",
                f"**{guild.name}** ist aktuell im Raid-Modus.\n"
                f"Der Zugang ist vorübergehend eingeschränkt.\n"
                f"Bitte versuche es später erneut.",
                COLOR_DANGER,
                thumbnail=guild.icon.url if guild.icon else None
            )
            await safe_dm(member, dm_embed, cooldown_key=f"raidmode_dm:{guild.id}:{member.id}")
        except Exception:
            pass

    if sec_level >= 2:
        account_age = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).days
        if account_age < 5:
            try:
                await member.kick(reason="Sicherheitsstufe 2: Account zu jung (< 5 Tage)")
                await bot.log_action(guild, f"{E.SHIELD} Sicherheitsstufe 2: Kick",
                                     f"{member.mention} (Account-Alter: {account_age} Tage).", COLOR_DANGER, user=member, module="antiraid")
                return
            except discord.Forbidden:
                pass
    if sec_level >= 3:
        try:
            await member.ban(reason="Sicherheitsstufe 3: BLACKOUT aktiv")
            await bot.log_action(guild, f"{E.SHIELD} Sicherheitsstufe 3: BLACKOUT BAN",
                                 f"{member.mention} sofort gebannt.", COLOR_DANGER, user=member, module="antiraid")
            return
        except discord.Forbidden:
            pass
    if raid_cfg.get("enabled"):
        now = time.time()
        dq = bot.tracker.raid_tracker[guild.id]
        dq.append(now)
        bot.tracker.clean_old(dq, raid_cfg.get("window", 20))
        min_age_days = raid_cfg.get("min_account_age", 7)
        account_age = (discord.utils.utcnow() - member.created_at.replace(tzinfo=None)).days
        if account_age < min_age_days and raid_cfg.get("auto_kick"):
            try:
                await member.kick(reason=f"Anti-Raid: Account zu jung ({account_age} Tage)")
                await bot.log_action(guild, f"{E.NEWACC} Neuer Account gekickt",
                                     f"{member.mention} (Account-Alter: {account_age} Tage).", COLOR_DANGER,
                                     [("Minimum", f"{min_age_days} Tage", True)], user=member, module="antiraid")
                return
            except discord.Forbidden:
                pass
        new_acc_window = raid_cfg.get("new_account_window", 600)
        new_acc_thresh = raid_cfg.get("new_account_threshold", 5)
        if account_age < min_age_days:
            ndq = bot.tracker.new_account_tracker[guild.id]
            ndq.append(now)
            bot.tracker.clean_old(ndq, new_acc_window)
            if len(ndq) >= new_acc_thresh:
                await bot.log_action(guild, f"{E.RAID} Neue-Account-Cluster",
                                     f"{len(ndq)} junge Accounts in {new_acc_window}s.", COLOR_DANGER, module="antiraid")
        if raid_cfg.get("suspicious_name_check") and SUSPICIOUS_NAME_REGEX.match(member.name):
            await bot.log_action(guild, f"{E.RAID} Verdächtiger Username",
                                 f"{member.mention} (`{member.name}`).", COLOR_WARNING, user=member, module="antiraid")
        if len(dq) >= raid_cfg.get("join_threshold", 10):
            dq.clear()
            if not bot.tracker.lockdown_active[guild.id] and raid_cfg.get("lockdown"):
                bot.tracker.lockdown_active[guild.id] = True
                await _activate_lockdown(guild)
            await bot.log_action(guild, f"{E.NUKE} RAID ERKANNT – LOCKDOWN", "Zu viele Beitritte!", COLOR_DANGER, module="antiraid")
    if member.bot:
        nuke_cfg = cfg.get("anti_nuke", {})
        if nuke_cfg.get("enabled"):
            try:
                async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
                    await _nuke_check(guild, entry.user.id, "Bot hinzugefügt")
            except discord.Forbidden:
                pass
        await bot.log_action(guild, f"{E.BOT} Bot hinzugefügt", f"Bot **{member.mention}**", COLOR_WARNING, user=member, module="members")
        return
    await bot.log_action(guild, f"{E.JOIN} Mitglied beigetreten", f"{member.mention}", COLOR_SUCCESS, user=member, module="members")

    # ── Welcome-Nachricht senden ──
    try:
        from bot.bot import _send_welcome, _restore_sticky_roles
        await _send_welcome(member)
        await _restore_sticky_roles(member)
    except Exception as ex:
        log.debug(f"Welcome/Sticky-Roles Fehler: {ex}")

    # ── Temp-Voice: Nichts bei Join nötig ──

# ═══════════════════════════════════════════════════════════════
# APPEAL SESSIONS & HELFER
# ═══════════════════════════════════════════════════════════════
appeal_sessions: dict = {}

APPEAL_QUESTIONS = [
    "**Frage 1/5** – Warum glaubst du, wurdest du gebannt?",
    "**Frage 2/5** – Siehst du deinen Fehler ein? *(Bitte antworte mit `ja` oder `nein`)*",
    "**Frage 3/5** – Was möchtest du dem Moderationsteam zu deinem Ban sagen?",
    "**Frage 4/5** – Versprichst du, die Serverregeln in Zukunft zu befolgen? *(ja/nein)*",
    "**Frage 5/5** – Gibt es noch etwas, das du hinzufügen möchtest? *(Wenn nein, schreibe `nein`)*"
]
APPEAL_KEYS = ["ban_grund", "fehler_eingesehen", "statement", "regeln_versprechen", "zusatz"]

async def handle_appeal_dm(message: discord.Message) -> bool:
    if message.author.bot or message.guild:
        return False

    user_id = message.author.id
    content = message.content.strip()

    if user_id in appeal_sessions:
        session = appeal_sessions[user_id]

        if content.lower() == "!abbruch":
            del appeal_sessions[user_id]
            await message.author.send(embed=create_embed(
                "🚫 Appeal abgebrochen", "Du hast den Entbannungs-Antrag abgebrochen.", COLOR_WARNING))
            return True

        step = session["step"]

        if step == -1:
            if content.lower() == "!start":
                session["step"] = 0
                await message.author.send(embed=create_embed(
                    "📋 Entbannungs-Antrag – Start",
                    ("Super! Ich stelle dir jetzt **5 Fragen**. "
                     "Bitte beantworte jede ehrlich und vollständig.\n\n"
                     "Du kannst den Antrag jederzeit mit `!abbruch` beenden.\n\n"
                     + APPEAL_QUESTIONS[0]),
                    COLOR_PRIMARY))
            else:
                await message.author.send(embed=create_embed(
                    "ℹ️ Hinweis",
                    "Schreibe `!start` um den Antrag zu beginnen, oder ignoriere diese Nachricht.",
                    COLOR_INFO))
            return True

        session["answers"][APPEAL_KEYS[step]] = content
        session["step"] += 1
        next_step = session["step"]

        if next_step < len(APPEAL_QUESTIONS):
            await message.author.send(embed=create_embed(
                f"{E.OK} Antwort gespeichert", APPEAL_QUESTIONS[next_step], COLOR_INFO))
        else:
            await _submit_appeal(message.author, session)
            del appeal_sessions[user_id]

        return True

    return False

async def _submit_appeal(user: discord.User, session: dict) -> None:
    guild_id = session["guild_id"]
    guild = bot.get_guild(guild_id)
    answers = session["answers"]
    ban_reason = session.get("ban_reason", "Unbekannt")

    if not guild:
        await user.send(f"{E.FAIL} Der Server konnte nicht gefunden werden.")
        return

    cfg = bot.db.get_config(guild_id)
    channel_id = cfg.get("appeal_log_channel")
    if not channel_id:
        await user.send(embed=create_embed(
            f"{E.FAIL} Kein Appeal-Kanal",
            "Auf diesem Server wurde noch kein Appeal-Kanal eingerichtet. "
            "Bitte wende dich direkt an einen Admin.",
            COLOR_DANGER))
        return

    channel = guild.get_channel(int(channel_id))
    if not channel:
        return

    embed = create_embed(
        "📋 Neuer Entbannungs-Antrag",
        "Ein gebannter Nutzer hat einen Entbannungs-Antrag gestellt.",
        COLOR_PRIMARY,
        fields=[
            ("👤 Nutzer", f"{user.mention} (`{user}`)", True),
            ("🆔 User-ID", str(user.id), True),
            ("🔨 Ban-Grund", ban_reason, False),
            (f"{E.QUESTION} Warum gebannt?", answers.get("ban_grund", "–"), False),
            (f"{E.OK} Fehler eingesehen?", answers.get("fehler_eingesehen", "–"), True),
            ("📜 Statement", answers.get("statement", "–"), False),
            ("🤝 Regeln versprechen?", answers.get("regeln_versprechen", "–"), True),
            (f"{E.TEXT} Zusatz", answers.get("zusatz", "–"), False),
        ],
        thumbnail=user.display_avatar.url
    )
    embed.set_footer(text=f"Powered by BotForge 🔒 | UserID: {user.id}", icon_url=FOOTER_ICON)

    view = AppealActionView(bot_ref=bot, appeal_data={"user_id": user.id, "guild_id": guild_id})
    await channel.send(embed=embed, view=view)

    await user.send(embed=create_embed(
        f"{E.OK} Antrag eingereicht!",
        (f"Dein Entbannungs-Antrag wurde erfolgreich an das Team von **{guild.name}** gesendet.\n"
         "Bitte habe etwas Geduld – du wirst per DM über die Entscheidung informiert."),
        COLOR_SUCCESS,
        thumbnail=guild.icon.url if guild.icon else None))

# ═══════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN FÜR LOCKDOWN & NUKE
# ═══════════════════════════════════════════════════════════════

async def _activate_lockdown(guild: discord.Guild) -> None:
    """Sperrt alle Textkanäle für @everyone."""

    for channel in guild.text_channels:

        try:
            await channel.set_permissions(
                guild.default_role,
                send_messages=False,
                reason="Anti-Raid Lockdown"
            )

        except discord.Forbidden:
            pass

        await asyncio.sleep(0.3)

    await bot.log_action(
        guild,
        f"{E.LOCK} Lockdown aktiviert",
        "Alle Kanäle wurden für @everyone gesperrt.",
        COLOR_DANGER,
        module="antiraid"
    )

async def _deactivate_lockdown(guild: discord.Guild) -> None:
    """Hebt den Lockdown vollständig auf."""

    for channel in guild.text_channels:

        try:
            await channel.set_permissions(
                guild.default_role,
                send_messages=None,
                reason="Lockdown aufgehoben"
            )

        except discord.Forbidden:
            pass

        await asyncio.sleep(0.3)

    bot.tracker.lockdown_active[guild.id] = False

    await bot.log_action(
        guild,
        f"{E.UNLOCK} Lockdown aufgehoben",
        "Alle Kanäle wurden wieder entsperrt.",
        COLOR_SUCCESS,
        module="antiraid"
    )

async def _auto_deactivate_lockdown(
    guild: discord.Guild,
    delay: int
) -> None:
    """Hebt den Lockdown nach `delay` Sekunden auf."""

    await asyncio.sleep(delay)

    if bot.tracker.lockdown_active[guild.id]:
        await _deactivate_lockdown(guild)

async def _notify_owner_nuke(
    guild: discord.Guild,
    executor: Optional[discord.Member],
    executor_id: int,
    action: str,
    punishment: str
) -> None:
    """Sendet eine detaillierte Anti-Nuke-Alarm-DM an den Server-Owner."""

    owner = guild.owner

    if not owner:

        try:
            owner = await guild.fetch_member(
                guild.owner_id
            )

        except Exception:
            return

    if not owner:
        return

    now = datetime.datetime.now(
        datetime.timezone.utc
    )

    timestamp_f = (
        f"<t:{int(now.timestamp())}:F>"
    )

    timestamp_r = (
        f"<t:{int(now.timestamp())}:R>"
    )

    user_line = (
        executor.mention
        if executor
        else f"Unbekannter User (`{executor_id}`)"
    )

    if executor:

        account_created = (
            f"<t:{int(executor.created_at.timestamp())}:R>"
        )

        account_age = (
            f"\n**Account erstellt:** "
            f"{account_created}"
        )

        roles = ", ".join(
            r.name
            for r in executor.roles
            if r.name != "@everyone"
        ) or "Keine"

    else:

        account_age = ""

        roles = "Nicht verfügbar"

    embed = create_embed(
        title=(
            f"{E.NUKE}  Anti-Nuke — Kritischer Alarm"
        ),

        description=(
            f"Ein **zerstörerischer Massenangriff** "
            f"wurde auf **{guild.name}** erkannt und "
            f"**automatisch neutralisiert**. "
            f"ModForge hat sofort eingegriffen."
        ),

        color=COLOR_DANGER,

        thumbnail=(
            guild.icon.url
            if guild.icon
            else None
        )
    )

    # ── Vorfall ────────────────────────────────────────────────

    embed.add_field(
        name="🔍  Vorfall",

        value=(
            f"```\n{action}\n```"
            f"📅  {timestamp_f}  ·  {timestamp_r}\n"
            f"🏠  {guild.name}  ·  `{guild.id}`"
        ),

        inline=True
    )

    # ── Verursacher ────────────────────────────────────────────

    embed.add_field(
        name="👤  Verursacher",

        value=(
            f"{user_line}"
            f"`{executor_id}`\n"
            f"{account_age}\n"
            f"🎭  {roles}"
        ),

        inline=True
    )

    # ── Strafe ─────────────────────────────────────────────────

    embed.add_field(
        name=f"{E.LAW}️  Strafe",

        value=(
            f"```fix\n"
            f"{punishment}\n"
            f"```"
        ),

        inline=True
    )

    # ── Sofortmaßnahmen ────────────────────────────────────────

    embed.add_field(
        name="🛡️  Automatische Sofortmaßnahmen",

        value=(
            f"> 🔒  **Server-Lockdown** aktiv "
            f"für **10 Minuten**\n"

            f"> 🚫  **Alle Rollen** des Täters "
            f"wurden entzogen\n"

            f"> {E.LAW}️  **Strafe** `{punishment}` "
            f"wurde verhängt\n"

            f"> {E.FOLDER}  **Case** wurde automatisch "
            f"im System gespeichert"
        ),

        inline=False
    )

    # ── Lockdown ───────────────────────────────────────────────

    embed.add_field(
        name="⏳  Lockdown-Status",

        value=(
            "Der Lockdown **läuft automatisch aus** – "
            "Mitglieder können währenddessen "
            "**keine Nachrichten senden**.\n"

            "Vorzeitig aufheben: `/unlockdown`"
        ),

        inline=False
    )

    # ── Empfehlungen ───────────────────────────────────────────

    embed.add_field(
        name="📋  Empfohlene Maßnahmen",

        value=(
            "`1`  Audit-Log prüfen "
            "→ *Servereinstellungen → Audit-Log*\n"

            "`2`  Rollen & Berechtigungen "
            "des Täters überprüfen\n"

            "`3`  Sicherheitsstufe erhöhen "
            "→ `/security_level 2`\n"

            "`4`  Admin-Team über den Vorfall "
            "informieren\n"

            "`5`  Case einsehen "
            "→ `/case <id>`"
        ),

        inline=False
    )

    # ── Footer ─────────────────────────────────────────────────

    embed.set_footer(
        text=(
            f"ModForge Security  ·  "
            f"{guild.name}  ·  "
            f"Case gespeichert"
        ),

        icon_url=FOOTER_ICON
    )

    embed.timestamp = now

    await safe_dm(
        owner, embed,
        cooldown_key=f"nuke_alert:{guild.id}",
        cooldown_seconds=60
    )
    if False:  # kept for structure
        pass

async def _nuke_check(
    guild: discord.Guild,
    executor_id: int,
    action: str
) -> None:
    """Überwacht verdächtige Massenaktionen und leitet Gegenmaßnahmen ein."""

    cfg = bot.db.get_config(guild.id)

    nuke_cfg = cfg.get(
        "anti_nuke",
        {}
    )

    if not nuke_cfg.get("enabled"):
        return

    now = time.time()

    dq = bot.tracker.nuke_tracker[
        guild.id
    ][executor_id]

    dq.append(now)

    bot.tracker.clean_old(
        dq,
        nuke_cfg.get("window", 10)
    )

    if len(dq) >= nuke_cfg.get("threshold", 5):

        dq.clear()

        executor = guild.get_member(
            executor_id
        )

        if (
            not executor
            or bot.is_whitelisted(executor)
        ):
            return

        # Rolle(n) entfernen

        if (
            nuke_cfg.get("remove_roles")
            and executor
        ):

            try:
                await executor.edit(
                    roles=[],
                    reason=(
                        "Anti-Nuke: Rollen entfernt"
                    )
                )

            except (
                discord.Forbidden,
                discord.HTTPException
            ):
                pass

        # Nie gegen den Bot selbst oder Owner handeln
        if executor.id == bot.user.id:
            return
        if executor.id == guild.owner_id:
            return

        punishment = nuke_cfg.get(
            "punishment",
            "ban"
        )

        # Hierarchie-Check: Kann der Bot den Täter überhaupt bestrafen?
        bot_member = guild.me
        can_act = True
        hierarchy_msg = ""
        try:
            if bot_member.top_role <= executor.top_role:
                can_act = False
                hierarchy_msg = (
                    f"Die Rolle von **{executor.display_name}** "
                    f"(`{executor.top_role.name}`) ist höher oder gleich "
                    f"der Bot-Rolle (`{bot_member.top_role.name}`).\n"
                    f"Der Bot kann diesen User **nicht bestrafen**."
                )
        except Exception:
            pass

        if can_act:
            await bot.punish(
                executor,
                punishment,
                (
                    f"Anti-Nuke: "
                    f"Verdächtige Aktivität "
                    f"({action})"
                )
            )
        else:
            # Bot kann nicht handeln → Owner-DM mit Warnung
            owner = guild.owner
            if owner:
                alert_embed = create_embed(
                    f"{E.NUKE} {E.ALERT}️ ANTI-NUKE ALARM — Bot kann nicht handeln!",
                    (
                        f"**{executor.mention}** führt verdächtige "
                        f"Massenaktionen auf **{guild.name}** durch!\n\n"
                        f"**{E.ALERT}️ Problem:** {hierarchy_msg}\n\n"
                        f"**Was du tun solltest:**\n"
                        f"> 1. Rolle von `{executor.display_name}` sofort entfernen\n"
                        f"> 2. User manuell bannen\n"
                        f"> 3. Bot-Rolle über alle Admin-Rollen verschieben\n"
                        f"> 4. `/security_level 3` für Lockdown"
                    ),
                    COLOR_DANGER,
                    thumbnail=executor.display_avatar.url if executor else None
                )
                alert_embed.add_field(
                    name="🔍 Erkannte Aktion",
                    value=f"```{action}```",
                    inline=False
                )
                await safe_dm(owner, alert_embed,
                              cooldown_key=f"nuke_hierarchy:{guild.id}:{executor.id}",
                              cooldown_seconds=120)

        # Automatischer Lockdown

        if not bot.tracker.lockdown_active[guild.id]:

            bot.tracker.lockdown_active[
                guild.id
            ] = True

            asyncio.create_task(
                _auto_deactivate_lockdown(
                    guild,
                    600
                )
            )

            await _activate_lockdown(
                guild
            )

        # Owner informieren

        await _notify_owner_nuke(
            guild,
            executor,
            executor_id,
            action,
            punishment
        )

        # Log-Eintrag

        await bot.log_action(
            guild,

            f"{E.NUKE} ANTI-NUKE AUSGELÖST",

            (
                f"**"
                f"{executor.mention if executor else executor_id}"
                f"** hat verdächtige "
                f"Massenaktionen durchgeführt!\n"

                f"**Lockdown:** "
                f"automatisch aktiviert "
                f"(10 min)."
            ),

            COLOR_DANGER,

            [
                (
                    "Aktion",
                    action,
                    True
                ),

                (
                    "Strafe",
                    punishment,
                    True
                ),

                (
                    "Lockdown",
                    "10 Minuten",
                    True
                )
            ],

            user=executor,
            module="antinuke"
        )

async def _audit_actor(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_id: Optional[int] = None
) -> Optional[discord.abc.User]:
    """Holt den letzten Audit-Log Akteur für eine bestimmte Aktion."""

    try:

        async for entry in guild.audit_logs(
            limit=5,
            action=action
        ):

            if (
                target_id is None
                or (
                    entry.target
                    and getattr(
                        entry.target,
                        "id",
                        None
                    ) == target_id
                )
            ):
                return entry.user

    except discord.Forbidden:
        return None

    return None
    
# ═══════════════════════════════════════════════════════════════
# EVENT: ON_MESSAGE
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_message(message: discord.Message) -> None:
    if not message.guild:
        await handle_appeal_dm(message)
        return

    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    member = message.author
    guild = message.guild
    cfg = bot.db.get_config(guild.id)

    # ── 48h Nachrichten-Archiv (für Pre-Ban Snapshot in Cases) ──
    archive_cfg = cfg.get("message_archive", {}) or {}
    if archive_cfg.get("enabled"):
        try:
            await bot.db.arecord_message(
                guild_id=guild.id,
                channel_id=message.channel.id,
                message_id=message.id,
                user_id=member.id,
                content=message.content or "",
                attachments=[a.url for a in message.attachments],
            )
        except Exception as ex:
            log.debug(f"arecord_message Fehler: {ex}")

    # ── Logging: jede gesendete Nachricht (nur wenn Kanal konfiguriert) ──
    log_channels = cfg.get("log_channels", {}) or {}
    if log_channels.get("messages_sent"):
        content_preview = message.content or "*(leer / nur Anhang)*"
        if len(content_preview) > 1000:
            content_preview = content_preview[:1000] + "…"
        attach_info = ""
        if message.attachments:
            attach_info = f"\n**Anhänge:** {len(message.attachments)} ({', '.join(a.filename for a in message.attachments)[:200]})"
        await bot.log_action(
            guild,
            f"{E.MESSAGE} Nachricht gesendet",
            f"**Autor:** {member.mention} (`{member.id}`)\n"
            f"**Kanal:** {message.channel.mention}\n"
            f"**Inhalt:**\n{content_preview}{attach_info}",
            COLOR_INFO, user=member, module="messages_sent",
        )

    if bot.is_whitelisted(member):
        await bot.process_commands(message)
        return

    # Ghost-Ping Tracking
    if cfg.get("anti_ghost_ping", {}).get("enabled"):
        if message.mentions or message.role_mentions:
            bot.tracker.ghost_tracker[guild.id][message.id] = (
                member.id,
                [u.id for u in message.mentions],
                [r.id for r in message.role_mentions]
            )

    if bot.is_whitelisted(member, "bypass_antispam"):
        await bot.process_commands(message)
        return

    spam_cfg = cfg.get("anti_spam", {})
    if spam_cfg.get("enabled"):
        now = time.time()
        dq = bot.tracker.spam_tracker[guild.id][member.id]
        dq.append(now)
        bot.tracker.clean_old(dq, spam_cfg.get("msg_window", 10))

        if len(dq) > spam_cfg.get("msg_limit", 5):
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            await bot.punish(member, spam_cfg.get("punishment", "timeout"),
                             "Anti-Spam: Nachrichtenflut",
                             spam_cfg.get("timeout_duration", 30))
            await bot.log_action(guild, f"{E.SPAM} Anti-Spam ausgelöst",
                                 f"{member.mention} hat zu viele Nachrichten gesendet.",
                                 COLOR_WARNING, user=member, module="antispam")
            await bot.process_commands(message)
            return

        content = message.content or ""
        if len(content) > 10:
            caps_ratio = sum(1 for c in content if c.isupper()) / max(len(content), 1) * 100
            if caps_ratio > spam_cfg.get("caps_pct", 70):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await bot.punish(member, spam_cfg.get("punishment", "timeout"),
                                 "Anti-Spam: Caps-Spam",
                                 spam_cfg.get("timeout_duration", 30))
                await bot.log_action(guild, f"{E.CAPS} Caps-Spam erkannt",
                                     f"{member.mention} hat Caps-Spam gesendet ({caps_ratio:.0f}% Großbuchstaben).",
                                     COLOR_WARNING, user=member, module="antispam")
                await bot.process_commands(message)
                return

        emoji_count = len(re.findall(r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF]", content))
        if emoji_count > spam_cfg.get("emoji_max", 10):
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            await bot.punish(member, spam_cfg.get("punishment", "timeout"),
                             "Anti-Spam: Emoji-Spam",
                             spam_cfg.get("timeout_duration", 30))
            await bot.log_action(guild, f"{E.EMOJI} Emoji-Spam erkannt",
                                 f"{member.mention} hat {emoji_count} Emojis in einer Nachricht gesendet.",
                                 COLOR_WARNING, user=member, module="antispam")
            await bot.process_commands(message)
            return

        dup_list = bot.tracker.dup_tracker[guild.id][member.id]
        dup_list.append(content.lower().strip())
        if len(dup_list) > 10:
            dup_list.pop(0)
        if dup_list.count(content.lower().strip()) > spam_cfg.get("duplicate_max", 3):
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            await bot.punish(member, spam_cfg.get("punishment", "timeout"),
                             "Anti-Spam: Doppelte Nachrichten",
                             spam_cfg.get("timeout_duration", 30))
            await bot.log_action(guild, f"{E.DUP} Duplikat-Spam erkannt",
                                 f"{member.mention} hat dieselbe Nachricht zu oft gesendet.",
                                 COLOR_WARNING, user=member, module="antispam")
            await bot.process_commands(message)
            return

    automod_cfg = cfg.get("automod", {})
    if automod_cfg.get("enabled"):
        content = message.content or ""

        for word in automod_cfg.get("bad_words", []):
            try:
                if re.search(rf"\b{re.escape(word)}\b", content, re.IGNORECASE):
                    try:
                        await message.delete()
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    await bot.punish(member, automod_cfg.get("punishment", "warn"),
                                     f"AutoMod: Verbotenes Wort '{word}'")
                    await bot.log_action(guild, f"{E.BADWORD} Verbotenes Wort erkannt",
                                         f"{member.mention} hat ein verbotenes Wort verwendet.",
                                         COLOR_DANGER, [("Wort", f"||{word}||", True)],
                                         user=member, module="automod")
                    await bot.process_commands(message)
                    return
            except re.error:
                continue

        # Custom Regex-Regeln
        for pattern in automod_cfg.get("regex_rules", []):
            try:
                if re.search(pattern, content):
                    try:
                        await message.delete()
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    await bot.punish(member, automod_cfg.get("punishment", "warn"),
                                     f"AutoMod: Regex-Regel '{pattern[:40]}'")
                    await bot.log_action(guild, f"{E.BADWORD} AutoMod Regex",
                                         f"{member.mention} – Pattern erkannt.",
                                         COLOR_DANGER, [("Pattern", f"`{pattern[:80]}`", False)],
                                         user=member, module="automod")
                    await bot.process_commands(message)
                    return
            except re.error:
                continue

        if automod_cfg.get("invite_filter") and INVITE_REGEX.search(content):
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            await bot.punish(member, automod_cfg.get("punishment", "warn"),
                             "AutoMod: Discord Einladungslink")
            await bot.log_action(guild, f"{E.BADWORD} Invite-Link erkannt",
                                 f"{member.mention} hat einen Discord-Einladungslink gesendet.",
                                 COLOR_DANGER, user=member, module="automod")
            await bot.process_commands(message)
            return

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
                    await bot.punish(member, automod_cfg.get("punishment", "warn"),
                                     "AutoMod: Nicht erlaubter Link")
                    await bot.log_action(guild, f"{E.BADWORD} Link-Filter ausgelöst",
                                         f"{member.mention} hat einen nicht erlaubten Link gesendet.",
                                         COLOR_WARNING, [("URL", f"`{url[:100]}`", False)],
                                         user=member, module="automod")
                    await bot.process_commands(message)
                    return

        if automod_cfg.get("zalgo_filter") and ZALGO_REGEX.search(content):
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            await bot.punish(member, automod_cfg.get("punishment", "warn"),
                             "AutoMod: Zalgo-Text erkannt")
            await bot.log_action(guild, f"{E.BADWORD} Zalgo-Text erkannt",
                                 f"{member.mention} hat Zalgo-Text gesendet.",
                                 COLOR_WARNING, user=member, module="automod")
            await bot.process_commands(message)
            return

        if automod_cfg.get("unicode_abuse"):
            suspicious = sum(1 for c in content if unicodedata.category(c) in ("Cf", "Cs", "Co"))
            if suspicious > 5:
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await bot.punish(member, automod_cfg.get("punishment", "warn"),
                                 "AutoMod: Unicode-Missbrauch")
                await bot.log_action(guild, f"{E.BADWORD} Unicode-Missbrauch erkannt",
                                     f"{member.mention} hat verdächtige Unicode-Zeichen verwendet.",
                                     COLOR_WARNING, user=member, module="automod")
                await bot.process_commands(message)
                return

        if automod_cfg.get("phishing_check") and URL_REGEX.search(content):
            if await check_phishing_url(content):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await bot.punish(member, automod_cfg.get("punishment", "warn"),
                                 "AutoMod: Phishing-Link")
                await bot.log_action(guild, f"{E.NUKE} Phishing erkannt",
                                     f"Link von {member.mention} gelöscht.",
                                     COLOR_DANGER, user=member, module="automod")
                await bot.process_commands(message)
                return

    scam_cfg = cfg.get("anti_scam", {})
    if scam_cfg.get("enabled"):
        for domain in SCAM_DOMAINS:
            if domain.lower() in message.content.lower():
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await bot.punish(member, scam_cfg.get("punishment", "ban"),
                                 f"Anti-Scam: Scam-Domain '{domain}'")
                await bot.log_action(guild, f"{E.BADWORD} Scam-Link erkannt",
                                     f"{member.mention} hat einen Scam-Link gesendet!",
                                     COLOR_DANGER, [("Domain", domain, True)],
                                     user=member, module="antiscam")
                await bot.process_commands(message)
                return

    short_cfg = cfg.get("anti_url_shortener", {})
    if short_cfg.get("enabled"):
        for shortener in URL_SHORTENERS:
            if shortener.lower() in message.content.lower():
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await bot.punish(member, short_cfg.get("punishment", "warn"),
                                 f"Anti-URL-Shortener: '{shortener}'")
                await bot.log_action(guild, f"{E.URLSHORT} URL-Shortener erkannt",
                                     f"{member.mention} hat einen URL-Shortener verwendet.",
                                     COLOR_WARNING, user=member, module="antishortener")
                await bot.process_commands(message)
                return

    mention_cfg = cfg.get("anti_mention", {})
    if mention_cfg.get("enabled") and (message.mentions or message.role_mentions):
        total_mentions = len(message.mentions) + len(message.role_mentions)
        now = time.time()
        dq = bot.tracker.mention_tracker[guild.id][member.id]
        for _ in range(total_mentions):
            dq.append(now)
        bot.tracker.clean_old(dq, mention_cfg.get("window", 10))
        if len(dq) > mention_cfg.get("mention_limit", 5):
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            await bot.punish(member, mention_cfg.get("punishment", "timeout"),
                             "Anti-Mention: Mention-Spam",
                             mention_cfg.get("timeout_duration", 60))
            await bot.log_action(guild, f"{E.MENTION} Mention-Spam erkannt",
                                 f"{member.mention} hat zu viele Mentions gesendet.",
                                 COLOR_DANGER, user=member, module="antimention")
            await bot.process_commands(message)
            return

    await bot.process_commands(message)

# ═══════════════════════════════════════════════════════════════
# EVENT: ON_MESSAGE_DELETE
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_message_delete(message: discord.Message) -> None:
    if not message.guild or message.author.bot:
        return
    guild = message.guild
    cfg = bot.db.get_config(guild.id)
    ghost_cfg = cfg.get("anti_ghost_ping", {})

    if ghost_cfg.get("enabled") and message.id in bot.tracker.ghost_tracker.get(guild.id, {}):
        data = bot.tracker.ghost_tracker[guild.id].pop(message.id)
        author = guild.get_member(data[0])
        mentions = [guild.get_member(uid) for uid in data[1] if guild.get_member(uid)]
        mention_str = ", ".join(m.mention for m in mentions if m) or "Unbekannt"
        await bot.log_action(
            guild, f"{E.GHOST} Ghost-Ping erkannt",
            f"**{author.mention if author else 'Unbekannt'}** hat eine Nachricht mit Mentions gelöscht.",
            COLOR_WARNING,
            [("Gepingte User", mention_str, False),
             ("Inhalt", f"||{message.content[:200]}||" if message.content else "*(leer)*", False)],
            user=author, module="ghostping"
        )
        return

    # Archiv: Nachricht als gelöscht markieren (falls aufgezeichnet)
    try:
        await bot.db.amark_message_deleted(guild.id, message.id)
    except Exception as ex:
        log.debug(f"amark_message_deleted Fehler: {ex}")

    await bot.log_action(
        guild, f"{E.DELETE} Nachricht gelöscht",
        f"Nachricht von {message.author.mention} in {message.channel.mention} wurde gelöscht.",
        COLOR_INFO,
        [("Inhalt", message.content[:1000] or "*(Kein Text)*", False)],
        user=message.author, module="messages"
    )

# ═══════════════════════════════════════════════════════════════
# EVENT: ON_MESSAGE_EDIT
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
    if before.author.bot or before.content == after.content:
        return
    # Archiv: alte Version als Edit anhängen (falls aufgezeichnet)
    if before.guild:
        try:
            await bot.db.aappend_message_edit(
                before.guild.id, before.id, before.content or "",
            )
        except Exception as ex:
            log.debug(f"aappend_message_edit Fehler: {ex}")

    await bot.log_action(
        before.guild, f"{E.EDIT} Nachricht bearbeitet",
        f"{before.author.mention} hat eine Nachricht in {before.channel.mention} bearbeitet.",
        COLOR_INFO,
        [("Vorher", before.content[:500] or "*(leer)*", False),
         ("Nachher", after.content[:500] or "*(leer)*", False)],
        user=before.author, module="messages"
    )

# ═══════════════════════════════════════════════════════════════
# EVENT: ON_VOICE_STATE_UPDATE
# ═══════════════════════════════════════════════════════════════

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState,
                                after: discord.VoiceState) -> None:
    """Vollständiges Voice-Logging – loggt JEDEN Voice-State-Change zuverlässig."""
    guild = member.guild
    now = discord.utils.utcnow()

    # ── Temp-Voice: Join-to-Create ──
    if not member.bot:
        try:
            cfg_tv = bot.db.get_config(guild.id)
            tv = cfg_tv.get("temp_voice", {})
            if tv.get("enabled") and tv.get("channel_id"):
                if after.channel and after.channel.id == tv["channel_id"]:
                    cat = guild.get_channel(tv.get("category_id")) if tv.get("category_id") else None
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(read_messages=True, connect=True),
                        member: discord.PermissionOverwrite(read_messages=True, connect=True, manage_channels=True, move_members=True),
                        guild.me: discord.PermissionOverwrite(read_messages=True, connect=True, manage_channels=True),
                    }
                    temp_ch = await guild.create_voice_channel(
                        name=f"{E.VOICE} {member.display_name}", category=cat, overwrites=overwrites,
                        reason=f"Temp-Voice von {member}"
                    )
                    await member.move_to(temp_ch, reason="Temp-Voice erstellt")
                    await bot.log_action(guild, "🎤 Temp-Voice erstellt",
                                         f"{member.mention} hat {temp_ch.mention} erstellt.",
                                         COLOR_SUCCESS, user=member, module="voice")

                if before.channel and before.channel != after.channel:
                    if before.channel.name.startswith(f"{E.VOICE} ") and len(before.channel.members) == 0:
                        try:
                            await before.channel.delete(reason="Temp-Voice: Kanal leer")
                        except (discord.Forbidden, discord.NotFound):
                            pass
        except Exception as ex:
            log.debug(f"Temp-Voice Fehler: {ex}")

    # ── Channel Join / Leave / Switch ──
    if before.channel != after.channel:
        try:
            # JOIN
            if not before.channel and after.channel:
                await bot.log_action(guild, f"{E.VOICE_IN} Voice Join",
                                     f"{member.mention} ist **{after.channel.mention}** beigetreten.",
                                     COLOR_SUCCESS, user=member, module="voice")
            # LEAVE
            elif before.channel and not after.channel:
                # Check for Mod Disconnect
                actor = None
                if not member.bot:
                    try:
                        # Wait a tiny bit for Audit Log to populate
                        await asyncio.sleep(0.4)
                        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_disconnect):
                            if entry.target and entry.target.id == member.id and (now - entry.created_at).total_seconds() < 7:
                                actor = entry.user
                                break
                    except Exception:
                        pass
                if actor:
                    await bot.log_action(guild, "📤 Voice Disconnect (Mod)",
                                         f"**{member.mention}** wurde aus **{before.channel.mention}** entfernt von **{actor.mention}**.",
                                         COLOR_WARNING, user=member, module="voice")
                else:
                    await bot.log_action(guild, f"{E.VOICE_OUT} Voice Leave",
                                         f"{member.mention} hat **{before.channel.mention}** verlassen.",
                                         COLOR_DANGER, user=member, module="voice")
            # SWITCH
            elif before.channel and after.channel:
                # Check for Mod Move
                actor = None
                if not member.bot:
                    try:
                        await asyncio.sleep(0.4)
                        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_move):
                            if entry.target and entry.target.id == member.id and (now - entry.created_at).total_seconds() < 7:
                                actor = entry.user
                                break
                    except Exception:
                        pass
                if actor:
                    await bot.log_action(guild, "↔️ Voice Verschoben (Mod)",
                                         f"**{member.mention}** verschoben von **{actor.mention}**: {before.channel.mention} → {after.channel.mention}",
                                         COLOR_INFO, user=member, module="voice")
                else:
                    await bot.log_action(guild, f"{E.VOICE_SW} Voice Wechsel",
                                         f"{member.mention}: {before.channel.mention} → {after.channel.mention}",
                                         COLOR_INFO, user=member, module="voice")
        except Exception as ex:
            log.debug(f"Voice Channel Event Fehler: {ex}")

    # ── Server Mute / Unmute ──
    if before.mute != after.mute:
        try:
            mod_info = ""
            if not member.bot:
                try:
                    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                        if entry.target and entry.target.id == member.id and (now - entry.created_at).total_seconds() < 5:
                            mod_info = f"\nDurch: **{entry.user.mention}**"
                            if entry.reason: mod_info += f"\nGrund: {entry.reason}"
                            break
                except Exception:
                    pass
            title = f"{E.MUTE} Server Mute" if after.mute else f"{E.UNMUTE} Server Unmute"
            status = "Server-stummgeschaltet 🔇" if after.mute else "Server-entstummgeschaltet"
            color = COLOR_WARNING if after.mute else COLOR_SUCCESS
            await bot.log_action(guild, title, f"**{member.mention}** wurde **{status}**{mod_info}", color, user=member, module="voice")
        except Exception:
            pass

    # ── Server Deafen / Undeafen ──
    if before.deaf != after.deaf:
        try:
            mod_info = ""
            if not member.bot:
                try:
                    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                        if entry.target and entry.target.id == member.id and (now - entry.created_at).total_seconds() < 5:
                            mod_info = f"\nDurch: **{entry.user.mention}**"
                            break
                except Exception:
                    pass
            title = "🔇 Server Deafen" if after.deaf else f"{E.VOICE} Server Undeafen"
            status = "Server-taubgeschaltet" if after.deaf else "Server-Taub aufgehoben"
            color = COLOR_WARNING if after.deaf else COLOR_SUCCESS
            await bot.log_action(guild, title, f"**{member.mention}** wurde **{status}**{mod_info}", color, user=member, module="voice")
        except Exception:
            pass

    # ── Stream / Video / Stage Suppress (Reduced noise) ──
    if before.self_stream != after.self_stream:
        try:
            title = "📺 Stream gestartet" if after.self_stream else "📺 Stream beendet"
            desc = f"**{member.mention}** streamt in {after.channel.mention if after.channel else 'Voice'}" if after.self_stream else f"**{member.mention}** hat den Stream beendet."
            await bot.log_action(guild, title, desc, COLOR_PRIMARY if after.self_stream else COLOR_INFO, user=member, module="voice")
        except Exception:
            pass

    if before.self_video != after.self_video:
        try:
            title = "📹 Kamera an" if after.self_video else "📹 Kamera aus"
            await bot.log_action(guild, title, f"**{member.mention}** Kamera {'eingeschaltet' if after.self_video else 'ausgeschaltet'}", COLOR_PRIMARY if after.self_video else COLOR_INFO, user=member, module="voice")
        except Exception:
            pass

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member) -> None:
    guild = after.guild

    # ── Rollen-Änderungen ───────────────────────────────────────
    if before.roles != after.roles:
        added = [r.mention for r in after.roles if r not in before.roles]
        removed = [r.mention for r in before.roles if r not in after.roles]
        mod: Any = "Unbekannt"
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
                mod = entry.user
                break
        except discord.Forbidden:
            pass
        if added:
            await bot.log_action(
                guild, f"{E.ROLE} Rolle gegeben",
                f"{after.mention} wurde eine Rolle gegeben.", COLOR_SUCCESS,
                [("Rollen", ", ".join(added), False),
                 ("Moderator", mod.mention if hasattr(mod, 'mention') else str(mod), True)],
                user=after, module="members"
            )
        if removed:
            await bot.log_action(
                guild, f"{E.ROLE} Rolle entfernt",
                f"{after.mention} wurde eine Rolle entzogen.", COLOR_DANGER,
                [("Rollen", ", ".join(removed), False),
                 ("Moderator", mod.mention if hasattr(mod, 'mention') else str(mod), True)],
                user=after, module="members"
            )

    # ── Nickname-Änderungen ─────────────────────────────────────
    if before.nick != after.nick:
        mod_nick: Any = "Selbst / Unbekannt"
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                if entry.target and entry.target.id == after.id and entry.user.id != after.id:
                    mod_nick = entry.user
                break
        except discord.Forbidden:
            pass
        await bot.log_action(
            guild, f"{E.NICK} Nickname geändert",
            f"{after.mention} hat einen neuen Nicknamen.", COLOR_INFO,
            [("Vorher", f"`{before.nick or before.name}`", True),
             ("Nachher", f"`{after.nick or after.name}`", True),
             ("Geändert von", mod_nick.mention if hasattr(mod_nick, 'mention') else str(mod_nick), True)],
            user=after, module="nicknames",
        )

# ═══════════════════════════════════════════════════════════════

    # ── Timeout (Server-Timeout) ───────────────────────────────
    before_timeout = getattr(before, 'timed_out_until', None)
    after_timeout = getattr(after, 'timed_out_until', None)

    if before_timeout != after_timeout:
        if after_timeout and (not before_timeout or after_timeout > before_timeout):
            # Timeout wurde gesetzt oder verlängert
            moderator_info = ""
            reason_info = ""
            try:
                async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.member_update):
                    if entry.target and entry.target.id == after.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 10:
                        moderator_info = f"\nDurch: **{entry.user.mention}**"
                        if entry.reason:
                            reason_info = f"\nGrund: {entry.reason}"
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

            # Dauer berechnen
            remaining = ""
            try:
                delta = after_timeout - discord.utils.utcnow()
                total_seconds = int(delta.total_seconds())
                if total_seconds > 86400:
                    remaining = f"{total_seconds // 86400}d {(total_seconds % 86400) // 3600}h"
                elif total_seconds > 3600:
                    remaining = f"{total_seconds // 3600}h {(total_seconds % 3600) // 60}m"
                elif total_seconds > 60:
                    remaining = f"{total_seconds // 60}m {total_seconds % 60}s"
                else:
                    remaining = f"{total_seconds}s"
            except Exception:
                remaining = "Unbekannt"

            await bot.log_action(
                guild, f"{E.MUTE} Timeout gesetzt",
                f"**{after.mention}** wurde **getimeoutet**.{moderator_info}{reason_info}\n"
                f"Dauer: **{remaining}**\n"
                f"Endet: <t:{int(after_timeout.timestamp())}:R>",
                COLOR_DANGER, user=after, module="moderation"
            )

            # DM an den User
            dm_embed = create_embed(
                f"{E.MUTE} Du wurdest getimeoutet",
                (
                    f"Du wurdest auf **{guild.name}** getimeoutet.\n\n"
                    f"**Dauer:** {remaining}\n"
                    f"**Endet:** <t:{int(after_timeout.timestamp())}:R>\n"
                    f"{reason_info.replace(chr(10)+'Grund: ', chr(10)+'**Grund:** ') if reason_info else ''}\n"
                    f"{moderator_info.replace(chr(10)+'Durch: ', chr(10)+'**Moderator:** ') if moderator_info else ''}"
                ),
                COLOR_DANGER,
                thumbnail=guild.icon.url if guild.icon else None
            )
            dm_embed.set_footer(text=f"{guild.name} · ModForge Security", icon_url=FOOTER_ICON)
            await safe_dm(after, dm_embed, cooldown_key=f"timeout_set:{guild.id}:{after.id}")

        elif before_timeout and (not after_timeout or after_timeout <= discord.utils.utcnow()):
            # Timeout wurde aufgehoben
            moderator_info = ""
            try:
                async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.member_update):
                    if entry.target and entry.target.id == after.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 10:
                        if entry.user.id != after.id:
                            moderator_info = f"\nDurch: **{entry.user.mention}**"
                        break
            except (discord.Forbidden, discord.HTTPException):
                pass

            await bot.log_action(
                guild, f"{E.UNMUTE} Timeout aufgehoben",
                f"**{after.mention}** wurde **aus dem Timeout entfernt**.{moderator_info}",
                COLOR_SUCCESS, user=after, module="moderation"
            )

            # DM an den User
            dm_embed = create_embed(
                f"{E.UNMUTE} Timeout aufgehoben",
                (
                    f"Dein Timeout auf **{guild.name}** wurde aufgehoben.\n"
                    f"{moderator_info.replace(chr(10)+'Durch: ', chr(10)+'**Durch:** ') if moderator_info else 'Das Timeout ist abgelaufen.'}"
                ),
                COLOR_SUCCESS,
                thumbnail=guild.icon.url if guild.icon else None
            )
            dm_embed.set_footer(text=f"{guild.name} · ModForge", icon_url=FOOTER_ICON)
            await safe_dm(after, dm_embed, cooldown_key=f"timeout_remove:{guild.id}:{after.id}")

# ANTI-NUKE EVENTS
# ═══════════════════════════════════════════════════════════════

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel) -> None:
    actor = await _audit_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
    if actor:
        await _nuke_check(channel.guild, actor.id, "Channel gelöscht")
    await bot.log_action(
        channel.guild, f"{E.CHANNEL} Channel gelöscht",
        f"**Name:** `{channel.name}` (`{channel.id}`)\n"
        f"**Typ:** `{type(channel).__name__}`\n"
        f"**Gelöscht von:** {actor.mention if actor else 'Unbekannt'}",
        COLOR_DANGER, module="channels",
    )

@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel) -> None:
    actor = await _audit_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
    if actor:
        await _nuke_check(channel.guild, actor.id, "Channel erstellt")
    await bot.log_action(
        channel.guild, f"{E.CHANNEL} Channel erstellt",
        f"**Name:** {channel.mention} (`{channel.id}`)\n"
        f"**Typ:** `{type(channel).__name__}`\n"
        f"**Erstellt von:** {actor.mention if actor else 'Unbekannt'}",
        COLOR_SUCCESS, module="channels",
    )

@bot.event
async def on_guild_channel_update(before: discord.abc.GuildChannel,
                                  after: discord.abc.GuildChannel) -> None:
    """Loggt Channel-Updates (Name, Topic, Slowmode) und Permission-Overwrite-Änderungen."""
    guild = after.guild
    actor = await _audit_actor(guild, discord.AuditLogAction.channel_update, after.id)

    diffs: List[Tuple[str, str, bool]] = []
    if getattr(before, "name", None) != getattr(after, "name", None):
        diffs.append(("Name", f"`{before.name}` → `{after.name}`", False))
    if getattr(before, "topic", None) != getattr(after, "topic", None):
        b_t = (before.topic or "")[:200]
        a_t = (after.topic or "")[:200]
        diffs.append(("Topic", f"`{b_t}` → `{a_t}`", False))
    if getattr(before, "slowmode_delay", None) != getattr(after, "slowmode_delay", None):
        diffs.append(("Slowmode", f"`{before.slowmode_delay}s` → `{after.slowmode_delay}s`", True))
    if getattr(before, "nsfw", None) != getattr(after, "nsfw", None):
        diffs.append(("NSFW", f"`{before.nsfw}` → `{after.nsfw}`", True))

    if diffs:
        await bot.log_action(
            guild, f"{E.UPDATE} Channel aktualisiert",
            f"**Channel:** {after.mention if hasattr(after, 'mention') else after.name}\n"
            f"**Geändert von:** {actor.mention if actor else 'Unbekannt'}",
            COLOR_INFO, diffs, module="channels",
        )

    # Permission-Overwrites diff
    before_ow = before.overwrites
    after_ow = after.overwrites
    if before_ow != after_ow:
        perm_actor = await _audit_actor(guild, discord.AuditLogAction.overwrite_update, after.id) or actor
        changes: List[str] = []
        all_targets = set(before_ow.keys()) | set(after_ow.keys())
        for target in all_targets:
            b = before_ow.get(target)
            a = after_ow.get(target)
            target_label = getattr(target, "mention", str(target))
            if b is None and a is not None:
                changes.append(f"{E.PLUS} Overwrite hinzugefügt für {target_label}")
            elif a is None and b is not None:
                changes.append(f"{E.MINUS} Overwrite entfernt für {target_label}")
            elif b != a:
                b_pair = b.pair() if b else (discord.Permissions.none(), discord.Permissions.none())
                a_pair = a.pair() if a else (discord.Permissions.none(), discord.Permissions.none())
                # ALLOW + DENY-Bitmasks vergleichen → geänderte Bits identifizieren
                allow_diff = b_pair[0].value ^ a_pair[0].value
                deny_diff = b_pair[1].value ^ a_pair[1].value
                changed_perms: List[str] = []
                if allow_diff or deny_diff:
                    diff_perms = discord.Permissions(allow_diff | deny_diff)
                    for perm_name, has in diff_perms:
                        if has:
                            bv = (getattr(b_pair[0], perm_name), getattr(b_pair[1], perm_name))
                            av = (getattr(a_pair[0], perm_name), getattr(a_pair[1], perm_name))
                            changed_perms.append(f"`{perm_name}`: {bv}→{av}")
                if changed_perms:
                    changes.append(f"🔧 {target_label}: " + ", ".join(changed_perms[:6]))
        if changes:
            desc = "\n".join(changes[:15])
            if len(changes) > 15:
                desc += f"\n… und {len(changes) - 15} weitere"
            await bot.log_action(
                guild, f"{E.PERMS} Permissions geändert",
                f"**Channel:** {after.mention if hasattr(after, 'mention') else after.name}\n"
                f"**Geändert von:** {perm_actor.mention if perm_actor else 'Unbekannt'}\n\n{desc}",
                COLOR_WARNING, module="permissions",
            )

@bot.event
async def on_guild_role_delete(role: discord.Role) -> None:
    actor = await _audit_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
    if actor:
        await _nuke_check(role.guild, actor.id, "Rolle gelöscht")
    await bot.log_action(
        role.guild, f"{E.ROLE_DEL} Rolle gelöscht",
        f"**Name:** `{role.name}` (`{role.id}`)\n"
        f"**Farbe:** `{role.color}`\n"
        f"**Gelöscht von:** {actor.mention if actor else 'Unbekannt'}",
        COLOR_DANGER, module="roles",
    )

@bot.event
async def on_guild_role_create(role: discord.Role) -> None:
    actor = await _audit_actor(role.guild, discord.AuditLogAction.role_create, role.id)
    if actor:
        await _nuke_check(role.guild, actor.id, "Rolle erstellt")
    await bot.log_action(
        role.guild, f"{E.ROLE_ADD} Rolle erstellt",
        f"**Name:** {role.mention} (`{role.id}`)\n"
        f"**Farbe:** `{role.color}`\n"
        f"**Erstellt von:** {actor.mention if actor else 'Unbekannt'}",
        COLOR_SUCCESS, module="roles",
    )

@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role) -> None:
    """Loggt Rollen-Updates (Name, Farbe, Permissions, Hoist, Mentionable)."""
    guild = after.guild
    actor = await _audit_actor(guild, discord.AuditLogAction.role_update, after.id)
    diffs: List[Tuple[str, str, bool]] = []
    if before.name != after.name:
        diffs.append(("Name", f"`{before.name}` → `{after.name}`", False))
    if before.color != after.color:
        diffs.append(("Farbe", f"`{before.color}` → `{after.color}`", True))
    if before.hoist != after.hoist:
        diffs.append(("Separat anzeigen", f"`{before.hoist}` → `{after.hoist}`", True))
    if before.mentionable != after.mentionable:
        diffs.append(("Erwähnbar", f"`{before.mentionable}` → `{after.mentionable}`", True))
    if before.permissions != after.permissions:
        b_perms = {p for p, v in before.permissions if v}
        a_perms = {p for p, v in after.permissions if v}
        added_p = a_perms - b_perms
        removed_p = b_perms - a_perms
        if added_p:
            diffs.append((f"{E.PLUS} Permissions hinzugefügt", "`" + "`, `".join(sorted(added_p))[:900] + "`", False))
        if removed_p:
            diffs.append((f"{E.MINUS} Permissions entfernt", "`" + "`, `".join(sorted(removed_p))[:900] + "`", False))

    if diffs:
        await bot.log_action(
            guild, f"{E.ROLE} Rolle aktualisiert",
            f"**Rolle:** {after.mention} (`{after.id}`)\n"
            f"**Geändert von:** {actor.mention if actor else 'Unbekannt'}",
            COLOR_INFO, diffs, module="roles",
        )

@bot.event
async def on_webhooks_update(channel: discord.abc.GuildChannel) -> None:
    """Loggt Webhook-Änderungen in einem Channel."""
    guild = channel.guild
    actor: Optional[discord.abc.User] = None
    for action in (discord.AuditLogAction.webhook_create,
                   discord.AuditLogAction.webhook_update,
                   discord.AuditLogAction.webhook_delete):
        actor = await _audit_actor(guild, action)
        if actor:
            action_name = action.name.replace("webhook_", "").title()
            break
    else:
        action_name = "Aktualisiert"

    await bot.log_action(
        guild, f"{E.WEBHOOK} Webhook geändert",
        f"**Channel:** {channel.mention if hasattr(channel, 'mention') else channel.name}\n"
        f"**Aktion:** `{action_name}`\n"
        f"**Verantwortlich:** {actor.mention if actor else 'Unbekannt'}",
        COLOR_WARNING, module="webhooks",
    )

@bot.event
async def on_member_ban(guild: discord.Guild, user: Union[discord.User, discord.Member]) -> None:
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            await _nuke_check(guild, entry.user.id, "Mass-Ban")
    except discord.Forbidden:
        pass

@bot.event
async def on_member_remove(member: discord.Member) -> None:
    ACTIVITY.push(
        "leave",
        f"{member} hat **{member.guild.name}** verlassen "
        f"(jetzt {member.guild.member_count} Member).",
        guild_id=member.guild.id, guild_name=member.guild.name,
        user_id=member.id, user_name=str(member),
    )
    try:
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if entry.target.id == member.id:
                await _nuke_check(member.guild, entry.user.id, "Mass-Kick")
    except discord.Forbidden:
        pass

    # ── Leave-Nachricht senden ──
    try:
        from bot.bot import _send_leave, _save_sticky_roles
        await _send_leave(member)
        await _save_sticky_roles(member)
    except Exception as ex:
        log.debug(f"Leave/Sticky-Roles Fehler: {ex}")

# ═══════════════════════════════════════════════════════════════
# EVENT: GUILD JOIN / LEAVE  (Bot wird zu Server hinzugefügt/entfernt)
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_guild_remove(guild: discord.Guild) -> None:
    log.info(f"Bot von Guild entfernt: {guild.name} ({guild.id})")
    ACTIVITY.push(
        "guild_leave",
        f"Bot von **{guild.name}** entfernt.",
        guild_id=guild.id, guild_name=guild.name,
    )
    await bot.db.arecord_guild_event(
        guild.id, guild.name, guild.member_count or 0, "leave",
    )

# ═══════════════════════════════════════════════════════════════════
# ON GUILD JOIN  —  Welcome-Embed & Guild-Event-Aufzeichnung
# ═══════════════════════════════════════════════════════════════════

@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    """Sendet beim Bot-Beitritt ein vollständiges Feature-Embed und zeichnet das Guild-Event auf.
    (Ursprünglich gab es zwei Handler – diese sind nun in EINEM zusammengeführt,
     damit BOTH arecord_guild_event UND das Welcome-Embed ausgeführt werden.)
    """
    # ── Guild-Event aufzeichnen ───────────────────────────
    log.info(f"Bot zu Guild beigetreten: {guild.name} ({guild.id}) – {guild.member_count} Member")
    ACTIVITY.push(
        "guild_join",
        f"Bot zu **{guild.name}** hinzugefügt – {guild.member_count} Member.",
        guild_id=guild.id, guild_name=guild.name,
    )
    await bot.db.arecord_guild_event(
        guild.id, guild.name, guild.member_count or 0, "join",
    )

    """Sendet beim Bot-Beitritt ein vollständiges Feature-Embed in den ersten beschreibbaren Kanal."""

    # ── Besten Kanal finden ────────────────────────────────
    target_channel = None
    # 1. System-Kanal (falls vorhanden & beschreibbar)
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        target_channel = guild.system_channel
    # 2. Ersten beschreibbaren Text-Kanal
    if not target_channel:
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages and ch.permissions_for(guild.me).embed_links:
                target_channel = ch
                break

    if not target_channel:
        log.warning(f"on_guild_join: Kein Kanal gefunden in {guild.name} ({guild.id})")
        return

    # ── Embed bauen ────────────────────────────────────────
    embed = discord.Embed(
        title="🛡️ ModForge wurde hinzugefügt!",
        description=(
            f"Hey {guild.owner.mention if guild.owner else '**Admin**'}, danke dass du "
            f"**ModForge** auf **{guild.name}** eingeladen hast! 🎉\n\n"
            f"Ich bin dein All-in-One **Security & AutoMod Bot** — "
            f"kein Stress mit 10 verschiedenen Bots.\n"
            f"Richte mich mit `/setup` ein oder öffne das **Web-Dashboard**.\n"
            f"──────────────────────────────────"
        ),
        color=COLOR_PRIMARY,
        timestamp=discord.utils.utcnow(),
    )

    # ── Thumbnail: Bot-Avatar ──────────────────────────────
    if bot.user.display_avatar:
        embed.set_thumbnail(url=bot.user.display_avatar.url)

    # ── Banner / Image ─────────────────────────────────────
    # Optional: embed.set_image(url="https://dein-banner-link.png")

    # ── SECURITY FEATURES ─────────────────────────────────
    embed.add_field(
        name="🔒 Security & Schutz",
        value=(
            "```\n"
            "🛡️  Anti-Nuke     — Massen-Bans / Kicks / Wipes\n"
            f"{E.SPEED}  Anti-Spam     — Nachrichten-, CAPS-, Emoji-Flood\n"
            "🚨  Anti-Raid     — Koordinierte Beitritts-Angriffe\n"
            "🔔  Anti-Mention  — Massen-Erwähnungen\n"
            "🎣  Anti-Scam     — Scam-Domains, Nitro-Fakes\n"
            "🌐  Anti-Shortener— Kurz-URL Erkennung\n"
            "```"
        ),
        inline=False,
    )

    # ── AUTOMOD FEATURES ──────────────────────────────────
    embed.add_field(
        name="🤖 AutoMod",
        value=(
            "```\n"
            "📝  BadWords-Filter  — Eigene Wortliste\n"
            "🔍  Regex-Filter     — Custom Patterns\n"
            "📩  Invite-Blocker   — Discord Invite Links\n"
            f"{E.ALERT}️  Zalgo-Schutz     — Zalgo / Unicode-Spam\n"
            "🎣  Phishing-Schutz  — Externe URL-Prüfung\n"
            "```"
        ),
        inline=True,
    )

    # ── MODERATION FEATURES ───────────────────────────────
    embed.add_field(
        name=f"{E.LAW}️ Moderation",
        value=(
            "```\n"
            "📋  Case-System    — IDs, Beweise, Archiv\n"
            f"{E.ALERT}️  Warn-System    — Schwellen + Auto-Punish\n"
            f"{E.OK}  Verifizierung  — One-Click oder CAPTCHA\n"
            "🎫  Tickets        — Support-Ticket-System\n"
            "🔍  Perms-Audit    — Rollen-Hierarchie Check\n"
            "🔒  Appeal-System  — Entbannungs-Anträge\n"
            "```"
        ),
        inline=True,
    )

    # ── LOGGING ───────────────────────────────────────────
    embed.add_field(
        name="📝 Logging — 26 Module",
        value=(
            "> Jedes Modul bekommt seinen **eigenen Log-Kanal**.\n"
            "> Kein Event bleibt unbemerkt.\n\n"
            "**Module:** `moderation` `anti-spam` `anti-nuke` `anti-raid`\n"
            "`automod` `anti-scam` `members` `channels` `roles`\n"
            "`permissions` `webhooks` `tickets` `verify` `cases`\n"
            "`warns` `appeal` `backup` `welcome` `audit` `+mehr`"
        ),
        inline=False,
    )

    # ── WELCOME & DASHBOARD ───────────────────────────────
    embed.add_field(
        name="👋 Welcome & Leave",
        value=(
            "> Vollständiger **Embed-Builder** im Dashboard.\n"
            "> Eigene Bilder, Texte, Rollen-Vergabe."
        ),
        inline=True,
    )

    embed.add_field(
        name="📊 Web-Dashboard",
        value=(
            "> Alle Module grafisch konfigurieren.\n"
            "> **Discord OAuth2** Login · Live-Charts."
        ),
        inline=True,
    )

    # ── COMMANDS OVERVIEW ─────────────────────────────────
    embed.add_field(
        name="⌨️ Über 40 Commands · Slash & Prefix",
        value=(
            "`/ban` `/tempban` `/kick` `/warn` `/mute` `/unmute`\n"
            "`/case` `/cases` `/warnlist` `/clearwarn` `/massban`\n"
            "`/audit-perms` `/security view` `/setup` `/whitelist`\n"
            "`/logsetup` `/warnsetup` `/backupsetup` `/forcereset`\n"
            "`/ticket-setup` `/verify-setup` `/setup_tempvoice`
            `/logban` `/help`"
        ),
        inline=False,
    )

    # ── QUICK START ───────────────────────────────────────
    embed.add_field(
        name="🚀 Quick-Start",
        value=(
            "**1.** Gib mir die Rolle **`Administrator`** oder alle nötigen Perms\n"
            "**2.** Tippe `/setup` — interaktives Setup-Panel\n"
            "**3.** Konfiguriere deine Module im **Web-Dashboard**\n"
            "**4.** Setze deine Log-Kanäle mit `/logsetup`\n\n"
            f"**Fertig in unter 2 Minuten! {E.SPEED}**"
        ),
        inline=False,
    )

    # ── LINKS ─────────────────────────────────────────────
    embed.add_field(
        name="🔗 Links",
        value=(
            "🌐 **[Dashboard öffnen](https://mod-forge.up.railway.app/login)**"
            "　・　"
            f"{E.TEXT} **[Support Server](https://discord.gg/gwryX3dbkt)**"
            "　・　"
            f"{E.FILE} **[Terms of Service](https://mod-forge.up.railway.app/terms)**"
        ),
        inline=False,
    )

    # ── FOOTER ────────────────────────────────────────────
    embed.set_footer(
        text=f"{FOOTER_TEXT}  ·  Server-ID: {guild.id}  ·  v3.0.0",
        icon_url=FOOTER_ICON if FOOTER_ICON else (bot.user.display_avatar.url if bot.user.display_avatar else None),
    )

    # ── Senden ────────────────────────────────────────────
    try:
        await target_channel.send(
            content=f"👋 Hey {guild.owner.mention if guild.owner else ''}! Danke für die Einladung.",
            embed=embed,
        )
        log.info(f"on_guild_join: Welcome-Embed gesendet in #{target_channel.name} ({guild.name})")
    except discord.Forbidden:
        log.warning(f"on_guild_join: Keine Rechte in #{target_channel.name} ({guild.name})")
    except discord.HTTPException as ex:
        log.error(f"on_guild_join: HTTP-Fehler: {ex}")

# ═══════════════════════════════════════════════════════════════
# PREFIX COMMANDS
# ═══════════════════════════════════════════════════════════════
def has_mod_perms() -> Callable:
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.guild_permissions.manage_messages:
            return True
        cfg = bot.db.get_config(ctx.guild.id)
        mod_role_id = cfg.get("mod_role")
        if mod_role_id:
            return any(r.id == int(mod_role_id) for r in ctx.author.roles)
        return False
    return commands.check(predicate)

def has_admin_perms() -> Callable:
    async def predicate(ctx: commands.Context) -> bool:
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

@bot.command(name="ban")
@has_mod_perms()
async def prefix_ban(ctx: commands.Context, member: discord.Member, *,
                     reason: str = "Kein Grund angegeben") -> None:
    ok, why = can_moderate(ctx.author, member, ctx.guild.me)
    if not ok:
        await ctx.send(embed=create_embed(f"{E.FAIL} Aktion blockiert", why, COLOR_DANGER))
        return
    try:
        await member.ban(reason=f"{ctx.author}: {reason}")
    except discord.Forbidden:
        await ctx.send(embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER))
        return
    embed = create_embed(f"{E.BAN} Gebannt", f"{member.mention} wurde gebannt.", COLOR_DANGER,
                         [("Grund", reason, False), ("Moderator", ctx.author.mention, True)])
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.BAN} Ban", f"{member.mention} wurde gebannt.", COLOR_DANGER,
                         [("Grund", reason, False), ("Moderator", ctx.author.mention, True)],
                         user=member, module="moderation")

@bot.command(name="kick")
@has_mod_perms()
async def prefix_kick(ctx: commands.Context, member: discord.Member, *,
                      reason: str = "Kein Grund angegeben") -> None:
    ok, why = can_moderate(ctx.author, member, ctx.guild.me)
    if not ok:
        await ctx.send(embed=create_embed(f"{E.FAIL} Aktion blockiert", why, COLOR_DANGER))
        return
    try:
        await member.kick(reason=f"{ctx.author}: {reason}")
    except discord.Forbidden:
        await ctx.send(embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER))
        return
    embed = create_embed(f"{E.KICK} Gekickt", f"{member.mention} wurde gekickt.", COLOR_WARNING,
                         [("Grund", reason, False), ("Moderator", ctx.author.mention, True)])
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.KICK} Kick", f"{member.mention} wurde gekickt.",
                         COLOR_WARNING,
                         [("Grund", reason, False), ("Moderator", ctx.author.mention, True)],
                         user=member, module="moderation")

@bot.command(name="warn")
@has_mod_perms()
async def prefix_warn(ctx: commands.Context, member: discord.Member, *,
                      reason: str = "Kein Grund angegeben") -> None:
    count = await bot.db.aadd_warning(ctx.guild.id, member.id, reason, ctx.author.id)
    await bot._check_warn_thresholds(member, count)
    embed = create_embed(f"{E.WARN} Verwarnt", f"{member.mention} wurde verwarnt.", COLOR_WARNING,
                         [("Grund", reason, False),
                          ("Verwarnungen gesamt", str(count), True),
                          ("Moderator", ctx.author.mention, True)])
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.WARN} Warn",
                         f"{member.mention} verwarnt von {ctx.author.mention}.",
                         COLOR_WARNING,
                         [("Grund", reason, False), ("Total", str(count), True)],
                         user=member, module="moderation")

@bot.command(name="mute")
@has_mod_perms()
async def prefix_mute(ctx: commands.Context, member: discord.Member, duration: int = 60, *,
                      reason: str = "Kein Grund") -> None:
    ok, why = can_moderate(ctx.author, member, ctx.guild.me)
    if not ok:
        await ctx.send(embed=create_embed(f"{E.FAIL} Aktion blockiert", why, COLOR_DANGER))
        return
    until = discord.utils.utcnow() + datetime.timedelta(seconds=duration)
    try:
        await member.timeout(until, reason=f"{ctx.author}: {reason}")
    except discord.Forbidden:
        await ctx.send(embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER))
        return
    await bot.db.aadd_mute(ctx.guild.id, member.id, reason, ctx.author.id, duration)
    embed = create_embed(f"{E.MUTE} Gemutet", f"{member.mention} wurde für {duration}s gemutet.",
                         COLOR_WARNING,
                         [("Grund", reason, False), ("Dauer", f"{duration}s", True)])
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.MUTE} Mute",
                         f"{member.mention} gemutet von {ctx.author.mention}",
                         COLOR_WARNING,
                         [("Grund", reason, False), ("Dauer", f"{duration}s", True)],
                         user=member, module="moderation")

@bot.command(name="unmute")
@has_mod_perms()
async def prefix_unmute(ctx: commands.Context, member: discord.Member) -> None:
    try:
        await member.timeout(None, reason=f"Unmute durch {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER))
        return
    await bot.db.adeactivate_mute(ctx.guild.id, member.id)
    embed = create_embed(f"{E.UNMUTE} Entmutet", f"{member.mention} wurde entmutet.", COLOR_SUCCESS)
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.UNMUTE} Unmute",
                         f"{member.mention} entmutet von {ctx.author.mention}",
                         COLOR_SUCCESS, user=member, module="moderation")

@bot.command(name="clear")
@has_mod_perms()
async def prefix_clear(ctx: commands.Context, amount: int = 10) -> None:
    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
    except discord.Forbidden:
        await ctx.send(embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER))
        return
    embed = create_embed(f"{E.DELETE} Nachrichten gelöscht",
                         f"**{len(deleted) - 1}** Nachrichten wurden gelöscht.", COLOR_SUCCESS)
    msg = await ctx.send(embed=embed)
    await asyncio.sleep(3)
    try:
        await msg.delete()
    except discord.NotFound:
        pass
    await bot.log_action(ctx.guild, f"{E.DELETE} Clear",
                         f"{ctx.author.mention} hat {len(deleted) - 1} Nachrichten in {ctx.channel.mention} gelöscht.",
                         COLOR_INFO, user=ctx.author, module="moderation")

@bot.command(name="slowmode")
@has_mod_perms()
async def prefix_slowmode(ctx: commands.Context, seconds: int = 0) -> None:
    try:
        await ctx.channel.edit(slowmode_delay=seconds, reason=f"Slowmode durch {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER))
        return
    embed = create_embed(f"{E.SLOW} Slowmode",
                         f"Slowmode auf **{seconds}s** gesetzt." if seconds > 0 else "Slowmode deaktiviert.",
                         COLOR_INFO)
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.SLOW} Slowmode",
                         f"{ctx.author.mention} hat Slowmode in {ctx.channel.mention} auf {seconds}s gesetzt.",
                         COLOR_INFO, user=ctx.author, module="moderation")

@bot.command(name="lock")
@has_mod_perms()
async def prefix_lock(ctx: commands.Context) -> None:
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False,
                                          reason=f"Lock durch {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER))
        return
    embed = create_embed(f"{E.LOCK} Kanal gesperrt", f"{ctx.channel.mention} wurde gesperrt.", COLOR_DANGER)
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.LOCK} Lock",
                         f"{ctx.channel.mention} gesperrt von {ctx.author.mention}",
                         COLOR_DANGER, user=ctx.author, module="moderation")

@bot.command(name="unlock")
@has_mod_perms()
async def prefix_unlock(ctx: commands.Context) -> None:
    try:
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None,
                                          reason=f"Unlock durch {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER))
        return
    embed = create_embed(f"{E.UNLOCK} Kanal entsperrt", f"{ctx.channel.mention} wurde entsperrt.", COLOR_SUCCESS)
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.UNLOCK} Unlock",
                         f"{ctx.channel.mention} entsperrt von {ctx.author.mention}",
                         COLOR_SUCCESS, user=ctx.author, module="moderation")

@bot.command(name="warnings")
@has_mod_perms()
async def prefix_warnings(ctx: commands.Context, member: discord.Member) -> None:
    warns = await bot.db.aget_warnings(ctx.guild.id, member.id)
    if not warns:
        embed = create_embed(f"{E.CHANNEL} Verwarnungen",
                             f"{member.mention} hat keine Verwarnungen.", COLOR_SUCCESS)
    else:
        fields = []
        for i, w in enumerate(warns):
            ts = w.get("timestamp")
            if isinstance(ts, datetime.datetime):
                ts_text = f"<t:{int(ts.timestamp())}:R>"
            else:
                ts_text = str(ts)
            fields.append((f"#{i} – {w['reason'][:80]}", f"{ts_text} • Mod: <@{w.get('mod_id', '?')}>", False))
        embed = create_embed(f"{E.CHANNEL} Verwarnungen – {member.display_name}",
                             f"**{len(warns)}** Verwarnungen insgesamt.", COLOR_WARNING,
                             fields, thumbnail=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(name="clearwarnings")
@has_mod_perms()
async def prefix_clearwarnings(ctx: commands.Context, member: discord.Member) -> None:
    deleted = await bot.db.aclear_warnings(ctx.guild.id, member.id)
    embed = create_embed(f"{E.DELETE} Verwarnungen gelöscht",
                         f"**{deleted}** Verwarnungen von {member.mention} wurden gelöscht.",
                         COLOR_SUCCESS)
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.DELETE} Clear-Warnings",
                         f"{ctx.author.mention} hat {deleted} Verwarnungen von {member.mention} gelöscht.",
                         COLOR_INFO, user=member, module="moderation")

@bot.command(name="unban")
@has_mod_perms()
async def prefix_unban(ctx: commands.Context, user_id: int) -> None:
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=f"Unban durch {ctx.author}")
    except discord.NotFound:
        await ctx.send(embed=create_embed(f"{E.FAIL} Nicht gefunden",
                                          "Nutzer/Ban nicht gefunden.", COLOR_DANGER))
        return
    except discord.Forbidden:
        await ctx.send(embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER))
        return
    embed = create_embed(f"{E.OK} Entbannt", f"**{user}** wurde entbannt.", COLOR_SUCCESS)
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.OK} Unban",
                         f"{user} entbannt von {ctx.author.mention}",
                         COLOR_SUCCESS, module="moderation")

@bot.command(name="nick")
@has_mod_perms()
async def prefix_nick(ctx: commands.Context, member: discord.Member, *, nickname: str = None) -> None:
    try:
        await member.edit(nick=nickname, reason=f"Nick durch {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER))
        return
    embed = create_embed(f"{E.NICK} Nickname geändert",
                         f"Nickname von {member.mention} auf **{nickname or 'Standard'}** gesetzt.",
                         COLOR_INFO)
    await ctx.send(embed=embed)
    await bot.log_action(ctx.guild, f"{E.NICK} Nick",
                         f"{member.mention} → **{nickname or 'Standard'}** durch {ctx.author.mention}",
                         COLOR_INFO, user=member, module="moderation")

@bot.command(name="role")
@has_mod_perms()
async def prefix_role(ctx: commands.Context, action: str, member: discord.Member,
                      role: discord.Role) -> None:
    try:
        if action.lower() == "add":
            await member.add_roles(role, reason=f"Role-Add durch {ctx.author}")
            embed = create_embed(f"{E.ROLE_ADD} Rolle hinzugefügt",
                                 f"{role.mention} wurde {member.mention} gegeben.", COLOR_SUCCESS)
        elif action.lower() == "remove":
            await member.remove_roles(role, reason=f"Role-Remove durch {ctx.author}")
            embed = create_embed(f"{E.ROLE_DEL} Rolle entfernt",
                                 f"{role.mention} wurde {member.mention} entfernt.", COLOR_WARNING)
        else:
            embed = create_embed(f"{E.FAIL} Fehler", "Nutze `add` oder `remove`.", COLOR_DANGER)
    except discord.Forbidden:
        embed = create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER)
    await ctx.send(embed=embed)

# ─────────────────────────────────────────────────────────────────
# APPEAL COMMAND (PREFIX)
# ─────────────────────────────────────────────────────────────────
@bot.command(name="banappeal")
@commands.has_permissions(ban_members=True)
async def cmd_banappeal(ctx: commands.Context, user_id: int, *,
                        ban_reason: str = "Kein Grund angegeben") -> None:
    cfg = bot.db.get_config(ctx.guild.id)
    if not cfg.get("appeal_log_channel"):
        await ctx.send(embed=create_embed(f"{E.ALERT}️ Kein Appeal-Kanal gesetzt",
                                          "Bitte zuerst mit `/logban #kanal` einen Appeal-Kanal setzen!",
                                          COLOR_WARNING))
        return

    try:
        user = await bot.fetch_user(user_id)
    except discord.NotFound:
        await ctx.send(embed=create_embed(f"{E.FAIL} Nutzer nicht gefunden",
                                          f"Kein Nutzer mit ID `{user_id}` gefunden.",
                                          COLOR_DANGER))
        return

    try:
        await ctx.guild.fetch_ban(discord.Object(id=user_id))
    except discord.NotFound:
        await ctx.send(embed=create_embed(f"{E.FAIL} Nutzer nicht gebannt",
                                          f"**{user}** ist auf diesem Server nicht gebannt.",
                                          COLOR_DANGER))
        return

    appeal_sessions[user_id] = {
        "guild_id": ctx.guild.id,
        "step": -1,
        "answers": {},
        "ban_reason": ban_reason
    }

    try:
        embed_dm = create_embed(
            f"{E.LAW}️ Entbannungs-Antrag möglich",
            (f"Du wurdest vom Server **{ctx.guild.name}** gebannt.\n\n"
             f"**Ban-Grund:** {ban_reason}\n\n"
             "Das Moderationsteam gibt dir die Möglichkeit, einen **Entbannungs-Antrag** zu stellen.\n\n"
             "Wenn du einen Antrag stellen möchtest, schreibe `!start`.\n"
             "Wenn du keinen Antrag stellen möchtest, ignoriere diese Nachricht.\n\n"),
            COLOR_PRIMARY,
            thumbnail=ctx.guild.icon.url if ctx.guild.icon else None
        )
        await user.send(embed=embed_dm)

        embed_confirm = create_embed(f"{E.OK} Appeal-DM gesendet",
                                     f"**{user}** (`{user_id}`) hat eine Appeal-DM erhalten.",
                                     COLOR_SUCCESS,
                                     fields=[("Ban-Grund", ban_reason, False),
                                             ("Appeal-Kanal", f"<#{cfg['appeal_log_channel']}>", True)],
                                     thumbnail=user.display_avatar.url)
        await ctx.send(embed=embed_confirm)

    except discord.Forbidden:
        appeal_sessions.pop(user_id, None)
        await ctx.send(embed=create_embed(f"{E.FAIL} DM nicht möglich",
                                          f"**{user}** hat DMs deaktiviert oder hat den Bot blockiert.",
                                          COLOR_DANGER))

# ═══════════════════════════════════════════════════════════════
# SLASH COMMANDS – Verifizierung & Tickets
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="setup_verify", description="Richtet das Verifizierungssystem ein")
@app_commands.describe(channel="Kanal für die Nachricht", mode="Modus (One-Click oder Captcha)",
                       difficulty="Captcha-Stärke")
@app_commands.choices(
    mode=[app_commands.Choice(name="One-Click", value="one_click"),
          app_commands.Choice(name="Captcha", value="captcha")],
    difficulty=[app_commands.Choice(name="Leicht", value="easy"),
                app_commands.Choice(name="Mittel", value="medium"),
                app_commands.Choice(name="Schwer", value="hard")])
@app_commands.default_permissions(administrator=True)
async def setup_verify(interaction: discord.Interaction, channel: discord.TextChannel,
                       mode: str, difficulty: str = "medium") -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    cfg["verify_system"].update({"enabled": True, "mode": mode, "verify_channel": channel.id,
                                 "captcha_difficulty": difficulty})
    await bot.db.set_config(interaction.guild.id, cfg)

    embed = create_embed(f"{E.SHIELD} Verifizierung erforderlich",
                         "Klicke auf den Button unten, um Zugriff auf den Server zu erhalten.",
                         COLOR_PRIMARY)
    embed.set_image(url=VERIFY_BANNER_URL)
    msg = await channel.send(embed=embed, view=VerifyView(bot))
    cfg["verify_system"]["message_id"] = msg.id
    await bot.db.set_config(interaction.guild.id, cfg)
    await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description=f"{E.OK} Verifizierung in {channel.mention} eingerichtet!", color=COLOR_SUCCESS), ephemeral=True)

@bot.tree.command(name="verify_roles", description="Stellt die Rollen für die Verifizierung ein")
@app_commands.describe(add_role="Rolle die gegeben wird", remove_role="Rolle die entfernt wird")
@app_commands.default_permissions(administrator=True)
async def verify_roles(interaction: discord.Interaction,
                       add_role: Optional[discord.Role] = None,
                       remove_role: Optional[discord.Role] = None) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    if add_role:
        cfg["verify_system"]["add_roles"] = [add_role.id]
    if remove_role:
        cfg["verify_system"]["remove_roles"] = [remove_role.id]
    await bot.db.set_config(interaction.guild.id, cfg)
    await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description=f"{E.OK} Verifizierungs-Rollen aktualisiert!", color=COLOR_SUCCESS), ephemeral=True)

@bot.tree.command(name="setup_tickets", description="Richtet das Ticket-System ein")
@app_commands.describe(category="Kategorie für Tickets", log_channel="Kanal für Ticket-Logs")
@app_commands.default_permissions(administrator=True)
async def setup_tickets(interaction: discord.Interaction,
                        category: discord.CategoryChannel,
                        log_channel: discord.TextChannel) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    cfg["ticket_system"].update({"enabled": True, "category_id": category.id,
                                 "log_channel_id": log_channel.id})
    embed = create_embed(f"{E.TICKETBOX} Support Tickets",
                         "Klicke auf den Button unten, um ein privates Support-Ticket zu eröffnen.",
                         COLOR_INFO)
    msg = await interaction.channel.send(embed=embed, view=TicketView(bot))
    cfg["ticket_system"]["ticket_message_id"] = msg.id
    await bot.db.set_config(interaction.guild.id, cfg)
    await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description=f"{E.OK} Ticket-System eingerichtet!", color=COLOR_SUCCESS), ephemeral=True)

# ├────────────────────────────────────────────────────────────────
# SLASH COMMANDS – Moderation
# ├────────────────────────────────────────────────────────────────
@bot.tree.command(name="ban", description="Bannt einen Nutzer vom Server")
@app_commands.describe(member="Der zu bannende Nutzer", reason="Grund für den Ban")
@app_commands.default_permissions(ban_members=True)
async def slash_ban(interaction: discord.Interaction, member: discord.Member,
                    reason: str = "Kein Grund") -> None:
    ok, why = can_moderate(interaction.user, member, interaction.guild.me)
    if not ok:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Aktion blockiert", why, COLOR_DANGER), ephemeral=True)
        return
    # Pre-Ban Snapshot SAMMELN, bevor der Ban läuft
    pre_msgs = await bot.db.aget_user_messages(interaction.guild.id, member.id, hours=48, limit=500)
    try:
        await member.ban(reason=f"{interaction.user}: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    case_id = await bot.db.acreate_case(
        interaction.guild.id, member.id, interaction.user.id, "ban", reason, duration=None,
    )
    if pre_msgs:
        serializable = [
            {"channel_id": m.get("channel_id"), "message_id": m.get("message_id"),
             "content": m.get("content", ""), "attachments": m.get("attachments", []),
             "deleted": bool(m.get("deleted")), "edits": m.get("edits", []),
             "timestamp": (m.get("timestamp") or discord.utils.utcnow()).isoformat() + "Z"}
            for m in pre_msgs
        ]
        await bot.db.aattach_messages_to_case(interaction.guild.id, case_id, serializable)
    ACTIVITY.push("case", f"Case #{case_id} (ban) – {member} via /ban",
                  guild_id=interaction.guild.id, guild_name=interaction.guild.name,
                  user_id=interaction.user.id, user_name=str(interaction.user))
    embed = create_embed(f"{E.BAN} Gebannt – Case #{case_id}",
                         f"{member.mention} wurde gebannt.", COLOR_DANGER,
                         [("Grund", reason, False),
                          ("Moderator", interaction.user.mention, True),
                          ("Case-ID", f"`{case_id}`", True),
                          ("Archivierte Nachrichten", str(len(pre_msgs)), True)],
                         thumbnail=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.BAN} Ban – Case #{case_id}",
                         f"{member.mention} wurde gebannt.", COLOR_DANGER,
                         [("Grund", reason, False), ("Moderator", interaction.user.mention, True),
                          ("Case-ID", f"`{case_id}` – `/case {case_id}`", True),
                          ("Archiv", f"{len(pre_msgs)} Nachrichten", True)],
                         user=member, module="moderation")

@bot.tree.command(name="tempban", description="Bannt einen Nutzer temporär")
@app_commands.describe(member="Der zu bannende Nutzer",
                       duration="Dauer (z.B. 30m, 2h, 7d)",
                       reason="Grund")
@app_commands.default_permissions(ban_members=True)
async def slash_tempban(interaction: discord.Interaction, member: discord.Member,
                        duration: str, reason: str = "Kein Grund") -> None:
    ok, why = can_moderate(interaction.user, member, interaction.guild.me)
    if not ok:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Aktion blockiert", why, COLOR_DANGER), ephemeral=True)
        return
    seconds = parse_duration(duration)
    if not seconds or seconds < 60:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Ungültige Dauer",
                               "Format: `30m`, `2h`, `7d` (mind. 60s)", COLOR_DANGER),
            ephemeral=True)
        return
    end = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
    pre_msgs = await bot.db.aget_user_messages(interaction.guild.id, member.id, hours=48, limit=500)
    try:
        await member.ban(reason=f"Tempban {duration} – {interaction.user}: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    await bot.db.aadd_tempaction("tempban", interaction.guild.id, member.id, end, reason, interaction.user.id)
    case_id = await bot.create_mod_case(
        interaction.guild, member, interaction.user, "tempban", reason, duration=seconds,
    )
    if pre_msgs:
        serializable = [
            {"channel_id": m.get("channel_id"), "message_id": m.get("message_id"),
             "content": m.get("content", ""), "attachments": m.get("attachments", []),
             "deleted": bool(m.get("deleted")), "edits": m.get("edits", []),
             "timestamp": (m.get("timestamp") or discord.utils.utcnow()).isoformat() + "Z"}
            for m in pre_msgs
        ]
        await bot.db.aattach_messages_to_case(interaction.guild.id, case_id, serializable)
    embed = create_embed(f"{E.BAN} Tempban – Case #{case_id}",
                         f"{member.mention} wurde für **{duration}** gebannt.",
                         COLOR_DANGER,
                         [("Grund", reason, False),
                          ("Endet", f"<t:{int(end.timestamp())}:R>", True),
                          ("Moderator", interaction.user.mention, True),
                          ("Case-ID", f"`{case_id}`", True)])
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.BAN} Tempban – Case #{case_id}",
                         f"{member.mention} – Tempban {duration}", COLOR_DANGER,
                         [("Grund", reason, False),
                          ("Endet", f"<t:{int(end.timestamp())}:R>", True),
                          ("Moderator", interaction.user.mention, True),
                          ("Case-ID", f"`{case_id}` – `/case {case_id}`", True)],
                         user=member, module="moderation")

@bot.tree.command(name="tempmute", description="Persistenter Timeout (überlebt Neustart)")
@app_commands.describe(member="Nutzer", duration="Dauer (z.B. 30m, 2h)", reason="Grund")
@app_commands.default_permissions(moderate_members=True)
async def slash_tempmute(interaction: discord.Interaction, member: discord.Member,
                         duration: str, reason: str = "Kein Grund") -> None:
    ok, why = can_moderate(interaction.user, member, interaction.guild.me)
    if not ok:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Aktion blockiert", why, COLOR_DANGER), ephemeral=True)
        return
    seconds = parse_duration(duration)
    if not seconds or seconds < 1 or seconds > 60 * 60 * 24 * 28:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Ungültige Dauer",
                               "Format: `30m`, `2h`, `7d` (max 28d)", COLOR_DANGER),
            ephemeral=True)
        return
    end = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
    try:
        await member.timeout(end, reason=f"Tempmute {duration} – {interaction.user}: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    await bot.db.aadd_mute(interaction.guild.id, member.id, reason, interaction.user.id, seconds)
    await bot.db.aadd_tempaction("tempmute", interaction.guild.id, member.id, end, reason, interaction.user.id)
    case_id = await bot.create_mod_case(
        interaction.guild, member, interaction.user, "tempmute", reason, duration=seconds,
    )
    embed = create_embed(f"{E.MUTE} Tempmute – Case #{case_id}",
                         f"{member.mention} ist für **{duration}** gemutet.",
                         COLOR_WARNING,
                         [("Grund", reason, False),
                          ("Endet", f"<t:{int(end.timestamp())}:R>", True),
                          ("Case-ID", f"`{case_id}`", True)])
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.MUTE} Tempmute – Case #{case_id}",
                         f"{member.mention} ({duration})", COLOR_WARNING,
                         [("Grund", reason, False),
                          ("Endet", f"<t:{int(end.timestamp())}:R>", True),
                          ("Moderator", interaction.user.mention, True),
                          ("Case-ID", f"`{case_id}` – `/case {case_id}`", True)],
                         user=member, module="moderation")

@bot.tree.command(name="kick", description="Kickt einen Nutzer vom Server")
@app_commands.describe(member="Der zu kickende Nutzer", reason="Grund")
@app_commands.default_permissions(kick_members=True)
async def slash_kick(interaction: discord.Interaction, member: discord.Member,
                     reason: str = "Kein Grund") -> None:
    ok, why = can_moderate(interaction.user, member, interaction.guild.me)
    if not ok:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Aktion blockiert", why, COLOR_DANGER), ephemeral=True)
        return
    try:
        await member.kick(reason=f"{interaction.user}: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    case_id = await bot.create_mod_case(
        interaction.guild, member, interaction.user, "kick", reason,
    )
    embed = create_embed(f"{E.KICK} Gekickt – Case #{case_id}",
                         f"{member.mention} wurde gekickt.", COLOR_WARNING,
                         [("Grund", reason, False),
                          ("Moderator", interaction.user.mention, True),
                          ("Case-ID", f"`{case_id}`", True)])
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.KICK} Kick – Case #{case_id}",
                         f"{member.mention} gekickt von {interaction.user.mention}",
                         COLOR_WARNING,
                         [("Grund", reason, False),
                          ("Moderator", interaction.user.mention, True),
                          ("Case-ID", f"`{case_id}` – `/case {case_id}`", True)],
                         user=member, module="moderation")

@bot.tree.command(name="warn", description="Verwarnt einen Nutzer")
@app_commands.describe(member="Der zu verwarnende Nutzer", reason="Grund")
@app_commands.default_permissions(manage_messages=True)
async def slash_warn(interaction: discord.Interaction, member: discord.Member,
                     reason: str = "Kein Grund") -> None:
    count = await bot.db.aadd_warning(interaction.guild.id, member.id, reason, interaction.user.id)
    case_id = await bot.create_mod_case(
        interaction.guild, member, interaction.user, "warn", reason,
    )
    await bot._check_warn_thresholds(member, count)
    embed = create_embed(f"{E.WARN} Verwarnt – Case #{case_id}",
                         f"{member.mention} wurde verwarnt.", COLOR_WARNING,
                         [("Grund", reason, False),
                          ("Verwarnungen", str(count), True),
                          ("Moderator", interaction.user.mention, True),
                          ("Case-ID", f"`{case_id}`", True)],
                         thumbnail=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.WARN} Warn – Case #{case_id}",
                         f"{member.mention} verwarnt von {interaction.user.mention}",
                         COLOR_WARNING,
                         [("Grund", reason, False), ("Total", str(count), True),
                          ("Case-ID", f"`{case_id}` – `/case {case_id}`", True)],
                         user=member, module="moderation")

@bot.tree.command(name="mute", description="Mutet einen Nutzer (Timeout)")
@app_commands.describe(member="Nutzer", duration="Dauer in Sekunden", reason="Grund")
@app_commands.default_permissions(moderate_members=True)
async def slash_mute(interaction: discord.Interaction, member: discord.Member,
                     duration: int = 60, reason: str = "Kein Grund") -> None:
    ok, why = can_moderate(interaction.user, member, interaction.guild.me)
    if not ok:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Aktion blockiert", why, COLOR_DANGER), ephemeral=True)
        return
    until = discord.utils.utcnow() + datetime.timedelta(seconds=duration)
    try:
        await member.timeout(until, reason=f"{interaction.user}: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    await bot.db.aadd_mute(interaction.guild.id, member.id, reason, interaction.user.id, duration)
    case_id = await bot.create_mod_case(
        interaction.guild, member, interaction.user, "mute", reason, duration=duration,
    )
    embed = create_embed(f"{E.MUTE} Gemutet – Case #{case_id}",
                         f"{member.mention} wurde für {duration}s gemutet.", COLOR_WARNING,
                         [("Grund", reason, False), ("Dauer", f"{duration}s", True),
                          ("Case-ID", f"`{case_id}`", True)])
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.MUTE} Mute – Case #{case_id}",
                         f"{member.mention} gemutet von {interaction.user.mention}",
                         COLOR_WARNING,
                         [("Grund", reason, False), ("Dauer", f"{duration}s", True),
                          ("Case-ID", f"`{case_id}` – `/case {case_id}`", True)],
                         user=member, module="moderation")

@bot.tree.command(name="unmute", description="Entmutet einen Nutzer")
@app_commands.describe(member="Nutzer")
@app_commands.default_permissions(moderate_members=True)
async def slash_unmute(interaction: discord.Interaction, member: discord.Member) -> None:
    try:
        await member.timeout(None, reason=f"Unmute durch {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    await bot.db.adeactivate_mute(interaction.guild.id, member.id)
    embed = create_embed(f"{E.UNMUTE} Entmutet", f"{member.mention} wurde entmutet.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.UNMUTE} Unmute",
                         f"{member.mention} entmutet von {interaction.user.mention}",
                         COLOR_SUCCESS, user=member, module="moderation")

@bot.tree.command(name="clear", description="Löscht Nachrichten im Kanal")
@app_commands.describe(amount="Anzahl der zu löschenden Nachrichten")
@app_commands.default_permissions(manage_messages=True)
async def slash_clear(interaction: discord.Interaction, amount: int = 10) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await interaction.channel.purge(limit=amount)
    except discord.Forbidden:
        await interaction.followup.send(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    embed = create_embed(f"{E.DELETE} Gelöscht",
                         f"**{len(deleted)}** Nachrichten gelöscht.", COLOR_SUCCESS)
    await interaction.followup.send(embed=embed, ephemeral=True)
    await bot.log_action(interaction.guild, f"{E.DELETE} Clear",
                         f"{interaction.user.mention} hat {len(deleted)} Nachrichten in {interaction.channel.mention} gelöscht.",
                         COLOR_INFO, user=interaction.user, module="moderation")

@bot.tree.command(name="slowmode", description="Setzt den Slowmode im Kanal")
@app_commands.describe(seconds="Sekunden (0 = deaktiviert)")
@app_commands.default_permissions(manage_channels=True)
async def slash_slowmode(interaction: discord.Interaction, seconds: int = 0) -> None:
    try:
        await interaction.channel.edit(slowmode_delay=seconds, reason=f"Slowmode durch {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    embed = create_embed(f"{E.SLOW} Slowmode",
                         f"Slowmode auf **{seconds}s** gesetzt." if seconds > 0 else "Slowmode deaktiviert.",
                         COLOR_INFO)
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.SLOW} Slowmode",
                         f"{interaction.user.mention} setzte Slowmode in {interaction.channel.mention} auf {seconds}s.",
                         COLOR_INFO, user=interaction.user, module="moderation")

@bot.tree.command(name="lock", description="Sperrt den aktuellen Kanal")
@app_commands.default_permissions(manage_channels=True)
async def slash_lock(interaction: discord.Interaction) -> None:
    try:
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False,
                                                  reason=f"Lock durch {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    embed = create_embed(f"{E.LOCK} Gesperrt",
                         f"{interaction.channel.mention} wurde gesperrt.", COLOR_DANGER)
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.LOCK} Lock",
                         f"{interaction.channel.mention} gesperrt von {interaction.user.mention}",
                         COLOR_DANGER, user=interaction.user, module="moderation")

@bot.tree.command(name="unlock", description="Entsperrt den aktuellen Kanal")
@app_commands.default_permissions(manage_channels=True)
async def slash_unlock(interaction: discord.Interaction) -> None:
    try:
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None,
                                                  reason=f"Unlock durch {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    embed = create_embed(f"{E.UNLOCK} Entsperrt",
                         f"{interaction.channel.mention} wurde entsperrt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.UNLOCK} Unlock",
                         f"{interaction.channel.mention} entsperrt von {interaction.user.mention}",
                         COLOR_SUCCESS, user=interaction.user, module="moderation")

@bot.tree.command(name="unban", description="Entbannt einen Nutzer")
@app_commands.describe(user_id="Die Discord-ID des Nutzers")
@app_commands.default_permissions(ban_members=True)
async def slash_unban(interaction: discord.Interaction, user_id: str) -> None:
    try:
        uid = int(user_id)
        user = await bot.fetch_user(uid)
        await interaction.guild.unban(user, reason=f"Unban durch {interaction.user}")
    except ValueError:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Ungültige ID", "Bitte eine Zahl angeben.", COLOR_DANGER),
            ephemeral=True)
        return
    except discord.NotFound:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Nicht gefunden", "Nutzer/Ban nicht gefunden.", COLOR_DANGER),
            ephemeral=True)
        return
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    embed = create_embed(f"{E.OK} Entbannt", f"**{user}** wurde entbannt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.OK} Unban",
                         f"{user} entbannt von {interaction.user.mention}",
                         COLOR_SUCCESS, module="moderation")

@bot.tree.command(name="warnings", description="Zeigt Verwarnungen eines Nutzers")
@app_commands.describe(member="Nutzer")
@app_commands.default_permissions(manage_messages=True)
async def slash_warnings(interaction: discord.Interaction, member: discord.Member) -> None:
    warns = await bot.db.aget_warnings(interaction.guild.id, member.id)
    if not warns:
        embed = create_embed(f"{E.CHANNEL} Verwarnungen",
                             f"{member.mention} hat keine Verwarnungen.", COLOR_SUCCESS)
    else:
        fields = []
        for i, w in enumerate(warns):
            ts = w.get("timestamp")
            if isinstance(ts, datetime.datetime):
                ts_text = f"<t:{int(ts.timestamp())}:R>"
            else:
                ts_text = str(ts)
            fields.append((f"#{i} – {w['reason'][:80]}",
                           f"{ts_text} • Mod: <@{w.get('mod_id', '?')}>", False))
        embed = create_embed(f"{E.CHANNEL} Verwarnungen – {member.display_name}",
                             f"**{len(warns)}** Verwarnungen insgesamt.", COLOR_WARNING,
                             fields, thumbnail=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clearwarnings", description="Löscht ALLE Verwarnungen eines Nutzers")
@app_commands.describe(member="Nutzer")
@app_commands.default_permissions(manage_messages=True)
async def slash_clearwarnings(interaction: discord.Interaction, member: discord.Member) -> None:
    deleted = await bot.db.aclear_warnings(interaction.guild.id, member.id)
    embed = create_embed(f"{E.DELETE} Verwarnungen gelöscht",
                         f"**{deleted}** Verwarnungen von {member.mention} gelöscht.",
                         COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.DELETE} Clear-Warnings",
                         f"{interaction.user.mention} hat {deleted} Verwarnungen von {member.mention} gelöscht.",
                         COLOR_INFO, user=member, module="moderation")

@bot.tree.command(name="clearwarning", description="Löscht eine einzelne Verwarnung (Index aus /warnings)")
@app_commands.describe(member="Nutzer", index="Index aus /warnings (#0, #1, ...)")
@app_commands.default_permissions(manage_messages=True)
async def slash_clearwarning(interaction: discord.Interaction, member: discord.Member, index: int) -> None:
    success = await bot.db.aremove_warning(interaction.guild.id, member.id, index)
    if success:
        embed = create_embed(f"{E.OK} Verwarnung entfernt",
                             f"Verwarnung #{index} von {member.mention} entfernt.", COLOR_SUCCESS)
        await bot.log_action(interaction.guild, f"{E.OK} Clear-Warning",
                             f"{interaction.user.mention} hat Verwarnung #{index} von {member.mention} gelöscht.",
                             COLOR_INFO, user=member, module="moderation")
    else:
        embed = create_embed(f"{E.FAIL} Nicht gefunden",
                             f"Index {index} existiert nicht.", COLOR_DANGER)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="nick", description="Ändert den Nickname eines Nutzers")
@app_commands.describe(member="Nutzer", nickname="Neuer Nickname (leer = zurücksetzen)")
@app_commands.default_permissions(manage_nicknames=True)
async def slash_nick(interaction: discord.Interaction, member: discord.Member,
                     nickname: str = None) -> None:
    try:
        await member.edit(nick=nickname, reason=f"Nick durch {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    embed = create_embed(f"{E.NICK} Nickname geändert",
                         f"Nickname von {member.mention} auf **{nickname or 'Standard'}** gesetzt.",
                         COLOR_INFO)
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.NICK} Nick",
                         f"{member.mention} → **{nickname or 'Standard'}** durch {interaction.user.mention}",
                         COLOR_INFO, user=member, module="moderation")

# ═══════════════════════════════════════════════════════════════
# SECURITY GROUP
# ═══════════════════════════════════════════════════════════════
security_group = app_commands.Group(name="security", description="Security-Einstellungen verwalten")

@security_group.command(name="view", description="Zeigt die aktuelle Security-Konfiguration")
@app_commands.default_permissions(administrator=True)
async def security_view(interaction: discord.Interaction) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    modules = ["anti_spam", "anti_nuke", "anti_raid", "anti_mention", "automod",
               "anti_ghost_ping", "anti_scam", "anti_url_shortener"]
    fields = []
    for mod in modules:
        mod_cfg = cfg.get(mod, {})
        status = f"{E.OK} Aktiv" if mod_cfg.get("enabled") else f"{E.FAIL} Inaktiv"
        fields.append((mod.replace("_", " ").title(), status, True))
    embed = create_embed(f"{E.SHIELD} Security Übersicht",
                         f"Aktuelle Konfiguration für **{interaction.guild.name}**",
                         COLOR_PRIMARY, fields,
                         thumbnail=interaction.guild.icon.url if interaction.guild.icon else None)
    await interaction.response.send_message(embed=embed)

@security_group.command(name="toggle", description="Aktiviert/Deaktiviert ein Modul")
@app_commands.describe(module="Modul-Name (z.B. anti_spam)")
@app_commands.default_permissions(administrator=True)
async def security_toggle(interaction: discord.Interaction, module: str) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    if module not in cfg or not isinstance(cfg[module], dict):
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Fehler", f"Modul `{module}` nicht gefunden.", COLOR_DANGER),
            ephemeral=True)
        return
    current = cfg[module].get("enabled", False)
    await bot.db.update_module(interaction.guild.id, module, "enabled", not current)
    status = f"{E.OK} Aktiviert" if not current else f"{E.FAIL} Deaktiviert"
    embed = create_embed(f"{E.SETTINGS} Modul geändert",
                         f"**{module}** wurde **{status}**.",
                         COLOR_SUCCESS if not current else COLOR_WARNING)
    await interaction.response.send_message(embed=embed)

@security_group.command(name="set", description="Setzt einen Wert in einem Modul")
@app_commands.describe(module="Modul", setting="Einstellung", value="Wert")
@app_commands.default_permissions(administrator=True)
async def security_set(interaction: discord.Interaction, module: str, setting: str, value: str) -> None:
    parsed: Any = value
    if value.lower() in ("true", "false"):
        parsed = value.lower() == "true"
    elif value.isdigit():
        parsed = int(value)
    await bot.db.update_module(interaction.guild.id, module, setting, parsed)
    embed = create_embed(f"{E.OK} Einstellung gespeichert",
                         f"`{module}.{setting}` = `{parsed}`", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@security_group.command(name="punishment", description="Setzt die Strafe für ein Modul")
@app_commands.describe(module="Modul", punishment_type="warn / timeout / kick / ban")
@app_commands.default_permissions(administrator=True)
async def security_punishment(interaction: discord.Interaction, module: str,
                              punishment_type: str) -> None:
    if punishment_type not in VALID_PUNISHMENTS:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Ungültige Strafe",
                               f"Erlaubte Werte: {', '.join(VALID_PUNISHMENTS)}", COLOR_DANGER),
            ephemeral=True)
        return
    await bot.db.update_module(interaction.guild.id, module, "punishment", punishment_type)
    embed = create_embed(f"{E.OK} Strafe gesetzt",
                         f"Strafe für **{module}** auf **{punishment_type}** gesetzt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@security_group.command(name="reset", description="Setzt ein Modul auf Standardwerte zurück")
@app_commands.describe(module="Modul-Name")
@app_commands.default_permissions(administrator=True)
async def security_reset(interaction: discord.Interaction, module: str) -> None:
    if module not in DEFAULT_CONFIG:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Fehler", f"Modul `{module}` nicht gefunden.", COLOR_DANGER),
            ephemeral=True)
        return
    cfg = bot.db.get_config(interaction.guild.id)
    default_val = DEFAULT_CONFIG[module]
    cfg[module] = default_val.copy() if isinstance(default_val, (dict, list)) else default_val
    await bot.db.set_config(interaction.guild.id, cfg)
    embed = create_embed(f"{E.DUP} Modul zurückgesetzt",
                         f"**{module}** wurde auf Standardwerte zurückgesetzt.", COLOR_INFO)
    await interaction.response.send_message(embed=embed)

bot.tree.add_command(security_group)

# ═══════════════════════════════════════════════════════════════
# WHITELIST GROUP
# ═══════════════════════════════════════════════════════════════
whitelist_group = app_commands.Group(name="whitelist", description="Whitelist verwalten")

WL_CATEGORIES = [
    app_commands.Choice(name="Nutzer", value="users"),
    app_commands.Choice(name="Rollen", value="roles"),
    app_commands.Choice(name="Kanäle", value="channels"),
    app_commands.Choice(name="Bypass Anti-Spam", value="bypass_antispam"),
    app_commands.Choice(name="Bypass Anti-Nuke", value="bypass_antinuke"),
]

@whitelist_group.command(name="add", description="Fügt einen Eintrag zur Whitelist hinzu")
@app_commands.describe(category="Kategorie wählen", entry_id="ID des Eintrags")
@app_commands.choices(category=WL_CATEGORIES)
@app_commands.default_permissions(administrator=True)
async def whitelist_add(interaction: discord.Interaction,
                        category: app_commands.Choice[str], entry_id: str) -> None:
    if not entry_id.isdigit():
        await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Die ID muss eine Zahl sein.", color=COLOR_DANGER), ephemeral=True)
        return
    await bot.db.aadd_whitelist(interaction.guild.id, category.value, int(entry_id))
    embed = create_embed(f"{E.OK} Whitelist aktualisiert",
                         f"ID `{entry_id}` zur Kategorie **{category.name}** hinzugefügt.",
                         COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@whitelist_group.command(name="bulk_add", description="Fügt viele IDs gleichzeitig hinzu")
@app_commands.describe(category="Kategorie wählen",
                       ids="IDs getrennt durch Komma oder Leerzeichen")
@app_commands.choices(category=WL_CATEGORIES)
@app_commands.default_permissions(administrator=True)
async def whitelist_bulk_add(interaction: discord.Interaction,
                             category: app_commands.Choice[str], ids: str) -> None:
    id_list = re.split(r'[,\s]+', ids.strip())
    added = 0
    for eid in id_list:
        if eid.isdigit():
            await bot.db.aadd_whitelist(interaction.guild.id, category.value, int(eid))
            added += 1
    embed = create_embed(f"{E.OK} Bulk-Add abgeschlossen",
                         f"**{added}** IDs wurden zur Kategorie **{category.name}** hinzugefügt.",
                         COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@whitelist_group.command(name="remove", description="Entfernt einen Eintrag aus der Whitelist")
@app_commands.describe(category="Kategorie", entry_id="ID")
@app_commands.choices(category=WL_CATEGORIES)
@app_commands.default_permissions(administrator=True)
async def whitelist_remove(interaction: discord.Interaction,
                           category: app_commands.Choice[str], entry_id: str) -> None:
    if not entry_id.isdigit():
        await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Die ID muss eine Zahl sein.", color=COLOR_DANGER), ephemeral=True)
        return
    await bot.db.aremove_whitelist(interaction.guild.id, category.value, int(entry_id))
    embed = create_embed(f"{E.OK} Entfernt",
                         f"ID `{entry_id}` aus **{category.name}** entfernt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@whitelist_group.command(name="add_user", description="Fügt einen Nutzer bequem zur Whitelist hinzu")
@app_commands.describe(user="Nutzer")
@app_commands.default_permissions(administrator=True)
async def whitelist_add_user(interaction: discord.Interaction, user: discord.User) -> None:
    await bot.db.aadd_whitelist(interaction.guild.id, "users", user.id)
    embed = create_embed(f"{E.OK} Nutzer hinzugefügt",
                         f"{user.mention} wurde zur Whitelist hinzugefügt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@whitelist_group.command(name="add_role", description="Fügt eine Rolle bequem zur Whitelist hinzu")
@app_commands.describe(role="Rolle")
@app_commands.default_permissions(administrator=True)
async def whitelist_add_role(interaction: discord.Interaction, role: discord.Role) -> None:
    await bot.db.aadd_whitelist(interaction.guild.id, "roles", role.id)
    embed = create_embed(f"{E.OK} Rolle hinzugefügt",
                         f"{role.mention} wurde zur Whitelist hinzugefügt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@whitelist_group.command(name="add_channel", description="Fügt einen Kanal bequem zur Whitelist hinzu")
@app_commands.describe(channel="Kanal")
@app_commands.default_permissions(administrator=True)
async def whitelist_add_channel(interaction: discord.Interaction,
                                channel: discord.TextChannel) -> None:
    await bot.db.aadd_whitelist(interaction.guild.id, "channels", channel.id)
    embed = create_embed(f"{E.OK} Kanal hinzugefügt",
                         f"{channel.mention} wurde zur Whitelist hinzugefügt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@whitelist_group.command(name="remove_role", description="Entfernt eine Rolle bequem aus der Whitelist")
@app_commands.describe(role="Rolle")
@app_commands.default_permissions(administrator=True)
async def whitelist_remove_role(interaction: discord.Interaction, role: discord.Role) -> None:
    await bot.db.aremove_whitelist(interaction.guild.id, "roles", role.id)
    embed = create_embed(f"{E.OK} Rolle entfernt",
                         f"{role.mention} wurde aus der Whitelist entfernt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@whitelist_group.command(name="clear", description="Leert eine Whitelist-Kategorie komplett")
@app_commands.describe(category="Kategorie")
@app_commands.choices(category=WL_CATEGORIES)
@app_commands.default_permissions(administrator=True)
async def whitelist_clear(interaction: discord.Interaction,
                          category: app_commands.Choice[str]) -> None:
    wl = bot.db.get_whitelist(interaction.guild.id)
    wl[category.value] = []
    await bot.db.set_whitelist(interaction.guild.id, wl)
    embed = create_embed(f"{E.OK} Geleert",
                         f"Kategorie **{category.name}** wurde komplett geleert.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@whitelist_group.command(name="list", description="Zeigt die aktuelle Whitelist")
@app_commands.default_permissions(administrator=True)
async def whitelist_list(interaction: discord.Interaction) -> None:
    wl = bot.db.get_whitelist(interaction.guild.id)
    fields = [
        (f"{E.USERS} Nutzer",
         "\n".join(f"<@{uid}>" for uid in wl.get("users", [])) or "Keine", False),
        (f"{E.ROLES} Rollen",
         "\n".join(f"<@&{rid}>" for rid in wl.get("roles", [])) or "Keine", False),
        (f"{E.CHANNELS} Kanäle",
         "\n".join(f"<#{cid}>" for cid in wl.get("channels", [])) or "Keine", False),
        (f"{E.SPAM} Bypass Anti-Spam",
         "\n".join(f"<@{uid}>" for uid in wl.get("bypass_antispam", [])) or "Keine", False),
        (f"{E.NUKE} Bypass Anti-Nuke",
         "\n".join(f"<@{uid}>" for uid in wl.get("bypass_antinuke", [])) or "Keine", False),
    ]
    embed = create_embed(f"{E.CHANNEL} Whitelist",
                         f"Whitelist für **{interaction.guild.name}**", COLOR_INFO, fields)
    await interaction.response.send_message(embed=embed)

bot.tree.add_command(whitelist_group)

# ═══════════════════════════════════════════════════════════════
# AUTOMOD GROUP
# ═══════════════════════════════════════════════════════════════
automod_group = app_commands.Group(name="automod", description="AutoMod verwalten")

@automod_group.command(name="badword_add", description="Fügt ein verbotenes Wort hinzu")
@app_commands.describe(word="Das verbotene Wort")
@app_commands.default_permissions(manage_guild=True)
async def automod_badword_add(interaction: discord.Interaction, word: str) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    bad_words = cfg.get("automod", {}).get("bad_words", [])
    if word.lower() not in bad_words:
        bad_words.append(word.lower())
        await bot.db.update_module(interaction.guild.id, "automod", "bad_words", bad_words)
    embed = create_embed(f"{E.OK} Wort hinzugefügt",
                         f"`{word}` zur Wortliste hinzugefügt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@automod_group.command(name="badword_remove", description="Entfernt ein verbotenes Wort")
@app_commands.describe(word="Das Wort")
@app_commands.default_permissions(manage_guild=True)
async def automod_badword_remove(interaction: discord.Interaction, word: str) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    bad_words = cfg.get("automod", {}).get("bad_words", [])
    bad_words = [w for w in bad_words if w != word.lower()]
    await bot.db.update_module(interaction.guild.id, "automod", "bad_words", bad_words)
    embed = create_embed(f"{E.OK} Wort entfernt",
                         f"`{word}` aus der Wortliste entfernt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@automod_group.command(name="badword_list", description="Zeigt alle verbotenen Wörter")
@app_commands.default_permissions(manage_guild=True)
async def automod_badword_list(interaction: discord.Interaction) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    bad_words = cfg.get("automod", {}).get("bad_words", [])
    if not bad_words:
        embed = create_embed(f"{E.CHANNEL} Verbotene Wörter",
                             "Keine verbotenen Wörter konfiguriert.", COLOR_INFO)
    else:
        word_list = "\n".join(f"• ||{w}||" for w in bad_words)
        embed = create_embed(f"{E.CHANNEL} Verbotene Wörter",
                             f"**{len(bad_words)}** verbotene Wörter:\n{word_list}",
                             COLOR_WARNING)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@automod_group.command(name="regex_add", description="Fügt eine Custom Regex-Regel hinzu")
@app_commands.describe(pattern="Regex-Pattern (Python re)")
@app_commands.default_permissions(manage_guild=True)
async def automod_regex_add(interaction: discord.Interaction, pattern: str) -> None:
    try:
        re.compile(pattern)
    except re.error as ex:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Ungültiges Regex", f"`{ex}`", COLOR_DANGER),
            ephemeral=True)
        return
    cfg = bot.db.get_config(interaction.guild.id)
    rules = cfg.get("automod", {}).get("regex_rules", [])
    rules.append(pattern)
    await bot.db.update_module(interaction.guild.id, "automod", "regex_rules", rules)
    embed = create_embed(f"{E.OK} Regex hinzugefügt",
                         f"Regel hinzugefügt:\n`{pattern[:200]}`", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@automod_group.command(name="regex_remove", description="Entfernt eine Regex-Regel per Index")
@app_commands.describe(index="Index aus /automod regex_list")
@app_commands.default_permissions(manage_guild=True)
async def automod_regex_remove(interaction: discord.Interaction, index: int) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    rules = cfg.get("automod", {}).get("regex_rules", [])
    if not (0 <= index < len(rules)):
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Ungültig", f"Index {index} existiert nicht.", COLOR_DANGER),
            ephemeral=True)
        return
    removed = rules.pop(index)
    await bot.db.update_module(interaction.guild.id, "automod", "regex_rules", rules)
    embed = create_embed(f"{E.OK} Regex entfernt",
                         f"Entfernt: `{removed[:200]}`", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@automod_group.command(name="regex_list", description="Zeigt alle Custom Regex-Regeln")
@app_commands.default_permissions(manage_guild=True)
async def automod_regex_list(interaction: discord.Interaction) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    rules = cfg.get("automod", {}).get("regex_rules", [])
    if not rules:
        embed = create_embed(f"{E.CHANNEL} Regex-Regeln",
                             "Keine Custom-Regeln konfiguriert.", COLOR_INFO)
    else:
        fields = [(f"#{i}", f"`{p[:200]}`", False) for i, p in enumerate(rules)]
        embed = create_embed(f"{E.CHANNEL} Regex-Regeln",
                             f"**{len(rules)}** Regeln aktiv.", COLOR_WARNING, fields)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@automod_group.command(name="domain_allow", description="Erlaubt eine Domain im Link-Filter")
@app_commands.describe(domain="Domain (z.B. youtube.com)")
@app_commands.default_permissions(manage_guild=True)
async def automod_domain_allow(interaction: discord.Interaction, domain: str) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    allowed = cfg.get("automod", {}).get("allowed_domains", [])
    if domain.lower() not in allowed:
        allowed.append(domain.lower())
        await bot.db.update_module(interaction.guild.id, "automod", "allowed_domains", allowed)
    embed = create_embed(f"{E.OK} Domain erlaubt",
                         f"`{domain}` zur Whitelist hinzugefügt.", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

bot.tree.add_command(automod_group)

# ═══════════════════════════════════════════════════════════════
# SETUP & SYSTEM COMMANDS
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="setup", description="Interaktives Setup-Panel")
@app_commands.default_permissions(administrator=True)
async def slash_setup(interaction: discord.Interaction) -> None:
    embed = create_embed(f"{E.GEAR} ModForge Setup",
                         "Wähle ein Modul aus dem Dropdown, um dessen Konfiguration zu sehen.\n"
                         "Nutze die Buttons, um grundlegende Einstellungen zu ändern.",
                         COLOR_PRIMARY,
                         thumbnail=interaction.guild.icon.url if interaction.guild.icon else None)
    await interaction.response.send_message(embed=embed, view=SetupView())

@bot.tree.command(name="status", description="Zeigt den Bot-Status")
async def slash_status(interaction: discord.Interaction) -> None:
    uptime = get_uptime(bot.start_time)
    embed = create_embed(f"{E.CAPS} Bot Status", "Alle Systeme aktiv.", COLOR_SUCCESS, [
        (f"{E.BOT} Bot", f"{bot.user}", True),
        (f"{E.LATENCY} Latenz", f"{round(bot.latency * 1000)}ms", True),
        (f"{E.SERVER} Server", str(len(bot.guilds)), True),
        (f"{E.USERS} Nutzer", str(sum(g.member_count for g in bot.guilds)), True),
        (f"{E.CLOCK} Uptime", f"{uptime // 3600}h {(uptime % 3600) // 60}m", True),
        ("Version", "3.0.0", True)
    ], thumbnail=bot.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="stats", description="Zeigt Server-Statistiken")
async def slash_stats(interaction: discord.Interaction) -> None:
    guild = interaction.guild
    embed = create_embed(f"{E.CAPS} Stats – {guild.name}", "", COLOR_INFO, [
        (f"{E.USERS} Mitglieder", str(guild.member_count), True),
        (f"{E.BOT} Bots", str(sum(1 for m in guild.members if m.bot)), True),
        (f"{E.CHANNELS} Kanäle", str(len(guild.channels)), True),
        (f"{E.ROLE} Rollen", str(len(guild.roles)), True),
        (f"{E.EMOJI_LIST} Emojis", str(len(guild.emojis)), True),
        (f"{E.CREATED} Erstellt", f"<t:{int(guild.created_at.timestamp())}:D>", True)
    ], thumbnail=guild.icon.url if guild.icon else None)
    await interaction.response.send_message(embed=embed)

# ═══════════════════════════════════════════════════════════════
# CASE-SYSTEM SLASH COMMANDS
# ═══════════════════════════════════════════════════════════════
def _format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"

@bot.tree.command(name="case", description="Zeigt einen Case (Mod-Vorgang) per ID an")
@app_commands.describe(case_id="Die Case-ID (z. B. 42)")
@app_commands.default_permissions(manage_messages=True)
async def slash_case(interaction: discord.Interaction, case_id: int) -> None:
    case = await bot.db.aget_case(interaction.guild.id, case_id)
    if not case:
        await interaction.response.send_message(
            embed=create_embed(f"{E.NO} Case nicht gefunden",
                               f"Es gibt keinen Case mit ID `{case_id}` in diesem Server.",
                               COLOR_DANGER),
            ephemeral=True)
        return

    user = interaction.guild.get_member(case["user_id"]) or await bot.fetch_user(case["user_id"])
    mod = interaction.guild.get_member(case["mod_id"]) or await bot.fetch_user(case["mod_id"])
    user_name = f"{user} (`{case['user_id']}`)" if user else f"`{case['user_id']}`"
    mod_name = f"{mod}" if mod else f"`{case['mod_id']}`"

    arch_count = len(case.get("message_archive", []))
    ev_count = len(case.get("evidence", []))
    history = case.get("reason_history", [])

    fields = [
        (f"{E.USER} User", user_name, True),
        (f"{E.MOD} Moderator", mod_name, True),
        (f"{E.WARN} Aktion", case["action"].upper(), True),
        (f"{E.CLOCK} Dauer", _format_duration(case.get("duration")), True),
        (f"{E.MESSAGE} Archiv-Nachrichten", str(arch_count), True),
        (f"{E.IMAGE} Beweise", str(ev_count), True),
        (f"{E.NOTE} Grund", case.get("reason", "—")[:1000], False),
    ]
    if history:
        last = history[-1]
        fields.append((
            f"{E.EDIT} Letzte Grund-Änderung",
            f"<t:{int(last['changed_at'].timestamp())}:R> von <@{last['changed_by']}>",
            False,
        ))
    if case.get("evidence"):
        ev_lines = []
        for i, ev in enumerate(case["evidence"][:5], 1):
            note = f" – {ev.get('note', '')}" if ev.get("note") else ""
            ev_lines.append(f"`{i}` [Link]({ev['url']}){note}")
        fields.append((f"{E.IMAGE} Beweise (max. 5)", "\n".join(ev_lines), False))

    embed = create_embed(
        f"{E.SHIELD} Case #{case_id}",
        f"Erstellt <t:{int(case['created_at'].timestamp())}:F>",
        COLOR_INFO if case["action"] != "ban" else COLOR_DANGER,
        fields,
        thumbnail=user.display_avatar.url if isinstance(user, (discord.Member, discord.User)) else None,
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="reason", description="Ändert/ergänzt den Grund eines Cases")
@app_commands.describe(case_id="Die Case-ID", grund="Der neue oder ergänzende Grund")
@app_commands.default_permissions(manage_messages=True)
async def slash_reason(
    interaction: discord.Interaction, case_id: int, grund: str,
) -> None:
    ok = await bot.db.aupdate_case_reason(
        interaction.guild.id, case_id, grund, interaction.user.id,
    )
    if not ok:
        await interaction.response.send_message(
            embed=create_embed(f"{E.NO} Case nicht gefunden",
                               f"Kein Case `{case_id}` in diesem Server.",
                               COLOR_DANGER),
            ephemeral=True)
        return
    ACTIVITY.push(
        "case",
        f"Case #{case_id} – Grund aktualisiert von {interaction.user}.",
        guild_id=interaction.guild.id, guild_name=interaction.guild.name,
        user_id=interaction.user.id, user_name=str(interaction.user),
    )
    await bot.log_action(
        interaction.guild,
        f"{E.EDIT} Case #{case_id} – Grund geändert",
        f"**Geändert von:** {interaction.user.mention}\n"
        f"**Neuer Grund:** {grund[:1000]}",
        COLOR_INFO, user=interaction.user, module="cases",
    )
    await interaction.response.send_message(
        embed=create_embed(f"{E.OK} Case #{case_id} aktualisiert",
                           f"Neuer Grund:\n```\n{grund[:500]}\n```",
                           COLOR_SUCCESS),
        ephemeral=True)

@bot.tree.command(name="addproof", description="Fügt einem Case einen Beweis (URL/Screenshot) hinzu")
@app_commands.describe(
    case_id="Die Case-ID",
    proof="Ein Bild-Anhang als Beweis",
    url="ODER eine direkte URL zum Beweis",
    notiz="Optionale Notiz zum Beweis",
)
@app_commands.default_permissions(manage_messages=True)
async def slash_addproof(
    interaction: discord.Interaction,
    case_id: int,
    proof: Optional[discord.Attachment] = None,
    url: Optional[str] = None,
    notiz: Optional[str] = None,
) -> None:
    if not proof and not url:
        await interaction.response.send_message(
            embed=create_embed(f"{E.NO} Fehlender Beweis",
                               "Hänge ein Bild **oder** gib eine URL an.",
                               COLOR_DANGER),
            ephemeral=True)
        return
    final_url = proof.url if proof else url
    ok = await bot.db.aadd_case_evidence(
        interaction.guild.id, case_id, final_url, interaction.user.id, notiz or "",
    )
    if not ok:
        await interaction.response.send_message(
            embed=create_embed(f"{E.NO} Case nicht gefunden",
                               f"Kein Case `{case_id}` in diesem Server.",
                               COLOR_DANGER),
            ephemeral=True)
        return
    ACTIVITY.push(
        "case",
        f"Case #{case_id} – Beweis hinzugefügt von {interaction.user}.",
        guild_id=interaction.guild.id, guild_name=interaction.guild.name,
    )
    await bot.log_action(
        interaction.guild,
        f"{E.IMAGE} Case #{case_id} – Beweis hinzugefügt",
        f"**Von:** {interaction.user.mention}\n[Beweis-Link]({final_url})\n"
        f"{('**Notiz:** ' + notiz) if notiz else ''}",
        COLOR_INFO, user=interaction.user, module="cases",
    )
    await interaction.response.send_message(
        embed=create_embed(f"{E.OK} Beweis gespeichert",
                           f"Case #{case_id} hat jetzt einen neuen Beweis.",
                           COLOR_SUCCESS),
        ephemeral=True)

@bot.tree.command(name="setarchive",
                  description="Aktiviert/deaktiviert das 48h-Nachrichten-Archiv (für Pre-Ban Snapshot)")
@app_commands.describe(enabled="An/Aus")
@app_commands.default_permissions(administrator=True)
async def slash_setarchive(interaction: discord.Interaction, enabled: bool) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    arch = cfg.get("message_archive", {}) or {}
    arch["enabled"] = bool(enabled)
    arch.setdefault("ttl_hours", 48)
    cfg["message_archive"] = arch
    await bot.db.set_config(interaction.guild.id, cfg)
    state = f"AKTIVIERT {E.OK}" if enabled else "DEAKTIVIERT {E.FAIL}"
    await interaction.response.send_message(
        embed=create_embed(
            f"{E.SHIELD} Nachrichten-Archiv {state}",
            ("Ab sofort werden alle User-Nachrichten **48 Stunden** in MongoDB "
             "(TTL-Index) gespeichert. Bei einem Ban wird der Archiv-Snapshot "
             "automatisch dem Case angehängt und ist via `/case <id>` einsehbar."
             if enabled else
             "Das Archiv wurde deaktiviert. Bestehende Einträge laufen via "
             "TTL-Index regulär aus (max. 48h)."),
            COLOR_SUCCESS if enabled else COLOR_WARNING,
        ),
        ephemeral=True)

# ═══════════════════════════════════════════════════════════════
# PERMISSIONS-AUDITOR  (/audit-perms)
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="audit-perms",
                  description="Prüft alle Rollen auf gefährliche Berechtigungen & Hierarchie")
@app_commands.default_permissions(administrator=True)
async def slash_audit_perms(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    cfg = bot.db.get_config(guild.id)
    audit_cfg = cfg.get("perms_audit", {}) or {}
    danger_perms: List[str] = audit_cfg.get("danger_perms", [
        "administrator", "manage_guild", "manage_roles", "manage_channels",
        "ban_members", "kick_members", "mention_everyone",
        "manage_webhooks", "manage_messages", "moderate_members",
    ])
    max_safe_pct = int(audit_cfg.get("max_safe_position_pct", 80))

    findings: List[Tuple[str, str, str]] = []   # (severity, role_label, message)
    total_roles = max(len(guild.roles) - 1, 1)  # ohne @everyone

    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        if role.is_default():  # @everyone separat
            perms = role.permissions
            risky = [p for p in danger_perms if getattr(perms, p, False)]
            if risky:
                findings.append((
                    "CRITICAL",
                    "@everyone",
                    f"@everyone hat **{', '.join(risky)}** – sofort entfernen!",
                ))
            continue

        perms = role.permissions
        risky = [p for p in danger_perms if getattr(perms, p, False)]
        member_count = len(role.members)
        position_pct = int((role.position / total_roles) * 100)

        # Admin-Role checks
        if perms.administrator:
            sev = "CRITICAL"
            extra = ""
            if member_count > 5:
                extra = f" – aber **{member_count} Member**!"
            findings.append((
                sev, role.name,
                f"`Administrator` aktiv{extra}. "
                f"Position: #{role.position} ({position_pct}% der Hierarchie). "
                f"Member: {member_count}.",
            ))
            continue

        if risky:
            sev = "HIGH" if any(p in risky for p in ("ban_members", "manage_guild",
                                                    "manage_roles", "manage_webhooks")) else "MEDIUM"
            note = ""
            if "mention_everyone" in risky and member_count > 20:
                note = f" {E.ALERT}️ {member_count} Member können @everyone pingen!"
            if position_pct > max_safe_pct:
                note += f" {E.ALERT}️ Sehr hohe Hierarchie-Position ({position_pct}%)."
            findings.append((
                sev, role.name,
                f"Gefährliche Perms: **{', '.join(risky)}**. "
                f"Position #{role.position} ({position_pct}%). "
                f"Member: {member_count}.{note}",
            ))

    # Bot-Hierarchie prüfen
    bot_member = guild.me
    bot_top = bot_member.top_role
    higher_roles = [r for r in guild.roles
                    if r.position > bot_top.position and not r.is_default()]
    if higher_roles:
        findings.append((
            "HIGH", "Bot-Hierarchie",
            f"Bot-Top-Rolle ist **{bot_top.name}** (#{bot_top.position}). "
            f"Es gibt **{len(higher_roles)} Rolle(n) darüber** – diese kann "
            f"ModForge **nicht moderieren**: "
            f"{', '.join(r.name for r in higher_roles[:5])}"
            + (" …" if len(higher_roles) > 5 else ""),
        ))

    # 2FA / Verifizierung
    if guild.mfa_level == discord.MFALevel.disabled:
        findings.append((
            "MEDIUM", "Server-Settings",
            "**2FA-Pflicht für Mods ist DEAKTIVIERT** – aktiviere sie unter "
            "Server-Einstellungen → Sicherheit.",
        ))
    if guild.verification_level.value < 2:  # 0 NONE, 1 LOW, 2 MEDIUM
        findings.append((
            "LOW", "Server-Settings",
            f"Verifizierungs-Level ist **{guild.verification_level.name}** – "
            "empfohlen: MEDIUM oder höher.",
        ))

    # Zusammenfassung
    sev_color = {
        "CRITICAL": COLOR_DANGER, "HIGH": COLOR_DANGER,
        "MEDIUM": COLOR_WARNING, "LOW": COLOR_INFO,
    }
    sev_emoji = {"CRITICAL": E.RED, "HIGH": E.ORANGE, "MEDIUM": E.YELLOW, "LOW": E.BLUE}

    if not findings:
        embed = create_embed(
            f"{E.SHIELD} Permissions-Audit – {guild.name}",
            f"{E.OK} Keine Auffälligkeiten. Alle Rollen sehen gesund aus.",
            COLOR_SUCCESS,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    findings.sort(key=lambda f: severity_order.get(f[0], 9))
    worst = findings[0][0]

    desc_lines: List[str] = []
    for sev, label, msg in findings[:25]:
        desc_lines.append(f"{sev_emoji.get(sev, '{E.DOT}')} **[{sev}] {label}**\n{msg}")
    if len(findings) > 25:
        desc_lines.append(f"\n_…und {len(findings) - 25} weitere Funde._")

    embed = create_embed(
        f"{E.SHIELD} Permissions-Audit – {guild.name}",
        "\n\n".join(desc_lines)[:4000],
        sev_color.get(worst, COLOR_WARNING),
    )
    embed.set_footer(text=f"{len(findings)} Befunde · ModForge Security Audit")

    # Loggen
    await bot.log_action(
        guild,
        f"{E.SHIELD} Permissions-Audit ausgeführt",
        f"**Von:** {interaction.user.mention}\n"
        f"**Befunde:** {len(findings)} (höchste Stufe: {worst})",
        sev_color.get(worst, COLOR_WARNING),
        user=interaction.user, module="audit",
    )
    ACTIVITY.push(
        "audit",
        f"Audit auf {guild.name} – {len(findings)} Befunde (worst: {worst}).",
        guild_id=guild.id, guild_name=guild.name,
        user_id=interaction.user.id, user_name=str(interaction.user),
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="help", description="Zeigt alle verfügbaren Commands")
async def slash_help(interaction: discord.Interaction) -> None:
    view = HelpView()
    embed = create_embed(f"{E.HELP} ModForge Help",
                         "Wähle eine Kategorie aus dem Dropdown-Menü.\n"
                         "Jeder Eintrag zeigt **Beschreibung**, **Berechtigung** und ein **Beispiel**.",
                         COLOR_PRIMARY, thumbnail=bot.user.display_avatar.url)
    await interaction.response.send_message(embed=embed, view=view)

# ═══════════════════════════════════════════════════════════════
# LOG-KANAL COMMANDS (pro Modul)
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="logs", description="Setzt den Standard-Log-Kanal")
@app_commands.describe(channel="Der Log-Kanal")
@app_commands.default_permissions(administrator=True)
async def slash_logs(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    await interaction.response.defer(ephemeral=True)    # ← NEU: sofort Bescheid geben, dass es dauert
    cfg = bot.db.get_config(interaction.guild.id)
    cfg["log_channel"] = channel.id
    await bot.db.set_config(interaction.guild.id, cfg)
    embed = create_embed(f"{E.CHANNEL} Standard-Log-Kanal gesetzt",
                         f"Standard-Log-Kanal auf {channel.mention} gesetzt.\n"
                         "Nutze `/logset <module> <channel>` für modul-spezifische Kanäle.",
                         COLOR_SUCCESS)
    await interaction.followup.send(embed=embed)        # ← statt response.send_message

def _module_choices() -> List[app_commands.Choice[str]]:
    return [app_commands.Choice(name=m, value=m) for m in LOG_MODULES]

@bot.tree.command(name="logset", description="Setzt den Log-Kanal für ein bestimmtes Modul")
@app_commands.describe(module="Modul wählen", channel="Kanal für dieses Modul")
@app_commands.choices(module=_module_choices())
@app_commands.default_permissions(administrator=True)
async def slash_logset(interaction: discord.Interaction,
                       module: app_commands.Choice[str],
                       channel: discord.TextChannel) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    log_channels = cfg.get("log_channels", {}) or {}
    log_channels[module.value] = channel.id
    cfg["log_channels"] = log_channels
    await bot.db.set_config(interaction.guild.id, cfg)
    embed = create_embed(f"{E.OK} Modul-Log-Kanal gesetzt",
                         f"Modul **{module.value}** loggt jetzt in {channel.mention}.",
                         COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="logreset", description="Setzt den Log-Kanal für ein Modul zurück (auf Standard)")
@app_commands.describe(module="Modul wählen")
@app_commands.choices(module=_module_choices())
@app_commands.default_permissions(administrator=True)
async def slash_logreset(interaction: discord.Interaction,
                         module: app_commands.Choice[str]) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    log_channels = cfg.get("log_channels", {}) or {}
    log_channels.pop(module.value, None)
    cfg["log_channels"] = log_channels
    await bot.db.set_config(interaction.guild.id, cfg)
    embed = create_embed(f"{E.OK} Modul-Log zurückgesetzt",
                         f"**{module.value}** nutzt jetzt wieder den Standard-Log-Kanal.",
                         COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="logview", description="Zeigt alle konfigurierten Log-Kanäle")
@app_commands.default_permissions(administrator=True)
async def slash_logview(interaction: discord.Interaction) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    default_id = cfg.get("log_channel")
    log_channels = cfg.get("log_channels", {}) or {}

    fields = [("Standard / Fallback",
               f"<#{default_id}>" if default_id else "*Nicht gesetzt*", False)]
    all_modules = list(LOG_MODULES) + list(LOG_MODULES_EXTRA)
    for mod in all_modules:
        cid = log_channels.get(mod)
        fields.append((mod, f"<#{cid}>" if cid else "*Standard*", True))
    embed = create_embed(f"{E.CHANNEL} Log-Konfiguration",
                         "Übersicht aller Log-Kanäle pro Modul.",
                         COLOR_INFO, fields)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="logmodules", description="Listet alle verfügbaren Log-Module")
@app_commands.default_permissions(administrator=True)
async def slash_logmodules(interaction: discord.Interaction) -> None:
    all_mods = list(LOG_MODULES) + list(LOG_MODULES_EXTRA)
    text = "\n".join(f"• `{m}`" for m in all_mods)
    embed = create_embed(f"{E.CHANNEL} Verfügbare Log-Module",
                         text, COLOR_INFO)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════════
# OWNER / ADMIN PRO COMMANDS
# ═══════════════════════════════════════════════════════════════
@bot.tree.command(name="security_level", description="Setzt die Sicherheitsstufe des Servers")
@app_commands.describe(level="Stufe 0-3")
@app_commands.choices(level=[
    app_commands.Choice(name="Level 0: Normal", value=0),
    app_commands.Choice(name="Level 1: Erhöht (Verifizierung Pflicht)", value=1),
    app_commands.Choice(name="Level 2: Sturmflut (Auto-Kick neue Accounts)", value=2),
    app_commands.Choice(name="Level 3: BLACKOUT (Server eingefroren, Joins = Ban)", value=3)
])
@app_commands.default_permissions(administrator=True)
async def slash_security_level(interaction: discord.Interaction,
                               level: app_commands.Choice[int]) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    cfg["security_level"] = level.value
    await bot.db.set_config(interaction.guild.id, cfg)
    if level.value == 3:
        await _activate_lockdown(interaction.guild)
        bot.tracker.lockdown_active[interaction.guild.id] = True
    embed = create_embed(f"{E.SHIELD} Sicherheitsstufe geändert",
                         f"Der Server befindet sich nun auf **{level.name}**.",
                         COLOR_DANGER if level.value > 0 else COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="panic", description="Aktiviert sofort den Lockdown (Level 3)")
@app_commands.default_permissions(administrator=True)
async def slash_panic(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    cfg = bot.db.get_config(interaction.guild.id)
    cfg["security_level"] = 3
    await bot.db.set_config(interaction.guild.id, cfg)
    await _activate_lockdown(interaction.guild)
    bot.tracker.lockdown_active[interaction.guild.id] = True
    embed = create_embed(f"{E.NUKE} PANIC – BLACKOUT AKTIVIERT",
                         "Sicherheitsstufe 3 wurde sofort aktiviert. Alle Kanäle gesperrt!",
                         COLOR_DANGER, [("Ausgeführt von", interaction.user.mention, True)])
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="unlockdown", description="Hebt den Lockdown auf")
@app_commands.default_permissions(administrator=True)
async def slash_unlockdown(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    await _deactivate_lockdown(interaction.guild)
    embed = create_embed(f"{E.LOCK} Lockdown aufgehoben",
                         "Alle Kanäle wurden entsperrt.", COLOR_SUCCESS)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="massunban", description="Entbannt alle gebannten Nutzer (Rate-Limit-geschützt)")
@app_commands.default_permissions(administrator=True)
async def slash_massunban(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    bans = [entry async for entry in interaction.guild.bans()]
    count = 0
    for ban_entry in bans:
        try:
            # Zentrales Semaphore + automatisches 429-Retry
            await rate_limited(
                lambda be=ban_entry: interaction.guild.unban(
                    be.user, reason=f"Mass-Unban durch {interaction.user}"
                )
            )
            count += 1
        except discord.Forbidden:
            pass
        except discord.NotFound:
            pass
    embed = create_embed(f"{E.OK} Mass-Unban abgeschlossen",
                         f"**{count}** von {len(bans)} Nutzern wurden entbannt.", COLOR_SUCCESS)
    await interaction.followup.send(embed=embed)
    await bot.log_action(interaction.guild, f"{E.OK} Mass-Unban",
                         f"{interaction.user.mention} hat {count} Nutzer entbannt.",
                         COLOR_SUCCESS, module="moderation")

@bot.tree.command(name="massrole_remove", description="Entfernt eine Rolle von allen Mitgliedern (Rate-Limit-geschützt)")
@app_commands.describe(role="Die zu entfernende Rolle")
@app_commands.default_permissions(administrator=True)
async def slash_massrole_remove(interaction: discord.Interaction, role: discord.Role) -> None:
    await interaction.response.defer()
    count = 0
    targets = [m for m in interaction.guild.members if role in m.roles]
    for member in targets:
        try:
            await rate_limited(
                lambda m=member: m.remove_roles(role, reason=f"Mass-Role-Remove durch {interaction.user}")
            )
            count += 1
        except discord.Forbidden:
            pass
    embed = create_embed(f"{E.OK} Mass-Role-Remove",
                         f"Rolle {role.mention} von **{count}** Mitgliedern entfernt.",
                         COLOR_SUCCESS)
    await interaction.followup.send(embed=embed)
    await bot.log_action(interaction.guild, f"{E.OK} Mass-Role-Remove",
                         f"{interaction.user.mention} entfernte {role.mention} von {count} Mitgliedern.",
                         COLOR_INFO, module="moderation")

@bot.tree.command(name="forcereset", description="Setzt die gesamte Server-Konfiguration zurück")
@app_commands.default_permissions(administrator=True)
async def slash_forcereset(interaction: discord.Interaction) -> None:
    cfg = DEFAULT_CONFIG.copy()
    await bot.db.set_config(interaction.guild.id, cfg)
    embed = create_embed(f"{E.DUP} Config zurückgesetzt",
                         "Die gesamte Konfiguration wurde auf Standardwerte zurückgesetzt.",
                         COLOR_WARNING)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="warnsetup", description="Konfiguriert Warn-Schwellen interaktiv")
@app_commands.default_permissions(administrator=True)
async def slash_warnsetup(interaction: discord.Interaction) -> None:
    await interaction.response.send_modal(WarnSetupModal())

# ─────────────────────────────────────────────────────────────────
# APPEAL SETUP COMMAND
# ─────────────────────────────────────────────────────────────────
@bot.tree.command(name="logban", description="Setzt den Kanal für Entbannungs-Anträge")
@app_commands.describe(channel="Der Kanal, in dem Appeals gepostet werden")
@app_commands.default_permissions(administrator=True)
async def slash_logban(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    cfg["appeal_log_channel"] = channel.id
    await bot.db.set_config(interaction.guild.id, cfg)
    embed = create_embed(
        "🔒 Appeal-Kanal gesetzt",
        f"Entbannungs-Anträge werden nun in {channel.mention} gepostet.\n\n"
        f"**Verwendung:** `!banappeal <UserID>` – Sendet einem gebannten User eine Appeal-DM.",
        COLOR_SUCCESS
    )
    await interaction.response.send_message(embed=embed)

# ═══════════════════════════════════════════════════════════════
# ERROR HANDLING
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_command_error(ctx: commands.Context, error: Exception) -> None:
    if isinstance(error, commands.MissingPermissions):
        embed = create_embed(f"{E.FAIL} Keine Berechtigung",
                             "Du hast keine Berechtigung für diesen Command.", COLOR_DANGER)
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MemberNotFound):
        embed = create_embed(f"{E.FAIL} Nutzer nicht gefunden",
                             "Der angegebene Nutzer wurde nicht gefunden.", COLOR_DANGER)
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BadArgument):
        embed = create_embed(f"{E.FAIL} Ungültiges Argument",
                             f"Ungültiges Argument: `{error}`", COLOR_DANGER)
        await ctx.send(embed=embed)
    elif isinstance(error, commands.CheckFailure):
        embed = create_embed(f"{E.FAIL} Zugriff verweigert",
                             "Du hast keine Berechtigung für diesen Command.", COLOR_DANGER)
        await ctx.send(embed=embed)
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        log.error(f"Command-Fehler: {error}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction,
                               error: app_commands.AppCommandError) -> None:
    """
    Globaler Slash-Command-Error-Handler.
    """
    cmd_name = interaction.command.qualified_name if interaction.command else "unbekannt"

    user_msg: Optional[str] = None
    color = COLOR_DANGER

    if isinstance(error, app_commands.CommandOnCooldown):
        user_msg = f"{E.CLOCK} Bitte warte noch **{error.retry_after:.1f}s**."
        color = COLOR_WARNING
    elif isinstance(error, app_commands.MissingPermissions):
        user_msg = f"{E.FAIL} Dir fehlen Berechtigungen: `{', '.join(error.missing_permissions)}`"
    elif isinstance(error, app_commands.BotMissingPermissions):
        user_msg = f"{E.FAIL} Dem Bot fehlen Berechtigungen: `{', '.join(error.missing_permissions)}`"
    elif isinstance(error, app_commands.CheckFailure):
        user_msg = f"{E.FAIL} Du hast keinen Zugriff auf diesen Befehl."
    elif isinstance(error, app_commands.CommandNotFound):
        user_msg = f"{E.FAIL} Befehl nicht (mehr) verfügbar."
    elif isinstance(error, app_commands.TransformerError):
        user_msg = f"{E.FAIL} Ungültiger Parameterwert."

    embed = create_embed(
        f"{E.FAIL} Fehler",
        user_msg or f"Ein unerwarteter Fehler ist aufgetreten: `{str(error)[:200]}`",
        color,
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except (discord.HTTPException, discord.NotFound):
        pass

    if user_msg is not None:
        log.warning(f"Slash-Cmd '{cmd_name}' von {interaction.user}: {type(error).__name__}: {error}")
        return

    original = getattr(error, "original", error)
    tb = "".join(traceback.format_exception(type(original), original, original.__traceback__))
    log.error(
        f"Unhandled Slash-Cmd-Fehler in '{cmd_name}' (User {interaction.user}, "
        f"Guild {interaction.guild_id}):\n{tb}"
    )

    if interaction.guild:
        snippet = tb[-1500:] if len(tb) > 1500 else tb
        await bot.log_action(
            interaction.guild,
            f"{E.FAIL} Slash-Command Exception",
            f"**Befehl:** `/{cmd_name}`\n"
            f"**Nutzer:** {interaction.user.mention} (`{interaction.user.id}`)\n"
            f"**Typ:** `{type(original).__name__}`\n"
            f"```py\n{snippet}\n```",
            COLOR_DANGER,
            user=interaction.user if isinstance(interaction.user, discord.Member) else None,
            module="errors",
        )
# ═══════════════════════════════════════════════════════════════════
# BACKUP SYSTEM – Komplettes Server-Backup & Restore mit Passwort
# ═══════════════════════════════════════════════════════════════════

import hashlib as _hashlib

# ── Passwort-Hashing für Backups ──────────────────────────────────
def _hash_password(password: str) -> str:
    """Erzeugt einen SHA256-Hash mit Salt für Backup-Passwörter."""
    salt = f"ModForge_Backup_{random.randint(10000,99999)}"
    return _hashlib.sha256(f"{salt}:{password}".encode()).hexdigest() + f":{salt}"

def _verify_password(password: str, stored_hash: str) -> bool:
    """Überprüft ein Passwort gegen den gespeicherten Hash."""
    try:
        parts = stored_hash.split(":")
        if len(parts) < 2:
            return False
        salt = parts[-1]
        expected = _hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return expected == parts[0]
    except Exception:
        return False

# ── Backup-Daten sammeln ──────────────────────────────────────────
async def _collect_backup_data(guild: discord.Guild) -> dict:
    """Sammelt alle Server-Daten in ein serialisierbares Dict."""
    data = {
        "guild_id": guild.id,
        "guild_name": guild.name,
        "guild_icon_url": str(guild.icon.url) if guild.icon else None,
        "guild_description": guild.description,
        "verification_level": guild.verification_level.value,
        "explicit_content_filter": guild.explicit_content_filter.value,
        "default_notifications": guild.default_notifications.value,
        "mfa_level": guild.mfa_level.value,
        "system_channel_id": guild.system_channel.id if guild.system_channel else None,
        "rules_channel_id": guild.rules_channel.id if guild.rules_channel else None,
        "public_updates_channel_id": guild.public_updates_channel.id if guild.public_updates_channel else None,
        "timestamp": discord.utils.utcnow().isoformat() + "Z",
    }
    # Rollen
    roles_list = []
    for role in sorted(guild.roles, key=lambda r: r.position):
        if role.is_default() or role.managed:
            continue
        roles_list.append({
            "role_id": role.id, "name": role.name,
            "color": role.color.value, "hoist": role.hoist,
            "mentionable": role.mentionable, "position": role.position,
            "permissions": role.permissions.value,
            "is_bot_role": role.tags and role.tags.bot_id is not None,
            "bot_id": role.tags.bot_id if role.tags else None,
        })
    data["roles"] = roles_list
    # Kategorien
    categories_list = []
    for cat in guild.categories:
        categories_list.append({
            "category_id": cat.id, "name": cat.name,
            "position": cat.position, "nsfw": getattr(cat, "nsfw", False),
            "overwrites": _serialize_overwrites(cat.overwrites),
        })
    data["categories"] = sorted(categories_list, key=lambda c: c["position"])
    # Kanäle
    channels_list = []
    for channel in guild.channels:
        if isinstance(channel, discord.CategoryChannel):
            continue
        ch_data = {
            "channel_id": channel.id, "name": channel.name,
            "position": channel.position, "type": str(channel.type),
            "category_id": channel.category.id if channel.category else None,
            "overwrites": _serialize_overwrites(channel.overwrites),
        }
        if isinstance(channel, discord.TextChannel):
            ch_data["topic"] = channel.topic
            ch_data["slowmode_delay"] = channel.slowmode_delay
            ch_data["nsfw"] = channel.nsfw
        elif isinstance(channel, discord.VoiceChannel):
            ch_data["bitrate"] = channel.bitrate
            ch_data["user_limit"] = channel.user_limit
        channels_list.append(ch_data)
    data["channels"] = sorted(channels_list, key=lambda c: c["position"])
    # Emojis
    data["emojis"] = [{"emoji_id": e.id, "name": e.name, "url": str(e.url), "animated": e.animated} for e in guild.emojis]
    data["stats"] = {
        "total_members": guild.member_count,
        "total_roles": len(guild.roles),
        "total_channels": len(guild.channels),
        "total_emojis": len(guild.emojis),
    }
    return data

def _serialize_overwrites(overwrites: dict) -> list:
    result = []
    for target, overwrite in overwrites.items():
        target_id = target.id if hasattr(target, "id") else int(target)
        target_type = "role" if isinstance(target, discord.Role) else "member"
        result.append({"target_id": target_id, "target_type": target_type, "allow": overwrite.pair()[0].value, "deny": overwrite.pair()[1].value})
    return result

def _deserialize_overwrites(guild: discord.Guild, overwrites_data: list, role_map: dict) -> dict:
    result = {}
    for ow in overwrites_data:
        target_id = ow["target_id"]
        overwrite = discord.PermissionOverwrite.from_pair(discord.Permissions(ow.get("allow", 0)), discord.Permissions(ow.get("deny", 0)))
        if ow.get("target_type", "role") == "role":
            role = role_map.get(target_id) or guild.get_role(target_id)
            if role:
                result[role] = overwrite
            elif target_id == guild.default_role.id:
                result[guild.default_role] = overwrite
        else:
            member = guild.get_member(target_id)
            if member:
                result[member] = overwrite
    return result

# ── Backup Restore ────────────────────────────────────────────────
async def _restore_from_backup(guild: discord.Guild, backup: dict, interaction: discord.Interaction) -> dict:
    report = {"roles_created": 0, "roles_updated": 0, "roles_skipped": 0,
              "channels_created": 0, "channels_updated": 0, "channels_skipped": 0,
              "categories_created": 0, "categories_updated": 0, "errors": []}
    role_map: Dict[int, discord.Role] = {}
    category_map: Dict[int, discord.CategoryChannel] = {}
    existing_categories = {c.name.lower(): c for c in guild.categories}
    for cat_data in backup.get("categories", []):
        try:
            existing = guild.get_channel(cat_data["category_id"])
            if existing and isinstance(existing, discord.CategoryChannel):
                try:
                    await existing.edit(name=cat_data["name"], overwrites=_deserialize_overwrites(guild, cat_data.get("overwrites", []), role_map), reason="Backup-Restore")
                except (discord.Forbidden, discord.HTTPException):
                    pass
                category_map[cat_data["category_id"]] = existing
                report["categories_updated"] += 1
            else:
                existing_by_name = existing_categories.get(cat_data["name"].lower())
                if existing_by_name:
                    category_map[cat_data["category_id"]] = existing_by_name
                    report["categories_updated"] += 1
                    continue
                try:
                    new_cat = await guild.create_category(name=cat_data["name"], overwrites=_deserialize_overwrites(guild, cat_data.get("overwrites", []), role_map), reason="Backup-Restore")
                    category_map[cat_data["category_id"]] = new_cat
                    report["categories_created"] += 1
                except (discord.Forbidden, discord.HTTPException) as e:
                    report["errors"].append(f"Kategorie '{cat_data['name']}': {e}")
        except Exception as e:
            report["errors"].append(f"Kategorie '{cat_data.get('name', '?')}': {e}")
    existing_roles = {r.name.lower(): r for r in guild.roles}
    for role_data in backup.get("roles", []):
        try:
            if role_data.get("is_bot_role"):
                report["roles_skipped"] += 1
                continue
            existing = guild.get_role(role_data["role_id"])
            if existing:
                try:
                    await existing.edit(name=role_data["name"], color=discord.Color(role_data["color"]), hoist=role_data["hoist"], mentionable=role_data["mentionable"], permissions=discord.Permissions(role_data["permissions"]), reason="Backup-Restore")
                except (discord.Forbidden, discord.HTTPException):
                    pass
                role_map[role_data["role_id"]] = existing
                report["roles_updated"] += 1
            else:
                existing_by_name = existing_roles.get(role_data["name"].lower())
                if existing_by_name:
                    role_map[role_data["role_id"]] = existing_by_name
                    try:
                        await existing_by_name.edit(color=discord.Color(role_data["color"]), hoist=role_data["hoist"], mentionable=role_data["mentionable"], permissions=discord.Permissions(role_data["permissions"]), reason="Backup-Restore")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
                    report["roles_updated"] += 1
                    continue
                try:
                    new_role = await guild.create_role(name=role_data["name"], color=discord.Color(role_data["color"]), hoist=role_data["hoist"], mentionable=role_data["mentionable"], permissions=discord.Permissions(role_data["permissions"]), reason="Backup-Restore")
                    role_map[role_data["role_id"]] = new_role
                    report["roles_created"] += 1
                except (discord.Forbidden, discord.HTTPException) as e:
                    report["errors"].append(f"Rolle '{role_data['name']}': {e}")
        except Exception as e:
            report["errors"].append(f"Rolle '{role_data.get('name', '?')}': {e}")
    existing_channels = {c.name.lower(): c for c in guild.channels if not isinstance(c, discord.CategoryChannel)}
    for ch_data in backup.get("channels", []):
        try:
            category = category_map.get(ch_data.get("category_id"))
            overwrites = _deserialize_overwrites(guild, ch_data.get("overwrites", []), role_map)
            existing = guild.get_channel(ch_data["channel_id"])
            if existing:
                kwargs = {"name": ch_data["name"], "overwrites": overwrites, "reason": "Backup-Restore"}
                if isinstance(existing, discord.TextChannel):
                    if ch_data.get("topic"):
                        kwargs["topic"] = ch_data["topic"]
                    kwargs["slowmode_delay"] = ch_data.get("slowmode_delay", 0)
                    kwargs["nsfw"] = ch_data.get("nsfw", False)
                if category:
                    kwargs["category"] = category
                try:
                    await existing.edit(**kwargs)
                except (discord.Forbidden, discord.HTTPException):
                    pass
                report["channels_updated"] += 1
                continue
            existing_by_name = existing_channels.get(ch_data["name"].lower())
            if existing_by_name:
                try:
                    kwargs = {"overwrites": overwrites, "reason": "Backup-Restore"}
                    if isinstance(existing_by_name, discord.TextChannel) and ch_data.get("topic"):
                        kwargs["topic"] = ch_data["topic"]
                    if category:
                        kwargs["category"] = category
                    await existing_by_name.edit(**kwargs)
                except (discord.Forbidden, discord.HTTPException):
                    pass
                report["channels_updated"] += 1
                continue
            ch_type = ch_data.get("type", "text")
            try:
                if "voice" in ch_type:
                    new_ch = await guild.create_voice_channel(name=ch_data["name"], category=category, overwrites=overwrites, bitrate=ch_data.get("bitrate", 64000), user_limit=ch_data.get("user_limit", 0), reason="Backup-Restore")
                else:
                    new_ch = await guild.create_text_channel(name=ch_data["name"], category=category, overwrites=overwrites, topic=ch_data.get("topic"), slowmode_delay=ch_data.get("slowmode_delay", 0), nsfw=ch_data.get("nsfw", False), reason="Backup-Restore")
                report["channels_created"] += 1
            except (discord.Forbidden, discord.HTTPException) as e:
                report["errors"].append(f"Kanal-Erstellung '{ch_data['name']}': {e}")
        except Exception as e:
            report["errors"].append(f"Kanal '{ch_data.get('name', '?')}': {e}")
    try:
        await guild.edit(verification_level=discord.VerificationLevel(backup.get("verification_level", 0)), explicit_content_filter=discord.ExplicitContentFilter(backup.get("explicit_content_filter", 0)), default_notifications=discord.NotificationLevel(backup.get("default_notifications", 0)), reason="Backup-Restore")
    except (discord.Forbidden, discord.HTTPException) as e:
        report["errors"].append(f"Server-Einstellungen: {e}")
    return report

# ── Backup DB-Operationen ─────────────────────────────────────────
async def _backup_db_save(backup_data: dict, created_by: int, label: str = None, password_hash: str = None) -> str:
    backup_id = _hashlib.sha256(f"{backup_data['guild_id']}_{time.time()}_{random.randint(0, 999999)}".encode()).hexdigest()[:16]
    doc = {
        "backup_id": backup_id, "guild_id": backup_data["guild_id"],
        "guild_name": backup_data.get("guild_name", "Unbekannt"),
        "label": label or f"Backup vom {discord.utils.utcnow().strftime('%d.%m.%Y %H:%M')} UTC",
        "created_by": created_by, "created_at": discord.utils.utcnow(),
        "data": backup_data, "stats": backup_data.get("stats", {}),
        "password_hash": password_hash,
        "has_password": password_hash is not None,
    }
    try:
        collection = bot.db.client["ModForge"]["backups"]
        await collection.insert_one(doc)
        return backup_id
    except Exception as e:
        log.error(f"Backup-Save Fehler: {e}")
        return None

async def _backup_db_list(guild_id: int, limit: int = 10) -> list:
    try:
        collection = bot.db.client["ModForge"]["backups"]
        cursor = collection.find({"guild_id": guild_id}, {"backup_id": 1, "label": 1, "created_at": 1, "created_by": 1, "stats": 1, "has_password": 1, "_id": 0}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception as e:
        log.error(f"Backup-List Fehler: {e}")
        return []

async def _backup_db_get(guild_id: int, backup_id: str) -> dict:
    try:
        collection = bot.db.client["ModForge"]["backups"]
        return await collection.find_one({"guild_id": guild_id, "backup_id": backup_id})
    except Exception as e:
        log.error(f"Backup-Get Fehler: {e}")
        return None

async def _backup_db_get_any(backup_id: str) -> dict:
    """Holt ein Backup von JEDEM Server (für Cross-Server-Restore)."""
    try:
        collection = bot.db.client["ModForge"]["backups"]
        return await collection.find_one({"backup_id": backup_id})
    except Exception as e:
        log.error(f"Backup-Get-Any Fehler: {e}")
        return None

async def _backup_db_delete(guild_id: int, backup_id: str) -> bool:
    try:
        collection = bot.db.client["ModForge"]["backups"]
        result = await collection.delete_one({"guild_id": guild_id, "backup_id": backup_id})
        return result.deleted_count > 0
    except Exception as e:
        log.error(f"Backup-Delete Fehler: {e}")
        return False

# ── Backup Passwort-Modal ─────────────────────────────────────────
class BackupPasswordModal(discord.ui.Modal, title="🔐 Backup-Passwort eingeben"):
    password = discord.ui.TextInput(label="Passwort", placeholder="Gib das Backup-Passwort ein...", style=discord.TextStyle.short, required=True, min_length=1, max_length=100)
    def __init__(self, backup_id: str, backup_label: str, guild: discord.Guild, user: discord.Member, source_guild_id: int = None) -> None:
        super().__init__()
        self.backup_id = backup_id
        self.backup_label = backup_label
        self.guild = guild
        self.user = user
        self.source_guild_id = source_guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if self.source_guild_id:
            doc = await _backup_db_get_any(self.backup_id)
        else:
            doc = await _backup_db_get(self.guild.id, self.backup_id)
        if not doc or not doc.get("data"):
            embed = create_embed(f"{E.FAIL} Fehler", "Backup nicht gefunden.", COLOR_DANGER)
            await interaction.followup.send(embed=embed)
            return
        pw_hash = doc.get("password_hash")
        if not pw_hash or not _verify_password(self.password.value, pw_hash):
            embed = create_embed(f"{E.FAIL} Falsches Passwort", "Das eingegebene Passwort ist falsch.", COLOR_DANGER)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        report = await _restore_from_backup(self.guild, doc["data"], interaction)
        fields = [
            ("Rollen erstellt/aktualisiert/übersprungen", f"{E.OK} {report['roles_created']} / 🔄 {report['roles_updated']} / ⏭️ {report['roles_skipped']}", False),
            ("Kategorien", f"{E.OK} {report['categories_created']} / 🔄 {report['categories_updated']}", False),
            ("Kanäle", f"{E.OK} {report['channels_created']} / 🔄 {report['channels_updated']}", False),
        ]
        if report["errors"]:
            error_text = "\n".join(f"• {e[:100]}" for e in report["errors"][:10])
            fields.append((f"{E.ALERT}️ Fehler", error_text, False))
        result_color = COLOR_SUCCESS if not report["errors"] else COLOR_WARNING
        result_embed = create_embed(f"{E.OK} Backup-Restore abgeschlossen", f"Backup **{self.backup_label}** wurde wiederhergestellt.", result_color, fields)
        await interaction.followup.send(embed=result_embed)
        await bot.log_action(self.guild, f"{E.OK} Backup-Restore", f"Backup **{self.backup_label}** von {self.user.mention} wiederhergestellt.", result_color, fields, user=self.user, module="backup")

# ── Backup Confirm Views ──────────────────────────────────────────
class BackupRestoreConfirmView(discord.ui.View):
    def __init__(self, backup_id: str, backup_label: str, guild: discord.Guild, user: discord.Member, has_password: bool = False) -> None:
        super().__init__(timeout=60)
        self.backup_id = backup_id
        self.backup_label = backup_label
        self.guild = guild
        self.user = user
        self.has_password = has_password

    @discord.ui.button(label="Ja, Restore bestätigen", style=discord.ButtonStyle.danger, emoji="{E.ALERT}️")
    async def confirm_restore(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Nur der Initiator kann bestätigen.", color=COLOR_DANGER), ephemeral=True)
            return
        await interaction.response.defer()
        if self.has_password:
            embed = create_embed("🔐 Passwort erforderlich", "Dieses Backup ist passwortgeschützt. Bitte gib das Passwort ein.", COLOR_WARNING)
            await interaction.followup.send(embed=embed, view=BackupPasswordPromptView(self.backup_id, self.backup_label, self.guild, self.user))
            return
        doc = await _backup_db_get(self.guild.id, self.backup_id)
        if not doc or not doc.get("data"):
            embed = create_embed(f"{E.FAIL} Fehler", "Backup nicht gefunden.", COLOR_DANGER)
            await interaction.followup.send(embed=embed)
            return
        embed_progress = create_embed("⏳ Backup-Restore läuft...", f"Backup **{self.backup_label}** wird wiederhergestellt.", COLOR_WARNING)
        await interaction.followup.send(embed=embed_progress)
        report = await _restore_from_backup(self.guild, doc["data"], interaction)
        fields = [("Rollen", f"{E.OK}{report['roles_created']} 🔄{report['roles_updated']} ⏭️{report['roles_skipped']}", False), ("Kategorien", f"{E.OK}{report['categories_created']} 🔄{report['categories_updated']}", False), ("Kanäle", f"{E.OK}{report['channels_created']} 🔄{report['channels_updated']}", False)]
        if report["errors"]:
            fields.append(("{E.ALERT}️ Fehler", "\n".join(f"• {e[:100]}" for e in report["errors"][:10]), False))
        rc = COLOR_SUCCESS if not report["errors"] else COLOR_WARNING
        await interaction.channel.send(embed=create_embed(f"{E.OK} Backup-Restore abgeschlossen", f"Backup **{self.backup_label}** wiederhergestellt.", rc, fields))
        await bot.log_action(self.guild, f"{E.OK} Backup-Restore", f"Backup **{self.backup_label}** von {self.user.mention} wiederhergestellt.", rc, fields, user=self.user, module="backup")

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary, emoji=E.FAIL)
    async def cancel_restore(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user.id:
            return
        await interaction.response.edit_message(embed=create_embed("🚫 Restore abgebrochen", "Backup wurde NICHT wiederhergestellt.", COLOR_WARNING), view=None)

class BackupPasswordPromptView(discord.ui.View):
    def __init__(self, backup_id: str, backup_label: str, guild: discord.Guild, user: discord.Member, source_guild_id: int = None) -> None:
        super().__init__(timeout=120)
        self.backup_id = backup_id
        self.backup_label = backup_label
        self.guild = guild
        self.user = user
        self.source_guild_id = source_guild_id

    @discord.ui.button(label="Passwort eingeben", style=discord.ButtonStyle.primary, emoji="🔑")
    async def enter_pw(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Nur der Initiator.", color=COLOR_DANGER), ephemeral=True)
            return
        await interaction.response.send_modal(BackupPasswordModal(self.backup_id, self.backup_label, self.guild, self.user, self.source_guild_id))

class BackupDeleteConfirmView(discord.ui.View):
    def __init__(self, backup_id: str, backup_label: str, guild_id: int, user: discord.Member) -> None:
        super().__init__(timeout=60)
        self.backup_id = backup_id
        self.backup_label = backup_label
        self.guild_id = guild_id
        self.user = user

    @discord.ui.button(label="Ja, löschen", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user.id:
            return
        success = await _backup_db_delete(self.guild_id, self.backup_id)
        if success:
            await interaction.response.edit_message(embed=create_embed(f"{E.DELETE} Backup gelöscht", f"Backup **{self.backup_label}** gelöscht.", COLOR_SUCCESS), view=None)
        else:
            await interaction.response.edit_message(embed=create_embed(f"{E.FAIL} Fehler", "Konnte nicht löschen.", COLOR_DANGER), view=None)
        await bot.log_action(interaction.guild, f"{E.DELETE} Backup gelöscht", f"Backup **{self.backup_label}** von {self.user.mention} gelöscht.", COLOR_WARNING, user=self.user, module="backup")

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary, emoji=E.FAIL)
    async def cancel_delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user.id:
            return
        await interaction.response.edit_message(embed=create_embed("🚫 Abgebrochen", "Backup wurde NICHT gelöscht.", COLOR_WARNING), view=None)

# ── Backup-Passwort setzen Modal ──────────────────────────────────
class BackupSetPasswordModal(discord.ui.Modal, title="🔐 Backup mit Passwort sichern"):
    password = discord.ui.TextInput(label="Passwort", placeholder="Sicheres Passwort eingeben...", style=discord.TextStyle.short, required=True, min_length=4, max_length=100)
    label = discord.ui.TextInput(label="Backup-Label (optional)", placeholder="z.B. Vor Server-Reset", style=discord.TextStyle.short, required=False, max_length=100)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        guild = interaction.guild
        backup_data = await _collect_backup_data(guild)
        pw_hash = _hash_password(self.password.value)
        backup_id = await _backup_db_save(backup_data, interaction.user.id, self.label.value or None, password_hash=pw_hash)
        if not backup_id:
            await interaction.followup.send(embed=create_embed(f"{E.FAIL} Fehler", "Backup konnte nicht gespeichert werden.", COLOR_DANGER))
            return
        stats = backup_data.get("stats", {})
        fields = [("Backup-ID", f"`{backup_id}`", True), ("🔐 Passwortgeschützt", "{E.OK} Ja", True), ("Label", self.label.value or "Automatisch", True), ("Rollen", str(len(backup_data.get("roles", []))), True), ("Kanäle", str(len(backup_data.get("channels", []))), True), ("Kategorien", str(len(backup_data.get("categories", []))), True)]
        await interaction.followup.send(embed=create_embed(f"{E.OK} Passwortgeschütztes Backup erstellt", f"Backup **{backup_id}** wurde mit Passwort gesichert.", COLOR_SUCCESS, fields))
        await bot.log_action(guild, f"{E.OK} Passwort-Backup erstellt", f"Backup `{backup_id}` (passwortgeschützt) von {interaction.user.mention}.", COLOR_SUCCESS, user=interaction.user, module="backup")

# ── Interaktives Backup-Dropdown-Menü ─────────────────────────────
class BackupMainDropdown(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="📦 Backup erstellen", value="create", description="Neues Backup des Servers erstellen", emoji="📦"),
            discord.SelectOption(label="🔐 Passwort-Backup erstellen", value="create_pw", description="Backup mit Passwort sichern", emoji="🔐"),
            discord.SelectOption(label="📋 Backups anzeigen", value="list", description="Alle Backups auflisten", emoji="📋"),
            discord.SelectOption(label="🔍 Backup-Details", value="info", description="Details zu einem Backup anzeigen", emoji="🔍"),
            discord.SelectOption(label=f"{E.REFRESH}️ Backup wiederherstellen", value="restore", description="Backup auf diesem Server restoren", emoji="{E.REFRESH}️"),
            discord.SelectOption(label="🌐 Cross-Server Restore", value="restore_cross", description="Backup von einem anderen Server restoren", emoji="🌐"),
            discord.SelectOption(label="🗑️ Backup löschen", value="delete", description="Ein Backup löschen", emoji="🗑️"),
            discord.SelectOption(label="💣 Alle Backups löschen", value="purge", description="ALLE Backups dieses Servers löschen", emoji="💣"),
            discord.SelectOption(label=f"{E.GEAR}️ Auto-Backup konfigurieren", value="autosetup", description="Automatische Backups einstellen", emoji="{E.GEAR}️"),
        ]
        super().__init__(placeholder="🔧 Backup-Aktion wählen...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val == "create":
            backup_data = await _collect_backup_data(interaction.guild)
            backup_id = await _backup_db_save(backup_data, interaction.user.id)
            if not backup_id:
                await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Fehler", "Backup fehlgeschlagen.", COLOR_DANGER), ephemeral=True)
                return
            stats = backup_data.get("stats", {})
            fields = [("Backup-ID", f"`{backup_id}`", True), ("Rollen", str(len(backup_data.get("roles", []))), True), ("Kanäle", str(len(backup_data.get("channels", []))), True), ("Kategorien", str(len(backup_data.get("categories", []))), True), ("Mitglieder", str(stats.get("total_members", "?")), True), ("Emojis", str(len(backup_data.get("emojis", []))), True)]
            await interaction.response.send_message(embed=create_embed(f"{E.OK} Backup erstellt", f"Backup **{backup_id}** gespeichert.", COLOR_SUCCESS, fields), ephemeral=True)
            await bot.log_action(interaction.guild, f"{E.OK} Backup erstellt", f"Backup `{backup_id}` von {interaction.user.mention}.", COLOR_SUCCESS, user=interaction.user, module="backup")
        elif val == "create_pw":
            await interaction.response.send_modal(BackupSetPasswordModal())
        elif val == "list":
            await interaction.response.defer(ephemeral=True)
            backups = await _backup_db_list(interaction.guild.id, limit=15)
            if not backups:
                await interaction.followup.send(embed=create_embed(f"{E.CHANNEL} Backups", "Keine Backups vorhanden.", COLOR_INFO), ephemeral=True)
                return
            fields = []
            for b in backups:
                ts = b.get("created_at")
                ts_text = f"<t:{int(ts.timestamp())}:R>" if isinstance(ts, datetime.datetime) else str(ts)
                pw_icon = " 🔐" if b.get("has_password") else ""
                fields.append((f"`{b.get('backup_id')}`{pw_icon} – {b.get('label', 'Ohne Label')}", f"Erstellt {ts_text} von <@{b.get('created_by')}>", False))
            await interaction.followup.send(embed=create_embed(f"{E.CHANNEL} Backups – {interaction.guild.name}", f"**{len(backups)}** Backups.", COLOR_PRIMARY, fields), ephemeral=True)
        elif val == "info":
            await interaction.response.send_message(embed=create_embed("🔍 Backup-Info", "Nutze `/backup_info <backup_id>` für Details.", COLOR_INFO), ephemeral=True)
        elif val == "restore":
            await interaction.response.send_message(embed=create_embed(f"{E.REFRESH}️ Backup Restore", "Nutze `/backup_restore <backup_id>` um ein Backup wiederherzustellen.", COLOR_INFO), ephemeral=True)
        elif val == "restore_cross":
            await interaction.response.send_message(embed=create_embed("🌐 Cross-Server Restore", "Nutze `/backup_restore_cross <backup_id>` um ein Backup von einem anderen Server zu laden.", COLOR_INFO), ephemeral=True)
        elif val == "delete":
            await interaction.response.send_message(embed=create_embed("🗑️ Backup löschen", "Nutze `/backup_delete <backup_id>`.", COLOR_INFO), ephemeral=True)
        elif val == "purge":
            await interaction.response.defer(ephemeral=True)
            collection = bot.db.client["ModForge"]["backups"]
            result = await collection.delete_many({"guild_id": interaction.guild.id})
            await interaction.followup.send(embed=create_embed(f"{E.DELETE} Alle Backups gelöscht", f"**{result.deleted_count}** Backups gelöscht.", COLOR_SUCCESS), ephemeral=True)
        elif val == "autosetup":
            await interaction.response.send_message(embed=create_embed(f"{E.GEAR}️ Auto-Backup", "Nutze `/backup_autosetup` für die Konfiguration.", COLOR_INFO), ephemeral=True)

class BackupMainView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)
        self.add_item(BackupMainDropdown())

# ═══════════════════════════════════════════════════════════════════
# BACKUP SLASH COMMANDS
# ═══════════════════════════════════════════════════════════════════
@bot.tree.command(name="backup", description="Interaktives Backup-Menü mit Dropdown")
@app_commands.default_permissions(administrator=True)
async def slash_backup_menu(interaction: discord.Interaction) -> None:
    embed = create_embed(f"{E.SHIELD} Backup-System", "Wähle eine Aktion aus dem Dropdown-Menü:\n\n📦 **Erstellen** – Backup ohne Passwort\n🔐 **Passwort-Backup** – Verschlüsselt mit Passwort\n📋 **Anzeigen** – Alle Backups listen\n{E.REFRESH}️ **Restore** – Auf diesem Server wiederherstellen\n🌐 **Cross-Server** – Backup von anderem Server laden\n🗑️ **Löschen** – Einzelnes oder alle Backups\n{E.GEAR}️ **Auto-Backup** – Automatische Backups konfigurieren", COLOR_PRIMARY,
        [("Tipp", "Passwort-Backups können auf **jedem Server** restored werden, wenn du das Passwort kennst!", False)],
        thumbnail=interaction.guild.icon.url if interaction.guild.icon else None)
    await interaction.response.send_message(embed=embed, view=BackupMainView(), ephemeral=True)

@bot.tree.command(name="backup_create", description="Erstellt ein vollständiges Backup des Servers")
@app_commands.describe(label="Optionales Label für das Backup")
@app_commands.default_permissions(administrator=True)
async def slash_backup_create(interaction: discord.Interaction, label: str = None) -> None:
    await interaction.response.defer()
    backup_data = await _collect_backup_data(interaction.guild)
    backup_id = await _backup_db_save(backup_data, interaction.user.id, label)
    if not backup_id:
        await interaction.followup.send(embed=create_embed(f"{E.FAIL} Fehler", "Backup fehlgeschlagen.", COLOR_DANGER))
        return
    stats = backup_data.get("stats", {})
    fields = [("Backup-ID", f"`{backup_id}`", True), ("Label", label or "Automatisch", True), ("Erstellt von", interaction.user.mention, True), ("Rollen", str(len(backup_data.get("roles", []))), True), ("Kanäle", str(len(backup_data.get("channels", []))), True), ("Kategorien", str(len(backup_data.get("categories", []))), True)]
    await interaction.followup.send(embed=create_embed(f"{E.OK} Backup erstellt", f"Backup **{backup_id}** gespeichert.", COLOR_SUCCESS, fields))
    await bot.log_action(interaction.guild, f"{E.OK} Backup erstellt", f"Backup `{backup_id}` von {interaction.user.mention}.", COLOR_SUCCESS, user=interaction.user, module="backup")

@bot.tree.command(name="backup_secure", description="Erstellt ein passwortgeschütztes Backup")
@app_commands.default_permissions(administrator=True)
async def slash_backup_secure(interaction: discord.Interaction) -> None:
    await interaction.response.send_modal(BackupSetPasswordModal())

@bot.tree.command(name="backup_list", description="Zeigt alle gespeicherten Backups")
@app_commands.default_permissions(administrator=True)
async def slash_backup_list(interaction: discord.Interaction) -> None:
    backups = await _backup_db_list(interaction.guild.id, limit=15)
    if not backups:
        await interaction.response.send_message(embed=create_embed(f"{E.CHANNEL} Backups", "Keine Backups. Nutze `/backup_create`.", COLOR_INFO), ephemeral=True)
        return
    fields = []
    for b in backups:
        ts = b.get("created_at")
        ts_text = f"<t:{int(ts.timestamp())}:R>" if isinstance(ts, datetime.datetime) else str(ts)
        pw_icon = " 🔐" if b.get("has_password") else ""
        fields.append((f"`{b.get('backup_id')}`{pw_icon} – {b.get('label', 'Ohne Label')}", f"Erstellt {ts_text} von <@{b.get('created_by')}>", False))
    await interaction.response.send_message(embed=create_embed(f"{E.CHANNEL} Backups – {interaction.guild.name}", f"**{len(backups)}** Backups.", COLOR_PRIMARY, fields), ephemeral=True)

@bot.tree.command(name="backup_info", description="Zeigt Details zu einem Backup")
@app_commands.describe(backup_id="Die Backup-ID")
@app_commands.default_permissions(administrator=True)
async def slash_backup_info(interaction: discord.Interaction, backup_id: str) -> None:
    await interaction.response.defer(ephemeral=True)
    doc = await _backup_db_get(interaction.guild.id, backup_id)
    if not doc:
        await interaction.followup.send(embed=create_embed(f"{E.FAIL} Nicht gefunden", f"Kein Backup `{backup_id}`.", COLOR_DANGER))
        return
    data = doc.get("data", {})
    stats = data.get("stats", {})
    ts = doc.get("created_at")
    ts_text = f"<t:{int(ts.timestamp())}:F>" if isinstance(ts, datetime.datetime) else str(ts)
    pw_status = "🔐 Ja" if doc.get("has_password") else "{E.FAIL} Nein"
    fields = [("Backup-ID", f"`{doc.get('backup_id')}`", True), ("Label", doc.get("label", "Ohne Label"), True), ("Erstellt", ts_text, True), ("Von", f"<@{doc.get('created_by')}>", True), ("Passwortgeschützt", pw_status, True), ("Rollen", str(len(data.get("roles", []))), True), ("Kanäle", str(len(data.get("channels", []))), True), ("Kategorien", str(len(data.get("categories", []))), True), ("Emojis", str(len(data.get("emojis", []))), True)]
    roles = data.get("roles", [])
    if roles:
        role_names = ", ".join(r["name"] for r in roles[:15])
        if len(roles) > 15:
            role_names += f" … +{len(roles)-15}"
        fields.append(("Gesicherte Rollen", role_names, False))
    await interaction.followup.send(embed=create_embed(f"{E.SHIELD} Backup-Info", f"Details zu **{backup_id}**", COLOR_INFO, fields))

@bot.tree.command(name="backup_restore", description="Stellt ein Backup auf diesem Server wieder her")
@app_commands.describe(backup_id="Die Backup-ID")
@app_commands.default_permissions(administrator=True)
async def slash_backup_restore(interaction: discord.Interaction, backup_id: str) -> None:
    doc = await _backup_db_get(interaction.guild.id, backup_id)
    if not doc:
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Nicht gefunden", f"Kein Backup `{backup_id}`.", COLOR_DANGER), ephemeral=True)
        return
    label = doc.get("label", backup_id)
    pw = doc.get("has_password", False)
    pw_text = "\n🔐 **Dieses Backup ist passwortgeschützt!** Du musst das Passwort eingeben." if pw else ""
    embed = create_embed(f"{E.ALERT}️ Backup-Restore bestätigen", f"Backup **{label}** (`{backup_id}`) wiederherstellen?\n\n> Fehlende Rollen/Kanäle werden **erstellt**\n> Bestehende werden **aktualisiert**\n> Nichts wird gelöscht{pw_text}", COLOR_DANGER)
    await interaction.response.send_message(embed=embed, view=BackupRestoreConfirmView(backup_id, label, interaction.guild, interaction.user, has_password=pw))

@bot.tree.command(name="backup_restore_cross", description="Stellt ein passwortgeschütztes Backup von einem anderen Server wieder her")
@app_commands.describe(backup_id="Die Backup-ID vom anderen Server")
@app_commands.default_permissions(administrator=True)
async def slash_backup_restore_cross(interaction: discord.Interaction, backup_id: str) -> None:
    doc = await _backup_db_get_any(backup_id)
    if not doc:
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Nicht gefunden", f"Kein Backup `{backup_id}` gefunden.", COLOR_DANGER), ephemeral=True)
        return
    label = doc.get("label", backup_id)
    source_name = doc.get("guild_name", "Unbekannt")
    if not doc.get("has_password"):
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Kein Passwort-Schutz", "Cross-Server-Restore erfordert ein passwortgeschütztes Backup. Erstelle es mit `/backup_secure`.", COLOR_WARNING), ephemeral=True)
        return
    embed = create_embed("🌐 Cross-Server Restore", f"Backup **{label}** vom Server **{source_name}** (`{backup_id}`).\n\n🔐 Gib das Passwort ein, um fortzufahren.", COLOR_PRIMARY)
    await interaction.response.send_message(embed=embed, view=BackupPasswordPromptView(backup_id, label, interaction.guild, interaction.user, source_guild_id=doc.get("guild_id")), ephemeral=True)

@bot.tree.command(name="backup_delete", description="Löscht ein Backup")
@app_commands.describe(backup_id="Die Backup-ID")
@app_commands.default_permissions(administrator=True)
async def slash_backup_delete(interaction: discord.Interaction, backup_id: str) -> None:
    doc = await _backup_db_get(interaction.guild.id, backup_id)
    if not doc:
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Nicht gefunden", f"Kein Backup `{backup_id}`.", COLOR_DANGER), ephemeral=True)
        return
    label = doc.get("label", backup_id)
    await interaction.response.send_message(embed=create_embed("🗑️ Backup löschen?", f"**{label}** (`{backup_id}`) wirklich löschen?", COLOR_DANGER), view=BackupDeleteConfirmView(backup_id, label, interaction.guild.id, interaction.user), ephemeral=True)

@bot.tree.command(name="backup_autosetup", description="Konfiguriert automatische Backups")
@app_commands.describe(enabled="Aktivieren/Deaktivieren", interval_hours="Intervall in Stunden", max_backups="Max. Anzahl")
@app_commands.choices(interval_hours=[app_commands.Choice(name="Alle 6 Stunden", value=6), app_commands.Choice(name="Alle 12 Stunden", value=12), app_commands.Choice(name="Täglich (24h)", value=24), app_commands.Choice(name="Alle 2 Tage (48h)", value=48)])
@app_commands.default_permissions(administrator=True)
async def slash_backup_autosetup(interaction: discord.Interaction, enabled: bool, interval_hours: int = 24, max_backups: int = 5) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    backup_cfg = cfg.get("backup_system", {}) or {}
    backup_cfg["auto_enabled"] = enabled
    backup_cfg["auto_interval_hours"] = interval_hours
    backup_cfg["auto_max_backups"] = max_backups
    cfg["backup_system"] = backup_cfg
    await bot.db.set_config(interaction.guild.id, cfg)
    status = f"{E.OK} **Aktiviert**" if enabled else f"{E.FAIL} **Deaktiviert**"
    embed = create_embed(f"{E.SETTINGS} Auto-Backup", "Automatische Backups aktualisiert.", COLOR_SUCCESS, [("Status", status, True), ("Intervall", f"{interval_hours}h", True), ("Max.", str(max_backups), True)])
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.SETTINGS} Auto-Backup {status}", f"{interaction.user.mention}: Intervall={interval_hours}h, Max={max_backups}", COLOR_INFO, user=interaction.user, module="backup")

@bot.tree.command(name="backup_purge", description="Löscht ALLE Backups dieses Servers")
@app_commands.default_permissions(administrator=True)
async def slash_backup_purge(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    collection = bot.db.client["ModForge"]["backups"]
    result = await collection.delete_many({"guild_id": interaction.guild.id})
    await interaction.followup.send(embed=create_embed(f"{E.DELETE} Gelöscht", f"**{result.deleted_count}** Backups gelöscht.", COLOR_SUCCESS))
    await bot.log_action(interaction.guild, f"{E.DELETE} Backup-Purge", f"{interaction.user.mention}: {result.deleted_count} Backups.", COLOR_WARNING, user=interaction.user, module="backup")

# ═══════════════════════════════════════════════════════════════════
# AUTO-BACKUP TASK
# ═══════════════════════════════════════════════════════════════════
@tasks.loop(minutes=30)
async def auto_backup_loop() -> None:
    now = discord.utils.utcnow()
    for guild in bot.guilds:
        try:
            cfg = bot.db.get_config(guild.id)
            backup_cfg = cfg.get("backup_system", {}) or {}
            if not backup_cfg.get("auto_enabled"):
                continue
            interval_hours = backup_cfg.get("auto_interval_hours", 24)
            last_backup_ts = backup_cfg.get("auto_last_backup")
            if last_backup_ts:
                try:
                    last_dt = datetime.datetime.fromisoformat(last_backup_ts.replace("Z", "")) if isinstance(last_backup_ts, str) else last_backup_ts
                except ValueError:
                    last_dt = datetime.datetime.min
                if (now - last_dt).total_seconds() / 3600 < interval_hours:
                    continue
            backup_data = await _collect_backup_data(guild)
            backup_id = await _backup_db_save(backup_data, bot.user.id, f"Auto-Backup ({now.strftime('%d.%m.%Y %H:%M')})")
            if backup_id:
                backup_cfg["auto_last_backup"] = now.isoformat() + "Z"
                cfg["backup_system"] = backup_cfg
                await bot.db.set_config(guild.id, cfg)
                max_backups = backup_cfg.get("auto_max_backups", 5)
                try:
                    collection = bot.db.client["ModForge"]["backups"]
                    all_bk = await collection.find({"guild_id": guild.id}, {"_id": 1}).sort("created_at", 1).to_list(1000)
                    if len(all_bk) > max_backups:
                        for old_b in all_bk[:-max_backups]:
                            await collection.delete_one({"_id": old_b["_id"]})
                except Exception:
                    pass
                await bot.log_action(guild, f"{E.OK} Auto-Backup", f"`{backup_id}` erstellt. Intervall: **{interval_hours}h**", COLOR_SUCCESS, module="backup")
        except Exception as e:
            log.error(f"Auto-Backup Loop Fehler für {guild.name}: {e}")

# ═══════════════════════════════════════════════════════════════════
# 1) WELCOME & LEAVE SYSTEM
# ═══════════════════════════════════════════════════════════════════
async def _send_welcome(member: discord.Member) -> None:
    cfg = bot.db.get_config(member.guild.id)
    wc = cfg.get("welcome", {})
    if not wc.get("enabled"):
        return
    channel_id = wc.get("channel_id")
    if not channel_id:
        return
    channel = member.guild.get_channel(int(channel_id))
    if not channel:
        return
    replacements = {
        "{mention}": member.mention, "{user}": str(member),
        "{server}": member.guild.name, "{count}": str(member.guild.member_count),
        "{name}": member.display_name, "{id}": str(member.id),
    }
    title = wc.get("embed_title", "👋 Willkommen!")
    desc = wc.get("embed_description", "")
    for k, v in replacements.items():
        title = title.replace(k, v)
        desc = desc.replace(k, v)
    color_hex = wc.get("embed_color", "#22c55e")
    try:
        color = int(color_hex.replace("#", ""), 16)
    except ValueError:
        color = COLOR_SUCCESS
    thumb = member.display_avatar.url if wc.get("embed_thumbnail", True) else None
    embed = create_embed(title, desc, color, thumbnail=thumb)
    if wc.get("embed_image"):
        embed.set_image(url=wc["embed_image"])
    # Welcome-Rollen geben
    add_roles_cfg = wc.get("add_roles", [])
    if add_roles_cfg:
        for r_id in add_roles_cfg:
            role = member.guild.get_role(int(r_id))
            if role:
                try:
                    await member.add_roles(role, reason="Welcome-Auto-Role")
                except (discord.Forbidden, discord.HTTPException):
                    pass
    try:
        await channel.send(content=member.mention if wc.get("mention", True) else None, embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass
    # DM senden
    if wc.get("dm_enabled") and wc.get("dm_description"):
        dm_text = wc["dm_description"]
        for k, v in replacements.items():
            dm_text = dm_text.replace(k, v)
        try:
            await member.send(dm_text)
        except (discord.Forbidden, discord.HTTPException):
            pass

async def _send_leave(member: discord.Member) -> None:
    cfg = bot.db.get_config(member.guild.id)
    lc = cfg.get("leave", {})
    if not lc.get("enabled"):
        return
    channel_id = lc.get("channel_id")
    if not channel_id:
        return
    channel = member.guild.get_channel(int(channel_id))
    if not channel:
        return
    replacements = {
        "{mention}": member.mention, "{user}": str(member),
        "{server}": member.guild.name, "{count}": str(member.guild.member_count),
        "{name}": member.display_name, "{id}": str(member.id),
    }
    title = lc.get("embed_title", "👋 Auf Wiedersehen!")
    desc = lc.get("embed_description", "")
    for k, v in replacements.items():
        title = title.replace(k, v)
        desc = desc.replace(k, v)
    color_hex = lc.get("embed_color", "#ef4444")
    try:
        color = int(color_hex.replace("#", ""), 16)
    except ValueError:
        color = COLOR_DANGER
    embed = create_embed(title, desc, color)
    if lc.get("embed_image"):
        embed.set_image(url=lc["embed_image"])
    try:
        await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass

# Welcome/Leave in on_member_join/remove einbinden
# Welcome Setup Dropdown
class WelcomeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(channel_types=[discord.ChannelType.text], placeholder="Kanal wählen...", max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        channel = self.values[0].resolve()
        if not channel:
            return
        cfg = bot.db.get_config(interaction.guild.id)
        wc = cfg.get("welcome", {})
        if not isinstance(wc, dict):
            wc = {}
        wc["channel_id"] = channel.id
        cfg["welcome"] = wc
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.edit_message(embed=create_embed(f"{E.OK} Welcome-Kanal gesetzt", f"Willkommens-Nachrichten werden in {channel.mention} gesendet.", COLOR_SUCCESS), view=None)

class WelcomeSetupView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)
    @discord.ui.button(label="Welcome-Kanal setzen", style=discord.ButtonStyle.primary, emoji="📢")
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("Wähle den Kanal:", view=discord.ui.View().add_item(WelcomeChannelSelect()), ephemeral=True)
    @discord.ui.button(label="Welcome aktivieren", style=discord.ButtonStyle.success, emoji=E.OK)
    async def enable(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cfg = bot.db.get_config(interaction.guild.id)
        wc = cfg.get("welcome", {})
        wc["enabled"] = True
        cfg["welcome"] = wc
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Welcome aktiviert", "Willkommens-Nachrichten sind jetzt aktiv.", COLOR_SUCCESS), ephemeral=True)
    @discord.ui.button(label="Leave-Kanal setzen", style=discord.ButtonStyle.secondary, emoji="👋")
    async def set_leave_ch(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("Wähle den Leave-Kanal:", view=discord.ui.View().add_item(LeaveChannelSelect()), ephemeral=True)
    @discord.ui.button(label="Leave aktivieren", style=discord.ButtonStyle.green, emoji="🚪")
    async def enable_leave(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        cfg = bot.db.get_config(interaction.guild.id)
        lc = cfg.get("leave", {})
        lc["enabled"] = True
        cfg["leave"] = lc
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Leave aktiviert", "Leave-Nachrichten sind jetzt aktiv.", COLOR_SUCCESS), ephemeral=True)

class LeaveChannelSelect(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(channel_types=[discord.ChannelType.text], placeholder="Leave-Kanal wählen...", max_values=1)
    async def callback(self, interaction: discord.Interaction) -> None:
        channel = self.values[0].resolve()
        if not channel:
            return
        cfg = bot.db.get_config(interaction.guild.id)
        lc = cfg.get("leave", {})
        lc["channel_id"] = channel.id
        cfg["leave"] = lc
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.edit_message(embed=create_embed(f"{E.OK} Leave-Kanal gesetzt", f"Leave-Nachrichten in {channel.mention}.", COLOR_SUCCESS), view=None)

@bot.tree.command(name="welcome_setup", description="Richtet das Welcome & Leave System ein")
@app_commands.default_permissions(administrator=True)
async def slash_welcome_setup(interaction: discord.Interaction) -> None:
    embed = create_embed("👋 Welcome & Leave Setup", "Konfiguriere Welcome- und Leave-Nachrichten.\n\nVariablen: `{mention}` `{user}` `{server}` `{count}` `{name}` `{id}`\n\nNutze das Web-Dashboard für den Embed-Builder mit Live-Vorschau.", COLOR_PRIMARY)
    await interaction.response.send_message(embed=embed, view=WelcomeSetupView(), ephemeral=True)

@bot.tree.command(name="welcome_channel", description="Setzt den Kanal für Willkommens-Nachrichten")
@app_commands.describe(channel="Der Welcome-Kanal")
@app_commands.default_permissions(administrator=True)
async def slash_welcome_channel(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    wc = cfg.get("welcome", {})
    wc["channel_id"] = channel.id
    cfg["welcome"] = wc
    await bot.db.set_config(interaction.guild.id, cfg)
    await interaction.response.send_message(embed=create_embed(f"{E.OK} Welcome-Kanal", f"Willkommens-Nachrichten in {channel.mention}.", COLOR_SUCCESS))

@bot.tree.command(name="leave_channel", description="Setzt den Kanal für Leave-Nachrichten")
@app_commands.describe(channel="Der Leave-Kanal")
@app_commands.default_permissions(administrator=True)
async def slash_leave_channel(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    lc = cfg.get("leave", {})
    lc["channel_id"] = channel.id
    cfg["leave"] = lc
    await bot.db.set_config(interaction.guild.id, cfg)
    await interaction.response.send_message(embed=create_embed(f"{E.OK} Leave-Kanal", f"Leave-Nachrichten in {channel.mention}.", COLOR_SUCCESS))

# ═══════════════════════════════════════════════════════════════════
# 2) AUTO-ROLE SYSTEM
# ═══════════════════════════════════════════════════════════════════
class AutoRoleDropdown(discord.ui.Select):
    def __init__(self, roles: list) -> None:
        options = [discord.SelectOption(label=r.name, value=str(r.id), emoji=E.LABEL) for r in roles[:25]]
        super().__init__(placeholder="Rolle(n) für Auto-Role wählen...", options=options, min_values=1, max_values=min(len(options), 10))
    async def callback(self, interaction: discord.Interaction) -> None:
        cfg = bot.db.get_config(interaction.guild.id)
        wc = cfg.get("welcome", {})
        wc["add_roles"] = [int(v) for v in self.values]
        cfg["welcome"] = wc
        await bot.db.set_config(interaction.guild.id, cfg)
        role_mentions = " ".join(f"<@&{v}>" for v in self.values)
        await interaction.response.edit_message(embed=create_embed(f"{E.OK} Auto-Rollen gesetzt", f"Neue Mitglieder erhalten: {role_mentions}", COLOR_SUCCESS), view=None)

class AutoRoleView(discord.ui.View):
    def __init__(self, roles: list) -> None:
        super().__init__(timeout=120)
        self.add_item(AutoRoleDropdown(roles))

@bot.tree.command(name="autorole", description="Setzt Rollen die neue Mitglieder automatisch erhalten")
@app_commands.describe(role="Rolle die automatisch gegeben wird (oder nutze Dropdown ohne Parameter)")
@app_commands.default_permissions(administrator=True)
async def slash_autorole(interaction: discord.Interaction, role: Optional[discord.Role] = None) -> None:
    if role:
        cfg = bot.db.get_config(interaction.guild.id)
        wc = cfg.get("welcome", {})
        roles_list = wc.get("add_roles", [])
        if role.id not in roles_list:
            roles_list.append(role.id)
        wc["add_roles"] = roles_list
        cfg["welcome"] = wc
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Auto-Role", f"{role.mention} wird neuen Mitgliedern gegeben.", COLOR_SUCCESS))
    else:
        manageable_roles = [r for r in interaction.guild.roles if not r.is_default() and not r.managed and r.position < interaction.guild.me.top_role.position]
        if not manageable_roles:
            await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Keine Rollen", "Keine verwaltbaren Rollen gefunden.", COLOR_DANGER), ephemeral=True)
            return
        await interaction.response.send_message(embed=create_embed(f"{E.LABEL} Auto-Role wählen", "Wähle eine oder mehrere Rollen:", COLOR_PRIMARY), view=AutoRoleView(manageable_roles), ephemeral=True)

@bot.tree.command(name="autorole_remove", description="Entfernt eine Auto-Role")
@app_commands.describe(role="Die zu entfernende Rolle")
@app_commands.default_permissions(administrator=True)
async def slash_autorole_remove(interaction: discord.Interaction, role: discord.Role) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    wc = cfg.get("welcome", {})
    roles_list = wc.get("add_roles", [])
    if role.id in roles_list:
        roles_list.remove(role.id)
        wc["add_roles"] = roles_list
        cfg["welcome"] = wc
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Entfernt", f"{role.mention} ist keine Auto-Role mehr.", COLOR_SUCCESS))
    else:
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Nicht gefunden", f"{role.mention} war keine Auto-Role.", COLOR_WARNING), ephemeral=True)

# ═══════════════════════════════════════════════════════════════════
# 3) CASES-LIST mit Pagination & Dropdown
# ═══════════════════════════════════════════════════════════════════
class CasesPageView(discord.ui.View):
    def __init__(self, cases: list, guild: discord.Guild, page: int = 0, per_page: int = 10) -> None:
        super().__init__(timeout=120)
        self.cases = cases
        self.guild = guild
        self.page = page
        self.per_page = per_page
        self.max_page = max(0, (len(cases) - 1) // per_page)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.children.clear()
        if self.page > 0:
            self.add_item(discord.ui.Button(label="◀️ Zurück", style=discord.ButtonStyle.secondary, custom_id="prev"))
        if self.page < self.max_page:
            self.add_item(discord.ui.Button(label="▶️ Weiter", style=discord.ButtonStyle.secondary, custom_id="next"))

    def _get_embed(self) -> discord.Embed:
        start = self.page * self.per_page
        end = start + self.per_page
        page_cases = self.cases[start:end]
        if not page_cases:
            return create_embed(f"{E.CHANNEL} Cases", "Keine Cases vorhanden.", COLOR_INFO)
        fields = []
        for c in page_cases:
            ts = c.get("created_at")
            ts_text = f"<t:{int(ts.timestamp())}:R>" if isinstance(ts, datetime.datetime) else "?"
            fields.append((f"Case #{c.get('case_id', '?')} – {c.get('action', '?').upper()}", f"<@{c.get('user_id', '?')}> | {c.get('reason', '—')[:60]} | {ts_text}", False))
        return create_embed(f"{E.CHANNEL} Cases – {self.guild.name} (Seite {self.page+1}/{self.max_page+1})", f"**{len(self.cases)}** Cases insgesamt.", COLOR_INFO, fields)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        log.error(f"CasesPageView Fehler: {error}")

    @discord.ui.button(label="◀️ Zurück", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._get_embed(), view=self)

    @discord.ui.button(label="▶️ Weiter", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = min(self.max_page, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._get_embed(), view=self)

@bot.tree.command(name="cases", description="Zeigt alle Cases mit Pagination")
@app_commands.describe(user="Optional: Nur Cases eines bestimmten Nutzers")
@app_commands.default_permissions(manage_messages=True)
async def slash_cases(interaction: discord.Interaction, user: Optional[discord.User] = None) -> None:
    await interaction.response.defer(ephemeral=True)
    if user:
        cases = await bot.db.aget_recent_cases(interaction.guild.id, limit=200)
        cases = [c for c in cases if c.get("user_id") == user.id]
    else:
        cases = await bot.db.aget_recent_cases(interaction.guild.id, limit=200)
    if not cases:
        await interaction.followup.send(embed=create_embed(f"{E.CHANNEL} Cases", "Keine Cases gefunden.", COLOR_INFO), ephemeral=True)
        return
    view = CasesPageView(cases, interaction.guild)
    await interaction.followup.send(embed=view._get_embed(), view=view, ephemeral=True)

# ═══════════════════════════════════════════════════════════════════
# 4) STICKY ROLES
# ═══════════════════════════════════════════════════════════════════
async def _save_sticky_roles(member: discord.Member) -> None:
    cfg = bot.db.get_config(member.guild.id)
    sticky_roles = cfg.get("sticky_roles", [])
    if not sticky_roles:
        return
    member_sticky = [r.id for r in member.roles if r.id in sticky_roles and not r.is_default() and not r.managed]
    if member_sticky:
        try:
            collection = bot.db.client["ModForge"]["sticky_roles"]
            await collection.update_one({"guild_id": member.guild.id, "user_id": member.id}, {"$set": {"roles": member_sticky, "saved_at": discord.utils.utcnow()}}, upsert=True)
        except Exception as e:
            log.error(f"Sticky-Roles Save Fehler: {e}")

async def _restore_sticky_roles(member: discord.Member) -> None:
    cfg = bot.db.get_config(member.guild.id)
    sticky_roles = cfg.get("sticky_roles", [])
    if not sticky_roles:
        return
    try:
        collection = bot.db.client["ModForge"]["sticky_roles"]
        doc = await collection.find_one({"guild_id": member.guild.id, "user_id": member.id})
        if doc and doc.get("roles"):
            for r_id in doc["roles"]:
                role = member.guild.get_role(r_id)
                if role and role.id in sticky_roles:
                    try:
                        await member.add_roles(role, reason="Sticky-Roles Restore")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
    except Exception as e:
        log.error(f"Sticky-Roles Restore Fehler: {e}")

class StickyRoleDropdown(discord.ui.Select):
    def __init__(self, roles: list, current_sticky: list) -> None:
        options = [discord.SelectOption(label=r.name, value=str(r.id), default=r.id in current_sticky, emoji="📌") for r in roles[:25]]
        super().__init__(placeholder="Sticky-Rollen wählen...", options=options, min_values=0, max_values=min(len(options), 10))
    async def callback(self, interaction: discord.Interaction) -> None:
        cfg = bot.db.get_config(interaction.guild.id)
        cfg["sticky_roles"] = [int(v) for v in self.values]
        await bot.db.set_config(interaction.guild.id, cfg)
        roles_text = " ".join(f"<@&{v}>" for v in self.values) if self.values else "Keine"
        await interaction.response.edit_message(embed=create_embed(f"{E.OK} Sticky-Rollen aktualisiert", f"Aktive Sticky-Rollen: {roles_text}", COLOR_SUCCESS), view=None)

class StickyRoleView(discord.ui.View):
    def __init__(self, roles: list, current_sticky: list) -> None:
        super().__init__(timeout=120)
        self.add_item(StickyRoleDropdown(roles, current_sticky))

@bot.tree.command(name="stickyrole", description="Konfiguriert Sticky-Rollen (werden nach Rejoin zurückgegeben)")
@app_commands.describe(role="Rolle als Sticky markieren (oder ohne Parameter für Dropdown)")
@app_commands.default_permissions(administrator=True)
async def slash_stickyrole(interaction: discord.Interaction, role: Optional[discord.Role] = None) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    sticky = cfg.get("sticky_roles", [])
    if role:
        if role.id not in sticky:
            sticky.append(role.id)
        cfg["sticky_roles"] = sticky
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Sticky-Role", f"{role.mention} ist jetzt eine Sticky-Role.", COLOR_SUCCESS))
    else:
        manageable = [r for r in interaction.guild.roles if not r.is_default() and not r.managed and r.position < interaction.guild.me.top_role.position]
        if not manageable:
            await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Keine Rollen", "Keine verwaltbaren Rollen.", COLOR_DANGER), ephemeral=True)
            return
        await interaction.response.send_message(embed=create_embed("📌 Sticky-Rollen", "Wähle Rollen die nach Rejoin zurückgegeben werden:", COLOR_PRIMARY), view=StickyRoleView(manageable, sticky), ephemeral=True)

@bot.tree.command(name="stickyrole_remove", description="Entfernt eine Sticky-Role")
@app_commands.describe(role="Die zu entfernende Rolle")
@app_commands.default_permissions(administrator=True)
async def slash_stickyrole_remove(interaction: discord.Interaction, role: discord.Role) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    sticky = cfg.get("sticky_roles", [])
    if role.id in sticky:
        sticky.remove(role.id)
        cfg["sticky_roles"] = sticky
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Entfernt", f"{role.mention} ist keine Sticky-Role mehr.", COLOR_SUCCESS))
    else:
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Nicht gefunden", f"{role.mention} ist keine Sticky-Role.", COLOR_WARNING), ephemeral=True)

# ═══════════════════════════════════════════════════════════════════
# 5) TEMPORARY VOICE CHANNELS
# ═══════════════════════════════════════════════════════════════════
class TempVoiceDropdown(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="🎤 Kanal erstellen", value="create", description="Temp-Voice-Setup starten", emoji="🎤"),
            discord.SelectOption(label=f"{E.GEAR}️ Einstellungen", value="settings", description="Temp-Voice konfigurieren", emoji="{E.GEAR}️"),
            discord.SelectOption(label="🗑️ Setup entfernen", value="remove", description="Temp-Voice deaktivieren", emoji="🗑️"),
        ]
        super().__init__(placeholder="Temp-Voice Aktion...", options=options, min_values=1, max_values=1)
    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        if val == "create":
            await interaction.response.send_message(embed=create_embed("🎤 Temp-Voice Setup", "Nutze `/tempvoice_setup <channel>` um einen Join-to-Create Kanal einzurichten.", COLOR_INFO), ephemeral=True)
        elif val == "settings":
            cfg = bot.db.get_config(interaction.guild.id)
            tv = cfg.get("temp_voice", {})
            fields = [("Aktiviert", f"{'{E.OK}' if tv.get('enabled') else '{E.FAIL}'}", True), ("Join-Kanal", f"<#{tv.get('channel_id')}>" if tv.get('channel_id') else "Nicht gesetzt", True), ("Kategorie", f"<#{tv.get('category_id')}>" if tv.get('category_id') else "Auto", True)]
            await interaction.response.edit_message(embed=create_embed(f"{E.GEAR}️ Temp-Voice Einstellungen", "", COLOR_INFO, fields), view=None)
        elif val == "remove":
            cfg = bot.db.get_config(interaction.guild.id)
            cfg["temp_voice"] = {"enabled": False}
            await bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.edit_message(embed=create_embed(f"{E.OK} Temp-Voice deaktiviert", "Temporäre Voice-Kanäle sind jetzt deaktiviert.", COLOR_SUCCESS), view=None)

class TempVoiceMenuView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)
        self.add_item(TempVoiceDropdown())

@bot.tree.command(name="tempvoice", description="Interaktives Temp-Voice Menü")
@app_commands.default_permissions(administrator=True)
async def slash_tempvoice_menu(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=create_embed("🎤 Temp-Voice System", "Wähle eine Aktion:", COLOR_PRIMARY), view=TempVoiceMenuView(), ephemeral=True)

@bot.tree.command(name="tempvoice_setup", description="Richtet temporäre Voice-Kanäle ein")
@app_commands.describe(channel="Der Join-to-Create Kanal", category="Kategorie für temporäre Kanäle")
@app_commands.default_permissions(administrator=True)
async def slash_tempvoice_setup(interaction: discord.Interaction, channel: discord.VoiceChannel, category: Optional[discord.CategoryChannel] = None) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    cfg["temp_voice"] = {"enabled": True, "channel_id": channel.id, "category_id": category.id if category else None}
    await bot.db.set_config(interaction.guild.id, cfg)
    embed = create_embed(f"{E.OK} Temp-Voice eingerichtet", f"Join-to-Create: {channel.mention}\nKategorie: {category.mention if category else 'Automatisch'}", COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.OK} Temp-Voice Setup", f"{channel.mention} als Join-to-Create von {interaction.user.mention}.", COLOR_SUCCESS, user=interaction.user, module="moderation")

# ═══════════════════════════════════════════════════════════════════
# 8) MASS-BAN COMMAND
# ═══════════════════════════════════════════════════════════════════
class MassBanConfirmView(discord.ui.View):
    def __init__(self, user_ids: list, reason: str, user: discord.Member) -> None:
        super().__init__(timeout=60)
        self.user_ids = user_ids
        self.reason = reason
        self.user = user

    @discord.ui.button(label="Ja, alle Bannen", style=discord.ButtonStyle.danger, emoji="🔨")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user.id:
            return
        await interaction.response.defer()
        banned = 0
        failed = 0
        for uid in self.user_ids:
            try:
                target = await interaction.guild.fetch_member(uid)
                await target.ban(reason=f"Mass-Ban: {self.reason} (durch {interaction.user})")
                banned += 1
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                failed += 1
            await asyncio.sleep(0.5)
        embed = create_embed(f"{E.BAN} Mass-Ban abgeschlossen", f"**{banned}** gebannt, **{failed}** fehlgeschlagen.", COLOR_DANGER if banned > 0 else COLOR_WARNING)
        await interaction.followup.send(embed=embed)
        await bot.log_action(interaction.guild, f"{E.BAN} Mass-Ban", f"{interaction.user.mention} hat {banned} Nutzer gebannt: {self.reason}", COLOR_DANGER, user=interaction.user, module="moderation")

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary, emoji=E.FAIL)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user.id:
            return
        await interaction.response.edit_message(embed=create_embed("🚫 Abgebrochen", "Mass-Ban nicht ausgeführt.", COLOR_WARNING), view=None)

@bot.tree.command(name="massban", description="Bannt mehrere Nutzer gleichzeitig")
@app_commands.describe(user_ids="Komma-getrennte User-IDs (z.B. 123,456,789)", reason="Grund für den Mass-Ban")
@app_commands.default_permissions(ban_members=True)
async def slash_massban(interaction: discord.Interaction, user_ids: str, reason: str = "Mass-Ban") -> None:
    id_list = []
    for part in re.split(r'[,;\s]+', user_ids.strip()):
        part = part.strip()
        if part.isdigit():
            id_list.append(int(part))
    if not id_list:
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Fehler", "Keine gültigen IDs gefunden.", COLOR_DANGER), ephemeral=True)
        return
    if len(id_list) > 50:
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Zu viele", "Max. 50 Nutzer pro Mass-Ban.", COLOR_DANGER), ephemeral=True)
        return
    id_text = ", ".join(f"`{uid}`" for uid in id_list[:10])
    if len(id_list) > 10:
        id_text += f" … +{len(id_list)-10}"
    embed = create_embed(f"{E.ALERT}️ Mass-Ban bestätigen", f"**{len(id_list)} Nutzer** werden gebannt.\nGrund: {reason}\nIDs: {id_text}", COLOR_DANGER)
    await interaction.response.send_message(embed=embed, view=MassBanConfirmView(id_list, reason, interaction.user))

# ═══════════════════════════════════════════════════════════════════
# 10) REACTION ROLES
# ═══════════════════════════════════════════════════════════════════
class ReactionRoleDropdown(discord.ui.Select):
    def __init__(self, roles: list) -> None:
        options = [discord.SelectOption(label=r.name, value=str(r.id), emoji="🎭") for r in roles[:25]]
        super().__init__(placeholder="Rolle(n) wählen...", options=options, min_values=1, max_values=min(len(options), 10))
    async def callback(self, interaction: discord.Interaction) -> None:
        selected_roles = self.values
        role_mentions = " ".join(f"<@&{r}>" for r in selected_roles)
        await interaction.response.edit_message(embed=create_embed(f"{E.OK} Rollen erhalten", f"Dir wurden folgende Rollen gegeben: {role_mentions}", COLOR_SUCCESS), view=None)
        for r_id in selected_roles:
            role = interaction.guild.get_role(int(r_id))
            if role:
                try:
                    await interaction.user.add_roles(role, reason="Reaction Role (Dropdown)")
                except (discord.Forbidden, discord.HTTPException):
                    pass

class ReactionRoleView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Wähle eine Rolle...", min_values=1, max_values=1, custom_id="modforge:reactionrole_select")
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect) -> None:
        role = select.values[0]
        if role.managed or role.is_default():
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Diese Rolle kann nicht vergeben werden.", color=COLOR_DANGER), ephemeral=True)
            return
        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Reaction Role (abgewählt)")
                await interaction.response.send_message(embed=create_embed(f"{E.OK} Rolle entfernt", f"{role.mention} wurde entfernt.", COLOR_WARNING), ephemeral=True)
            else:
                await interaction.user.add_roles(role, reason="Reaction Role")
                await interaction.response.send_message(embed=create_embed(f"{E.OK} Rolle erhalten", f"{role.mention} wurde dir gegeben.", COLOR_SUCCESS), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"{E.FAIL} Keine Berechtigung.", color=COLOR_DANGER), ephemeral=True)

@bot.tree.command(name="reactionrole", description="Erstellt eine Reaction-Role Nachricht mit Dropdown")
@app_commands.describe(channel="Kanal für die Reaction-Role Nachricht", title="Titel der Nachricht", description="Beschreibung der Nachricht")
@app_commands.default_permissions(administrator=True)
async def slash_reactionrole(interaction: discord.Interaction, channel: discord.TextChannel, title: str = "🎭 Wähle deine Rollen", description: str = "Klicke auf das Dropdown um Rollen zu erhalten oder zu entfernen.") -> None:
    embed = create_embed(title, description, COLOR_PRIMARY, [("Anleitung", "Nutze das Dropdown unten um Rollen zu togglen.", False)],
        thumbnail=interaction.guild.icon.url if interaction.guild.icon else None)
    view = ReactionRoleView()
    try:
        msg = await channel.send(embed=embed, view=view)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Reaction-Role erstellt", f"Nachricht in {channel.mention}: [Link]({msg.jump_url})", COLOR_SUCCESS))
        await bot.log_action(interaction.guild, f"{E.OK} Reaction-Role", f"Dropdown in {channel.mention} von {interaction.user.mention}.", COLOR_SUCCESS, user=interaction.user, module="moderation")
    except discord.Forbidden:
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Keine Rechte", "Ich darf dort keine Nachrichten senden.", COLOR_DANGER), ephemeral=True)

# ═══════════════════════════════════════════════════════════════════
# 11) USERINFO (Slash + Prefix)
# ═══════════════════════════════════════════════════════════════════
async def _userinfo_logic(guild, target, requester):
    """Shared logic for /userinfo and !userinfo"""
    if not target:
        target = requester
    joined = f"<t:{int(target.joined_at.timestamp())}:R>" if target.joined_at else "Unbekannt"
    created = f"<t:{int(target.created_at.timestamp())}:R>"
    age_days = (discord.utils.utcnow() - target.created_at).days
    roles = [r.mention for r in target.roles if r != guild.default_role][:20]
    roles_str = ", ".join(roles) if roles else "Keine"

    # Cases count
    case_count = 0
    warn_count = 0
    try:
        case_count = await bot.db.cases.count_documents({"guild_id": str(guild.id), "user_id": str(target.id)}) or 0
        warns = await bot.db.aget_warnings(guild.id, target.id)
        warn_count = len(warns) if warns else 0
    except Exception:
        pass

    # Risk score
    risk = 0
    if age_days < 7: risk += 30
    elif age_days < 30: risk += 15
    if not target.avatar: risk += 10
    if warn_count > 0: risk += min(warn_count * 10, 30)
    if case_count > 0: risk += min(case_count * 5, 20)
    risk = min(risk, 100)
    risk_color = E.GREEN if risk < 25 else E.YELLOW if risk < 50 else E.ORANGE if risk < 75 else E.RED

    timeout_str = "Nein"
    if target.timed_out_until and target.timed_out_until > discord.utils.utcnow():
        timeout_str = f"Ja (bis <t:{int(target.timed_out_until.timestamp())}:R>)"

    # Voice status
    voice_str = "Nicht im Voice"
    if target.voice and target.voice.channel:
        v = target.voice
        flags = []
        if v.mute or v.self_mute: flags.append("🔇 Muted")
        if v.deaf or v.self_deaf: flags.append("🔇 Deafened")
        if v.self_stream: flags.append("📺 Streaming")
        if v.self_video: flags.append("📹 Kamera")
        voice_str = f"{v.channel.mention}" + (f" ({', '.join(flags)})" if flags else "")

    fields = [
        ("📅 Erstellt", created, True),
        ("📥 Beigetreten", joined, True),
        (f"{risk_color} Risk-Score", f"{risk}/100", True),
        (f"{E.ALERT}️ Warns", str(warn_count), True),
        ("📋 Cases", str(case_count), True),
        ("⏳ Timeout", timeout_str, True),
        ("🎤 Voice", voice_str, False),
        (f"{E.LABEL} Rollen ({len(roles)})", roles_str, False),
    ]
    embed = create_embed(
        f"{E.USERS} User Info – {target.display_name}",
        f"{target.mention} (`{target.id}`)",
        COLOR_INFO, fields,
        thumbnail=target.display_avatar.url
    )
    if target.banner:
        embed.set_image(url=target.banner.url)
    return embed

# ═══════════════════════════════════════════════════════════════════
# 12) SERVERINFO (Slash + Prefix)
# ═══════════════════════════════════════════════════════════════════
async def _serverinfo_logic(guild):
    created = f"<t:{int(guild.created_at.timestamp())}:R>"
    text_ch = len([c for c in guild.channels if isinstance(c, discord.TextChannel)])
    voice_ch = len([c for c in guild.channels if isinstance(c, discord.VoiceChannel)])
    cats = len(guild.categories)
    bots = sum(1 for m in guild.members if m.bot)
    humans = guild.member_count - bots
    online = sum(1 for m in guild.members if m.status != discord.Status.offline) if guild.chunked else "?"
    boosts = guild.premium_subscription_count or 0
    boost_tier = guild.premium_tier
    roles_count = len(guild.roles) - 1
    emojis_count = len(guild.emojis)

    # ModForge stats
    cfg = bot.db.get_config(guild.id)
    active_mods = sum(1 for k in ["anti_spam","anti_nuke","anti_raid","anti_mention","automod","anti_scam"]
                      if cfg.get(k, {}).get("enabled"))
    sec_level = cfg.get("security_level", 0)

    fields = [
        ("👑 Owner", f"{guild.owner.mention}" if guild.owner else "?", True),
        ("📅 Erstellt", created, True),
        ("🔐 Verif.-Level", str(guild.verification_level).title(), True),
        ("👥 Mitglieder", f"{humans:,} Humans + {bots:,} Bots", True),
        (f"{E.GREEN} Online", str(online), True),
        ("💎 Boosts", f"{boosts} (Tier {boost_tier})", True),
        ("{E.FOLDER} Kanäle", f"{E.TEXT} {text_ch} Text · {E.VOICE} {voice_ch} Voice · {E.CATEGORY} {cats} Kategorien", False),
        (f"{E.LABEL} Rollen", str(roles_count), True),
        ("😀 Emojis", str(emojis_count), True),
        ("🛡️ ModForge", f"{active_mods}/6 Module aktiv · Security Level {sec_level}", False),
    ]
    embed = create_embed(
        f"{E.SERVER} Server Info – {guild.name}",
        f"ID: `{guild.id}`",
        COLOR_PRIMARY, fields,
        thumbnail=guild.icon.url if guild.icon else None
    )
    if guild.banner:
        embed.set_image(url=guild.banner.url)
    return embed

# ═══════════════════════════════════════════════════════════════════
# 13) MODSTATS (Slash + Prefix)
# ═══════════════════════════════════════════════════════════════════
async def _modstats_logic(guild, moderator=None):
    db = bot.db
    query = {"guild_id": str(guild.id)}
    if moderator:
        query["moderator_id"] = str(moderator.id)

    cases_raw = []
    try:
        cases_raw = await db.cases.find(query).sort("timestamp", -1).to_list(1000) or []
    except Exception:
        pass

    if moderator:
        bans = sum(1 for c in cases_raw if c.get("action") == "ban")
        kicks = sum(1 for c in cases_raw if c.get("action") == "kick")
        warns = sum(1 for c in cases_raw if c.get("action") == "warn")
        mutes = sum(1 for c in cases_raw if c.get("action") in ("timeout", "mute", "tempmute"))
        total = len(cases_raw)
        last_case = cases_raw[0] if cases_raw else None
        last_str = f"<t:{int(last_case['timestamp'].timestamp())}:R>" if last_case and last_case.get("timestamp") else "Keine"

        fields = [
            ("🔨 Bans", str(bans), True),
            ("👢 Kicks", str(kicks), True),
            (f"{E.ALERT}️ Warns", str(warns), True),
            ("🔇 Mutes", str(mutes), True),
            ("📋 Gesamt", str(total), True),
            ("🕐 Letzter Case", last_str, True),
        ]
        return create_embed(
            f"📊 Mod-Stats – {moderator.display_name}",
            f"Statistiken für {moderator.mention}",
            COLOR_INFO, fields, thumbnail=moderator.display_avatar.url
        )
    else:
        # All mods ranking
        mod_counts = defaultdict(int)
        for c in cases_raw:
            mid = c.get("moderator_id")
            if mid:
                mod_counts[mid] += 1

        sorted_mods = sorted(mod_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ranking = ""
        for i, (mid, count) in enumerate(sorted_mods, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"`{i}.`"
            ranking += f"{medal} <@{mid}> — **{count}** Cases\n"

        if not ranking:
            ranking = "Noch keine Moderation-Aktionen."

        return create_embed(
            f"📊 Mod-Ranking – {guild.name}",
            f"**{len(cases_raw)}** Cases insgesamt\n\n{ranking}",
            COLOR_PRIMARY
        )

# ═══════════════════════════════════════════════════════════════════
# 14) SOFTBAN (Slash + Prefix)
# ═══════════════════════════════════════════════════════════════════
async def _softban_logic(guild, moderator, target, reason, days=1):
    if not can_moderate(moderator, target):
        return create_embed(f"{E.FAIL} Fehler", "Du kannst diesen User nicht bestrafen.", COLOR_DANGER)
    try:
        await target.ban(reason=f"Softban: {reason} (durch {moderator})", delete_message_seconds=days * 86400)
        await guild.unban(target, reason="Softban (auto-unban)")
        case_id = await bot.db.acreate_case(guild.id, target.id, moderator.id, "softban", reason)
        await bot.log_action(guild, "🔨 Softban", f"{target.mention} wurde von {moderator.mention} softgebannt.\nGrund: {reason}\nNachrichten: {days} Tag(e) gelöscht", COLOR_DANGER, user=target, module="moderation")
        return create_embed(f"{E.OK} Softban", f"{target.mention} wurde softgebannt.\nGrund: {reason}\nCase: #{case_id}", COLOR_SUCCESS)
    except discord.Forbidden:
        return create_embed(f"{E.FAIL} Fehler", "Keine Berechtigung.", COLOR_DANGER)
    except discord.HTTPException as ex:
        return create_embed(f"{E.FAIL} Fehler", f"Discord-Fehler: {ex}", COLOR_DANGER)

# ═══════════════════════════════════════════════════════════════════
# 15) REPORT SYSTEM (Slash + Prefix)
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# 16) INVITE TRACKER (Slash + Prefix)
# ═══════════════════════════════════════════════════════════════════
@bot.tree.command(name="invites_leaderboard", description="Zeigt Invite-Leaderboard")
@app_commands.default_permissions(manage_guild=True)
async def slash_invites_lb(interaction: discord.Interaction) -> None:
    try:
        invites = await interaction.guild.invites()
        inv_counts = defaultdict(int)
        for i in invites:
            if i.inviter:
                inv_counts[i.inviter.id] += i.uses
        sorted_inv = sorted(inv_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        lb = ""
        for idx, (uid, count) in enumerate(sorted_inv, 1):
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"`{idx}.`"
            lb += f"{medal} <@{uid}> — **{count}** Einladungen\n"
        if not lb:
            lb = "Keine Invites gefunden."
        await interaction.response.send_message(embed=create_embed("📨 Invite Leaderboard", lb, COLOR_PRIMARY))
    except discord.Forbidden:
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Keine Berechtigung.", COLOR_DANGER), ephemeral=True)

# ═══════════════════════════════════════════════════════════════════
# 17) LOCKALL / UNLOCKALL (Slash + Prefix)
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# 18) AUTO-RESPONSE SYSTEM
# ═══════════════════════════════════════════════════════════════════
@bot.tree.command(name="autoresponse_add", description="Fügt eine Auto-Response hinzu")
@app_commands.describe(trigger="Trigger-Wort/Phrase", response="Die Antwort die gesendet wird")
@app_commands.default_permissions(administrator=True)
async def slash_ar_add(interaction: discord.Interaction, trigger: str, response: str) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    ars = cfg.get("auto_responses", [])
    ars.append({"trigger": trigger.lower(), "response": response, "enabled": True})
    cfg["auto_responses"] = ars
    await bot.db.set_config(interaction.guild.id, cfg)
    await interaction.response.send_message(embed=create_embed(f"{E.OK} Auto-Response hinzugefügt", f"Trigger: `{trigger}`\nAntwort: {response}", COLOR_SUCCESS))

@bot.tree.command(name="autoresponse_list", description="Zeigt alle Auto-Responses")
@app_commands.default_permissions(manage_messages=True)
async def slash_ar_list(interaction: discord.Interaction) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    ars = cfg.get("auto_responses", [])
    if not ars:
        return await interaction.response.send_message(embed=create_embed("📝 Auto-Responses", "Keine eingerichtet. Nutze `/autoresponse_add`.", COLOR_INFO))
    listing = ""
    for i, ar in enumerate(ars, 1):
        status = E.OK if ar.get("enabled", True) else E.FAIL
        listing += f"`{i}.` {status} **{ar['trigger']}** → {ar['response'][:60]}\n"
    await interaction.response.send_message(embed=create_embed("📝 Auto-Responses", listing, COLOR_INFO))

@bot.tree.command(name="autoresponse_del", description="Löscht eine Auto-Response (Index aus /autoresponse_list)")
@app_commands.describe(index="Index der zu löschenden Response")
@app_commands.default_permissions(administrator=True)
async def slash_ar_del(interaction: discord.Interaction, index: int) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    ars = cfg.get("auto_responses", [])
    if index < 1 or index > len(ars):
        return await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Ungültiger Index. Nutze `/autoresponse_list`.", COLOR_DANGER), ephemeral=True)
    removed = ars.pop(index - 1)
    cfg["auto_responses"] = ars
    await bot.db.set_config(interaction.guild.id, cfg)
    await interaction.response.send_message(embed=create_embed(f"{E.OK} Gelöscht", f"Trigger `{removed['trigger']}` entfernt.", COLOR_SUCCESS))

# ═══════════════════════════════════════════════════════════════════
# 19) WARN-DECAY SYSTEM
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# 20) NO-PREFIX MODE + AUTO-RESPONSE IN on_message
# ═══════════════════════════════════════════════════════════════════
# This is handled by injecting into the existing on_message handler.
# We patch it via a listener instead:

# ═══════════════════════════════════════════════════════════════════
# 21) NO-PREFIX SETUP
# ═══════════════════════════════════════════════════════════════════
@bot.tree.command(name="noprefix_add", description="Fügt einen User zur No-Prefix-Whitelist hinzu")
@app_commands.describe(member="User der No-Prefix nutzen darf")
@app_commands.default_permissions(administrator=True)
async def slash_noprefix_add(interaction: discord.Interaction, member: discord.Member) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    np_users = cfg.get("no_prefix_users", [])
    uid = str(member.id)
    if uid not in [str(u) for u in np_users]:
        np_users.append(member.id)
    cfg["no_prefix_users"] = np_users
    cfg["no_prefix"] = True
    await bot.db.set_config(interaction.guild.id, cfg)
    await interaction.response.send_message(embed=create_embed(f"{E.OK}", f"{member.mention} kann jetzt No-Prefix nutzen.", COLOR_SUCCESS))

@bot.tree.command(name="noprefix_remove", description="Entfernt einen User von der No-Prefix-Whitelist")
@app_commands.describe(member="User entfernen")
@app_commands.default_permissions(administrator=True)
async def slash_noprefix_remove(interaction: discord.Interaction, member: discord.Member) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    np_users = cfg.get("no_prefix_users", [])
    np_users = [u for u in np_users if str(u) != str(member.id)]
    cfg["no_prefix_users"] = np_users
    await bot.db.set_config(interaction.guild.id, cfg)
    await interaction.response.send_message(embed=create_embed(f"{E.OK}", f"{member.mention} von No-Prefix entfernt.", COLOR_WARNING))

@bot.tree.command(name="noprefix_list", description="Zeigt die No-Prefix-Whitelist")
@app_commands.default_permissions(administrator=True)
async def slash_noprefix_list(interaction: discord.Interaction) -> None:
    cfg = bot.db.get_config(interaction.guild.id)
    np_users = cfg.get("no_prefix_users", [])
    enabled = cfg.get("no_prefix", False)
    if not enabled:
        return await interaction.response.send_message(embed=create_embed(f"{E.GEAR}️ No-Prefix", "No-Prefix ist **deaktiviert**. `/noprefix true` zum Aktivieren.", COLOR_WARNING))
    if not np_users:
        desc = "**Modus:** Alle mit `Manage Messages`\n\nNutze `/noprefix_add @User` für eine Whitelist."
    else:
        user_list = "\n".join(f"• <@{u}>" for u in np_users)
        desc = f"**Modus:** Whitelist ({len(np_users)} User)\n\n{user_list}"
    await interaction.response.send_message(embed=create_embed(f"{E.GEAR}️ No-Prefix Whitelist", desc, COLOR_INFO))

# ═══════════════════════════════════════════════════════════════════
# PREFIX MIRRORS — Fehlende Prefix-Pendants für wichtige Commands
# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════
# AUTO BAN-APPEAL SYSTEM
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# NEW: /note — Interne Moderator-Notizen
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
_snipe_cache = {}  # guild_id -> {channel_id: (message, timestamp)}

# ═══════════════════════════════════════════════════════════════════
# NEW: /poll — Abstimmung
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# NEW: /raidmode — Manueller Raid-Modus
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# NEW: Erweiterte /purge Varianten
# ═══════════════════════════════════════════════════════════════════
@bot.tree.command(name="purge_user", description="Löscht Nachrichten eines bestimmten Users")
@app_commands.describe(member="User", amount="Anzahl zu prüfender Nachrichten")
@app_commands.default_permissions(manage_messages=True)
async def slash_purge_user(interaction: discord.Interaction, member: discord.Member, amount: int = 100) -> None:
    await interaction.response.defer(ephemeral=True)
    amount = min(amount, 500)
    deleted = await interaction.channel.purge(limit=amount, check=lambda m: m.author.id == member.id)
    await interaction.followup.send(embed=create_embed(f"{E.DELETE}", f"**{len(deleted)}** Nachrichten von {member.mention} gelöscht.", COLOR_SUCCESS))
    await bot.log_action(interaction.guild, f"{E.DELETE} Purge User", f"{interaction.user.mention} hat {len(deleted)} Nachrichten von {member.mention} gelöscht.", COLOR_WARNING, user=interaction.user, module="moderation")

@bot.tree.command(name="purge_bots", description="Löscht nur Bot-Nachrichten")
@app_commands.describe(amount="Anzahl")
@app_commands.default_permissions(manage_messages=True)
async def slash_purge_bots(interaction: discord.Interaction, amount: int = 100) -> None:
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=min(amount, 500), check=lambda m: m.author.bot)
    await interaction.followup.send(embed=create_embed(f"{E.DELETE}", f"**{len(deleted)}** Bot-Nachrichten gelöscht.", COLOR_SUCCESS))

@bot.tree.command(name="purge_links", description="Löscht nur Nachrichten mit Links")
@app_commands.describe(amount="Anzahl")
@app_commands.default_permissions(manage_messages=True)
async def slash_purge_links(interaction: discord.Interaction, amount: int = 100) -> None:
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=min(amount, 500), check=lambda m: "http" in m.content.lower())
    await interaction.followup.send(embed=create_embed(f"{E.DELETE}", f"**{len(deleted)}** Link-Nachrichten gelöscht.", COLOR_SUCCESS))

@bot.tree.command(name="purge_images", description="Löscht nur Nachrichten mit Bildern/Dateien")
@app_commands.describe(amount="Anzahl")
@app_commands.default_permissions(manage_messages=True)
async def slash_purge_images(interaction: discord.Interaction, amount: int = 100) -> None:
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=min(amount, 500), check=lambda m: len(m.attachments) > 0)
    await interaction.followup.send(embed=create_embed(f"{E.DELETE}", f"**{len(deleted)}** Bild/Datei-Nachrichten gelöscht.", COLOR_SUCCESS))

@bot.command(name="purge")
@commands.has_permissions(manage_messages=True)
async def prefix_purge(ctx, target: str = None, amount: int = 50):
    """!purge [user @User|bots|links|images|amount] [amount]"""
    if target and target.isdigit():
        amount = int(target)
        target = None
    amount = min(max(amount, 1), 500)
    check_fn = None
    label = "Nachrichten"
    if target == "bots":
        check_fn = lambda m: m.author.bot
        label = "Bot-Nachrichten"
    elif target == "links":
        check_fn = lambda m: "http" in m.content.lower()
        label = "Link-Nachrichten"
    elif target == "images":
        check_fn = lambda m: len(m.attachments) > 0
        label = "Bild-Nachrichten"
    elif target and target.startswith("<@"):
        uid = int(target.strip("<@!>"))
        check_fn = lambda m: m.author.id == uid
        label = f"Nachrichten von <@{uid}>"
    try:
        await ctx.message.delete()
    except Exception:
        pass
    deleted = await ctx.channel.purge(limit=amount, check=check_fn)
    msg = await ctx.send(embed=create_embed(f"{E.DELETE}", f"**{len(deleted)}** {label} gelöscht.", COLOR_SUCCESS))
    await asyncio.sleep(5)
    try:
        await msg.delete()
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# NEW: ANTI-VPN — VPN/Proxy-Erkennung bei Join
# ═══════════════════════════════════════════════════════════════════
_vpn_api_cache: Dict[str, bool] = {}

async def _check_vpn(ip: str) -> bool:
    """Prüft ob eine IP ein VPN/Proxy ist (via ip-api.com)."""
    if ip in _vpn_api_cache:
        return _vpn_api_cache[ip]
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://ip-api.com/json/{ip}?fields=proxy,hosting",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    is_vpn = data.get("proxy", False) or data.get("hosting", False)
                    _vpn_api_cache[ip] = is_vpn
                    # Cleanup cache
                    if len(_vpn_api_cache) > 5000:
                        keys = list(_vpn_api_cache.keys())[:2500]
                        for k in keys:
                            _vpn_api_cache.pop(k, None)
                    return is_vpn
    except Exception as e:
        log.debug(f"VPN check error for {ip}: {e}")
    return False

# ═══════════════════════════════════════════════════════════════════
# MODFORGE CUSTOM FEATURES
# ═══════════════════════════════════════════════════════════════════
from collections import defaultdict as _dd

_dm_sent = {}
# ── USERINFO ──
async def _userinfo(guild, target, requester):
    if not target: target = requester
    joined = f"<t:{int(target.joined_at.timestamp())}:R>" if target.joined_at else "?"
    created = f"<t:{int(target.created_at.timestamp())}:R>"
    age = (discord.utils.utcnow() - target.created_at).days
    roles = [r.mention for r in target.roles if r != guild.default_role][:15]
    risk = 0
    if age < 7: risk += 30
    elif age < 30: risk += 15
    if not target.avatar: risk += 10
    risk = min(risk, 100)
    rc = E.GREEN if risk < 25 else E.YELLOW if risk < 50 else E.ORANGE if risk < 75 else E.RED
    timeout_str = "Nein"
    if target.timed_out_until and target.timed_out_until > discord.utils.utcnow():
        timeout_str = f"Bis <t:{int(target.timed_out_until.timestamp())}:R>"
    voice_str = "—"
    if target.voice and target.voice.channel:
        v = target.voice
        flags = []
        if v.mute or v.self_mute: flags.append("🔇")
        if v.deaf or v.self_deaf: flags.append("🔇D")
        if v.self_stream: flags.append("📺")
        voice_str = f"{v.channel.mention}" + (f" ({' '.join(flags)})" if flags else "")
    e = create_embed(f"{E.USERS} {target.display_name}", f"{target.mention} (`{target.id}`)", COLOR_INFO,
        [("📅 Erstellt",created,True),("📥 Beigetreten",joined,True),(f"{rc} Risk",f"{risk}/100",True),
         ("⏳ Timeout",timeout_str,True),("🎤 Voice",voice_str,True),
         (f"{E.LABEL} Rollen ({len(roles)})",", ".join(roles) or "Keine",False)],
        thumbnail=target.display_avatar.url)
    return e

@bot.tree.command(name="userinfo", description="Zeigt User-Infos + Risk-Score")
@app_commands.describe(member="User (optional)")
async def slash_userinfo(interaction: discord.Interaction, member: discord.Member = None):
    try:
        await interaction.response.send_message(embed=await _userinfo(interaction.guild, member or interaction.user, interaction.user))
    except Exception as e:
        log.error(f"userinfo: {e}")
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="userinfo", aliases=["ui","whois"])
async def prefix_userinfo(ctx, member: discord.Member = None):
    try: await ctx.send(embed=await _userinfo(ctx.guild, member or ctx.author, ctx.author))
    except Exception as e: await ctx.send(f"Fehler: {e}")

# ── SERVERINFO ──
@bot.tree.command(name="serverinfo", description="Server-Statistiken")
async def slash_serverinfo(interaction: discord.Interaction):
    try:
        g = interaction.guild
        bots = sum(1 for m in g.members if m.bot)
        e = create_embed(f"{E.SERVER} {g.name}", f"ID: `{g.id}`", COLOR_PRIMARY,
            [("👑 Owner",g.owner.mention if g.owner else "?",True),("📅 Erstellt",f"<t:{int(g.created_at.timestamp())}:R>",True),
             ("👥 Members",f"{g.member_count-bots} + {bots} Bots",True),("💎 Boosts",f"{g.premium_subscription_count or 0} (T{g.premium_tier})",True),
             (f"{E.FOLDER} Kanäle",str(len(g.channels)),True),("{E.LABEL} Rollen",str(len(g.roles)-1),True)],
            thumbnail=g.icon.url if g.icon else None)
        await interaction.response.send_message(embed=e)
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="serverinfo", aliases=["si"])
async def prefix_serverinfo(ctx):
    try:
        g = ctx.guild
        await ctx.send(embed=create_embed(f"{E.SERVER} {g.name}", f"Members: {g.member_count} · Kanäle: {len(g.channels)} · Boosts: {g.premium_subscription_count or 0}", COLOR_PRIMARY, thumbnail=g.icon.url if g.icon else None))
    except Exception as e: await ctx.send(f"Fehler: {e}")

# ── MODSTATS ──
@bot.tree.command(name="modstats", description="Moderator-Statistiken")
@app_commands.describe(moderator="Spezifischer Mod (optional)")
async def slash_modstats(interaction: discord.Interaction, moderator: discord.Member = None):
    try:
        await interaction.response.defer()
        cases = await bot.db.cases.find({"guild_id": str(interaction.guild.id)} | ({"moderator_id": str(moderator.id)} if moderator else {})).sort("timestamp", -1).to_list(500) or []
        if moderator:
            bans = sum(1 for c in cases if c.get("action")=="ban")
            kicks = sum(1 for c in cases if c.get("action")=="kick")
            warns = sum(1 for c in cases if c.get("action")=="warn")
            await interaction.followup.send(embed=create_embed(f"📊 {moderator.display_name}",f"🔨 Bans: {bans} · 👢 Kicks: {kicks} · {E.ALERT}️ Warns: {warns} · 📋 Total: {len(cases)}",COLOR_INFO,thumbnail=moderator.display_avatar.url))
        else:
            counts = _dd(int)
            for c in cases: counts[c.get("moderator_id","?")] += 1
            top = sorted(counts.items(), key=lambda x:x[1], reverse=True)[:10]
            ranking = "\n".join(f"{'🥇🥈🥉'[i] if i < 3 else f'`{i+1}.`'} <@{mid}> — **{cnt}**" for i, (mid, cnt) in enumerate(top)) or "Keine Daten."
            await interaction.followup.send(embed=create_embed(f"📊 Mod-Ranking ({len(cases)} Cases)",ranking,COLOR_PRIMARY))
    except Exception as e:
        try: await interaction.followup.send(f"Fehler: {e}")
        except Exception:
            pass
@bot.command(name="modstats",aliases=["ms"])
async def prefix_modstats(ctx, member: discord.Member = None):
    try:
        cases = await bot.db.cases.find({"guild_id":str(ctx.guild.id)} | ({"moderator_id":str(member.id)} if member else {})).to_list(200) or []
        await ctx.send(embed=create_embed("📊 Mod-Stats",f"Total: {len(cases)} Cases",COLOR_INFO))
    except Exception as e: await ctx.send(f"Fehler: {e}")

# ── SOFTBAN ──
@bot.tree.command(name="softban", description="Ban+Unban (löscht Nachrichten)")
@app_commands.describe(member="User",reason="Grund",days="Tage Nachrichten löschen")
@app_commands.default_permissions(ban_members=True)
async def slash_softban(interaction: discord.Interaction, member: discord.Member, reason: str = "Softban", days: int = 1):
    try:
        days = max(1,min(days,7))
        dm_e = create_embed(f"{E.BAN} Softban",f"Du wurdest von **{interaction.guild.name}** softgebannt.\n**Grund:** {reason}",COLOR_DANGER,thumbnail=interaction.guild.icon.url if interaction.guild.icon else None)
        await safe_dm(member, dm_e, cooldown_key=f"softban:{interaction.guild.id}:{member.id}")
        await member.ban(reason=f"Softban: {reason}",delete_message_seconds=days*86400)
        await interaction.guild.unban(member,reason="Softban auto-unban")
        case_id = await bot.db.acreate_case(interaction.guild.id,member.id,interaction.user.id,"softban",reason)
        await bot.log_action(interaction.guild,"🔨 Softban",f"{member.mention} von {interaction.user.mention}\nGrund: {reason}",COLOR_DANGER,user=member,module="moderation")
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Softban",f"{member.mention} softgebannt. Case #{case_id}",COLOR_SUCCESS))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="softban",aliases=["sb"])
@commands.has_permissions(ban_members=True)
async def prefix_softban(ctx, member: discord.Member = None, *, reason="Softban"):
    if not member: return await ctx.send("Nutze: `!softban @User [Grund]`")
    try:
        await member.ban(reason=f"Softban: {reason}",delete_message_seconds=86400)
        await ctx.guild.unban(member,reason="Softban")
        await ctx.send(embed=create_embed(f"{E.OK}",f"{member.mention} softgebannt.",COLOR_SUCCESS))
    except Exception as e: await ctx.send(f"Fehler: {e}")

# ── REPORT ──
@bot.tree.command(name="report", description="Meldet einen User")
@app_commands.describe(member="User",reason="Grund")
async def slash_report(interaction: discord.Interaction, member: discord.Member, reason: str):
    try:
        cfg = bot.db.get_config(interaction.guild.id)
        ch_id = cfg.get("report_channel") or cfg.get("log_channel")
        if not ch_id: return await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description="Kein Report-Kanal eingerichtet.", color=COLOR_DANGER), ephemeral=True)
        ch = interaction.guild.get_channel(int(ch_id))
        if ch:
            await ch.send(embed=create_embed("🚨 Report",f"**User:** {member.mention}\n**Von:** {interaction.user.mention}\n**Grund:** {reason}",COLOR_DANGER,thumbnail=member.display_avatar.url))
        await interaction.response.send_message(embed=create_embed(f"{E.OK}","Report gesendet.",COLOR_SUCCESS),ephemeral=True)
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.tree.command(name="report_setup", description="Setzt Report-Kanal")
@app_commands.describe(channel="Kanal")
@app_commands.default_permissions(administrator=True)
async def slash_report_setup(interaction: discord.Interaction, channel: discord.TextChannel):
    try:
        cfg = bot.db.get_config(interaction.guild.id)
        cfg["report_channel"] = channel.id
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK}",f"Report-Kanal: {channel.mention}",COLOR_SUCCESS))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="report")
async def prefix_report(ctx, member: discord.Member = None, *, reason="Kein Grund"):
    if not member: return await ctx.send("Nutze: `!report @User Grund`")
    try:
        cfg = bot.db.get_config(ctx.guild.id)
        ch_id = cfg.get("report_channel") or cfg.get("log_channel")
        if ch_id:
            ch = ctx.guild.get_channel(int(ch_id))
            if ch: await ch.send(embed=create_embed("🚨 Report",f"**User:** {member.mention}\n**Von:** {ctx.author.mention}\n**Grund:** {reason}",COLOR_DANGER))
        await ctx.send(embed=create_embed(f"{E.OK}","Report gesendet.",COLOR_SUCCESS))
    except Exception as e: await ctx.send(f"Fehler: {e}")

# ── INVITES ──
@bot.tree.command(name="invites", description="Invite-Statistiken eines Users")
@app_commands.describe(member="User dessen Invites angezeigt werden")
async def slash_invites(interaction: discord.Interaction, member: discord.Member = None):
    try:
        target = member or interaction.user
        invites = await interaction.guild.invites()
        user_invites = [i for i in invites if i.inviter and i.inviter.id == target.id]
        total_uses = sum(i.uses for i in user_invites)

        if not user_invites:
            return await interaction.response.send_message(embed=create_embed(
                f"📨 Invites – {target.display_name}",
                f"{target.mention} hat **keine aktiven Einladungen**.",
                COLOR_INFO, thumbnail=target.display_avatar.url), ephemeral=True)

        lines = []
        for inv in sorted(user_invites, key=lambda x: x.uses, reverse=True)[:10]:
            created = f"<t:{int(inv.created_at.timestamp())}:R>" if inv.created_at else "?"
            expires = ""
            if inv.max_age:
                exp_ts = int(inv.created_at.timestamp() + inv.max_age) if inv.created_at else 0
                if exp_ts > time.time():
                    expires = f" · ⏰ läuft ab <t:{exp_ts}:R>"
                else:
                    expires = f" · {E.FAIL} abgelaufen"
            max_uses = f"/{inv.max_uses}" if inv.max_uses else "/∞"
            channel = f"#{inv.channel.name}" if inv.channel else "?"
            lines.append(
                f"**`{inv.code}`** — **{inv.uses}**{max_uses} Uses · {channel} · {created}{expires}"
            )

        embed = create_embed(
            f"📨 Invites – {target.display_name}",
            f"**{total_uses}** Einladungen über **{len(user_invites)}** Links\n\n" + "\n".join(lines),
            COLOR_INFO, thumbnail=target.display_avatar.url
        )
        embed.set_footer(text=f"Gesamt: {total_uses} Einladungen · {interaction.guild.name}")
        await interaction.response.send_message(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Keine Berechtigung für Invite-Zugriff.", COLOR_DANGER), ephemeral=True)
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
# prefix only: invite_track
@app_commands.describe(enabled="An/Aus")
@app_commands.default_permissions(administrator=True)
async def slash_invite_track(interaction: discord.Interaction, enabled: bool):
    try:
        cfg = bot.db.get_config(interaction.guild.id)
        cfg["invite_tracking"] = {"enabled": enabled}
        await bot.db.set_config(interaction.guild.id, cfg)
        if enabled:
            invites = await interaction.guild.invites()
            bot._invite_cache = getattr(bot, "_invite_cache", {})
            bot._invite_cache[interaction.guild.id] = {i.code: i.uses for i in invites}
        await interaction.response.send_message(embed=create_embed(f"{E.OK}",f"Invite-Tracking {'aktiviert' if enabled else 'deaktiviert'}",COLOR_SUCCESS if enabled else COLOR_WARNING))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="invites",aliases=["inv"])
async def prefix_invites(ctx, member: discord.Member = None):
    try:
        target = member or ctx.author
        invites = await ctx.guild.invites()
        total = sum(i.uses for i in invites if i.inviter and i.inviter.id == target.id)
        await ctx.send(embed=create_embed(f"📨 {target.display_name}",f"**{total}** Einladungen",COLOR_INFO))
    except Exception as e: await ctx.send(f"Fehler: {e}")

# ── LOCKALL / UNLOCKALL ──
@bot.tree.command(name="lockall", description="Sperrt ALLE Kanäle")
@app_commands.describe(reason="Grund")
@app_commands.default_permissions(administrator=True)
async def slash_lockall(interaction: discord.Interaction, reason: str = "Lockdown"):
    try:
        await interaction.response.defer()
        locked = 0
        for ch in interaction.guild.text_channels:
            try: await ch.set_permissions(interaction.guild.default_role,send_messages=False,reason=reason); locked += 1
            except Exception:
                pass
            await asyncio.sleep(0.3)
        await bot.log_action(interaction.guild,f"{E.LOCK} Lockdown",f"{interaction.user.mention}: {locked} Kanäle gesperrt\nGrund: {reason}",COLOR_DANGER,user=interaction.user,module="moderation")
        await interaction.followup.send(embed=create_embed(f"{E.LOCK}",f"**{locked}** Kanäle gesperrt.",COLOR_DANGER))
    except Exception as e:
        try: await interaction.followup.send(f"Fehler: {e}")
        except Exception:
            pass
@bot.tree.command(name="unlockall", description="Entsperrt ALLE Kanäle")
@app_commands.default_permissions(administrator=True)
async def slash_unlockall(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        ul = 0
        for ch in interaction.guild.text_channels:
            try: await ch.set_permissions(interaction.guild.default_role,send_messages=None,reason="Unlock"); ul += 1
            except Exception:
                pass
            await asyncio.sleep(0.3)
        await interaction.followup.send(embed=create_embed(f"{E.UNLOCK}",f"**{ul}** Kanäle entsperrt.",COLOR_SUCCESS))
    except Exception as e:
        try: await interaction.followup.send(f"Fehler: {e}")
        except Exception:
            pass
@bot.command(name="lockall")
@commands.has_permissions(administrator=True)
async def prefix_lockall(ctx, *, reason="Lockdown"):
    try:
        locked = 0
        for ch in ctx.guild.text_channels:
            try: await ch.set_permissions(ctx.guild.default_role,send_messages=False,reason=reason); locked += 1
            except Exception:
                pass
        await ctx.send(embed=create_embed(f"{E.LOCK}",f"{locked} Kanäle gesperrt.",COLOR_DANGER))
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="unlockall")
@commands.has_permissions(administrator=True)
async def prefix_unlockall(ctx):
    try:
        ul = 0
        for ch in ctx.guild.text_channels:
            try: await ch.set_permissions(ctx.guild.default_role,send_messages=None); ul += 1
            except Exception:
                pass
        await ctx.send(embed=create_embed(f"{E.UNLOCK}",f"{ul} Kanäle entsperrt.",COLOR_SUCCESS))
    except Exception as e: await ctx.send(f"Fehler: {e}")

# ── HISTORY ──
@bot.tree.command(name="history", description="Komplette Mod-History eines Users")
@app_commands.describe(member="User")
@app_commands.default_permissions(manage_messages=True)
async def slash_history(interaction: discord.Interaction, member: discord.Member):
    try:
        await interaction.response.defer()
        entries = []
        try:
            cases = await bot.db.cases.find({"guild_id":str(interaction.guild.id),"user_id":str(member.id)}).sort("timestamp",-1).to_list(20) or []
            for c in cases:
                ts = f"<t:{int(c['timestamp'].timestamp())}:R>" if c.get('timestamp') else ""
                entries.append(f"📋 **#{c.get('case_id','?')}** {c.get('action','?')} — {c.get('reason','—')[:40]} {ts}")
        except Exception:
            pass
        try:
            notes = await bot.db.notes.find({"guild_id":str(interaction.guild.id),"user_id":str(member.id)}).to_list(10) or []
            for n in notes: entries.append(f"📝 Notiz: {n.get('text','')[:40]}")
        except Exception:
            pass
        risk = min(len(entries)*8, 100)
        rc = E.GREEN if risk<25 else E.YELLOW if risk<50 else E.ORANGE if risk<75 else E.RED
        await interaction.followup.send(embed=create_embed(f"📜 History – {member.display_name} ({len(entries)})","\n".join(entries[:20]) or "Keine Einträge.",COLOR_INFO,
            [(f"{rc} Risk",f"{risk}/100",True)],thumbnail=member.display_avatar.url))
    except Exception as e:
        try: await interaction.followup.send(f"Fehler: {e}")
        except Exception:
            pass
@bot.command(name="history")
@commands.has_permissions(manage_messages=True)
async def prefix_history(ctx, member: discord.Member = None):
    if not member: return await ctx.send("Nutze: `!history @User`")
    try:
        cases = await bot.db.cases.find({"guild_id":str(ctx.guild.id),"user_id":str(member.id)}).sort("timestamp",-1).to_list(10) or []
        lines = [f"📋 #{c.get('case_id','?')} {c.get('action','?')} — {c.get('reason','—')[:40]}" for c in cases]
        await ctx.send(embed=create_embed(f"📜 History ({len(lines)})","\n".join(lines) or "Keine.",COLOR_INFO))
    except Exception as e: await ctx.send(f"Fehler: {e}")

# ── SNIPE / POLL / PURGE / RAIDMODE / ROLEINFO / AUTOSLOWMODE ──FO / AUTOSLOWMODE / ANTIVPN ──
# (keeping them shorter but all with try/except)

@bot.listen("on_message_delete")
async def snipe_del(msg):
    if msg.author.bot or not msg.guild: return
    _snipe_cache.setdefault(msg.guild.id,{})[msg.channel.id] = {"content":msg.content[:1500],"author":msg.author,"ts":time.time(),"attachments":[a.url for a in msg.attachments][:3]}

@bot.tree.command(name="snipe", description="Letzte gelöschte Nachricht")
@app_commands.default_permissions(manage_messages=True)
async def slash_snipe(interaction: discord.Interaction):
    try:
        d = _snipe_cache.get(interaction.guild.id,{}).get(interaction.channel.id)
        if not d or time.time()-d["ts"]>300: return await interaction.response.send_message(embed=discord.Embed(title="ℹ️ Info", description="Nichts zu snipen (keine kürzlich gelöschte Nachricht).", color=COLOR_INFO), ephemeral=True)
        e = create_embed("🔍 Snipe",d["content"] or "*Leer*",COLOR_WARNING)
        e.set_author(name=str(d["author"]),icon_url=d["author"].display_avatar.url)
        await interaction.response.send_message(embed=e,ephemeral=True)
    except Exception as ex:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {ex}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="snipe")
@commands.has_permissions(manage_messages=True)
async def prefix_snipe(ctx):
    d = _snipe_cache.get(ctx.guild.id,{}).get(ctx.channel.id)
    if not d or time.time()-d["ts"]>300: return await ctx.send("Nichts zu snipen.")
    e = create_embed("🔍",d["content"] or "*Leer*",COLOR_WARNING)
    e.set_author(name=str(d["author"]),icon_url=d["author"].display_avatar.url)
    await ctx.send(embed=e)

@bot.tree.command(name="poll", description="Abstimmung erstellen")
@app_commands.describe(frage="Frage",opt1="Option 1",opt2="Option 2",opt3="Option 3",opt4="Option 4")
async def slash_poll(interaction: discord.Interaction, frage: str, opt1: str, opt2: str, opt3: str=None, opt4: str=None):
    try:
        opts = [opt1,opt2]+(([opt3] if opt3 else [])+([opt4] if opt4 else []))
        emojis = ["1️⃣","2️⃣","3️⃣","4️⃣"]
        desc = "\n".join(f"{emojis[i]} {o}" for i,o in enumerate(opts))
        e = create_embed(f"📊 {frage}",desc,COLOR_PRIMARY)
        await interaction.response.send_message(embed=e)
        msg = await interaction.original_response()
        for i in range(len(opts)): await msg.add_reaction(emojis[i])
    except Exception as ex:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {ex}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="poll")
async def prefix_poll(ctx, *, args=""):
    parts = [p.strip() for p in args.split("|") if p.strip()]
    if len(parts)<3: return await ctx.send("`!poll Frage | Opt1 | Opt2`")
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣"]
    desc = "\n".join(f"{emojis[i]} {o}" for i,o in enumerate(parts[1:5]))
    msg = await ctx.send(embed=create_embed(f"📊 {parts[0]}",desc,COLOR_PRIMARY))
    for i in range(min(len(parts)-1,4)): await msg.add_reaction(emojis[i])

@bot.tree.command(name="roleinfo", description="Rollen-Info")
@app_commands.describe(role="Rolle")
async def slash_roleinfo(interaction: discord.Interaction, role: discord.Role):
    try:
        perms = ", ".join(p[0].replace("_"," ").title() for p in role.permissions if p[1])[:200] or "Keine"
        await interaction.response.send_message(embed=create_embed(f"{E.LABEL} {role.name}",f"Members: {len(role.members)} · Pos: {role.position} · Farbe: {role.color}",role.color.value or COLOR_INFO,
            [("Berechtigungen",perms,False)]))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.tree.command(name="channelinfo", description="Channel-Info")
@app_commands.describe(channel="Channel")
async def slash_channelinfo(interaction: discord.Interaction, channel: discord.TextChannel):
    try:
        await interaction.response.send_message(embed=create_embed(f"{E.FOLDER} #{channel.name}",
            f"Typ: {channel.type} · Slowmode: {channel.slowmode_delay}s · NSFW: {channel.nsfw}\nTopic: {channel.topic or '—'}",COLOR_INFO))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="roleinfo")
async def prefix_roleinfo(ctx, role: discord.Role = None):
    if not role: return await ctx.send("`!roleinfo @Rolle`")
    await ctx.send(embed=create_embed(f"{E.LABEL} {role.name}",f"Members: {len(role.members)} · Pos: {role.position}",role.color.value or COLOR_INFO))

@bot.command(name="channelinfo")
async def prefix_channelinfo(ctx, channel: discord.TextChannel = None):
    ch = channel or ctx.channel
    await ctx.send(embed=create_embed(f"{E.FOLDER} #{ch.name}",f"Slowmode: {ch.slowmode_delay}s · NSFW: {ch.nsfw}",COLOR_INFO))

# ── RAIDMODE ──
@bot.tree.command(name="raidmode", description="Manueller Raid-Modus")
@app_commands.describe(enabled="An/Aus",dauer="Minuten (0=manuell)")
@app_commands.default_permissions(administrator=True)
async def slash_raidmode(interaction: discord.Interaction, enabled: bool, dauer: int = 0):
    try:
        cfg = bot.db.get_config(interaction.guild.id)
        cfg["raidmode_active"] = enabled
        await bot.db.set_config(interaction.guild.id, cfg)
        if enabled:
            locked = 0
            for ch in interaction.guild.text_channels:
                try: await ch.set_permissions(interaction.guild.default_role,send_messages=False,reason="Raidmode"); locked += 1
                except Exception:
                    pass
            await interaction.response.send_message(embed=create_embed("🚨 RAID-MODUS",f"{locked} Kanäle gesperrt."+( f"\nAuto-off in {dauer}m" if dauer else ""),COLOR_DANGER))
            if dauer > 0:
                await asyncio.sleep(dauer*60)
                cfg2 = bot.db.get_config(interaction.guild.id)
                if cfg2.get("raidmode_active"):
                    cfg2["raidmode_active"] = False
                    await bot.db.set_config(interaction.guild.id, cfg2)
                    for ch in interaction.guild.text_channels:
                        try: await ch.set_permissions(interaction.guild.default_role,send_messages=None)
                        except Exception:
                            pass
        else:
            for ch in interaction.guild.text_channels:
                try: await ch.set_permissions(interaction.guild.default_role,send_messages=None)
                except Exception:
                    pass
            await interaction.response.send_message(embed=create_embed(E.OK,"Raid-Modus aus.",COLOR_SUCCESS))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="raidmode")
@commands.has_permissions(administrator=True)
async def prefix_raidmode(ctx, action="status"):
    cfg = bot.db.get_config(ctx.guild.id)
    if action in ("on","true","1"):
        cfg["raidmode_active"] = True
        await bot.db.set_config(ctx.guild.id, cfg)
        for ch in ctx.guild.text_channels:
            try: await ch.set_permissions(ctx.guild.default_role,send_messages=False)
            except Exception:
                pass
        await ctx.send(embed=create_embed("🚨","Raid-Modus AKTIV.",COLOR_DANGER))
    elif action in ("of","false","0"):
        cfg["raidmode_active"] = False
        await bot.db.set_config(ctx.guild.id, cfg)
        for ch in ctx.guild.text_channels:
            try: await ch.set_permissions(ctx.guild.default_role,send_messages=None)
            except Exception:
                pass
        await ctx.send(embed=create_embed(E.OK,"Raid-Modus aus.",COLOR_SUCCESS))
    else:
        await ctx.send(embed=create_embed("🚨",f"Status: {'AKTIV {E.RED}' if cfg.get('raidmode_active') else f"{E.GREEN}"}",COLOR_INFO))

# ── NOPREFIX ──
@bot.tree.command(name="noprefix", description="No-Prefix-Modus")
@app_commands.describe(enabled="An/Aus")
@app_commands.default_permissions(administrator=True)
async def slash_noprefix(interaction: discord.Interaction, enabled: bool):
    try:
        cfg = bot.db.get_config(interaction.guild.id)
        cfg["no_prefix"] = enabled
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK}",f"No-Prefix {'aktiviert' if enabled else 'deaktiviert'}",COLOR_SUCCESS if enabled else COLOR_WARNING))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="noprefix")
@commands.has_permissions(administrator=True)
async def prefix_noprefix(ctx, enabled: str = None):
    cfg = bot.db.get_config(ctx.guild.id)
    if enabled in ("on","true"): cfg["no_prefix"] = True
    elif enabled in ("of","false"): cfg["no_prefix"] = False
    else: cfg["no_prefix"] = not cfg.get("no_prefix",False)
    await bot.db.set_config(ctx.guild.id, cfg)
    await ctx.send(embed=create_embed(f"{E.OK}",f"No-Prefix {'AN' if cfg['no_prefix'] else 'AUS'}",COLOR_SUCCESS if cfg["no_prefix"] else COLOR_WARNING))

# prefix only: autobanappeal
@app_commands.describe(enabled="An/Aus")
@app_commands.default_permissions(administrator=True)
async def slash_autobanappeal(interaction: discord.Interaction, enabled: bool):
    try:
        cfg = bot.db.get_config(interaction.guild.id)
        cfg["auto_ban_appeal"] = {"enabled":enabled}
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK}",f"Auto-Ban-Appeal {'aktiviert' if enabled else 'deaktiviert'}",COLOR_SUCCESS if enabled else COLOR_WARNING))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
# prefix only: warndecay
@app_commands.describe(days="Tage (0=aus)")
@app_commands.default_permissions(administrator=True)
async def slash_warndecay(interaction: discord.Interaction, days: int):
    try:
        cfg = bot.db.get_config(interaction.guild.id)
        cfg["warn_decay"] = {"enabled":days>0,"decay_days":days}
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.OK}",f"Warn-Decay: {days} Tage" if days>0 else "Warn-Decay deaktiviert.",COLOR_SUCCESS if days>0 else COLOR_WARNING))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
# prefix only: antivpn
@app_commands.describe(enabled="An/Aus",action="kick/ban/log")
@app_commands.default_permissions(administrator=True)
async def slash_antivpn(interaction: discord.Interaction, enabled: bool, action: str = "kick"):
    try:
        cfg = bot.db.get_config(interaction.guild.id)
        cfg["anti_vpn"] = {"enabled":enabled,"action":action if action in ("kick","ban","log") else "kick"}
        await bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(f"{E.SHIELD}",f"Anti-VPN {'aktiviert' if enabled else 'deaktiviert'} · Aktion: {action}",COLOR_SUCCESS if enabled else COLOR_WARNING))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
# ── PREFIX MIRRORS ──
@bot.command(name="tempban",aliases=["tb"])
@commands.has_permissions(ban_members=True)
async def prefix_tempban(ctx, member: discord.Member=None, duration: str="1d", *, reason="Tempban"):
    if not member: return await ctx.send("`!tempban @User 7d Grund`")
    try:
        dur = parse_duration(duration)
        if not dur: return await ctx.send("Ungültige Dauer.")
        await member.ban(reason=f"Tempban: {reason}",delete_message_seconds=86400)
        await ctx.send(embed=create_embed(f"{E.OK}",f"{member.mention} für {duration} gebannt.",COLOR_SUCCESS))
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="tempmute",aliases=["tm"])
@commands.has_permissions(moderate_members=True)
async def prefix_tempmute(ctx, member: discord.Member=None, duration: str="1h", *, reason="Timeout"):
    if not member: return await ctx.send("`!tempmute @User 2h Grund`")
    try:
        dur = parse_duration(duration)
        if not dur: return await ctx.send("Ungültige Dauer.")
        until = discord.utils.utcnow() + datetime.timedelta(seconds=dur)
        await member.timeout(until,reason=reason)
        await ctx.send(embed=create_embed(f"{E.OK}",f"{member.mention} für {duration} gemutet.",COLOR_SUCCESS))
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="case")
@commands.has_permissions(manage_messages=True)
async def prefix_case(ctx, case_id: int = None):
    if not case_id: return await ctx.send("`!case <ID>`")
    try:
        c = await bot.db.cases.find_one({"guild_id":str(ctx.guild.id),"case_id":case_id})
        if not c: return await ctx.send("Case nicht gefunden.")
        await ctx.send(embed=create_embed(f"📋 #{case_id}",f"Aktion: {c.get('action')}\nUser: <@{c.get('user_id')}>\nMod: <@{c.get('moderator_id')}>\nGrund: {c.get('reason','—')}",COLOR_INFO))
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="cases")
@commands.has_permissions(manage_messages=True)
async def prefix_cases(ctx, member: discord.Member = None):
    try:
        q = {"guild_id":str(ctx.guild.id)}
        if member: q["user_id"] = str(member.id)
        raw = await bot.db.cases.find(q).sort("case_id",-1).to_list(15) or []
        lines = [f"**#{c.get('case_id')}** {c.get('action')} — {c.get('reason','—')[:40]}" for c in raw]
        await ctx.send(embed=create_embed(f"📋 Cases ({len(raw)})","\n".join(lines) or "Keine.",COLOR_INFO))
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="status")
async def prefix_status(ctx):
    try:
        lat = round(bot.latency*1000) if bot.latency else 0
        await ctx.send(embed=create_embed(f"{E.BOT} Status",f"Server: {len(bot.guilds)} · Latenz: {lat}ms",COLOR_PRIMARY))
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="stats")
async def prefix_stats(ctx):
    g = ctx.guild
    await ctx.send(embed=create_embed(f"{E.SERVER} {g.name}",f"Members: {g.member_count} · Kanäle: {len(g.channels)} · Rollen: {len(g.roles)}",COLOR_PRIMARY))

@bot.command(name="help")
async def prefix_help(ctx):
    from bot.config import HELP_DATA
    e = create_embed(f"{E.HELP} ModForge Hilfe","Nutze `/help` für die interaktive Hilfe.\n\n**Kategorien:**",COLOR_PRIMARY)
    for key,(title,cmds) in HELP_DATA.items():
        e.add_field(name=title,value=" · ".join(c[0].split(" ")[0] for c in cmds[:5])+" …",inline=False)
    await ctx.send(embed=e)

@bot.command(name="panic")
@commands.has_permissions(administrator=True)
async def prefix_panic(ctx):
    try:
        cfg = bot.db.get_config(ctx.guild.id)
        cfg["security_level"] = 3
        await bot.db.set_config(ctx.guild.id, cfg)
        for ch in ctx.guild.text_channels:
            try: await ch.set_permissions(ctx.guild.default_role,send_messages=False,reason="PANIC")
            except Exception:
                pass
        await ctx.send(embed=create_embed("🚨 LOCKDOWN","Security Level 3. `!unlockdown` zum Aufheben.",COLOR_DANGER))
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="unlockdown")
@commands.has_permissions(administrator=True)
async def prefix_unlockdown(ctx):
    try:
        cfg = bot.db.get_config(ctx.guild.id)
        cfg["security_level"] = 0
        await bot.db.set_config(ctx.guild.id, cfg)
        for ch in ctx.guild.text_channels:
            try: await ch.set_permissions(ctx.guild.default_role,send_messages=None)
            except Exception:
                pass
        await ctx.send(embed=create_embed(f"{E.OK}","Lockdown aufgehoben.",COLOR_SUCCESS))
    except Exception as e: await ctx.send(f"Fehler: {e}")

@bot.command(name="report_setup")
@commands.has_permissions(administrator=True)
async def prefix_report_setup(ctx, channel: discord.TextChannel = None):
    if not channel: return await ctx.send("`!report_setup #channel`")
    cfg = bot.db.get_config(ctx.guild.id)
    cfg["report_channel"] = channel.id
    await bot.db.set_config(ctx.guild.id, cfg)
    await ctx.send(embed=create_embed(f"{E.OK}",f"Report-Kanal: {channel.mention}",COLOR_SUCCESS))

@bot.command(name="autorole")
@commands.has_permissions(administrator=True)
async def prefix_autorole(ctx, role: discord.Role = None):
    if not role: return await ctx.send("`!autorole @Rolle`")
    cfg = bot.db.get_config(ctx.guild.id)
    ar = cfg.get("auto_role",{"enabled":True,"roles":[]})
    if role.id not in ar.get("roles",[]): ar.setdefault("roles",[]).append(role.id)
    ar["enabled"] = True
    cfg["auto_role"] = ar
    await bot.db.set_config(ctx.guild.id, cfg)
    await ctx.send(embed=create_embed(f"{E.OK}",f"Auto-Role {role.mention} hinzugefügt.",COLOR_SUCCESS))

@bot.command(name="massban")
@commands.has_permissions(ban_members=True)
async def prefix_massban(ctx, *, ids=""):
    if not ids: return await ctx.send("`!massban 123,456,789`")
    id_list = [int(p) for p in re.split(r'[,;\s]+',ids) if p.strip().isdigit()][:50]
    banned = 0
    for uid in id_list:
        try: await ctx.guild.ban(discord.Object(uid),reason=f"Massban durch {ctx.author}"); banned += 1
        except Exception:
            pass
    await ctx.send(embed=create_embed(f"{E.BAN}",f"{banned}/{len(id_list)} gebannt.",COLOR_DANGER))

@bot.command(name="autobanappeal")
@commands.has_permissions(administrator=True)
async def prefix_autobanappeal(ctx, enabled: str = None):
    cfg = bot.db.get_config(ctx.guild.id)
    on = enabled in ("on","true") if enabled else not cfg.get("auto_ban_appeal",{}).get("enabled",False)
    cfg["auto_ban_appeal"] = {"enabled":on}
    await bot.db.set_config(ctx.guild.id, cfg)
    await ctx.send(embed=create_embed(f"{E.OK}",f"Auto-Ban-Appeal {'AN' if on else 'AUS'}",COLOR_SUCCESS if on else COLOR_WARNING))

@bot.command(name="warndecay")
@commands.has_permissions(administrator=True)
async def prefix_warndecay(ctx, days: int = 0):
    cfg = bot.db.get_config(ctx.guild.id)
    cfg["warn_decay"] = {"enabled":days>0,"decay_days":days}
    await bot.db.set_config(ctx.guild.id, cfg)
    await ctx.send(embed=create_embed(f"{E.OK}",f"Warn-Decay: {days}d" if days>0 else "Warn-Decay aus.",COLOR_SUCCESS if days>0 else COLOR_WARNING))

@bot.command(name="antivpn")
@commands.has_permissions(administrator=True)
async def prefix_antivpn(ctx, action="status"):
    cfg = bot.db.get_config(ctx.guild.id)
    if action in ("on","true"): cfg["anti_vpn"]={"enabled":True,"action":"kick"}
    elif action in ("of","false"): cfg["anti_vpn"]={"enabled":False}
    else: return await ctx.send(embed=create_embed(f"{E.SHIELD}",f"Anti-VPN: {'AN' if cfg.get('anti_vpn',{}).get('enabled') else 'AUS'}",COLOR_INFO))
    await bot.db.set_config(ctx.guild.id, cfg)
    await ctx.send(embed=create_embed(f"{E.OK}",f"Anti-VPN {'AN' if cfg.get('anti_vpn',{}).get('enabled') else 'AUS'}",COLOR_SUCCESS))

# No-prefix handler
@bot.listen("on_message")
async def noprefix_handler(msg):
    if msg.author.bot or not msg.guild: return
    cfg = bot.db.get_config(msg.guild.id)
    if not cfg.get("no_prefix"): return
    content = msg.content.strip()
    if not content or content[0] in "!/?.": return
    cmd = content.split(None,1)[0].lower()
    allowed = {"ban","kick","warn","mute","unmute","clear","lock","unlock","nick","softban","lockall","unlockall","slowmode","tempban","tempmute","unban","userinfo","serverinfo","modstats","invites","report","cases","case","status","stats","help","panic","unlockdown","massban","autorole","warnings","clearwarnings","history","snipe","raidmode"}
    if cmd not in allowed: return
    np_users = cfg.get("no_prefix_users",[])
    ok = (str(msg.author.id) in [str(u) for u in np_users]) if np_users else msg.author.guild_permissions.manage_messages
    if ok:
        msg.content = f"{cfg.get('prefix','!')}{content}"
        await bot.process_commands(msg)

# Auto-response handler
@bot.listen("on_message")
async def ar_handler(msg):
    if msg.author.bot or not msg.guild: return
    cfg = bot.db.get_config(msg.guild.id)
    for ar in cfg.get("auto_responses",[]):
        if ar.get("enabled",True) and ar.get("trigger","").lower() in msg.content.lower():
            try: await msg.channel.send(ar["response"])
            except Exception:
                pass
            break

# ═══════════════════════════════════════════════════════════════════
# SERVER-TAG + BOOST SYSTEM
# ═══════════════════════════════════════════════════════════════════
@bot.tree.command(name="servertag", description="Server-Tag System einrichten")
@app_commands.describe(enabled="An/Aus", reward_role="Belohnungsrolle für Tag-Nutzer", tag="Tag-Text im Namen (z.B. '| MyServer')")
@app_commands.default_permissions(administrator=True)
async def slash_servertag(interaction: discord.Interaction, enabled: bool, reward_role: discord.Role = None, tag: str = None) -> None:
    try:
        cfg = bot.db.get_config(interaction.guild.id)
        old_st = cfg.get("server_tag", {})

        if not enabled:
            # Deaktivieren — Rolle von allen entfernen die sie haben
            old_role_id = old_st.get("reward_role")
            removed = 0
            if old_role_id:
                old_role = interaction.guild.get_role(old_role_id)
                if old_role:
                    for m in old_role.members:
                        try:
                            await m.remove_roles(old_role, reason="Server-Tag deaktiviert")
                            removed += 1
                        except Exception:
                            pass
            cfg["server_tag"] = {"enabled": False, "tag": None, "reward_role": None}
            await bot.db.set_config(interaction.guild.id, cfg)
            msg_text = "Tag-System ist jetzt **aus**.\n"
            if removed:
                msg_text += f"Rolle von {removed} Usern entfernt."
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Server-Tag deaktiviert",
                msg_text,
                COLOR_WARNING))
            return

        if not reward_role or not tag:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", "Bitte gib Tag und Rolle an:\n`/servertag true @Rolle | MyServer`", COLOR_DANGER), ephemeral=True)

        cfg["server_tag"] = {"enabled": True, "tag": tag, "reward_role": reward_role.id}
        await bot.db.set_config(interaction.guild.id, cfg)

        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Server-Tag eingerichtet",
            f"**Tag:** `{tag}`\n"
            f"**Rolle:** {reward_role.mention}\n\n"
            f"**So funktioniert es:**\n"
            f"> {E.LABEL} User setzt `{tag}` in seinen **Discord-Namen**\n"
            f"> 💎 Oder User **boostet** den Server UND hat den Tag\n"
            f"> {E.OK} → Bekommt automatisch {reward_role.mention}\n"
            f"> {E.FAIL} Tag entfernt → Rolle wird **sofort entzogen**\n\n"
            f"Der Bot prüft bei jedem Status-Update.",
            COLOR_SUCCESS))
        await bot.log_action(interaction.guild, f"{E.LABEL} Server-Tag eingerichtet",
            f"Tag: `{tag}` · Rolle: {reward_role.mention} · Von: {interaction.user.mention}",
            COLOR_SUCCESS, user=interaction.user, module="moderation")
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.command(name="servertag")
@commands.has_permissions(administrator=True)
async def prefix_servertag(ctx, action: str = "status", role: discord.Role = None, *, tag: str = ""):
    try:
        cfg = bot.db.get_config(ctx.guild.id)
        st = cfg.get("server_tag", {})
        if action.lower() in ("on", "true"):
            if not role or not tag:
                return await ctx.send(embed=create_embed(f"{E.FAIL}", "`!servertag on @Rolle | MeinTag`", COLOR_DANGER))
            cfg["server_tag"] = {"enabled": True, "tag": tag, "reward_role": role.id}
            await bot.db.set_config(ctx.guild.id, cfg)
            await ctx.send(embed=create_embed(f"{E.OK} Server-Tag", f"Tag: `{tag}` · Rolle: {role.mention}", COLOR_SUCCESS))
        elif action.lower() in ("of", "false"):
            cfg["server_tag"] = {"enabled": False, "tag": None, "reward_role": None}
            await bot.db.set_config(ctx.guild.id, cfg)
            await ctx.send(embed=create_embed(f"{E.OK}", "Server-Tag deaktiviert.", COLOR_WARNING))
        else:
            if st.get("enabled"):
                r = ctx.guild.get_role(st.get("reward_role"))
                await ctx.send(embed=create_embed(f"{E.LABEL} Server-Tag",
                    f"**Status:** {E.OK} Aktiv\n**Tag:** `{st['tag']}`\n**Rolle:** {r.mention if r else '?'}\n"
                    f"**User mit Rolle:** {len(r.members) if r else 0}", COLOR_SUCCESS))
            else:
                await ctx.send(embed=create_embed(E.LABEL, "Server-Tag ist **inaktiv**.\n`!servertag on @Rolle | MeinTag`", COLOR_WARNING))
    except Exception as e:
        await ctx.send(f"Fehler: {e}")

# Server-Tag Prüfung bei Member-Update (Name/Status/Boost)
@bot.listen("on_member_update")
async def servertag_check(before: discord.Member, after: discord.Member):
    if after.bot:
        return
    try:
        cfg = bot.db.get_config(after.guild.id)
        st = cfg.get("server_tag", {})
        if not st.get("enabled") or not st.get("tag") or not st.get("reward_role"):
            return

        tag = st["tag"]
        tag_lower = tag.lower()
        role = after.guild.get_role(st["reward_role"])
        if not role:
            return

        # Prüfe: Hat der User den Tag im Namen?
        has_tag = (
            tag_lower in (after.display_name or "").lower() or
            tag_lower in (after.name or "").lower()
        )

        # Prüfe: Hat der User den Server geboostet?
        is_booster = after.premium_since is not None

        # Regel: Tag UND (optional Boost) → Rolle
        # Kein Tag → Rolle weg (egal ob Boost oder nicht)
        should_have_role = has_tag

        if should_have_role and role not in after.roles:
            await after.add_roles(role, reason=f"Server-Tag erkannt: {tag}")
            await bot.log_action(after.guild, f"{E.LABEL} Server-Tag — Rolle gegeben",
                f"{after.mention} hat den Tag `{tag}` im Namen → {role.mention}\n"
                f"{'💎 Server-Booster' if is_booster else ''}",
                COLOR_SUCCESS, user=after, module="members")

        elif not should_have_role and role in after.roles:
            await after.remove_roles(role, reason=f"Server-Tag entfernt: {tag}")
            await bot.log_action(after.guild, f"{E.LABEL} Server-Tag — Rolle entzogen",
                f"{after.mention} hat den Tag `{tag}` **nicht mehr** im Namen → {role.mention} entzogen",
                COLOR_WARNING, user=after, module="members")

    except (discord.Forbidden, discord.HTTPException):
        pass
    except Exception as e:
        log.debug(f"Server-Tag check error: {e}")

# Auch bei Nickname-Änderung prüfen (on_member_update feuert dafür)
# Und bei Boost-Status-Änderung (premium_since ändert sich)


# ═══════════════════════════════════════════════════════════════════
# AUTO-NICKNAME SYSTE Bot Events
# ═══════════════════════════════════════════════════════════════════

@bot.listen("on_member_update")
async def auto_nickname_check(before: discord.Member, after: discord.Member):
    """Wenn sich Rollen ändern → prüfe Auto-Nickname Regeln."""
    if after.bot or after.id == after.guild.owner_id:
        return
    if before.roles == after.roles:
        return

    try:
        cfg = await bot.db.aget_config(after.guild.id)
        an  = cfg.get("auto_nickname", {})
        if not an.get("enabled") or not an.get("rules"):
            return

        # Ausnahme-Rollen prüfen
        exempt_ids = {str(r) for r in an.get("exempt_roles", [])}
        member_role_ids = {str(r.id) for r in after.roles}
        if exempt_ids & member_role_ids:
            return  # Mitglied hat eine Ausnahme-Rolle → nichts tun

        await _apply_autonick_to_member(after, an)

    except Exception as e:
        log.debug(f"Auto-nickname on_member_update error: {e}")


@bot.listen("on_member_join")
async def auto_nickname_on_join(member: discord.Member):
    """Bei Join: kurz warten bis Auto-Roles vergeben, dann Nick setzen."""
    if member.bot:
        return
    try:
        cfg = await bot.db.aget_config(member.guild.id)
        an  = cfg.get("auto_nickname", {})
        if not an.get("enabled") or not an.get("rules"):
            return

        # Kurz warten bis Auto-Roles vergeben wurden
        await asyncio.sleep(3)

        member = member.guild.get_member(member.id)
        if not member:
            return

        # Ausnahme-Rollen prüfen
        exempt_ids = {str(r) for r in an.get("exempt_roles", [])}
        member_role_ids = {str(r.id) for r in member.roles}
        if exempt_ids & member_role_ids:
            return

        await _apply_autonick_to_member(member, an)

    except Exception as e:
        log.debug(f"Auto-nickname on_member_join error: {e}")


async def _apply_autonick_to_member(member: discord.Member, an: dict) -> bool:
    """
    Wendet Auto-Nickname Regeln auf ein einzelnes Mitglied an.
    Gibt True zurück wenn Nick geändert wurde, False sonst.
    """
    if member.bot or member.id == member.guild.owner_id:
        return False

    rules = sorted(an.get("rules", []), key=lambda r: r.get("priority", 99))
    base_name = member.name
    new_nick  = None
    matched_rule = None

    for rule in rules:
        role_id = rule.get("role_id")
        if not role_id:
            continue
        role = member.guild.get_role(int(role_id))
        if not role or role not in member.roles:
            continue
        prefix = rule.get("prefix", "")
        suffix = rule.get("suffix", "")
        new_nick = f"{prefix}{base_name}{suffix}"[:32]
        matched_rule = rule
        break  # Erste passende Regel gewinnt

    if new_nick is None:
        # Keine Regel passt → alten Auto-Nick zurücksetzen wenn nötig
        for rule in rules:
            p = rule.get("prefix", "")
            s = rule.get("suffix", "")
            if member.nick and (
                (p and member.nick.startswith(p)) or
                (s and member.nick.endswith(s))
            ):
                try:
                    await member.edit(nick=None, reason="Auto-Nickname: Rolle entfernt")
                    await bot.log_action(
                        member.guild, "📝 Auto-Nick entfernt",
                        f"{member.mention} — Nickname zurückgesetzt",
                        0x94a3b8, user=member, module="nicknames"
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass
                return False
        return False

    if member.nick == new_nick:
        return False  # Bereits korrekt gesetzt

    try:
        await member.edit(nick=new_nick, reason="Auto-Nickname: Regel angewendet")
        await bot.log_action(
            member.guild, "📝 Auto-Nickname gesetzt",
            f"{member.mention} → **{new_nick}**",
            0x7c3aed, user=member, module="nicknames"
        )
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def _bulk_apply_autonick(guild: discord.Guild, an: dict,
                                role_id: str = None) -> dict:
    """
    Wendet Auto-Nickname Regeln auf ALLE Mitglieder an (mit Rate-Limit-Schutz).
    role_id: wenn gesetzt, nur Mitglieder mit dieser Rolle verarbeiten.
    Gibt Statistiken zurück: {applied, skipped, failed, total}
    """
    rules = an.get("rules", [])
    if not rules:
        return {"applied": 0, "skipped": 0, "failed": 0, "total": 0}

    exempt_ids = {str(r) for r in an.get("exempt_roles", [])}

    # Mitglieder sammeln
    members_to_process = []
    for member in guild.members:
        if member.bot or member.id == guild.owner_id:
            continue
        # Ausnahme-Rollen prüfen
        member_role_ids = {str(r.id) for r in member.roles}
        if exempt_ids & member_role_ids:
            continue
        # Wenn role_id angegeben: nur Mitglieder mit dieser Rolle
        if role_id:
            if role_id not in member_role_ids:
                continue
        members_to_process.append(member)

    total   = len(members_to_process)
    applied = 0
    skipped = 0
    failed  = 0

    # Rate-Limit: Discord erlaubt ~5 Nick-Änderungen/Sekunde pro Guild
    # Wir machen 1 Änderung pro 0.5s = sicher 2/s
    DELAY = 0.5  # Sekunden zwischen Requests

    for member in members_to_process:
        try:
            changed = await _apply_autonick_to_member(member, an)
            if changed:
                applied += 1
                await asyncio.sleep(DELAY)  # Nur schlafen wenn tatsächlich geändert
            else:
                skipped += 1
                await asyncio.sleep(0.05)   # Mini-Pause auch bei Skip
        except Exception as e:
            log.debug(f"Bulk autonick error for {member.id}: {e}")
            failed += 1
            await asyncio.sleep(DELAY)

    log.info(f"Bulk AutoNick [{guild.name}]: {applied} geändert, {skipped} skip, {failed} fehler / {total} gesamt")
    return {"applied": applied, "skipped": skipped, "failed": failed, "total": total}



# ═══════════════════════════════════════════════════════════════════
# PUBLIC BACKUP SHARING
# ═══════════════════════════════════════════════════════════════════
@bot.tree.command(name="backup_share", description="Macht ein Backup öffentlich teilbar")
@app_commands.describe(backup_id="Backup-ID", name="Öffentlicher Name", description="Beschreibung", category="Kategorie")
@app_commands.default_permissions(administrator=True)
async def slash_backup_share(interaction: discord.Interaction, backup_id: str, name: str, description: str = "", category: str = "general") -> None:
    try:
        backup = await _backup_db_get(interaction.guild.id, backup_id)
        if not backup:
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Backup nicht gefunden.", COLOR_DANGER), ephemeral=True)
        if backup.get("password_hash"):
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Passwortgeschützte Backups können nicht geteilt werden.", COLOR_DANGER), ephemeral=True)
        # Save to public collection
        col = bot.db.client["ModForge"]["public_backups"]
        await col.update_one(
            {"backup_id": backup_id},
            {"$set": {
                "backup_id": backup_id,
                "guild_id": str(interaction.guild.id),
                "name": name[:60],
                "description": description[:200],
                "category": category.lower(),
                "shared_by": str(interaction.user.id),
                "shared_at": discord.utils.utcnow(),
                "guild_name": interaction.guild.name,
                "guild_icon": str(interaction.guild.icon.url) if interaction.guild.icon else None,
                "roles_count": len(backup.get("roles", [])),
                "channels_count": len(backup.get("channels", [])),
                "categories_count": len(backup.get("categories", [])),
                "emojis_count": len(backup.get("emojis", [])),
                "downloads": 0,
            }},
            upsert=True
        )
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Backup geteilt!",
            f"**{name}** ist jetzt öffentlich.\n\n"
            f"🌐 Sichtbar auf: `/templates`\n"
            f"📋 ID: `{backup_id}`\n"
            f"{E.CATEGORY} Kategorie: {category}",
            COLOR_SUCCESS))
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass
@bot.tree.command(name="backup_unshare", description="Entfernt ein Backup aus der öffentlichen Liste")
@app_commands.describe(backup_id="Backup-ID")
@app_commands.default_permissions(administrator=True)
async def slash_backup_unshare(interaction: discord.Interaction, backup_id: str) -> None:
    try:
        col = bot.db.client["ModForge"]["public_backups"]
        result = await col.delete_one({"backup_id": backup_id, "guild_id": str(interaction.guild.id)})
        if result.deleted_count:
            await interaction.response.send_message(embed=create_embed(f"{E.OK}", f"Backup `{backup_id}` ist nicht mehr öffentlich.", COLOR_SUCCESS))
        else:
            await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Nicht gefunden oder nicht dein Backup.", COLOR_DANGER), ephemeral=True)
    except Exception as e:
        try: await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)
        except Exception:
            pass




