# -*- coding: utf-8 -*-
import os
import time
import re
import logging

# ═══════════════════════════════════════════════════════════════
# UPTIME
# ═══════════════════════════════════════════════════════════════
BOT_START_TIME = time.time()
EXTRA_UPTIME = 2334360

def get_uptime(start_time: float = BOT_START_TIME):
    return int(time.time() - start_time) + EXTRA_UPTIME

# ═══════════════════════════════════════════════════════════════
# TOKEN
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("DISCORD_TOKEN") or "DEIN_BOT_TOKEN_HIER"

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("modforge.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("ModForge")

# ═══════════════════════════════════════════════════════════════
# FARBEN & KONSTANTEN
# ═══════════════════════════════════════════════════════════════
COLOR_PRIMARY = 0x4169E1
COLOR_SUCCESS = 0x3CB371
COLOR_WARNING = 0xFEE75C
COLOR_DANGER  = 0xED4245
COLOR_INFO    = 0x00B0F4
COLOR_PURPLE  = 0x9B59B6

FOOTER_TEXT   = "Powered by BotForge 🔒"
FOOTER_ICON   = "https://cdn.discordapp.com/attachments/1484888992209047696/1491469357182615602/file_000000000b5c71f48f7e7249237db00d.png"
VERIFY_BANNER_URL = "https://cdn.discordapp.com/attachments/1484260674145353928/1491861030601490432/1775755687339.png?ex=69d93b5b&is=69d7e9db&hm=d65f0da063a98be84b880e8abbdaeaac62eefe7f674724835b3a7e56b20f4943&"

# ═══════════════════════════════════════════════════════════════
# EMOJI KLASSE
# ═══════════════════════════════════════════════════════════════
class E:
    OK         = "<:1000052153:1493631416355917845>"
    FAIL       = "<:1000052152:1493631418671169546>"
    SPAM       = "<:1000051794:1493333260774805697>"
    NUKE       = "<:1000051798:1493333267481362493>"
    RAID       = "<:1000051717:1493333511489191989>"
    MENTION    = "<:1000051804:1493333277413740625>"
    AUTOMOD    = "<:1000051809:1493333289887334581>"
    GHOST      = "<:1000051752:1493333170005999898>"
    SCAM       = "<:1000051714:1493333518489485485>"
    URLSHORT   = "<:1000051729:1493333478035423292>"
    GEAR       = "<:1000051763:1493333183637225632>"
    CHANNEL    = "<:1000051745:1493333161449619636>"
    PREFIX     = "<:1000051785:1493333233805562126>"
    SETTINGS   = "<:1000051765:1493333200293068963>"
    HELP       = "<:1000051767:1493333187332411503>"
    SYSTEM     = "<:1000051810:1493333291342757969>"
    OWNER      = "<:1000051807:1493333285718196244>"
    SHIELD     = "<:1000051808:1493333287874068660>"
    BOT        = "<:1000051809:1493333289887334581>"
    LATENCY    = "<:1000051758:1493333196438507760>"
    SERVER     = "<:1000051764:1493333190708957234>"
    USERS      = "<:1000051750:1493333172962721872>"
    CLOCK      = "<:1000051766:1493333185281659102>"
    BAN        = "<:1000051714:1493333518489485485>"
    KICK       = "<:1000051798:1493333267481362493>"
    WARN       = "<:1000051717:1493333511489191989>"
    MUTE       = "<:1000051715:1493333515478237409>"
    UNMUTE     = "<:1000051716:1493333509773988051>"
    DELETE     = "<:1000051793:1493333258233057361>"
    SLOW       = "<:1000051751:1493333171675201707>"
    LOCK       = "<:1000051721:1493333505449398382>"
    UNLOCK     = "<:1000051722:1493333498847690985>"
    NICK       = "<:1000051770:1493333205082837202>"
    EDIT       = "<:1000051770:1493333205082837202>"
    ROLE_ADD   = "<:1000051772:1493333206928199690>"
    ROLE_DEL   = "<:1000051788:1493333238817493215>"
    ROLE       = "<:1000051784:1493333231532118137>"
    VOICE_IN   = "<:1000051716:1493333509773988051>"
    VOICE_OUT  = "<:1000051715:1493333515478237409>"
    VOICE_SW   = "<:1000051730:1493333482644967564>"
    DUP        = "<:1000051730:1493333482644967564>"
    CAPS       = "<:1000051760:1493333181657649235>"
    EMOJI      = "<:1000051750:1493333172962721872>"
    BADWORD    = "<:1000051799:1493333269444427898>"
    NEWACC     = "<:1000051779:1493333222115770488>"
    JOIN       = "<:1000051772:1493333206928199690>"
    TICKET     = "<:1000051768:1493333201924390982>"
    TICKET_OK  = "<:1000051630:1493333448688013482>"
    TICKETBOX  = "<:1000051761:1493333192030162967>"
    VERIFY     = "<:1000051808:1493333287874068660>"
    VERIFY_BTN = "<:1000051808:1493333287874068660>"
    EMOJI_LIST = "<:1000051775:1493333213031174224>"
    CREATED    = "<:1000051755:1493333177710678118>"
    ROLES      = "<:1000051792:1493333255091388607>"
    CHANNELS   = "<:1000051804:1493333277413740625>"
    APPEAL     = "📋"
    MESSAGE    = "<:1000051770:1493333205082837202>"
    WEBHOOK    = "<:1000051809:1493333289887334581>"
    PERMS      = "<:1000051808:1493333287874068660>"
    UPDATE     = "<:1000051770:1493333205082837202>"
    NOTE       = "<:1000051767:1493333187332411503>"
    MOD        = "<:1000051808:1493333287874068660>"
    USER       = "<:1000051750:1493333172962721872>"
    IMAGE      = "<:1000051775:1493333213031174224>"
    NO         = "<:1000052152:1493631418671169546>"

# ═══════════════════════════════════════════════════════════════
# REGEX & LISTEN
# ═══════════════════════════════════════════════════════════════
URL_REGEX      = re.compile(r"https?://[^\s]+", re.IGNORECASE)
INVITE_REGEX   = re.compile(r"(discord\.gg|discord\.com/invite)/[a-zA-Z0-9]+", re.IGNORECASE)
ZALGO_REGEX    = re.compile(r"[\u0300-\u036f\u0489\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]{3,}")
SUSPICIOUS_NAME_REGEX = re.compile(r"^(disc(o|0)rd|m(o|0)d|admin|nitro|gift|free)[-_a-z0-9]{0,8}\d{2,}$", re.IGNORECASE)

SCAM_DOMAINS = [
    "discord-nitro", "free-nitro", "discordgift", "steamgift",
    "nitro-free", "discord.gift.com", "dlscord", "discrod"
]
URL_SHORTENERS = ["bit.ly", "tinyurl.com", "cutt.ly", "is.gd", "t.co", "ow.ly", "goo.gl", "rb.gy"]

VALID_PUNISHMENTS = ("warn", "timeout", "kick", "ban")

LOG_MODULES = (
    "default", "moderation", "antispam", "antinuke", "antiraid",
    "antimention", "automod", "antiscam", "antishortener", "voice",
    "members", "nicknames", "channels", "roles", "permissions",
    "webhooks", "appeal", "verify", "tickets", "warns", "errors",
    "cases", "audit", "backup", "welcome",
)

# Zusätzliche Module die per /logset als String eingegeben werden können
# (nicht als Dropdown-Choice, da Discord max 25 erlaubt)
LOG_MODULES_EXTRA = ("messages", "messages_sent", "ghostping", "leave")

DEFAULT_CONFIG = {
    "security_level": 0,
    "log_channel": None,
    "log_channels": {},
    "mod_role": None,
    "admin_role": None,
    "mute_role": None,
    "prefix": "!",
    "verify_system": {
        "enabled": False, "mode": "one_click", "verify_channel": None,
        "add_roles": [], "remove_roles": [], "message_id": None,
        "captcha_difficulty": "medium"
    },
    "ticket_system": {
        "enabled": False, "category_id": None,
        "log_channel_id": None, "ticket_message_id": None
    },
    "anti_spam": {
        "enabled": True, "msg_limit": 5, "msg_window": 10,
        "caps_pct": 70, "emoji_max": 10, "duplicate_max": 3,
        "punishment": "timeout", "timeout_duration": 30
    },
    "anti_nuke": {
        "enabled": True, "threshold": 5, "window": 10,
        "punishment": "ban", "remove_roles": True
    },
    "anti_raid": {
        "enabled": True, "join_threshold": 10, "window": 20,
        "min_account_age": 7, "auto_kick": False, "lockdown": False,
        "new_account_window": 600, "new_account_threshold": 5,
        "suspicious_name_check": True
    },
    "anti_mention": {
        "enabled": True, "mention_limit": 5, "window": 10,
        "punishment": "timeout", "timeout_duration": 60
    },
    "anti_webhook": {
        "enabled": True, "threshold": 3, "window": 30
    },
    "anti_ghost_ping": {
        "enabled": True
    },
    "anti_scam": {
        "enabled": True, "punishment": "ban"
    },
    "anti_url_shortener": {
        "enabled": True, "punishment": "warn"
    },
    "automod": {
        "enabled": True, "bad_words": [], "regex_rules": [],
        "invite_filter": True, "link_filter": True,
        "allowed_domains": [], "zalgo_filter": True,
        "unicode_abuse": True, "phishing_check": True,
        "punishment": "warn"
    },
    "warn_system": {
        "enabled": True,
        "thresholds": {"3": "timeout", "5": "kick", "7": "ban"}
    },
    "message_archive": {
        "enabled": False, "ttl_hours": 48
    },
    "perms_audit": {
        "danger_perms": [
            "administrator", "manage_guild", "manage_roles", "manage_channels",
            "ban_members", "kick_members", "mention_everyone",
            "manage_webhooks", "manage_messages", "moderate_members"
        ],
        "max_safe_position_pct": 80
    },
    "appeal_log_channel": None,
    "backup_system": {
        "auto_enabled": False,
        "auto_interval_hours": 24,
        "auto_max_backups": 5,
        "auto_last_backup": None
    },
    "welcome": {
        "enabled": False,
        "channel_id": None,
        "embed_title": "👋 Willkommen auf {server}!",
        "embed_description": "Hallo {mention}! Willkommen auf **{server}**! Du bist Mitglied #{count}.",
        "embed_color": "#22c55e",
        "embed_image": "",
        "embed_thumbnail": True,
        "embed": True,
        "mention": True,
        "add_roles": [],
        "dm_enabled": False,
        "dm_description": ""
    },
    "leave": {
        "enabled": False,
        "channel_id": None,
        "embed_title": "👋 Auf Wiedersehen!",
        "embed_description": "**{user}** hat den Server verlassen. Wir haben jetzt {count} Mitglieder.",
        "embed_color": "#ef4444",
        "embed_image": "",
        "embed": True
    },
    "sticky_roles": [],
    "temp_voice": {
        "enabled": False,
        "channel_id": None,
        "category_id": None
    },
    "no_prefix": False,
    "no_prefix_users": [],
    "report_channel": None,
    "auto_responses": [],
    "invite_tracking": {"enabled": False, "channel_id": None},
    "warn_decay": {"enabled": False, "decay_days": 30},
    "log_filters": {}
}

# ═══════════════════════════════════════════════════════════════
# HELP DATA
# ═══════════════════════════════════════════════════════════════
HELP_DATA = {
    "mod": (f"{E.NUKE} Moderation", [
        ("/ban <member> [reason]", "Bannt einen Nutzer", "Ban Members", "/ban @User Spam"),
        ("/tempban <member> <duration> [reason]", "Bannt temporär", "Ban Members", "/tempban @User 7d Werbung"),
        ("/softban <member> [days] [reason]", "Ban+Unban (löscht Nachrichten)", "Ban Members", "/softban @User 1 Spam"),
        ("/kick <member> [reason]", "Kickt einen Nutzer", "Kick Members", "/kick @User Beleidigung"),
        ("/warn <member> [reason]", "Verwarnt einen Nutzer", "Manage Messages", "/warn @User Regelverstoß"),
        ("/warnings <member>", "Zeigt Verwarnungen", "Manage Messages", "/warnings @User"),
        ("/clearwarning <member> <index>", "Einzelne Warnung löschen", "Manage Messages", "/clearwarning @User 2"),
        ("/clearwarnings <member>", "Alle Warnungen löschen", "Manage Messages", "/clearwarnings @User"),
        ("/mute <member> [duration] [reason]", "Timeout", "Moderate Members", "/mute @User 600 Spam"),
        ("/tempmute <member> <duration> [reason]", "Persistenter Mute", "Moderate Members", "/tempmute @User 2h Spam"),
        ("/unmute <member>", "Timeout aufheben", "Moderate Members", "/unmute @User"),
        ("/clear [amount]", "Löscht Nachrichten", "Manage Messages", "/clear 50"),
        ("/slowmode [seconds]", "Setzt Slowmode", "Manage Channels", "/slowmode 10"),
        ("/lock", "Sperrt Kanal", "Manage Channels", "/lock"),
        ("/unlock", "Entsperrt Kanal", "Manage Channels", "/unlock"),
        ("/lockall [reason]", "Sperrt ALLE Kanäle", "Administrator", "/lockall Raid"),
        ("/unlockall", "Entsperrt ALLE Kanäle", "Administrator", "/unlockall"),
        ("/unban <user_id>", "Entbannt per ID", "Ban Members", "/unban 123456789"),
        ("/nick <member> [name]", "Nickname ändern", "Manage Nicknames", "/nick @User Neuer Name"),
        ("/massban <ids> [reason]", "Mehrere User bannen", "Ban Members", "/massban 123,456 Spam"),
    ]),
    "info": (f"{E.USERS} Info & Stats", [
        ("/userinfo [member]", "User-Info mit Risk-Score", "—", "/userinfo @User"),
        ("/serverinfo", "Server-Statistiken", "—", "/serverinfo"),
        ("/modstats [mod]", "Moderator-Ranking", "—", "/modstats @Mod"),
        ("/status", "Bot-Status", "—", "/status"),
        ("/stats", "Server-Stats", "—", "/stats"),
        ("/case <id>", "Case-Details anzeigen", "Manage Messages", "/case 42"),
        ("/cases [user]", "Cases mit Pagination", "Manage Messages", "/cases @User"),
        ("/reason <case_id> <grund>", "Case-Grund ändern", "Manage Messages", "/reason 42 Spam"),
        ("/addproof <case_id> <url>", "Beweis anhängen", "Manage Messages", "/addproof 42 https://..."),
    ]),
    "sec": (f"{E.SHIELD} Security", [
        ("/security_level <0-3>", "Sicherheitsstufe setzen", "Administrator", "/security_level 2"),
        ("/panic", "Sofort-Lockdown (Stufe 3)", "Administrator", "/panic"),
        ("/unlockdown", "Lockdown aufheben", "Administrator", "/unlockdown"),
        ("/warnsetup", "Warn-Schwellen konfigurieren", "Administrator", "/warnsetup"),
        ("/warndecay <tage>", "Warns verfallen nach X Tagen", "Administrator", "/warndecay 30"),
    ]),
    "automod": (f"{E.AUTOMOD} AutoMod & Filter", [
        ("/autoresponse_add <trigger> <antwort>", "Auto-Antwort hinzufügen", "Administrator", "/autoresponse_add hallo Willkommen!"),
        ("/autoresponse_list", "Alle Auto-Antworten", "Manage Messages", "/autoresponse_list"),
        ("/autoresponse_del <index>", "Auto-Antwort löschen", "Administrator", "/autoresponse_del 1"),
    ]),
    "logs": (f"{E.CHANNEL} Logging", [
        ("/logs <#channel>", "Standard-Log-Kanal", "Administrator", "/logs #log"),
        ("/logset <modul> <#ch>", "Log pro Modul", "Administrator", "/logset antispam #spam-logs"),
        ("/logreset <modul>", "Modul-Log zurücksetzen", "Administrator", "/logreset antispam"),
        ("/logview", "Alle Log-Kanäle anzeigen", "Administrator", "/logview"),
        ("/logmodules", "Verfügbare Module", "Administrator", "/logmodules"),
        ("/report <member> <grund>", "User ans Mod-Team melden", "—", "/report @User Spam"),
        ("/report_setup <#ch>", "Report-Kanal setzen", "Administrator", "/report_setup #reports"),
    ]),
    "sys": (f"{E.SYSTEM} Setup & System", [
        ("/setup", "Interaktives Setup", "Administrator", "/setup"),
        ("/help", "Diese Hilfe", "—", "/help"),
        ("/noprefix <on/off>", "No-Prefix-Modus", "Administrator", "/noprefix true"),
        ("/setup_verify <#ch> <mode>", "Verifizierung", "Administrator", "/setup_verify #verify captcha"),
        ("/verify_roles", "Verify-Rollen", "Administrator", "/verify_roles @Member @Unverified"),
        ("/setup_tickets <kat> <#log>", "Ticket-System", "Administrator", "/setup_tickets Tickets #log"),
        ("/forcereset", "Config zurücksetzen", "Administrator", "/forcereset"),
    ]),
    "tools": (f"{E.GEAR} Tools & Extras", [
        ("/invites [member]", "Invite-Statistiken", "—", "/invites @User"),
        ("/invites_leaderboard", "Top-Einlader", "Manage Server", "/invites_leaderboard"),
        ("/autorole <role>", "Auto-Rolle für neue Member", "Administrator", "/autorole @Member"),
        ("/autorole_remove <role>", "Auto-Rolle entfernen", "Administrator", "/autorole_remove @Member"),
        ("/stickyrole <role>", "Rolle bleibt nach Rejoin", "Administrator", "/stickyrole @VIP"),
        ("/stickyrole_remove <role>", "Sticky-Role entfernen", "Administrator", "/stickyrole_remove @VIP"),
        ("/reactionrole <#ch>", "Reaction-Role Dropdown", "Administrator", "/reactionrole #roles"),
        ("/tempvoice_setup <#ch>", "Temp-Voice einrichten", "Administrator", "/tempvoice_setup #join"),
        ("/welcome_setup", "Welcome & Leave Setup", "Administrator", "/welcome_setup"),
        ("/welcome_channel <#ch>", "Welcome-Kanal", "Administrator", "/welcome_channel #welcome"),
        ("/leave_channel <#ch>", "Leave-Kanal", "Administrator", "/leave_channel #bye"),
    ]),
    "backup": (f"{E.SHIELD} Backup", [
        ("/backup", "Backup-Menü (Dropdown)", "Administrator", "/backup"),
        ("/backup_create [label]", "Backup erstellen", "Administrator", "/backup_create Vor Reset"),
        ("/backup_list", "Alle Backups", "Administrator", "/backup_list"),
        ("/backup_restore <id>", "Backup wiederherstellen", "Administrator", "/backup_restore abc"),
        ("/backup_delete <id>", "Backup löschen", "Administrator", "/backup_delete abc"),
        ("/backup_autosetup", "Auto-Backups", "Administrator", "/backup_autosetup"),
    ]),
    "owner": (f"{E.OWNER} Admin", [
        ("/massunban", "Alle entbannen", "Administrator", "/massunban"),
        ("/massrole_remove <role>", "Rolle von allen entfernen", "Administrator", "/massrole_remove @Old"),
        ("/audit-perms", "Rechte-Audit", "Administrator", "/audit-perms"),
        ("/setarchive <#ch>", "Archiv-Kanal setzen", "Administrator", "/setarchive #archiv"),
    ]),
}

# ═══════════════════════════════════════════════════════════════
# WEB KONSTANTEN (werden von web/routes.py genutzt)
# ═══════════════════════════════════════════════════════════════
FEATURES = [
    {"icon":"🛡️","title":"Anti-Nuke","desc":"Stoppt Massen-Bans, Kicks und Kanal-/Rollen-Wipes in Echtzeit.","bg":"rgba(237,66,69,.15)"},
    {"icon":"⚡","title":"Anti-Spam","desc":"Erkennt Nachrichten-Spam, CAPS-Missbrauch, Emoji-Flood.","bg":"rgba(254,231,92,.15)"},
    {"icon":"🚨","title":"Anti-Raid","desc":"Schützt vor koordinierten Beitritts-Angriffen.","bg":"rgba(65,105,225,.15)"},
    {"icon":"🤖","title":"AutoMod","desc":"BadWords, Regex, Invite-Filter, Zalgo, Phishing-Schutz.","bg":"rgba(155,89,182,.15)"},
    {"icon":"🔔","title":"Anti-Mention","desc":"Verhindert Massen-Erwähnungen und Mention-Spam.","bg":"rgba(0,176,244,.15)"},
    {"icon":"🎣","title":"Anti-Scam","desc":"Erkennt Scam-Domains und Nitro-Fake-Links.","bg":"rgba(60,179,113,.15)"},
    {"icon":"✅","title":"Verifizierung","desc":"One-Click oder CAPTCHA-Verifizierung.","bg":"rgba(65,105,225,.15)"},
    {"icon":"📋","title":"Case-System","desc":"Case-ID mit Beweisen, Verlauf und Nachrichtenarchiv.","bg":"rgba(254,231,92,.15)"},
    {"icon":"🔍","title":"Perms-Audit","desc":"Findet gefährliche Rollen und Hierarchie-Probleme.","bg":"rgba(155,89,182,.15)"},
    {"icon":"🎫","title":"Tickets","desc":"Professionelles Support-Ticket-System.","bg":"rgba(237,66,69,.15)"},
    {"icon":"👋","title":"Welcome & Leave","desc":"Embed-Builder im Dashboard.","bg":"rgba(60,179,113,.15)"},
    {"icon":"📝","title":"Granulare Logs","desc":"26 Log-Module mit eigenem Kanal.","bg":"rgba(91,110,255,.15)"},
]

CMDS_PREVIEW = [
    {"cmd":"/ban","desc":"Dauerhafter Ban"},{"cmd":"/tempban","desc":"Temporärer Ban"},
    {"cmd":"/kick","desc":"Kick"},{"cmd":"/warn","desc":"Verwarnung"},
    {"cmd":"/mute","desc":"Timeout"},{"cmd":"/case","desc":"Case anzeigen"},
    {"cmd":"/audit-perms","desc":"Perms prüfen"},{"cmd":"/security view","desc":"Sicherheitsübersicht"},
    {"cmd":"/setup","desc":"Setup-Panel"},{"cmd":"/help","desc":"Hilfe"},
]

VERSIONS = [
    {"ver":"3.0.0","date":"2026-05-02","icon":"🚀","badge":"Major","badge_cls":"major","changes":[
        "Neues Discord OAuth2 User-Dashboard (Login mit Discord)",
        "Vollständiger Welcome & Leave Embed-Builder im Dashboard",
        "Per-Modul Einstellungen direkt im Browser konfigurierbar",
        "Changelog-Seite hinzugefügt",
        "Fix: MongoDB-Datenbankname-Konflikt behoben",
        "Fix: log_action ist jetzt eine saubere Modul-Funktion",
        "Leave-System mit konfigurierbaren Embeds",
        "Bot-Status rotiert jetzt alle 10 Sekunden",
        "Verbessertes Anti-Nuke mit detaillierteren Logs",
        "Alle Bot-Antworten mit mehr Text und Details überarbeitet",
    ]},
    {"ver":"2.7.0","date":"2026-04-15","icon":"🛡️","badge":"Fix","badge_cls":"fix","changes":[
        "Voice-Channel-Commands komplett entfernt",
        "Status-Loop alle 10 Sekunden mit 3 rotierenden Texten",
        "Flask-Dashboard mit Dark-Sidebar-Design",
        "Anti-Nuke: Kanal-/Rollen-Löschungs-Tracker verbessert",
        "Tempaction-Loop für Tempban/Tempmute-Aufhebung",
        "Admin-Dashboard mit Live-API-Polling",
    ]},
    {"ver":"2.6.1","date":"2025-12-01","icon":"⚡","badge":"New","badge_cls":"new","changes":[
        "112 Command-Handler komplett überarbeitet",
        "Motor für async MongoDB",
        "Case-System mit Beweisen und Nachrichtenarchiv",
        "Anti-Ghost-Ping Erkennung",
        "URL-Shortener Filter",
        "Whitelist-System mit 5 Kategorien",
        "Permissions-Audit (CRITICAL/HIGH/MEDIUM)",
    ]},
    {"ver":"2.5.0","date":"2025-09-15","icon":"🔨","badge":"Major","badge_cls":"major","changes":[
        "Anti-Raid komplett neu geschrieben",
        "Verify-System mit CAPTCHA-Modal",
        "Ticket-System mit Kategorie-Support",
        "AutoMod: Zalgo, Regex, Domain-Filter",
        "Warn-Schwellen mit automatischen Maßnahmen",
    ]},
    {"ver":"2.0.0","date":"2025-06-01","icon":"🎉","badge":"Major","badge_cls":"major","changes":[
        "Erster öffentlicher Release",
        "Discord.py 2.x mit Slash-Commands",
        "MongoDB-Integration",
        "Anti-Spam, Anti-Nuke, Anti-Scam",
        "Grundlegendes Case- und Warn-System",
    ]},
]

LOG_MODS = ["Moderation","Anti-Spam","Anti-Nuke","Anti-Raid","Anti-Mention","AutoMod",
    "Anti-Scam","Anti-Shortener","Members","Nicknames","Channels","Roles","Permissions",
    "Webhooks","Appeal","Verify","Tickets","Warns","Errors","Cases","Audit","Backup","Welcome","Leave","Default"]

# ═══════════════════════════════════════════════════════════════
# ACTIVITY-STREAM (IN-MEMORY RING-BUFFER)
# ═══════════════════════════════════════════════════════════════
import threading
from collections import deque
from typing import Dict, Any, List, Optional

class ActivityStream:
    def __init__(self, maxlen: int = 500) -> None:
        self.events: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(
        self,
        kind: str,
        text: str,
        guild_id: Optional[int] = None,
        guild_name: Optional[str] = None,
        user_id: Optional[int] = None,
        user_name: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        import datetime
        evt = {
            "kind": kind,
            "text": text,
            "guild_id": guild_id,
            "guild_name": guild_name,
            "user_id": user_id,
            "user_name": user_name,
            "extra": extra or {},
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
        }
        with self._lock:
            self.events.append(evt)

    def snapshot(self, limit: int = 200) -> List[dict]:
        with self._lock:
            data = list(self.events)
        return data[-limit:][::-1]


ACTIVITY = ActivityStream(maxlen=500)
