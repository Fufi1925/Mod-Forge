# -*- coding: utf-8 -*-
import asyncio
import datetime
import logging
import random
import re
import time
import traceback
import unicodedata
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple, Union, Callable, Awaitable

import discord
from discord.ext import commands, tasks
from discord import app_commands

from bot.config import ACTIVITY

from bot.config import (
    BOT_TOKEN, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_INFO, COLOR_PURPLE, FOOTER_TEXT, FOOTER_ICON, VERIFY_BANNER_URL,
    E, URL_REGEX, INVITE_REGEX, ZALGO_REGEX, SUSPICIOUS_NAME_REGEX,
    SCAM_DOMAINS, URL_SHORTENERS, VALID_PUNISHMENTS, LOG_MODULES,
    DEFAULT_CONFIG, HELP_DATA, get_uptime, BOT_START_TIME, EXTRA_UPTIME, log
)
from bot.utils import (
    GLOBAL_API_SEMAPHORE, rate_limited, create_embed,
    generate_captcha, check_phishing_url, can_moderate, parse_duration
)


from bot import bot

logging.basicConfig(level=logging.INFO)

while True:
    try:
        logging.info("Starte Bot...")
        bot.run(BOT_TOKEN, log_handler=None)

    except Exception as e:
        logging.error(f"Bot Crash: {e}")

        # wartet bevor reconnect
        time.sleep(10)

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
                await interaction.response.send_message(f"{E.OK} Verifizierung erfolgreich!", ephemeral=True)
                await self.bot.log_action(interaction.guild, f"{E.VERIFY} Verifiziert",
                                          f"{interaction.user.mention} hat den Captcha gelöst.",
                                          COLOR_SUCCESS, user=interaction.user, module="verify")
            except discord.Forbidden:
                await interaction.response.send_message(f"{E.FAIL} Mir fehlen Rechte.", ephemeral=True)
            except discord.HTTPException as ex:
                log.warning(f"Captcha-Rollenfehler: {ex}")
                await interaction.response.send_message(f"{E.FAIL} Discord-Fehler.", ephemeral=True)
        else:
            await interaction.response.send_message(f"{E.FAIL} Falscher Code!", ephemeral=True)

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
                await interaction.response.send_message(f"{E.OK} Verifizierung erfolgreich!", ephemeral=True)
                await self.bot.log_action(interaction.guild, f"{E.VERIFY} Verifiziert",
                                          f"{interaction.user.mention} (One-Click).",
                                          COLOR_SUCCESS, user=interaction.user, module="verify")
            except discord.Forbidden:
                await interaction.response.send_message(f"{E.FAIL} Mir fehlen Rechte.", ephemeral=True)
            except discord.HTTPException:
                await interaction.response.send_message(f"{E.FAIL} Discord-Fehler.", ephemeral=True)
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
            await interaction.response.send_message(f"{E.FAIL} Mir fehlen Rechte.", ephemeral=True)
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
        await interaction.response.send_message("Das Ticket wird in 5 Sekunden geschlossen...")
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
            result_title = "✅ Appeal akzeptiert & Entbannt"
            result_desc = f"Notiz: {self.reason.value}"
        else:
            color = COLOR_DANGER
            result_title = "❌ Appeal abgelehnt"
            result_desc = f"Grund: {self.reason.value}"
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = color
        embed.add_field(name="Ergebnis", value=result_desc, inline=False)
        embed.add_field(name="Bearbeitet von", value=interaction.user.mention, inline=True)
        await interaction.response.edit_message(embed=embed, view=None)
        try:
            user = await self.bot_ref.fetch_user(user_id)
            dm_msg = (
                f"✅ **Dein Entbannungs-Antrag wurde angenommen!**\n"
                f"**Notiz:** {self.reason.value}" if self.action == "unban"
                else f"❌ **Dein Entbannungs-Antrag wurde abgelehnt.**\n"
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

    @discord.ui.button(label="Ablehnen", style=discord.ButtonStyle.danger, custom_id="appeal:decline", emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        data = self._get_appeal_data(interaction)
        user_id = data.get("user_id")
        guild = interaction.guild
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = COLOR_DANGER
        embed.add_field(name="❌ Status", value="Abgelehnt", inline=True)
        embed.add_field(name="Bearbeitet von", value=interaction.user.mention, inline=True)
        await interaction.response.edit_message(embed=embed, view=None)
        try:
            user = await interaction.client.fetch_user(user_id)
            await user.send(f"❌ **Dein Entbannungs-Antrag wurde abgelehnt.** Du bleibst vom Server **{guild.name}** gebannt.")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        await interaction.client.log_action(guild, "❌ Appeal abgelehnt", f"Appeal von <@{user_id}> abgelehnt.", COLOR_DANGER, module="appeal")

    @discord.ui.button(label="Entbannen", style=discord.ButtonStyle.success, custom_id="appeal:unban", emoji="✅")
    async def unban(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
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
        embed.add_field(name="✅ Status", value="Entbannt", inline=True)
        embed.add_field(name="Bearbeitet von", value=interaction.user.mention, inline=True)
        await interaction.response.edit_message(embed=embed, view=None)
        try:
            user = await interaction.client.fetch_user(user_id)
            await user.send(f"✅ **Dein Entbannungs-Antrag wurde angenommen!** Willkommen zurück auf **{guild.name}**.")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        await interaction.client.log_action(guild, "✅ Appeal akzeptiert", f"<@{user_id}> entbannt von {interaction.user.mention}", COLOR_SUCCESS, module="appeal")

    @discord.ui.button(label="Ablehnen + Grund", style=discord.ButtonStyle.secondary, custom_id="appeal:decline_reason", emoji="📝")
    async def decline_reason(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
            return
        data = self._get_appeal_data(interaction)
        await interaction.response.send_modal(AppealReasonModal("decline", data, interaction.client))

    @discord.ui.button(label="Entbannen + Notiz", style=discord.ButtonStyle.primary, custom_id="appeal:unban_reason", emoji="💬")
    async def unban_reason(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("Keine Berechtigung.", ephemeral=True)
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
            await interaction.response.send_message(f"{E.FAIL} Ungültige Kanal-ID.", ephemeral=True)
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

    async def _get_prefix(self, bot: commands.Bot, message: discord.Message) -> str:
        if not message.guild:
            return "!"
        cfg = self.db.get_config(message.guild.id)
        return cfg.get("prefix", "!")

    async def setup_hook(self) -> None:
        self.add_view(VerifyView(self))
        self.add_view(TicketView(self))
        self.add_view(TicketCloseView(self))
        self.add_view(AppealActionView(bot_ref=self))
        await self.db.ensure_indexes()
        await self.tree.sync()
        log.info("Slash-Commands synchronisiert.")
        self.cleanup_trackers.start()
        self.tempaction_loop.start()
        self.restore_persistent_mutes.start()
        global BOT_REF
        BOT_REF = self

    async def on_ready(self) -> None:
        log.info(f"Eingeloggt als {self.user} (ID: {self.user.id})")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="🔒 ModForge Security | /help"))
        await self._warmup_caches()
        ACTIVITY.push("ready", f"Bot online als {self.user} – {len(self.guilds)} Guilds, {sum(g.member_count or 0 for g in self.guilds)} Member.")

    async def _warmup_caches(self) -> None:
        tasks_list = []
        for guild in self.guilds:
            tasks_list.append(asyncio.create_task(self.db.fetch_config(guild.id)))
            tasks_list.append(asyncio.create_task(self.db.fetch_whitelist(guild.id)))
        if tasks_list:
            await asyncio.gather(*tasks_list, return_exceptions=True)
            log.info(f"Cache-Warmup für {len(self.guilds)} Guilds abgeschlossen.")

    async def log_action(self, guild, title, description, color=COLOR_INFO, fields=None, user=None, module="default") -> None:
        if not guild:
            return
        cfg = self.db.get_config(guild.id)
        log_channels = cfg.get("log_channels", {}) or {}
        log_ch_id = log_channels.get(module)
        if not log_ch_id and module != "default":
            log_ch_id = log_channels.get("default")
        if not log_ch_id:
            log_ch_id = cfg.get("log_channel")
        if not log_ch_id:
            return
        try:
            channel = guild.get_channel(int(log_ch_id))
        except (TypeError, ValueError):
            return
        if not channel:
            return
        thumb = user.display_avatar.url if user else None
        embed = create_embed(title, description, color, fields, thumbnail=thumb, user=user)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            log.warning(f"Keine Sende-Rechte im Log-Kanal {channel.id} ({guild.name})")
        except discord.HTTPException as ex:
            log.warning(f"HTTP-Fehler beim Loggen: {ex}")

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
            elif punishment == "timeout":
                until = discord.utils.utcnow() + datetime.timedelta(seconds=duration)
                await member.timeout(until, reason=reason)
                await self.db.aadd_mute(guild.id, member.id, reason, mod_id, duration)
                executed = True
            elif punishment == "kick":
                await member.kick(reason=reason)
                executed = True
            elif punishment == "ban":
                pre_messages = await self.db.aget_user_messages(guild.id, member.id, hours=48, limit=500)
                await member.ban(reason=reason, delete_message_days=1)
                executed = True
                case_id = await self.db.acreate_case(guild.id, member.id, mod_id, "ban", reason, duration=None)
                if pre_messages:
                    serializable = [{
                        "channel_id": m.get("channel_id"), "message_id": m.get("message_id"),
                        "content": m.get("content", ""), "attachments": m.get("attachments", []),
                        "deleted": bool(m.get("deleted")), "edits": m.get("edits", []),
                        "timestamp": (m.get("timestamp") or datetime.datetime.utcnow()).isoformat() + "Z",
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
                    "timestamp": (m.get("timestamp") or datetime.datetime.utcnow()).isoformat() + "Z",
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
        now = datetime.datetime.utcnow()
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

@bot.event
async def on_member_join(member):
    guild = member.guild
    cfg = bot.db.get_config(guild.id)
    sec_level = cfg.get("security_level", 0)
    raid_cfg = cfg.get("anti_raid", {})
    ACTIVITY.push("join", f"{member} ist **{guild.name}** beigetreten ({guild.member_count} Member).",
                  guild_id=guild.id, guild_name=guild.name, user_id=member.id, user_name=str(member))
    if bot.is_whitelisted(member, "bypass_antinuke"):
        await bot.log_action(guild, "➕ Mitglied beigetreten", f"{member.mention}", COLOR_SUCCESS, user=member, module="members")
        return
    if sec_level >= 2:
        account_age = (datetime.datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
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
        account_age = (datetime.datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
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
    await bot.log_action(guild, f"{E.JOIN} Mitglied beigetreten", f"{member.mention}", COLOR_SUCCESS, user=member, module="members")

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
                "✅ Antwort gespeichert", APPEAL_QUESTIONS[next_step], COLOR_INFO))
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
        await user.send("❌ Der Server konnte nicht gefunden werden.")
        return

    cfg = bot.db.get_config(guild_id)
    channel_id = cfg.get("appeal_log_channel")
    if not channel_id:
        await user.send(embed=create_embed(
            "❌ Kein Appeal-Kanal",
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
            ("❓ Warum gebannt?", answers.get("ban_grund", "–"), False),
            ("✅ Fehler eingesehen?", answers.get("fehler_eingesehen", "–"), True),
            ("📜 Statement", answers.get("statement", "–"), False),
            ("🤝 Regeln versprechen?", answers.get("regeln_versprechen", "–"), True),
            ("💬 Zusatz", answers.get("zusatz", "–"), False),
        ],
        thumbnail=user.display_avatar.url
    )
    embed.set_footer(text=f"Powered by BotForge 🔒 | UserID: {user.id}", icon_url=FOOTER_ICON)

    view = AppealActionView(bot_ref=bot, appeal_data={"user_id": user.id, "guild_id": guild_id})
    await channel.send(embed=embed, view=view)

    await user.send(embed=create_embed(
        "✅ Antrag eingereicht!",
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
            await channel.set_permissions(guild.default_role, send_messages=False,
                                          reason="Anti-Raid Lockdown")
        except discord.Forbidden:
            pass
        await asyncio.sleep(0.3)  # Rate-Limit-Schutz
    await bot.log_action(guild, f"{E.LOCK} Lockdown aktiviert",
                         "Alle Kanäle wurden für @everyone gesperrt.",
                         COLOR_DANGER, module="antiraid")


async def _deactivate_lockdown(guild: discord.Guild) -> None:
    """Hebt den Lockdown vollständig auf."""
    for channel in guild.text_channels:
        try:
            await channel.set_permissions(guild.default_role, send_messages=None,
                                          reason="Lockdown aufgehoben")
        except discord.Forbidden:
            pass
        await asyncio.sleep(0.3)
    bot.tracker.lockdown_active[guild.id] = False
    await bot.log_action(guild, f"{E.UNLOCK} Lockdown aufgehoben",
                         "Alle Kanäle wurden wieder entsperrt.",
                         COLOR_SUCCESS, module="antiraid")


async def _auto_deactivate_lockdown(guild: discord.Guild, delay: int) -> None:
    """Hebt den Lockdown nach `delay` Sekunden auf, falls er noch aktiv ist."""
    await asyncio.sleep(delay)
    if bot.tracker.lockdown_active[guild.id]:
        await _deactivate_lockdown(guild)


async def _notify_owner_nuke(guild: discord.Guild, executor: Optional[discord.Member],
                             executor_id: int, action: str, punishment: str) -> None:
    """Sendet eine detaillierte Anti-Nuke-Alarm-DM an den Server-Owner."""
    owner = guild.owner
    if not owner:
        try:
            owner = await guild.fetch_member(guild.owner_id)
        except Exception:
            return
    if not owner:
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp_f = f"<t:{int(now.timestamp())}:F>"
    timestamp_r = f"<t:{int(now.timestamp())}:R>"

    user_line = executor.mention if executor else f"Unbekannter User (`{executor_id}`)"
    if executor:
        account_created = f"<t:{int(executor.created_at.timestamp())}:R>"
        account_age = f"\n**Account erstellt:** {account_created}"
        roles = ", ".join(r.name for r in executor.roles if r.name != "@everyone") or "Keine"
    else:
        account_age = ""
        roles = "Nicht verfügbar"

    embed = create_embed(
        title=f"{E.NUKE} KRITISCHER ANTI-NUKE ALARM",
        description=(
            f"### ⚠️ Sicherheitsverstoß auf deinem Server!\n\n"
            f"Auf **{guild.name}** wurde eine potenziell zerstörerische Massenaktivität erkannt "
            f"und **automatisch gestoppt**. Um deinen Server zu schützen, hat ModForge sofort "
            f"einen **Lockdown aktiviert** und den Täter bestraft.\n\n"
            f"Bitte lies die folgenden Details sorgfältig durch – sie helfen dir, den Vorfall "
            f"vollständig zu verstehen und ggf. weitere Maßnahmen zu ergreifen."
        ),
        color=COLOR_DANGER,
        thumbnail=guild.icon.url if guild.icon else None
    )

    embed.add_field(
        name="📊 Analyse des Vorfalls",
        value=(
            f"**Erkannte Aktion:** `{action}`\n"
            f"**Status:** 🛑 Gestoppt & Isoliert\n"
            f"**Zeitpunkt:** {timestamp_f} ({timestamp_r})\n"
            f"**Betroffener Server:** {guild.name} (`{guild.id}`)"
        ),
        inline=False
    )

    embed.add_field(
        name="👤 Verursacher",
        value=(
            f"{user_line}{account_age}\n"
            f"**User‑ID:** `{executor_id}`\n"
            f"**Rollen:** {roles}\n"
            f"**Verhängte Strafe:** {punishment}"
        ),
        inline=False
    )

    embed.add_field(
        name="🔒 Sofortmaßnahmen",
        value=(
            f"1. **Server‑Lockdown** – alle Kanäle sind für Mitglieder gesperrt (Dauer: 10 Minuten).\n"
            f"2. **Rollenentzug** – der Täter hat alle Rollen verloren (falls aktiviert).\n"
            f"3. **Bestrafung** – der Täter wurde mit `{punishment}` bestraft.\n"
            f"4. **Audit‑Log** – ein detaillierter Eintrag wurde im Log‑Kanal hinterlegt."
        ),
        inline=False
    )

    embed.add_field(
        name="⏳ Lockdown-Informationen",
        value=(
            f"Der Lockdown wurde automatisch für **10 Minuten** aktiviert und wird danach "
            f"selbstständig aufgehoben. Während dieser Zeit können normale Nutzer **keine Nachrichten senden**.\n\n"
            f"Falls du den Lockdown vorzeitig beenden möchtest, nutze den Befehl `/unlockdown` "
            f"oder ändere die Kanaleinstellungen manuell."
        ),
        inline=False
    )

    embed.add_field(
        name="🛡️ Empfehlungen für dich",
        value=(
            "• **Audit‑Logs prüfen:** Gehe in die Server‑Einstellungen → Audit‑Log und "
            "durchsuche den Zeitraum nach dem Vorfall.\n"
            "• **Rollen & Berechtigungen:** Überprüfe, warum der Täter diese Aktionen ausführen "
            "konnte, und passe ggf. die Rechte an.\n"
            "• **Sicherheitsstufe erhöhen:** Erwäge `/security_level` auf 2 oder 3 zu setzen.\n"
            "• **Team informieren:** Alarmiere dein Admin‑Team über diesen Vorfall.\n"
            "• **Kontakt:** Bei Fragen oder Hilfe erstelle ein Ticket im Support‑Server."
        ),
        inline=False
    )

    embed.add_field(
        name="📋 Protokollierung",
        value=(
            "Dieser Vorfall wurde automatisch in der ModForge‑Datenbank als **Case** gespeichert "
            "und kann von Administratoren mit `/case <id>` eingesehen werden."
        ),
        inline=False
    )

    embed.set_footer(
        text=f"ModForge Security · Server: {guild.name}",
        icon_url=FOOTER_ICON
    )
    embed.timestamp = now

    try:
        await owner.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def _nuke_check(guild: discord.Guild, executor_id: int, action: str) -> None:
    """Überwacht verdächtige Massenaktionen und leitet Gegenmaßnahmen ein."""
    cfg = bot.db.get_config(guild.id)
    nuke_cfg = cfg.get("anti_nuke", {})
    if not nuke_cfg.get("enabled"):
        return

    now = time.time()
    dq = bot.tracker.nuke_tracker[guild.id][executor_id]
    dq.append(now)
    bot.tracker.clean_old(dq, nuke_cfg.get("window", 10))

    if len(dq) >= nuke_cfg.get("threshold", 5):
        dq.clear()
        executor = guild.get_member(executor_id)
        if not executor or bot.is_whitelisted(executor):
            return

        # Rolle(n) entfernen, falls konfiguriert
        if nuke_cfg.get("remove_roles") and executor:
            try:
                await executor.edit(roles=[], reason="Anti-Nuke: Rollen entfernt")
            except (discord.Forbidden, discord.HTTPException):
                pass

        # Täter bestrafen
        punishment = nuke_cfg.get("punishment", "ban")
        await bot.punish(executor, punishment,
                         f"Anti-Nuke: Verdächtige Aktivität ({action})")

        # Automatischer Lockdown (10 Minuten) – nur einmal aktivieren
        if not bot.tracker.lockdown_active[guild.id]:
            bot.tracker.lockdown_active[guild.id] = True
            asyncio.create_task(_auto_deactivate_lockdown(guild, 600))
            await _activate_lockdown(guild)

        # Server-Owner per DM informieren
        await _notify_owner_nuke(guild, executor, executor_id, action, punishment)

        # Ausführlicher Log-Eintrag
        await bot.log_action(
            guild,
            f"{E.NUKE} ANTI-NUKE AUSGELÖST",
            f"**{executor.mention if executor else executor_id}** hat verdächtige Massenaktionen durchgeführt!\n"
            f"**Lockdown:** automatisch aktiviert (10 min).",
            COLOR_DANGER,
            [("Aktion", action, True),
             ("Strafe", punishment, True),
             ("Lockdown", "10 Minuten", True)],
            user=executor,
            module="antinuke"
        )


async def _audit_actor(guild: discord.Guild, action: discord.AuditLogAction,
                       target_id: Optional[int] = None) -> Optional[discord.abc.User]:
    """Holt den letzten Audit-Log Akteur für eine bestimmte Aktion."""
    try:
        async for entry in guild.audit_logs(limit=5, action=action):
            if target_id is None or (entry.target and getattr(entry.target, "id", None) == target_id):
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
    guild = member.guild
    if before.channel == after.channel:
        return
    if not before.channel:
        await bot.log_action(guild, f"{E.VOICE_IN} Voice Join",
                             f"{member.mention} ist {after.channel.mention} beigetreten.",
                             COLOR_SUCCESS, user=member, module="voice")
    elif not after.channel:
        await bot.log_action(guild, f"{E.VOICE_OUT} Voice Leave",
                             f"{member.mention} hat {before.channel.mention} verlassen.",
                             COLOR_DANGER, user=member, module="voice")
    else:
        await bot.log_action(guild, f"{E.VOICE_SW} Voice Wechsel",
                             f"{member.mention} ist von {before.channel.mention} zu {after.channel.mention} gewechselt.",
                             COLOR_INFO, user=member, module="voice")


# ═══════════════════════════════════════════════════════════════
# EVENT: ON_MEMBER_UPDATE
# ═══════════════════════════════════════════════════════════════
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
                changes.append(f"➕ Overwrite hinzugefügt für {target_label}")
            elif a is None and b is not None:
                changes.append(f"➖ Overwrite entfernt für {target_label}")
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
            diffs.append(("➕ Permissions hinzugefügt", "`" + "`, `".join(sorted(added_p))[:900] + "`", False))
        if removed_p:
            diffs.append(("➖ Permissions entfernt", "`" + "`, `".join(sorted(removed_p))[:900] + "`", False))

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


# ═══════════════════════════════════════════════════════════════
# EVENT: GUILD JOIN / LEAVE  (Bot wird zu Server hinzugefügt/entfernt)
# ═══════════════════════════════════════════════════════════════
@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    log.info(f"Bot zu Guild beigetreten: {guild.name} ({guild.id}) – {guild.member_count} Member")
    ACTIVITY.push(
        "guild_join",
        f"Bot zu **{guild.name}** hinzugefügt – {guild.member_count} Member.",
        guild_id=guild.id, guild_name=guild.name,
    )
    await bot.db.arecord_guild_event(
        guild.id, guild.name, guild.member_count or 0, "join",
    )

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
# ON GUILD JOIN  —  Welcome-Embed
# Einfügen direkt in bot.py, z.B. nach on_ready oder nach on_guild_remove
# ═══════════════════════════════════════════════════════════════════

@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
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
            "⚡  Anti-Spam     — Nachrichten-, CAPS-, Emoji-Flood\n"
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
            "⚠️  Zalgo-Schutz     — Zalgo / Unicode-Spam\n"
            "🎣  Phishing-Schutz  — Externe URL-Prüfung\n"
            "```"
        ),
        inline=True,
    )

    # ── MODERATION FEATURES ───────────────────────────────
    embed.add_field(
        name="⚖️ Moderation",
        value=(
            "```\n"
            "📋  Case-System    — IDs, Beweise, Archiv\n"
            "⚠️  Warn-System    — Schwellen + Auto-Punish\n"
            "✅  Verifizierung  — One-Click oder CAPTCHA\n"
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
            "`/ticket-setup` `/verify-setup` `/logban` `/help`"
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
            f"**Fertig in unter 2 Minuten! ⚡**"
        ),
        inline=False,
    )

    # ── LINKS ─────────────────────────────────────────────
    embed.add_field(
        name="🔗 Links",
        value=(
            "🌐 **[Dashboard öffnen](https://mod-forge.up.railway.app/login)**"
            "　・　"
            "💬 **[Support Server](https://discord.gg/gwryX3dbkt)**"
            "　・　"
            "📄 **[Terms of Service](https://mod-forge.up.railway.app/terms)**"
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
        await ctx.send(embed=create_embed("⚠️ Kein Appeal-Kanal gesetzt",
                                          "Bitte zuerst mit `/logban #kanal` einen Appeal-Kanal setzen!",
                                          COLOR_WARNING))
        return

    try:
        user = await bot.fetch_user(user_id)
    except discord.NotFound:
        await ctx.send(embed=create_embed("❌ Nutzer nicht gefunden",
                                          f"Kein Nutzer mit ID `{user_id}` gefunden.",
                                          COLOR_DANGER))
        return

    try:
        await ctx.guild.fetch_ban(discord.Object(id=user_id))
    except discord.NotFound:
        await ctx.send(embed=create_embed("❌ Nutzer nicht gebannt",
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
            "⚖️ Entbannungs-Antrag möglich",
            (f"Du wurdest vom Server **{ctx.guild.name}** gebannt.\n\n"
             f"**Ban-Grund:** {ban_reason}\n\n"
             "Das Moderationsteam gibt dir die Möglichkeit, einen **Entbannungs-Antrag** zu stellen.\n\n"
             "Wenn du einen Antrag stellen möchtest, schreibe `!start`.\n"
             "Wenn du keinen Antrag stellen möchtest, ignoriere diese Nachricht.\n\n"),
            COLOR_PRIMARY,
            thumbnail=ctx.guild.icon.url if ctx.guild.icon else None
        )
        await user.send(embed=embed_dm)

        embed_confirm = create_embed("✅ Appeal-DM gesendet",
                                     f"**{user}** (`{user_id}`) hat eine Appeal-DM erhalten.",
                                     COLOR_SUCCESS,
                                     fields=[("Ban-Grund", ban_reason, False),
                                             ("Appeal-Kanal", f"<#{cfg['appeal_log_channel']}>", True)],
                                     thumbnail=user.display_avatar.url)
        await ctx.send(embed=embed_confirm)

    except discord.Forbidden:
        appeal_sessions.pop(user_id, None)
        await ctx.send(embed=create_embed("❌ DM nicht möglich",
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
    await interaction.response.send_message(f"{E.OK} Verifizierung in {channel.mention} eingerichtet!",
                                            ephemeral=True)


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
    await interaction.response.send_message(f"{E.OK} Verifizierungs-Rollen aktualisiert!", ephemeral=True)


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
    await interaction.response.send_message(f"{E.OK} Ticket-System eingerichtet!", ephemeral=True)


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
             "timestamp": (m.get("timestamp") or datetime.datetime.utcnow()).isoformat() + "Z"}
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
    end = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
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
             "timestamp": (m.get("timestamp") or datetime.datetime.utcnow()).isoformat() + "Z"}
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
    end = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
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


@bot.tree.command(name="tempkick", description="Kickt einen Nutzer (verhindert Rejoin per Tempban kurzzeitig)")
@app_commands.describe(member="Nutzer", duration="Sperrdauer (z.B. 1h, 1d)", reason="Grund")
@app_commands.default_permissions(kick_members=True, ban_members=True)
async def slash_tempkick(interaction: discord.Interaction, member: discord.Member,
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
    end = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
    try:
        await member.ban(reason=f"Tempkick {duration} – {interaction.user}: {reason}",
                         delete_message_days=0)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=create_embed(f"{E.FAIL} Forbidden", "Ich darf das nicht.", COLOR_DANGER), ephemeral=True)
        return
    await bot.db.aadd_tempaction("tempban", interaction.guild.id, member.id, end, reason, interaction.user.id)
    case_id = await bot.create_mod_case(
        interaction.guild, member, interaction.user, "tempkick", reason, duration=seconds,
    )
    embed = create_embed(f"{E.KICK} Tempkick – Case #{case_id}",
                         f"{member.mention} ist für **{duration}** ausgesperrt.",
                         COLOR_WARNING,
                         [("Grund", reason, False),
                          ("Wieder erlaubt", f"<t:{int(end.timestamp())}:R>", True),
                          ("Case-ID", f"`{case_id}`", True)])
    await interaction.response.send_message(embed=embed)
    await bot.log_action(interaction.guild, f"{E.KICK} Tempkick – Case #{case_id}",
                         f"{member.mention} – {duration}", COLOR_WARNING,
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
        await interaction.response.send_message(
            f"{E.FAIL} Die ID muss eine Zahl sein.", ephemeral=True)
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
        await interaction.response.send_message(
            f"{E.FAIL} Die ID muss eine Zahl sein.", ephemeral=True)
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
        ("Version", "2.6.1", True)
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
    state = "AKTIVIERT ✅" if enabled else "DEAKTIVIERT ❌"
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
                note = f" ⚠️ {member_count} Member können @everyone pingen!"
            if position_pct > max_safe_pct:
                note += f" ⚠️ Sehr hohe Hierarchie-Position ({position_pct}%)."
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
    sev_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}

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
        desc_lines.append(f"{sev_emoji.get(sev, '⚪')} **[{sev}] {label}**\n{msg}")
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
    for mod in LOG_MODULES:
        cid = log_channels.get(mod)
        fields.append((mod, f"<#{cid}>" if cid else "*Standard*", True))
    embed = create_embed(f"{E.CHANNEL} Log-Konfiguration",
                         "Übersicht aller Log-Kanäle pro Modul.",
                         COLOR_INFO, fields)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="logmodules", description="Listet alle verfügbaren Log-Module")
@app_commands.default_permissions(administrator=True)
async def slash_logmodules(interaction: discord.Interaction) -> None:
    text = "\n".join(f"• `{m}`" for m in LOG_MODULES)
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
