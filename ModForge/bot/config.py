# -*- coding: utf-8 -*-
import os
import time
import re
import logging

# ═══════════════════════════════════════════════════════════════
# UPTIME
# ═══════════════════════════════════════════════════════════════
import threading
from collections import deque
from typing import Dict, Any, List, Optional
BOT_START_TIME = time.time()
# EXTRA_UPTIME war früher fest auf 2334360 (~27 Tage) gesetzt, was die
# Dashboard-Uptime künstlich aufgeblasen hat. Wir lassen den Wert per
# Env-Variable konfigurierbar (z. B. um echte vorherige Laufzeiten
# weiterzuführen), defaulten aber auf 0.
try:
    EXTRA_UPTIME = max(0, int(os.getenv("EXTRA_UPTIME", "0")))
except (TypeError, ValueError):
    EXTRA_UPTIME = 0


def get_uptime(start_time: float = BOT_START_TIME) -> int:
    return int(time.time() - start_time) + EXTRA_UPTIME


# ═══════════════════════════════════════════════════════════════
# TOKEN
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("DISCORD_TOKEN") or ""

# ═══════════════════════════════════════════════════════════════
# DEV-/CONSOLE-LOGGING
# ═══════════════════════════════════════════════════════════════
SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")


def _logger_success(self, message, *args, **kwargs):
    if self.isEnabledFor(SUCCESS_LEVEL):
        self._log(SUCCESS_LEVEL, message, args, **kwargs)


if not hasattr(logging.Logger, "success"):
    logging.Logger.success = _logger_success


class DevConsoleFormatter(logging.Formatter):
    """Schöne, einheitliche Entwickler-Ausgabe für alle Console-Meldungen."""

    ICONS = {
        "DEBUG": "🔎",
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "CRITICAL": "🚨",
    }
    COLORS = {
        "DEBUG": "\033[90m",
        "INFO": "\033[96m",
        "SUCCESS": "\033[92m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "CRITICAL": "\033[95m",
    }
    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"

    def __init__(self) -> None:
        super().__init__()
        self.use_color = os.getenv("NO_COLOR") is None

    def _paint(self, text: str, color: str) -> str:
        if not self.use_color:
            return text
        return f"{color}{text}{self.RESET}"

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        icon = self.ICONS.get(level, "•")
        color = self.COLORS.get(level, "")
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        logger_name = record.name.replace("ModForge.", "").replace("ModForge", "Core")
        logger_name = logger_name[:22]
        message = record.getMessage()
        prefix = f"{icon} {ts} {level:<7}"
        if self.use_color:
            prefix = self._paint(prefix, color)
            logger_part = f"{self.DIM}{logger_name:<22}{self.RESET}"
        else:
            logger_part = f"{logger_name:<22}"
        line = f"{prefix} {logger_part} │ {message}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _setup_logging() -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = logging.FileHandler("modforge.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(DevConsoleFormatter())

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return logging.getLogger("ModForge")


log = _setup_logging()


def dev_print(message: str, level: str = "info", area: str = "Core") -> None:
    """Zentrale schöne Print-/Log-Funktion für Development-Meldungen."""
    logger = logging.getLogger(f"ModForge.{area}" if area else "ModForge")
    level = (level or "info").lower()
    if level in ("success", "ok", "done"):
        logger.success(message)
    elif level in ("warn", "warning"):
        logger.warning(message)
    elif level in ("err", "error", "fail"):
        logger.error(message)
    elif level in ("critical", "fatal"):
        logger.critical(message)
    elif level == "debug":
        logger.debug(message)
    else:
        logger.info(message)


def dev_banner(title: str, *lines: str, level: str = "info", area: str = "Startup") -> None:
    """Schöner Start-/Status-Block in der Console."""
    clean_lines = [str(line) for line in lines if str(line).strip()]
    width = max([len(title), *(len(line) for line in clean_lines)] or [len(title)]) + 4
    border = "═" * width
    dev_print(f"╔{border}╗", level, area)
    dev_print(f"║  {title:<{width-2}}║", level, area)
    for line in clean_lines:
        dev_print(f"║  {line:<{width-2}}║", level, area)
    dev_print(f"╚{border}╝", level, area)

# ═══════════════════════════════════════════════════════════════
# FARBEN & KONSTANTEN
# ═══════════════════════════════════════════════════════════════
COLOR_PRIMARY = 0x4169E1
COLOR_SUCCESS = 0x3CB371
COLOR_WARNING = 0xFEE75C
COLOR_DANGER = 0xED4245
COLOR_INFO = 0x00B0F4
COLOR_PURPLE = 0x9B59B6
# ═══════════════════════════════════════════════════════════════
# BADGE SYSTEM – 25 Badges für User-Tags
# ═══════════════════════════════════════════════════════════════
BADGES = {
    "bug_hunter":       {"name": "Bug Hunter",       "emoji": "🐛", "color": "#22d3ee", "desc": "Hat einen kritischen Bug gemeldet"},
    "premium":          {"name": "Premium",           "emoji": "💎", "color": "#c084fc", "desc": "Premium-Mitglied"},
    "early_supporter":  {"name": "Early Supporter",   "emoji": "🌟", "color": "#fbbf24", "desc": "ModForge seit Tag 1"},
    "contributor":      {"name": "Contributor",       "emoji": "🔧", "color": "#34d399", "desc": "Hat zum Code beigetragen"},
    "translator":       {"name": "Translator",        "emoji": "🌍", "color": "#60a5fa", "desc": "Hat Übersetzungen erstellt"},
    "designer":         {"name": "Designer",          "emoji": "🎨", "color": "#f472b6", "desc": "Hat UI/UX beigesteuert"},
    "moderator":        {"name": "Moderator",         "emoji": "🛡️", "color": "#818cf8", "desc": "Community-Moderator"},
    "veteran":          {"name": "Veteran",           "emoji": "🏆", "color": "#f59e0b", "desc": "1+ Jahr aktives Mitglied"},
    "challenger":       {"name": "Challenger",        "emoji": "⚔️", "color": "#ef4444", "desc": "Hat alle Challenges gemeistert"},
    "event_winner":     {"name": "Event Winner",      "emoji": "🥇", "color": "#facc15", "desc": "Hat ein Event gewonnen"},
    "nitro_booster":    {"name": "Nitro Booster",     "emoji": "💜", "color": "#d946ef", "desc": "Boostet ModForge mit Nitro"},
    "verified":         {"name": "Verified",          "emoji": "✅", "color": "#22c55e", "desc": "Verifiziertes Mitglied"},
    "partner":          {"name": "Partner",           "emoji": "🤝", "color": "#fb923c", "desc": "Offizieller Partner"},
    "staff":            {"name": "Staff",             "emoji": "👔", "color": "#a78bfa", "desc": "ModForge-Team-Mitglied"},
    "developer":        {"name": "Developer",         "emoji": "💻", "color": "#38bdf8", "desc": "Entwickelt Bots/Plugins"},
    "streamer":         {"name": "Streamer",          "emoji": "🎥", "color": "#e879f9", "desc": "Aktiver Streamer"},
    "artist":           {"name": "Artist",            "emoji": "🖌️", "color": "#fb7185", "desc": "Kreativer Künstler"},
    "musician":         {"name": "Musician",          "emoji": "🎵", "color": "#2dd4bf", "desc": "Musik-Talent"},
    "gamer":            {"name": "Gamer",             "emoji": "🎮", "color": "#4ade80", "desc": "Aktiver Gamer"},
    "collector":        {"name": "Collector",         "emoji": "🏅", "color": "#fbbf24", "desc": "Sammelt alle Badges"},
    "helper":           {"name": "Helper",            "emoji": "🙋", "color": "#38bdf8", "desc": "Hilft anderen Mitgliedern"},
    "innovator":        {"name": "Innovator",         "emoji": "💡", "color": "#a3e635", "desc": "Hat innovative Ideen eingebracht"},
    "beta_tester":      {"name": "Beta Tester",       "emoji": "🧪", "color": "#94a3b8", "desc": "Testet neue Features vor Release"},
    "donator":          {"name": "Donator",           "emoji": "❤️", "color": "#f43f5e", "desc": "Hat ModForge gespendet"},
    "og_member":        {"name": "OG Member",          "emoji": "👑", "color": "#eab308", "desc": "Eines der ersten 100 Mitglieder"},
    "message_100":       {"name": "Chat Aktiv",       "emoji": "💬", "color": "#38bdf8", "desc": "Hat 100 Nachrichten geschrieben", "category": "activity", "rarity": "rare", "style": "glow", "level": 1},
    "invite_10":         {"name": "Einlader",         "emoji": "📨", "color": "#22c55e", "desc": "Hat 10 Mitglieder eingeladen", "category": "activity", "rarity": "epic", "style": "shine", "level": 2},
    "member_one_year":   {"name": "1 Jahr Mitglied",  "emoji": "🎂", "color": "#f59e0b", "desc": "Ist seit mindestens einem Jahr auf dem Server", "category": "loyalty", "rarity": "legendary", "style": "legendary", "level": 3},
    "server_booster":    {"name": "Server Booster",   "emoji": "💜", "color": "#d946ef", "desc": "Boostet den Server", "category": "support", "rarity": "epic", "style": "pulse", "level": 2},
}

BADGES.update({
    "bot_owner_dev": {"name": "Bot Owner/Dev", "emoji": "👑", "color": "#f59e0b", "desc": "Offizieller ModForge Bot-Owner und Entwickler", "category": "team", "rarity": "mythic", "style": "legendary", "level": 999},
    "security_expert": {"name": "Security Expert", "emoji": "🔐", "color": "#60a5fa", "desc": "Kennt sich mit Discord-Security besonders gut aus", "category": "moderation", "rarity": "epic", "style": "glow", "level": 5},
    "raid_defender": {"name": "Raid Defender", "emoji": "🛡️", "color": "#22c55e", "desc": "Hat beim Abwehren eines Raids geholfen", "category": "moderation", "rarity": "legendary", "style": "shine", "level": 7},
    "case_master": {"name": "Case Master", "emoji": "📋", "color": "#a78bfa", "desc": "Hat viele Cases sauber bearbeitet", "category": "moderation", "rarity": "rare", "style": "outline", "level": 4},
    "event_host": {"name": "Event Host", "emoji": "🎤", "color": "#fb7185", "desc": "Organisiert Community-Events", "category": "event", "rarity": "rare", "style": "pulse", "level": 3},
    "community_star": {"name": "Community Star", "emoji": "🌟", "color": "#facc15", "desc": "Besonders positives Community-Mitglied", "category": "community", "rarity": "epic", "style": "shine", "level": 5},
    "trusted_member": {"name": "Trusted Member", "emoji": "✅", "color": "#34d399", "desc": "Sehr vertrauenswürdiges Mitglied", "category": "community", "rarity": "rare", "style": "glow", "level": 2},
    "legend": {"name": "Server Legende", "emoji": "🏆", "color": "#f97316", "desc": "Legendäres Mitglied mit besonderem Status", "category": "loyalty", "rarity": "legendary", "style": "legendary", "level": 10},
    "mythic_supporter": {"name": "Mythic Supporter", "emoji": "💠", "color": "#22d3ee", "desc": "Außergewöhnlicher Supporter", "category": "support", "rarity": "mythic", "style": "legendary", "level": 20},
    "founder_friend": {"name": "Founder Friend", "emoji": "🤝", "color": "#c084fc", "desc": "Enger Unterstützer des Projekts", "category": "team", "rarity": "legendary", "style": "shine", "level": 8},
})

_BADGE_STYLE_PRESETS = {
    "bug_hunter": ("moderation", "epic", "glow", 4),
    "premium": ("premium", "epic", "shine", 3),
    "early_supporter": ("support", "legendary", "legendary", 7),
    "contributor": ("team", "rare", "glow", 4),
    "translator": ("community", "rare", "outline", 2),
    "designer": ("team", "epic", "shine", 4),
    "moderator": ("moderation", "rare", "glow", 3),
    "veteran": ("loyalty", "legendary", "pulse", 6),
    "challenger": ("event", "epic", "shine", 4),
    "event_winner": ("event", "legendary", "legendary", 8),
    "nitro_booster": ("support", "epic", "pulse", 4),
    "verified": ("community", "common", "solid", 1),
    "partner": ("team", "epic", "outline", 4),
    "staff": ("team", "rare", "glow", 5),
    "developer": ("team", "epic", "shine", 6),
    "streamer": ("community", "rare", "pulse", 3),
    "artist": ("community", "rare", "shine", 3),
    "musician": ("community", "rare", "pulse", 3),
    "gamer": ("community", "common", "solid", 1),
    "collector": ("activity", "epic", "shine", 5),
    "helper": ("community", "rare", "glow", 3),
    "innovator": ("team", "epic", "glow", 5),
    "beta_tester": ("team", "rare", "outline", 3),
    "donator": ("support", "epic", "pulse", 4),
    "og_member": ("loyalty", "legendary", "legendary", 7),
}
for _bid, (_cat, _rarity, _style, _level) in _BADGE_STYLE_PRESETS.items():
    if _bid in BADGES:
        BADGES[_bid].setdefault("category", _cat)
        BADGES[_bid].setdefault("rarity", _rarity)
        BADGES[_bid].setdefault("style", _style)
        BADGES[_bid].setdefault("level", _level)

FOOTER_TEXT = "Powered by BotForge 🔒"
FOOTER_ICON = "https://cdn.discordapp.com/attachments/1509625552120840315/1511461866512056460/178042110349811.png?ex=6a208a0e&is=6a1f388e&hm=2e4a3f12ba9013ea8991f5835c39a5542b8e1c3385521d9a6ac88f0361a8a5eb"
VERIFY_BANNER_URL = "https://cdn.discordapp.com/attachments/1484260674145353928/1491861030601490432/1775755687339.png?ex=69d93b5b&is=69d7e9db&hm=d65f0da063a98be84b880e8abbdaeaac62eefe7f674724835b3a7e56b20f4943"


# ═══════════════════════════════════════════════════════════════
# EMOJI KLASSE
# ═══════════════════════════════════════════════════════════════
class E:
    OK = "<:1000052153:1493631416355917845>"
    FAIL = "<:1000052152:1493631418671169546>"
    SPAM = "<:1000051794:1493333260774805697>"
    NUKE = "<:1000051798:1493333267481362493>"
    RAID = "<:1000051717:1493333511489191989>"
    MENTION = "<:1000051804:1493333277413740625>"
    AUTOMOD = "<:1000051809:1493333289887334581>"
    GHOST = "<:1000051752:1493333170005999898>"
    SCAM = "<:1000051714:1493333518489485485>"
    URLSHORT = "<:1000051729:1493333478035423292>"
    GEAR = "<:1000051763:1493333183637225632>"
    CHANNEL = "<:1000051745:1493333161449619636>"
    PREFIX = "<:1000051785:1493333233805562126>"
    SETTINGS = "<:1000051765:1493333200293068963>"
    HELP = "<:1000051767:1493333187332411503>"
    SYSTEM = "<:1000051810:1493333291342757969>"
    OWNER = "<:1000051807:1493333285718196244>"
    SHIELD = "<:1000051808:1493333287874068660>"
    BOT = "<:1000051809:1493333289887334581>"
    LATENCY = "<:1000051758:1493333196438507760>"
    SERVER = "<:1000051764:1493333190708957234>"
    USERS = "<:1000051750:1493333172962721872>"
    CLOCK = "<:1000051766:1493333185281659102>"
    BAN = "<:1000051714:1493333518489485485>"
    KICK = "<:1000051798:1493333267481362493>"
    WARN = "<:1000051717:1493333511489191989>"
    MUTE = "<:1000051715:1493333515478237409>"
    UNMUTE = "<:1000051716:1493333509773988051>"
    DELETE = "<:1000051793:1493333258233057361>"
    SLOW = "<:1000051751:1493333171675201707>"
    LOCK = "<:1000051721:1493333505449398382>"
    UNLOCK = "<:1000051722:1493333498847690985>"
    NICK = "<:1000051770:1493333205082837202>"
    EDIT = "<:1000051770:1493333205082837202>"
    ROLE_ADD = "<:1000051772:1493333206928199690>"
    ROLE_DEL = "<:1000051788:1493333238817493215>"
    ROLE = "<:1000051784:1493333231532118137>"
    VOICE_IN = "<:1000051716:1493333509773988051>"
    VOICE_OUT = "<:1000051715:1493333515478237409>"
    VOICE_SW = "<:1000051730:1493333482644967564>"
    DUP = "<:1000051730:1493333482644967564>"
    CAPS = "<:1000051760:1493333181657649235>"
    EMOJI = "<:1000051750:1493333172962721872>"
    BADWORD = "<:1000051799:1493333269444427898>"
    NEWACC = "<:1000051779:1493333222115770488>"
    JOIN = "<:1000051772:1493333206928199690>"
    TICKET = "<:1000051768:1493333201924390982>"
    TICKET_OK = "<:1000051630:1493333448688013482>"
    TICKETBOX = "<:1000051761:1493333192030162967>"
    VERIFY = "<:1000051808:1493333287874068660>"
    VERIFY_BTN = "<:1000051808:1493333287874068660>"
    EMOJI_LIST = "<:1000051775:1493333213031174224>"
    CREATED = "<:1000051755:1493333177710678118>"
    ROLES = "<:1000051792:1493333255091388607>"
    CHANNELS = "<:1000051804:1493333277413740625>"
    APPEAL = "📋"
    MESSAGE = "<:1000051770:1493333205082837202>"
    WEBHOOK = "<:1000051809:1493333289887334581>"
    PERMS = "<:1000051808:1493333287874068660>"
    UPDATE = "<:1000051770:1493333205082837202>"
    NOTE = "<:1000051767:1493333187332411503>"
    MOD = "<:1000051808:1493333287874068660>"
    USER = "<:1000051750:1493333172962721872>"
    IMAGE = "<:1000051775:1493333213031174224>"
    NO = "<:1000052152:1493631418671169546>"
    SPEED = "⚡"
    ALERT = "⚠"
    PLUS = "➕"
    MINUS = "➖"
    QUESTION = "❓"
    LAW = "⚖"
    DOT = "⚪"
    REFRESH = "♻"
    SHIELD_UI = "🛡️"
    SPEED_UI = "⚡"
    RAID_UI = "🚨"
    BOT_UI = "🤖"
    MENTION_UI = "🔔"
    SCAM_UI = "🎣"
    OK_UI = "✅"
    APPEAL_UI = "📋"
    AUDIT_UI = "🔍"
    TICKET_UI = "🎫"
    WELCOME_UI = "👋"
    LOGS_UI = "📝"
    ROCKET = "🚀"
    HAMMER = "🔨"
    PARTY = "🎉"
    RED = "🔴"
    ORANGE = "🟠"
    YELLOW = "🟡"
    GREEN = "🟢"
    BLUE = "🔵"
    FOLDER = "📁"
    CATEGORY = "📂"
    FILE = "📄"
    SAVE = "💾"
    TEXT = "💬"
    VOICE = "🔊"
    LABEL = "🏷️"
    # ── Neue Custom-Emojis für erweiterte Features ──
    CASE = "<:1000051768:1493333201924390982>"
    STATS = "<:1000051764:1493333190708957234>"
    REPORT = "<:1000051717:1493333511489191989>"
    TRANSFER = "<:1000051798:1493333267481362493>"
    VANITY = "<:1000051785:1493333233805562126>"
    ICON_CHANGE = "<:1000051775:1493333213031174224>"
    BANNER_CHANGE = "<:1000051775:1493333213031174224>"
    TOKEN_LEAK = "<:1000051799:1493333269444427898>"
    WEBHOOK_LEAK = "<:1000051809:1493333289887334581>"
    HIERARCHY = "<:1000051808:1493333287874068660>"
    PERM_WARN = "<:1000051717:1493333511489191989>"
    TIMER = "<:1000051766:1493333185281659102>"
    HEART = "<:1000052153:1493631416355917845>"
    DOXX = "<:1000051799:1493333269444427898>"
    IMPERSONATE = "<:1000051752:1493333170005999898>"
    CRYPTO = "<:1000051714:1493333518489485485>"
    APPROVAL = "<:1000051767:1493333187332411503>"
    MULTI_RAID = "<:1000051717:1493333511489191989>"
    TIMEZONE = "<:1000051766:1493333185281659102>"
    PANIC = "<:1000051798:1493333267481362493>"
    SNAPSHOT = "<:1000051764:1493333190708957234>"
    GROWTH = "<:1000051772:1493333206928199690>"
    HEATMAP = "<:1000051764:1493333190708957234>"
    TRANSCRIPT = "<:1000051770:1493333205082837202>"
    PRIORITY_LOW = "<:1000052153:1493631416355917845>"
    PRIORITY_MED = "<:1000051717:1493333511489191989>"
    PRIORITY_HIGH = "<:1000052152:1493631418671169546>"
    PRIORITY_URGENT = "<:1000051798:1493333267481362493>"
    CLAIM = "<:1000051772:1493333206928199690>"
    SURVEY = "<:1000051767:1493333187332411503>"
    CANNED = "<:1000051770:1493333205082837202>"
    MATH = "<:1000051763:1493333183637225632>"
    QUIZ = "<:1000051767:1493333187332411503>"
    TRUST = "<:1000051808:1493333287874068660>"
    ALT = "<:1000051752:1493333170005999898>"
    LOGS_CMD = "<:1000051765:1493333200293068963>"


# ═══════════════════════════════════════════════════════════════
# REGEX & LISTEN
# ═══════════════════════════════════════════════════════════════
URL_REGEX = re.compile(r"https?://[^\s]+", re.IGNORECASE)
INVITE_REGEX = re.compile(
    r"(discord\.gg|discord\.com/invite)/[a-zA-Z0-9]+", re.IGNORECASE
)
ZALGO_REGEX = re.compile(
    r"[\u0300-\u036f\u0489\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]{3,}"
)
SUSPICIOUS_NAME_REGEX = re.compile(
    r"^(disc(o|0)rd|m(o|0)d|admin|nitro|gift|free)[-_a-z0-9]{0,8}\d{2,}$", re.IGNORECASE
)

SCAM_DOMAINS = [
    "discord-nitro",
    "free-nitro",
    "discordgift",
    "steamgift",
    "nitro-free",
    "discord.gift.com",
    "dlscord",
    "discrod",
]
URL_SHORTENERS = [
    "bit.ly",
    "tinyurl.com",
    "cutt.ly",
    "is.gd",
    "t.co",
    "ow.ly",
    "goo.gl",
    "rb.gy",
]

VALID_PUNISHMENTS = ("warn", "timeout", "kick", "ban")

LOG_MODULES = (
    "default",
    "moderation",
    "antispam",
    "antinuke",
    "antiraid",
    "antimention",
    "automod",
    "antiscam",
    "antishortener",
    "voice",
    "members",
    "nicknames",
    "channels",
    "roles",
    "permissions",
    "webhooks",
    "appeal",
    "verify",
    "tickets",
    "warns",
    "errors",
    "cases",
    "audit",
    "backup",
    "welcome",
    "security",
    "antivpn",
)

# Zusätzliche Log-Module für /log und /logchannel
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
        "enabled": False,
        "mode": "one_click",
        "verify_channel": None,
        "add_roles": [],
        "remove_roles": [],
        "message_id": None,
        "captcha_difficulty": "medium",
    },
    "ticket_system": {
        "enabled": False,
        "category_id": None,
        "log_channel_id": None,
        "ticket_message_id": None,
    },
    "anti_spam": {
        "enabled": True,
        "msg_limit": 5,
        "msg_window": 10,
        "caps_pct": 70,
        "emoji_max": 10,
        "duplicate_max": 3,
        "punishment": "timeout",
        "timeout_duration": 30,
    },
    "anti_nuke": {
        "enabled": True,
        "threshold": 5,
        "window": 10,
        "punishment": "ban",
        "remove_roles": True,
    },
    "anti_raid": {
        "enabled": True,
        "join_threshold": 10,
        "window": 20,
        "min_account_age": 7,
        "auto_kick": False,
        "lockdown": False,
        "new_account_window": 600,
        "new_account_threshold": 5,
        "suspicious_name_check": True,
    },
    "anti_mention": {
        "enabled": True,
        "mention_limit": 5,
        "window": 10,
        "punishment": "timeout",
        "timeout_duration": 60,
    },
    "anti_webhook": {"enabled": True, "threshold": 3, "window": 30},
    "anti_ghost_ping": {"enabled": True},
    "anti_scam": {"enabled": True, "punishment": "ban"},
    "anti_url_shortener": {"enabled": True, "punishment": "warn"},
    "automod": {
        "enabled": True,
        "bad_words": [],
        "regex_rules": [],
        "invite_filter": True,
        "link_filter": False,
        "block_all_links": False,
        "allowed_domains": [],
        "zalgo_filter": True,
        "unicode_abuse": True,
        "phishing_check": True,
        "punishment": "warn",
    },
    "warn_decay": {
        "enabled": False,
        "decay_days": 30,
    },
    "warn_system": {
        "enabled": True,
        "thresholds": {"3": "timeout", "5": "kick", "7": "ban"},
    },
    "message_archive": {"enabled": False, "ttl_hours": 48},
    "perms_audit": {
        "danger_perms": [
            "administrator",
            "manage_guild",
            "manage_roles",
            "manage_channels",
            "ban_members",
            "kick_members",
            "mention_everyone",
            "manage_webhooks",
            "manage_messages",
            "moderate_members",
        ],
        "max_safe_position_pct": 80,
    },
    "appeal_log_channel": None,
    "backup_system": {
        "auto_enabled": False,
        "auto_interval_hours": 24,
        "auto_max_backups": 5,
        "auto_last_backup": None,
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
        "dm_description": "",
    },
    "leave": {
        "enabled": False,
        "channel_id": None,
        "embed_title": "👋 Auf Wiedersehen!",
        "embed_description": "**{user}** hat den Server verlassen. Wir haben jetzt {count} Mitglieder.",
        "embed_color": "#ef4444",
        "embed_image": "",
        "embed": True,
    },
    "sticky_roles": [],
    "temp_voice": {
        "enabled": False,
        "category_id": None,
        "hub_channel_id": None,
        "name_template": "🔊 {user}'s Kanal",
        "panel_message_id": None,
        "panel_channel_id": None,
    },
    "no_prefix": False,
    "no_prefix_users": [],
    "report_channel": None,
    "auto_slowmode": {
        "enabled": False,
        "channels": [],
        "thresholds": {"30": 5, "60": 15, "100": 30},
    },
    "auto_responses": [],
    "invite_tracking": {"enabled": False, "channel_id": None},
    "log_filters": {},
    "auto_ban_appeal": {"enabled": False},
    "anti_vpn": {"enabled": False, "action": "kick", "whitelist_ids": []},
    "dashboard_theme": "purple",
    "dashboard_onboarding": {
        "wizard_popup_seen": False,
        "wizard_popup_seen_at": None,
        "wizard_profile": None,
    },
    "badge_automation": {
        "enabled": True,
        "message_badge_enabled": True,
        "message_threshold": 100,
        "message_badge_id": "message_100",
        "invite_badge_enabled": True,
        "invite_threshold": 10,
        "invite_badge_id": "invite_10",
        "one_year_enabled": True,
        "one_year_days": 365,
        "one_year_badge_id": "member_one_year",
        "booster_enabled": True,
        "booster_badge_id": "server_booster",
    },
    "server_tag": {"enabled": False, "tag": None, "reward_role": None},
    "auto_nickname": {"enabled": False, "rules": []},
    "webhook_logging": {"enabled": False, "webhooks": {}},
    "public_page": {"enabled": False, "invite_url": None},
    "birthday": {"enabled": False, "channel_id": None, "role_id": None},
    # ── NEUE FEATURES ──────────────────────────────────────
    # Security / Anti-Nuke (1-50)
    "nuke_protection": {
        "enabled": True,
        "auto_backup_on_nuke": True,
        "auto_restore_on_nuke": False,
        "channel_mass_delete_limit": 3,
        "role_mass_delete_limit": 3,
        "bot_mass_add_limit": 3,
        "emoji_mass_delete_limit": 5,
        "category_mass_create_limit": 3,
        "voice_mass_delete_limit": 3,
        "invite_mass_delete_limit": 5,
        "window": 15,
        "auto_restore_channels": True,
        "auto_restore_roles": True,
        "nuke_attempt_permaban_threshold": 3,
        "freeze_perms_on_nuke": True,
        "alert_all_admins": True,
        "emergency_contacts": [],
        "nuke_whitelist": [],
    },
    "server_protection": {
        "enabled": True,
        "vanity_url_protect": True,
        "server_icon_protect": True,
        "server_banner_protect": True,
        "server_transfer_protect": True,
        "webhook_spam_limit": 5,
        "webhook_spam_window": 10,
        "auto_regen_webhooks": True,
        "bot_approval_required": False,
        "bot_approval_channel": None,
        "approved_bots": [],
        "admin_perm_monitor": True,
        "role_hierarchy_protect": True,
        "channel_topic_spam_limit": 5,
        "suspicious_time_start": 2,
        "suspicious_time_end": 6,
    },
    "raid_detection": {
        "multi_server": True,
        "countdown_warning": True,
        "countdown_seconds": 60,
        "timezone_detection": True,
    },
    "leak_protection": {
        "enabled": True,
        "token_leak_scan": True,
        "webhook_url_leak_scan": True,
        "ip_leak_scan": True,
    },
    # Verification (51-110)
    "verify_extended": {
        "math_captcha": False,
        "quiz_mode": False,
        "quiz_questions": [],
        "multi_step": False,
        "steps": [],
        "timer_enabled": False,
        "timer_minutes": 10,
        "timer_action": "kick",
        "role_progression": False,
        "progression_roles": [],
        "bypass_trusted_servers": [],
        "bypass_account_age_days": 90,
        "reverify_days": 0,
        "level_system": False,
        "log_channel": None,
        "failed_counter_limit": 5,
        "failed_action": "kick",
        "rate_limit_per_minute": 3,
        "anti_alt_account": True,
        "anti_alt_min_age_hours": 24,
        "trust_score_enabled": True,
        "trust_score_min": 30,
        "blacklist_ids": [],
        "whitelist_ids": [],
        "admin_approval_required": False,
        "admin_approval_channel": None,
        "custom_questions": [],
        "embed_title": "✅ Verifizierung",
        "embed_description": "Klicke den Button um dich zu verifizieren.",
        "embed_color": "#4169E1",
        "button_label": "Verifizieren",
        "button_emoji": "✅",
        "dropdown_mode": False,
        "dropdown_options": [],
    },
    # Tickets (111-160)
    "ticket_extended": {
        "categories": [],
        "priority_enabled": True,
        "priority_levels": ["low", "medium", "high", "urgent"],
        "assignment_enabled": True,
        "escalation_enabled": False,
        "escalation_minutes": 60,
        "escalation_role": None,
        "sla_enabled": False,
        "sla_minutes": 120,
        "auto_close_hours": 48,
        "auto_archive": True,
        "transcript_format": "html",
        "satisfaction_survey": True,
        "response_tracking": True,
        "tag_system": True,
        "tags": [],
        "canned_responses": [],
        "templates": [],
        "thread_mode": False,
        "forum_mode": False,
        "max_open_per_user": 3,
        "claim_system": True,
        "color_coding": {"low": "#22c55e", "medium": "#f59e0b", "high": "#ef4444", "urgent": "#dc2626"},
        "duplicate_detection": True,
        "faq_suggestions": [],
    },
    # AutoMod Extended (162-230)
    "automod_extended": {
        "leetspeak_filter": True,
        "homoglyph_filter": True,
        "zero_width_filter": True,
        "invisible_char_filter": True,
        "spoiler_abuse_filter": True,
        "codeblock_abuse_filter": True,
        "markdown_spam_filter": True,
        "ascii_art_filter": True,
        "copypasta_filter": True,
        "copypasta_min_length": 500,
        "image_spam_limit": 5,
        "image_spam_window": 30,
        "gif_spam_limit": 5,
        "sticker_spam_limit": 5,
        "embed_spam_limit": 3,
        "link_spam_limit": 3,
        "link_spam_window": 10,
        "phishing_live_db": True,
        "crypto_scam_filter": True,
        "gambling_filter": True,
        "nsfw_link_filter": True,
        "token_grabber_filter": True,
        "ip_logger_filter": True,
        "fake_nitro_filter": True,
        "fake_giveaway_filter": True,
        "typosquat_filter": True,
        "self_harm_filter": True,
        "self_harm_response": "Wenn du Hilfe brauchst: Telefonseelsorge 0800 111 0 111",
        "doxxing_filter": True,
        "impersonation_filter": True,
        "account_age_filter_hours": 0,
        "message_length_max": 0,
        "char_repeat_max": 20,
        "word_repeat_max": 10,
        "rapid_message_limit": 10,
        "rapid_message_window": 5,
        "cross_channel_spam_limit": 5,
        "cross_channel_spam_window": 10,
        "ad_filter": True,
        "ad_keywords": ["buy", "sell", "cheap", "discount", "free robux", "free nitro"],
    },
    # Stats (301-350)
    "stats_system": {
        "enabled": False,
        "track_messages": True,
        "track_voice": True,
        "track_joins": True,
        "track_commands": True,
        "heatmap_enabled": True,
        "retention_days": 90,
    },
    # Admin (431-500)
    "admin_extended": {
        "panic_button_enabled": True,
        "panic_action": "lockdown",
        "emergency_mode": False,
        "scheduler_tasks": [],
        "reminders": [],
        "health_check_channel": None,
    },
    # Dashboard Theme (551-600)
    "dashboard_extended": {
        "theme": "dark",
        "accent_color": "#7c3aed",
        "custom_css": "",
        "large_text": False,
        "high_contrast": False,
        "reduced_motion": False,
        "language": "de",
    },
}

# ═══════════════════════════════════════════════════════════════
# HELP DATA
# ═══════════════════════════════════════════════════════════════
HELP_DATA = {
    "mod": (
        f"{E.NUKE} Moderation",
        [
            (
                "/ban <member> [reason]",
                "Bannt einen Nutzer",
                "Ban Members",
                "/ban @User Spam",
            ),
            (
                "/tempban <member> <duration> [reason]",
                "Bannt temporär",
                "Ban Members",
                "/tempban @User 7d Werbung",
            ),
            (
                "/softban <member> [days] [reason]",
                "Ban+Unban (löscht Nachrichten)",
                "Ban Members",
                "/softban @User 1 Spam",
            ),
            (
                "/kick <member> [reason]",
                "Kickt einen Nutzer",
                "Kick Members",
                "/kick @User Beleidigung",
            ),
            (
                "/warn <member> [reason]",
                "Verwarnt einen Nutzer",
                "Manage Messages",
                "/warn @User Regelverstoß",
            ),
            (
                "/warnings <member>",
                "Zeigt Verwarnungen",
                "Manage Messages",
                "/warnings @User",
            ),
            (
                "/clearwarning <member> <index>",
                "Einzelne Warnung löschen",
                "Manage Messages",
                "/clearwarning @User 2",
            ),
            (
                "/clearwarnings <member>",
                "Alle Warnungen löschen",
                "Manage Messages",
                "/clearwarnings @User",
            ),
            (
                "/mute <member> [duration] [reason]",
                "Timeout",
                "Moderate Members",
                "/mute @User 600 Spam",
            ),
            (
                "/tempmute <member> <duration> [reason]",
                "Persistenter Mute",
                "Moderate Members",
                "/tempmute @User 2h Spam",
            ),
            (
                "/unmute <member>",
                "Timeout aufheben",
                "Moderate Members",
                "/unmute @User",
            ),
            ("/clear [amount]", "Löscht Nachrichten", "Manage Messages", "/clear 50"),
            (
                "/slowmode [seconds]",
                "Setzt Slowmode",
                "Manage Channels",
                "/slowmode 10",
            ),
            ("/lock", "Sperrt Kanal", "Manage Channels", "/lock"),
            ("/unlock", "Entsperrt Kanal", "Manage Channels", "/unlock"),
            (
                "/lockall [reason]",
                "Sperrt ALLE Kanäle",
                "Administrator",
                "/lockall Raid",
            ),
            ("/unlockall", "Entsperrt ALLE Kanäle", "Administrator", "/unlockall"),
            ("/unban <user_id>", "Entbannt per ID", "Ban Members", "/unban 123456789"),
            (
                "/nick <member> [name]",
                "Nickname ändern",
                "Manage Nicknames",
                "/nick @User Neuer Name",
            ),
            (
                "/massban <ids> [reason]",
                "Mehrere User bannen",
                "Ban Members",
                "/massban 123,456 Spam",
            ),
        ],
    ),
    "info": (
        f"{E.USERS} Info & Stats",
        [
            ("/userinfo [member]", "User-Info mit Risk-Score", "—", "/userinfo @User"),
            ("/serverinfo", "Server-Statistiken", "—", "/serverinfo"),
            ("/modstats [mod]", "Moderator-Ranking", "—", "/modstats @Mod"),
            (
                "/note <member> <text>",
                "Interne Mod-Notiz",
                "Manage Messages",
                "/note @User Beobachten",
            ),
            (
                "/notes <member>",
                "Alle Notizen anzeigen",
                "Manage Messages",
                "/notes @User",
            ),
            (
                "/delnote <member> <index>",
                "Notiz löschen",
                "Manage Messages",
                "/delnote @User 1",
            ),
            ("/snipe", "Letzte gelöschte Nachricht", "Manage Messages", "/snipe"),
            ("/editsnipe", "Original vor Edit", "Manage Messages", "/editsnipe"),
            ("/case <id>", "Case-Details", "Manage Messages", "/case 42"),
            ("/cases [user]", "Cases mit Filter", "Manage Messages", "/cases @User"),
            ("/case_export [format]", "Cases als HTML/JSON exportieren", "Manage Messages", "/case_export html"),
            ("/status", "Bot-Status", "—", "/status"),
        ],
    ),
    "sec": (
        f"{E.SHIELD} Security",
        [
            (
                "/security_level <0-3>",
                "Sicherheitsstufe setzen",
                "Administrator",
                "/security_level 2",
            ),
            ("/panic", "Sofort-Lockdown (Stufe 3)", "Administrator", "/panic"),
            ("/unlockdown", "Lockdown aufheben", "Administrator", "/unlockdown"),
            (
                "/warnsetup",
                "Warn-Schwellen konfigurieren",
                "Administrator",
                "/warnsetup",
            ),
            (
                "/warndecay <tage>",
                "Warns verfallen nach X Tagen",
                "Administrator",
                "/warndecay 30",
            ),
        ],
    ),
    "automod": (
        f"{E.AUTOMOD} AutoMod & Filter",
        [
            (
                "/autoresponse_add <trigger> <antwort>",
                "Auto-Antwort hinzufügen",
                "Administrator",
                "/autoresponse_add hallo Willkommen!",
            ),
            (
                "/autoresponse_list",
                "Alle Auto-Antworten",
                "Manage Messages",
                "/autoresponse_list",
            ),
            (
                "/autoresponse_del <index>",
                "Auto-Antwort löschen",
                "Administrator",
                "/autoresponse_del 1",
            ),
        ],
    ),
    "logs": (
        f"{E.CHANNEL} Logging",
        [
            ("/log <#channel>", "Einfach: setzt einen Kanal für alle Logs", "Administrator", "/log #logs"),
            ("/logs <#channel>", "Alias von /log", "Administrator", "/logs #logs"),
            (
                "/logchannel <modul> <#ch>",
                "Setzt einen eigenen Log-Kanal für ein Modul",
                "Administrator",
                "/logchannel antispam #spam-logs",
            ),
            (
                "/logchannel_remove <modul>",
                "Entfernt den Modul-Kanal (nutzt wieder Standard)",
                "Administrator",
                "/logchannel_remove antispam",
            ),
            ("/logchannels", "Zeigt die aktuelle Log-Konfiguration", "Administrator", "/logchannels"),
            ("/logmodules", "Zeigt alle verfügbaren Log-Module", "Administrator", "/logmodules"),
            ("/log_test", "Sendet Test-Logs in alle Kanäle", "Administrator", "/log_test"),
            ("/logs_disable", "Deaktiviert alle Log-Kanäle", "Administrator", "/logs_disable"),
            (
                "/report <member> <grund>",
                "User ans Mod-Team melden",
                "—",
                "/report @User Spam",
            ),
            (
                "/report_setup <#ch>",
                "Report-Kanal setzen",
                "Administrator",
                "/report_setup #reports",
            ),
        ],
    ),
    "sys": (
        f"{E.SYSTEM} Setup & System",
        [
            ("/setup", "Interaktives Setup", "Administrator", "/setup"),
            ("/setup-wizard", "Schnelles Setup mit Profilen", "Administrator", "/setup-wizard"),
            ("/doctor", "Prüft Rechte, Logs, DB und Security", "Manage Server", "/doctor"),
            ("/help", "Diese Hilfe", "—", "/help"),
            (
                "/noprefix <on/off>",
                "No-Prefix-Modus",
                "Administrator",
                "/noprefix true",
            ),
            (
                "/setup_verify <#ch> <mode>",
                "Verifizierung",
                "Administrator",
                "/setup_verify #verify captcha",
            ),
            (
                "/verify_roles",
                "Verify-Rollen",
                "Administrator",
                "/verify_roles @Member @Unverified",
            ),
            (
                "/setup_tickets <kat> <#log>",
                "Ticket-System",
                "Administrator",
                "/setup_tickets Tickets #log",
            ),
            ("/forcereset", "Config zurücksetzen", "Administrator", "/forcereset"),
        ],
    ),
    "community": (
        f"{E.USERS} Community",
        [
            (
                "/poll <frage> <opt1> <opt2> [opt3] [opt4]",
                "Abstimmung",
                "—",
                "/poll Pizza oder Burger? Pizza Burger",
            ),
            ("/afk [grund]", "AFK-Status setzen", "—", "/afk Essen"),
            ("/invites [member]", "Invite-Statistiken", "—", "/invites @User"),
            (
                "/invites_leaderboard",
                "Top-Einlader",
                "Manage Server",
                "/invites_leaderboard",
            ),
            ("/report <member> <grund>", "User melden", "—", "/report @User Spam"),
        ],
    ),
    "modplus": (
        f"{E.SHIELD} Mod+",
        [
            (
                "/raidmode <on/off> [dauer]",
                "Manueller Raid-Modus",
                "Administrator",
                "/raidmode on 30",
            ),
            (
                "/softban <member> [days] [grund]",
                "Ban+Unban (löscht Nachrichten)",
                "Ban Members",
                "/softban @User",
            ),
            (
                "/purge_user <member> [amount]",
                "Nachrichten eines Users löschen",
                "Manage Messages",
                "/purge_user @User 50",
            ),
            (
                "/purge_bots [amount]",
                "Bot-Nachrichten löschen",
                "Manage Messages",
                "/purge_bots 50",
            ),
            (
                "/purge_links [amount]",
                "Link-Nachrichten löschen",
                "Manage Messages",
                "/purge_links",
            ),
            (
                "/purge_images [amount]",
                "Bild-Nachrichten löschen",
                "Manage Messages",
                "/purge_images",
            ),
            (
                "/lockall [grund]",
                "ALLE Kanäle sperren",
                "Administrator",
                "/lockall Raid",
            ),
            ("/unlockall", "Alle Kanäle entsperren", "Administrator", "/unlockall"),
            (
                "/noprefix [on/off]",
                "No-Prefix-Modus",
                "Administrator",
                "/noprefix true",
            ),
            (
                "/noprefix_add <member>",
                "Zur No-Prefix Whitelist",
                "Administrator",
                "/noprefix_add @Mod",
            ),
            (
                "/autobanappeal [on/off]",
                "Auto Ban-Appeal DMs",
                "Administrator",
                "/autobanappeal true",
            ),
        ],
    ),
    "tools": (
        f"{E.GEAR} Tools & Extras",
        [
            ("/invites [member]", "Invite-Statistiken", "—", "/invites @User"),
            (
                "/invites_leaderboard",
                "Top-Einlader",
                "Manage Server",
                "/invites_leaderboard",
            ),
            (
                "/autorole <role>",
                "Auto-Rolle für neue Member",
                "Administrator",
                "/autorole @Member",
            ),
            (
                "/autorole_remove <role>",
                "Auto-Rolle entfernen",
                "Administrator",
                "/autorole_remove @Member",
            ),
            (
                "/stickyrole <role>",
                "Rolle bleibt nach Rejoin",
                "Administrator",
                "/stickyrole @VIP",
            ),
            (
                "/stickyrole_remove <role>",
                "Sticky-Role entfernen",
                "Administrator",
                "/stickyrole_remove @VIP",
            ),
            (
                "/reactionrole <#ch>",
                "Reaction-Role Dropdown",
                "Administrator",
                "/reactionrole #roles",
            ),
            (
                "/setup_tempvoice",
                "Temp-Voice einrichten",
                "Administrator",
                "/setup_tempvoice",
            ),
            (
                "/welcome_setup",
                "Welcome & Leave Setup",
                "Administrator",
                "/welcome_setup",
            ),
            (
                "/welcome_channel <#ch>",
                "Welcome-Kanal",
                "Administrator",
                "/welcome_channel #welcome",
            ),
            (
                "/leave_channel <#ch>",
                "Leave-Kanal",
                "Administrator",
                "/leave_channel #bye",
            ),
        ],
    ),
    "backup": (
        f"{E.SHIELD} Backup",
        [
            ("/backup", "Backup-Menü (Dropdown)", "Administrator", "/backup"),
            (
                "/backup_create [label]",
                "Backup erstellen",
                "Administrator",
                "/backup_create Vor Reset",
            ),
            ("/backup_list", "Alle Backups", "Administrator", "/backup_list"),
            (
                "/backup_restore <id>",
                "Backup wiederherstellen",
                "Administrator",
                "/backup_restore abc",
            ),
            (
                "/backup_delete <id>",
                "Backup löschen",
                "Administrator",
                "/backup_delete abc",
            ),
            ("/backup_autosetup", "Auto-Backups", "Administrator", "/backup_autosetup"),
        ],
    ),
    "owner": (
        f"{E.OWNER} Admin",
        [
            ("/massunban", "Alle entbannen", "Administrator", "/massunban"),
            (
                "/massrole_remove <role>",
                "Rolle von allen entfernen",
                "Administrator",
                "/massrole_remove @Old",
            ),
            ("/audit-perms", "Rechte-Audit", "Administrator", "/audit-perms"),
            (
                "/setarchive <#ch>",
                "Archiv-Kanal setzen",
                "Administrator",
                "/setarchive #archiv",
            ),
        ],
    ),
    "wl": (
        f"{E.SHIELD} Whitelist",
        [
            ("/whitelist add [user] [role]", "User oder Rolle whitelisten", "Administrator", "/whitelist add @Mod"),
            ("/whitelist remove [user] [role]", "Whitelist-Eintrag entfernen", "Administrator", "/whitelist remove @Mod"),
            ("/whitelist list", "Whitelist anzeigen", "Administrator", "/whitelist list"),
            ("/nuke_whitelist add <user>", "Extra Anti-Nuke-Whitelist", "Administrator", "/nuke_whitelist add @Admin"),
        ],
    ),
    "appeal": (
        f"{E.APPEAL} Appeal",
        [
            ("/banappeal <on/off>", "Ban-Appeal DMs aktivieren", "Administrator", "/banappeal true"),
            ("/appeal_channel <#ch>", "Appeal-Log-Kanal setzen", "Administrator", "/appeal_channel #appeals"),
        ],
    ),
}

# ═══════════════════════════════════════════════════════════════
# WEB KONSTANTEN (werden von web/routes.py genutzt)
# ═══════════════════════════════════════════════════════════════
FEATURES = [
    {
        "icon": E.SHIELD_UI,
        "title": "Anti-Nuke",
        "desc": "Stoppt Massen-Bans, Kicks und Kanal-/Rollen-Wipes in Echtzeit.",
        "bg": "rgba(237,66,69,.15)",
    },
    {
        "icon": E.SPEED_UI,
        "title": "Anti-Spam",
        "desc": "Erkennt Nachrichten-Spam, CAPS-Missbrauch, Emoji-Flood.",
        "bg": "rgba(254,231,92,.15)",
    },
    {
        "icon": E.RAID_UI,
        "title": "Anti-Raid",
        "desc": "Schützt vor koordinierten Beitritts-Angriffen.",
        "bg": "rgba(65,105,225,.15)",
    },
    {
        "icon": E.BOT_UI,
        "title": "AutoMod",
        "desc": "BadWords, Regex, Invite-Filter, Zalgo, Phishing-Schutz.",
        "bg": "rgba(155,89,182,.15)",
    },
    {
        "icon": E.MENTION_UI,
        "title": "Anti-Mention",
        "desc": "Verhindert Massen-Erwähnungen und Mention-Spam.",
        "bg": "rgba(0,176,244,.15)",
    },
    {
        "icon": E.SCAM_UI,
        "title": "Anti-Scam",
        "desc": "Erkennt Scam-Domains und Nitro-Fake-Links.",
        "bg": "rgba(60,179,113,.15)",
    },
    {
        "icon": E.OK_UI,
        "title": "Verifizierung",
        "desc": "One-Click oder CAPTCHA-Verifizierung.",
        "bg": "rgba(65,105,225,.15)",
    },
    {
        "icon": E.APPEAL_UI,
        "title": "Case-System",
        "desc": "Case-ID mit Beweisen, Verlauf und Nachrichtenarchiv.",
        "bg": "rgba(254,231,92,.15)",
    },
    {
        "icon": E.AUDIT_UI,
        "title": "Perms-Audit",
        "desc": "Findet gefährliche Rollen und Hierarchie-Probleme.",
        "bg": "rgba(155,89,182,.15)",
    },
    {
        "icon": E.TICKET_UI,
        "title": "Tickets",
        "desc": "Professionelles Support-Ticket-System.",
        "bg": "rgba(237,66,69,.15)",
    },
    {
        "icon": E.WELCOME_UI,
        "title": "Welcome & Leave",
        "desc": "Embed-Builder im Dashboard.",
        "bg": "rgba(60,179,113,.15)",
    },
    {
        "icon": E.LOGS_UI,
        "title": "Granulare Logs",
        "desc": "26 Log-Module mit eigenem Kanal.",
        "bg": "rgba(91,110,255,.15)",
    },
]

CMDS_PREVIEW = [
    {"cmd": "/ban", "desc": "Dauerhafter Ban"},
    {"cmd": "/tempban", "desc": "Temporärer Ban"},
    {"cmd": "/kick", "desc": "Kick"},
    {"cmd": "/warn", "desc": "Verwarnung"},
    {"cmd": "/mute", "desc": "Timeout"},
    {"cmd": "/case", "desc": "Case anzeigen"},
    {"cmd": "/audit-perms", "desc": "Perms prüfen"},
    {"cmd": "/security view", "desc": "Sicherheitsübersicht"},
    {"cmd": "/setup", "desc": "Setup-Panel"},
    {"cmd": "/help", "desc": "Hilfe"},
]

VERSIONS = [
    {
        "ver": "3.0.0",
        "date": "2026-05-02",
        "icon": E.ROCKET,
        "badge": "Major",
        "badge_cls": "major",
        "changes": [
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
        ],
    },
    {
        "ver": "2.7.0",
        "date": "2026-04-15",
        "icon": E.SHIELD_UI,
        "badge": "Fix",
        "badge_cls": "fix",
        "changes": [
            "Voice-Channel-Commands komplett entfernt",
            "Status-Loop alle 10 Sekunden mit 3 rotierenden Texten",
            "Flask-Dashboard mit Dark-Sidebar-Design",
            "Anti-Nuke: Kanal-/Rollen-Löschungs-Tracker verbessert",
            "Tempaction-Loop für Tempban/Tempmute-Aufhebung",
            "Admin-Dashboard mit Live-API-Polling",
        ],
    },
    {
        "ver": "2.6.1",
        "date": "2025-12-01",
        "icon": E.SPEED_UI,
        "badge": "New",
        "badge_cls": "new",
        "changes": [
            "112 Command-Handler komplett überarbeitet",
            "Motor für async MongoDB",
            "Case-System mit Beweisen und Nachrichtenarchiv",
            "Anti-Ghost-Ping Erkennung",
            "URL-Shortener Filter",
            "Whitelist-System mit 5 Kategorien",
            "Permissions-Audit (CRITICAL/HIGH/MEDIUM)",
        ],
    },
    {
        "ver": "2.5.0",
        "date": "2025-09-15",
        "icon": E.HAMMER,
        "badge": "Major",
        "badge_cls": "major",
        "changes": [
            "Anti-Raid komplett neu geschrieben",
            "Verify-System mit CAPTCHA-Modal",
            "Ticket-System mit Kategorie-Support",
            "AutoMod: Zalgo, Regex, Domain-Filter",
            "Warn-Schwellen mit automatischen Maßnahmen",
        ],
    },
    {
        "ver": "2.0.0",
        "date": "2025-06-01",
        "icon": E.PARTY,
        "badge": "Major",
        "badge_cls": "major",
        "changes": [
            "Erster öffentlicher Release",
            "Discord.py 2.x mit Slash-Commands",
            "MongoDB-Integration",
            "Anti-Spam, Anti-Nuke, Anti-Scam",
            "Grundlegendes Case- und Warn-System",
        ],
    },
]

LOG_MODS = [
    "Moderation",
    "Anti-Spam",
    "Anti-Nuke",
    "Anti-Raid",
    "Anti-Mention",
    "AutoMod",
    "Anti-Scam",
    "Anti-Shortener",
    "Anti-VPN",
    "Security",
    "Members",
    "Nicknames",
    "Channels",
    "Roles",
    "Permissions",
    "Webhooks",
    "Appeal",
    "Verify",
    "Tickets",
    "Warns",
    "Errors",
    "Cases",
    "Audit",
    "Backup",
    "Welcome",
    "Leave",
    "Default",
]

# ═══════════════════════════════════════════════════════════════
# ACTIVITY-STREAM (IN-MEMORY RING-BUFFER)
# ═══════════════════════════════════════════════════════════════


class ActivityStream:
    def __init__(self, maxlen: int = 500) -> None:
        self.events: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.collection = None

    def set_collection(self, collection):
        self.collection = collection
        # Lade letzte 500 Events beim Start
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._load_initial())
        except RuntimeError:
            pass

    async def _load_initial(self):
        try:
            docs = await self.collection.find().sort("ts", -1).limit(500).to_list(length=500)
            with self._lock:
                for doc in reversed(docs):
                    if "_id" in doc:
                        del doc["_id"]
                    self.events.append(doc)
        except Exception:
            pass

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
        import asyncio

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
            
        if self.collection is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.collection.insert_one(evt.copy()))
            except RuntimeError:
                pass

    def snapshot(self, limit: int = 200) -> List[dict]:
        with self._lock:
            data = list(self.events)
        return data[-limit:][::-1]


ACTIVITY = ActivityStream(maxlen=500)
