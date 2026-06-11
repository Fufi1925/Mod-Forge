# -*- coding: utf-8 -*-
"""
ModForge – Kern-Datei (refactored)
Enthält nur: Imports, Tracker, Views/Modals, ModForge-Klasse, Bot-Instanz.
Alle Commands und Events sind in bot/cogs/ aufgeteilt.
"""
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
    DEFAULT_CONFIG, HELP_DATA, get_uptime, log,
    BADGES,
)
from bot.utils import (
    rate_limited, create_embed,
    generate_captcha, check_phishing_url, can_moderate, parse_duration
)

from database.db import Database
import aiohttp

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
        self.invite_cache: Dict[int, Dict[str, int]] = defaultdict(dict)

    @staticmethod
    def clean_old(dq: deque, window: float) -> None:
        now = time.time()
        while dq and now - dq[0] > window:
            dq.popleft()

# ═══════════════════════════════════════════════════════════════
# DM COOLDOWN — verhindert doppelte DMs
# ═══════════════════════════════════════════════════════════════
_dm_sent: Dict[str, float] = {}
_snipe_cache: Dict[int, Dict[int, dict]] = {}

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
        return False
    try:
        await user.send(embed=embed)
        _dm_sent[key] = now
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
        
        already_verified = False
        if add_roles:
            already_verified = any(discord.utils.get(interaction.user.roles, id=r_id) for r_id in add_roles)
        elif remove_roles:
            already_verified = not any(discord.utils.get(interaction.user.roles, id=r_id) for r_id in remove_roles)

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
            safe_name = re.sub(r'[^a-z0-9-]', '', interaction.user.name.lower())[:20] or str(interaction.user.id)
            channel = await interaction.guild.create_text_channel(
                f"ticket-{safe_name}", category=category, overwrites=overwrites,
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
        embed = create_embed(f"{E.GEAR} Konfiguration: {module.replace('_', ' ').title()}",
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


# ═══════════════════════════════════════════════════════════════════
# TempVoice Views
# ═══════════════════════════════════════════════════════════════════
class TempVoiceSelect(discord.ui.Select):
    def __init__(self, bot_ref) -> None:
        self._bot = bot_ref
        options = [
            discord.SelectOption(label="🔒 Lock", value="lock", description="Kanal für alle sperren"),
            discord.SelectOption(label="🔓 Unlock", value="unlock", description="Kanal für alle öffnen"),
            discord.SelectOption(label="👤 Kick", value="kick", description="Einen Nutzer entfernen"),
            discord.SelectOption(label="👥 Limit", value="limit", description="Maximale Nutzerzahl festlegen"),
            discord.SelectOption(label="✏️ Rename", value="rename", description="Kanal umbenennen"),
        ]
        super().__init__(placeholder="⚙️ Kanal verwalten...", options=options, min_values=1, max_values=1,
                         custom_id="modforge:tv_select")

    async def callback(self, interaction: discord.Interaction) -> None:
        action = self.values[0]
        if action == "limit":
            return await interaction.response.send_modal(TempVoiceLimitModal())
        if action == "rename":
            return await interaction.response.send_modal(TempVoiceRenameModal())
        member = interaction.user
        voice = member.voice
        if not voice or not voice.channel:
            return await interaction.response.send_message(
                embed=discord.Embed(title="❌ Fehler", description="Du bist in keinem Voice-Kanal.", color=COLOR_DANGER),
                ephemeral=True)
        ch = voice.channel
        overwrites = ch.overwrites_for(member)
        if not overwrites.manage_channels:
            return await interaction.response.send_message(
                embed=discord.Embed(title="❌ Fehler", description="Du bist nicht der Besitzer dieses Kanals.", color=COLOR_DANGER),
                ephemeral=True)
        try:
            if action == "lock":
                await ch.set_permissions(interaction.guild.default_role, connect=False)
                await interaction.response.send_message(
                    embed=discord.Embed(title="🔒 Kanal gesperrt", description=f"{ch.mention} ist jetzt gesperrt.", color=COLOR_WARNING),
                    ephemeral=True)
            elif action == "unlock":
                await ch.set_permissions(interaction.guild.default_role, connect=True)
                await interaction.response.send_message(
                    embed=discord.Embed(title="🔓 Kanal entsperrt", description=f"{ch.mention} ist jetzt offen.", color=COLOR_SUCCESS),
                    ephemeral=True)
            elif action == "kick":
                target = None
                for m in ch.members:
                    if m != member and not m.bot:
                        target = m
                        break
                if not target:
                    return await interaction.response.send_message(
                        embed=discord.Embed(title="❌ Fehler", description="Kein Nutzer zum Kicken gefunden.", color=COLOR_DANGER),
                        ephemeral=True)
                await target.move_to(None, reason=f"Temp-Voice Kick von {member}")
                await interaction.response.send_message(
                    embed=discord.Embed(title="👤 Nutzer gekickt", description=f"{target.mention} wurde aus {ch.mention} gekickt.", color=COLOR_WARNING),
                    ephemeral=True)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ Fehler", description=f"Fehler: {e}", color=COLOR_DANGER),
                ephemeral=True)

class TempVoiceView(discord.ui.View):
    def __init__(self, bot_ref) -> None:
        super().__init__(timeout=None)
        self.add_item(TempVoiceSelect(bot_ref))

class TempVoiceLimitModal(discord.ui.Modal, title="Nutzer-Limit setzen"):
    limit = discord.ui.TextInput(label="Maximale Nutzeranzahl (0 = kein Limit)", placeholder="z.B. 5", required=True, max_length=3)
    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            val = int(self.limit.value)
        except ValueError:
            return await interaction.response.send_message(embed=discord.Embed(title="❌", description="Ungültige Zahl.", color=COLOR_DANGER), ephemeral=True)
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(embed=discord.Embed(title="❌", description="Nicht in einem Voice-Kanal.", color=COLOR_DANGER), ephemeral=True)
        ch = interaction.user.voice.channel
        try:
            await ch.edit(user_limit=max(0, min(val, 99)))
            await interaction.response.send_message(embed=discord.Embed(title="👥 Limit gesetzt", description=f"Limit: **{val}**", color=COLOR_SUCCESS), ephemeral=True)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(embed=discord.Embed(title="❌", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)

class TempVoiceRenameModal(discord.ui.Modal, title="Kanal umbenennen"):
    name = discord.ui.TextInput(label="Neuer Kanalname", placeholder="z.B. 🔊 Mein Kanal", required=True, max_length=100)
    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(embed=discord.Embed(title="❌", description="Nicht in einem Voice-Kanal.", color=COLOR_DANGER), ephemeral=True)
        ch = interaction.user.voice.channel
        try:
            await ch.edit(name=self.name.value[:100])
            await interaction.response.send_message(embed=discord.Embed(title="✏️ Umbenannt", description=f"Neuer Name: **{self.name.value}**", color=COLOR_SUCCESS), ephemeral=True)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(embed=discord.Embed(title="❌", description=f"Fehler: {e}", color=COLOR_DANGER), ephemeral=True)


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
        self._log_dedup = {}
        self._config_cache = {}

        self.status_rotation = [
            (discord.ActivityType.watching, "🔒 ModForge Security | /help", 10),
            (discord.ActivityType.streaming, "🛡️ Anti Raid Active | /help", 3),
            (discord.ActivityType.listening, "🎵 Security Reports | /logs", 3),
            (discord.ActivityType.playing, "🔥 Live Protection | /setup", 3),
            (discord.ActivityType.competing, "👀 Watching {member_count} Members | /help", 10),
        ]

    async def _get_prefix(self, bot_instance: commands.Bot, message: discord.Message) -> str:
        if not message.guild:
            return "!"
        cfg = self.db.get_config(message.guild.id)
        return cfg.get("prefix", "!")

    async def setup_hook(self) -> None:
        # Persistent Views
        self.add_view(TempVoiceView(self))
        self.add_view(VerifyView(self))
        self.add_view(TicketView(self))
        self.add_view(TicketCloseView(self))
        self.add_view(AppealActionView(bot_ref=self))
        self.add_view(ReactionRoleView())

        await self.db.ensure_indexes()

        # Cogs laden
        from bot.cogs import COGS
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(f"Cog geladen: {cog}")
            except Exception as e:
                log.error(f"Cog {cog} konnte nicht geladen werden: {e}")

        await self.tree.sync()
        log.info("Slash-Commands synchronisiert.")

        # Tasks starten
        self.cleanup_trackers.start()
        self.tempaction_loop.start()
        self.restore_persistent_mutes.start()

    async def on_ready(self) -> None:
        log.info(f"Eingeloggt als {self.user} (ID: {self.user.id})")
        await self._warmup_caches()
        try:
            for g in self.guilds:
                if g.me.guild_permissions.manage_guild:
                    invites = await g.invites()
                    self.tracker.invite_cache[g.id] = {inv.code: inv.uses for inv in invites}
        except Exception:
            pass
        ACTIVITY.push("ready", f"Bot online als {self.user} – {len(self.guilds)} Guilds, {sum(g.member_count or 0 for g in self.guilds)} Member.")
        if not hasattr(self, "_status_task"):
            self._status_task = self.loop.create_task(self.rotate_status())

    async def rotate_status(self) -> None:
        while True:
            try:
                for activity_type, name, duration in self.status_rotation:
                    total_members = sum(g.member_count or 0 for g in self.guilds)
                    formatted_name = name.format(member_count=f"{total_members:,}")
                    activity = discord.Activity(type=activity_type, name=formatted_name)
                    await self.change_presence(activity=activity)
                    await asyncio.sleep(duration)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"rotate_status Fehler: {e}")
                await asyncio.sleep(60)

    async def _warmup_caches(self) -> None:
        async def _load_one(guild):
            r = 0
            try:
                await self.db.aget_config(guild.id)
                try:
                    await self.db.aget_whitelist(guild.id)
                except Exception:
                    pass
            except Exception:
                return -1
            try:
                backup = await self.db.log_channels_restore(guild.id)
                if backup and isinstance(backup, dict) and len(backup) > 0:
                    cfg = self.db.get_config(guild.id)
                    current = cfg.get("log_channels", {}) or {}
                    merged = dict(backup)
                    merged.update(current)
                    if merged != current:
                        cfg["log_channels"] = merged
                        await self.db.set_config(guild.id, cfg)
                        r = 1
                        log.info(f"Log-Channels restored+merged for {guild.name}: {len(merged)} modules")
            except Exception:
                pass
            return r
        results = await asyncio.gather(*[_load_one(g) for g in self.guilds], return_exceptions=True)
        loaded = sum(1 for r in results if isinstance(r, int) and r >= 0)
        failed = sum(1 for r in results if isinstance(r, int) and r == -1)
        log_restored = sum(r for r in results if isinstance(r, int) and r > 0)
        log.info(f"Cache-Warmup: {loaded} OK, {failed} failed, {log_restored} log-restores")
        self._cache_refresh_loop.start()
        self.log_backup_loop.start()

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
        "ghostping":      ("👻 Ghost-Ping", "https://cdn.discordapp.com/embed/avatars/2.png"),
        "appeal":         ("📋 Appeal", "https://cdn.discordapp.com/embed/avatars/3.png"),
        "permissions":    ("🔐 Permissions", "https://cdn.discordapp.com/embed/avatars/0.png"),
        "audit":          ("🔍 Audit", "https://cdn.discordapp.com/embed/avatars/1.png"),
        "security":       ("🔒 Security", "https://cdn.discordapp.com/embed/avatars/0.png"),
        "default":        ("🛡️ ModForge", "https://cdn.discordapp.com/embed/avatars/0.png"),
    }

    async def log_action(self, guild, title, description, color=COLOR_INFO, fields=None, user=None, module="default") -> None:
        if not guild:
            return
        now = time.time()
        user_id = user.id if user else ""
        dedup_key = f"{guild.id}:{module}:{title}:{user_id}"
        if dedup_key in self._log_dedup and now - self._log_dedup[dedup_key] < 2:
            return
        self._log_dedup[dedup_key] = now
        if len(self._log_dedup) > 500:
            expired = [k for k, v in self._log_dedup.items() if now - v > 30]
            for k in expired:
                self._log_dedup.pop(k, None)

        try:
            ACTIVITY.push(module, f"{title}: {description[:150]}",
                          guild_id=guild.id, guild_name=guild.name,
                          user_id=user_id, user_name=str(user) if user else "System")
        except Exception:
            pass

        try:
            cfg = await self.db.aget_config(guild.id)
        except Exception as e:
            log.error(f"Config-Ladefehler für Guild {guild.id}: {e}")
            return

        try:
            embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
            if fields:
                for fname, fvalue, finline in fields:
                    embed.add_field(name=str(fname)[:256], value=str(fvalue)[:1024], inline=bool(finline))
            if user and hasattr(user, 'display_avatar') and user.display_avatar:
                embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"{FOOTER_TEXT} • {module}", icon_url=FOOTER_ICON)
        except Exception:
            embed = discord.Embed(title=title, description=description, color=color)

        log_ch_id = self._resolve_log_channel(cfg, module)
        if not log_ch_id:
            return

        try:
            channel = guild.get_channel(log_ch_id)
            if channel is None:
                channel = await self._resolve_channel(guild, log_ch_id)
            if channel:
                await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException) as e:
            log.debug(f"Log-Send-Fehler {guild.id}/{module}: {e}")

    def _resolve_log_channel(self, cfg: dict, module: str):
        log_channels = cfg.get("log_channels", {})
        if isinstance(log_channels, dict):
            module_lower = module.lower().replace("-", "_").replace(" ", "_")
            for key in [module_lower, module, "default"]:
                ch_id = log_channels.get(key)
                if ch_id:
                    return int(ch_id)
        fallback = cfg.get("log_channel")
        return int(fallback) if fallback else None

    async def _resolve_channel(self, guild, channel_id: int, retries: int = 3):
        for _ in range(retries):
            try:
                ch = guild.get_channel(channel_id)
                if ch:
                    return ch
                ch = await guild.fetch_channel(channel_id)
                return ch
            except (discord.NotFound, discord.Forbidden):
                return None
            except discord.HTTPException:
                await asyncio.sleep(1)
        return None

    async def punish(self, member, punishment, reason, duration=60, moderator_id=None) -> Optional[int]:
        guild = member.guild
        mod_id = moderator_id or self.user.id
        executed = False
        case_id = None

        try:
            if punishment == "warn":
                cfg = self.db.get_config(guild.id)
                warns = cfg.get("warns", {}).get(str(member.id), [])
                warns.append({"reason": reason, "time": discord.utils.utcnow().isoformat(), "mod": mod_id})
                cfg.setdefault("warns", {})[str(member.id)] = warns
                await self.db.set_config(guild.id, cfg)
                executed = True
                await self._check_warn_thresholds(member, len(warns))
            elif punishment == "timeout":
                delta = datetime.timedelta(seconds=duration)
                await member.timeout(delta, reason=reason)
                executed = True
            elif punishment == "kick":
                dm_e = create_embed(
                    f"👢 Du wurdest gekickt",
                    f"**Server:** {guild.name}\n**Grund:** {reason}",
                    COLOR_WARNING, thumbnail=guild.icon.url if guild.icon else None
                )
                await safe_dm(member, dm_e, cooldown_key=f"kick:{guild.id}:{member.id}")
                await member.kick(reason=reason)
                executed = True
            elif punishment == "ban":
                pre_messages = await self.db.aget_user_messages(guild.id, member.id, hours=48, limit=500)
                dm_e = create_embed(
                    f"🔨 Du wurdest gebannt",
                    f"**Server:** {guild.name}\n**Grund:** {reason}",
                    COLOR_DANGER, thumbnail=guild.icon.url if guild.icon else None
                )
                await safe_dm(member, dm_e, cooldown_key=f"ban:{guild.id}:{member.id}")
                await member.ban(reason=reason, delete_message_seconds=86400)
                executed = True
                case_id = await self.db.acreate_case(guild.id, member.id, mod_id, "ban", reason)
                if pre_messages:
                    serializable = [{
                        "channel_id": m.get("channel_id"), "message_id": m.get("message_id"),
                        "content": m.get("content", ""), "attachments": m.get("attachments", []),
                        "deleted": bool(m.get("deleted")), "edits": m.get("edits", []),
                        "timestamp": (m.get("timestamp") or discord.utils.utcnow()).isoformat() + "Z",
                    } for m in pre_messages]
                    await self.db.aattach_messages_to_case(guild.id, case_id, serializable)
                ACTIVITY.push("case", f"Case #{case_id} (ban) – {member}",
                              guild_id=guild.id, guild_name=guild.name, user_id=member.id, user_name=str(member))
                await self.log_action(guild, f"{E.SHIELD} Case #{case_id} – Ban",
                                      f"**User:** {member.mention} (`{member.id}`)\n**Grund:** {reason}\n**Archiv:** {len(pre_messages)} Nachrichten",
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
        if member.id == self.user.id:
            return True
        if member.id == member.guild.owner_id:
            return True
        wl = self.db.get_whitelist(member.guild.id)
        if member.id == _BOT_DEV_ID:
            return True
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

    @tasks.loop(minutes=5)
    async def log_backup_loop(self) -> None:
        backed = 0
        for g in self.guilds:
            try:
                cfg = self.db.get_config(g.id)
                logchs = cfg.get("log_channels", {}) or {}
                if logchs:
                    await self.db.log_channels_snapshot(g.id, logchs)
                    backed += 1
            except Exception:
                pass
        if backed > 0:
            log.debug(f"Log-Backup: {backed} Guilds gesichert")

    @tasks.loop(hours=1)
    async def _cache_refresh_loop(self) -> None:
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
                    except (discord.NotFound, discord.Forbidden):
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
# BOT INSTANZ
# ═══════════════════════════════════════════════════════════════════
bot = ModForge()
BOT_REF = bot  # Sofort setzen, kein Race Condition

# Bot-Developer Check
@bot.check
async def global_dev_check(ctx):
    if ctx.author.id == _BOT_DEV_ID:
        return True
    return True
