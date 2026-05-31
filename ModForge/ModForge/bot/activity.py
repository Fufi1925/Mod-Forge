# -*- coding: utf-8 -*-
"""
ModForge Activity Bus
─────────────────────────────────────────────────────────────────────
Zentrales Event-Logging-System.

Jede interessante Aktion im Bot soll `track()` aufrufen.
Die Events werden:
  1. In den Ring-Buffer ACTIVITY gepusht (für Dashboard-Polling)
  2. Via SocketIO an verbundene Clients gesendet (für Live-Feed)
  3. In MongoDB persistiert (für Stats / Charts)
  4. Via Standard-Logger geloggt (für Railway-Logs)

Beispiel:
    from bot.activity import track
    track("spam", f"Spam von {member} ({count}/{window}s)",
          guild=ctx.guild, user=member, severity="warn",
          extra={"count": count, "window": window})
"""
import asyncio
import datetime
import logging
import threading
from collections import deque, defaultdict
from typing import Any, Dict, List, Optional, Union

# discord ist optional (für Type-Checks) — bei Tests evtl. nicht installiert
try:
    import discord
    _HAS_DISCORD = True
except ImportError:
    discord = None  # type: ignore
    _HAS_DISCORD = False

log = logging.getLogger("ModForge.Activity")

# ═══════════════════════════════════════════════════════════════════
# RING BUFFER
# ═══════════════════════════════════════════════════════════════════
class ActivityStream:
    """In-Memory Ring-Buffer pro Bot-Instanz."""

    def __init__(self, maxlen: int = 1000) -> None:
        self.events: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        # Per-guild rate counters (für Stats)
        self.counters: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # 24h rolling window per guild & kind (für /api/guild/<id>/live/stats)
        self.rolling: Dict[int, deque] = defaultdict(lambda: deque(maxlen=10000))

    def push(self, evt: dict) -> None:
        with self._lock:
            self.events.append(evt)
            gid = evt.get("guild_id")
            if gid:
                self.counters[gid][evt["kind"]] += 1
                self.rolling[gid].append((evt["_ts_unix"], evt["kind"]))

    def snapshot(self, limit: int = 200,
                 guild_id: Optional[int] = None) -> List[dict]:
        with self._lock:
            items = list(self.events)
        if guild_id:
            items = [e for e in items if e.get("guild_id") in (guild_id, None)]
        return items[-limit:][::-1]  # newest first

    def stats_24h(self, guild_id: int) -> Dict[str, Any]:
        """Liefert Event-Counts der letzten 24h für eine Guild."""
        import time
        cutoff = time.time() - 86400
        with self._lock:
            rolling = list(self.rolling.get(guild_id, []))
        counts: Dict[str, int] = defaultdict(int)
        per_hour = [0] * 24
        now = time.time()
        for ts, kind in rolling:
            if ts >= cutoff:
                counts[kind] += 1
                hr_back = int((now - ts) // 3600)
                if 0 <= hr_back < 24:
                    per_hour[23 - hr_back] += 1
        return {
            "total": sum(counts.values()),
            "by_kind": dict(counts),
            "per_hour": per_hour,
        }

    def clear_guild(self, guild_id: int) -> None:
        with self._lock:
            self.events = deque(
                (e for e in self.events if e.get("guild_id") != guild_id),
                maxlen=self.events.maxlen,
            )
            self.counters.pop(guild_id, None)
            self.rolling.pop(guild_id, None)


ACTIVITY = ActivityStream(maxlen=1000)


# ═══════════════════════════════════════════════════════════════════
# SEVERITY → ICON + LOG LEVEL
# ═══════════════════════════════════════════════════════════════════
SEVERITY_MAP = {
    "info":     ("ℹ️",  logging.INFO),
    "ok":       ("✅",  logging.INFO),
    "warn":     ("⚠️",  logging.WARNING),
    "danger":   ("🚨",  logging.WARNING),
    "critical": ("💥",  logging.ERROR),
    "debug":    ("🔍",  logging.DEBUG),
}

# Kind → defaults (icon + severity falls nicht überschrieben)
KIND_DEFAULTS = {
    "ready":      ("🟢", "ok"),
    "guild_join": ("➕", "ok"),
    "guild_leave":("➖", "info"),
    "join":       ("👋", "info"),
    "leave":      ("🚪", "info"),
    "ban":        ("🔨", "danger"),
    "unban":      ("🔓", "info"),
    "kick":       ("👢", "warn"),
    "warn":       ("⚠️", "warn"),
    "timeout":    ("⏱️", "warn"),
    "untimeout":  ("🔊", "info"),
    "mute":       ("🔇", "warn"),
    "unmute":     ("🔊", "info"),
    "case":       ("📋", "info"),
    "spam":       ("⚡", "warn"),
    "automod":    ("🤖", "warn"),
    "raid":       ("🚨", "danger"),
    "nuke":       ("💥", "critical"),
    "scam":       ("🎣", "danger"),
    "mention":    ("🔔", "warn"),
    "webhook":    ("🔌", "warn"),
    "ghost":      ("👻", "info"),
    "voice":      ("🎤", "debug"),
    "channel":    ("📁", "info"),
    "role":       ("🏷️", "info"),
    "message":    ("💬", "debug"),
    "error":      ("❌", "critical"),
    "verify":     ("✅", "ok"),
    "ticket":     ("🎫", "info"),
    "backup":     ("💾", "info"),
    "appeal":     ("📬", "info"),
    "lockdown":   ("🔒", "danger"),
    "unlockdown": ("🔓", "ok"),
}


def _kind_meta(kind: str, severity: Optional[str]) -> tuple:
    icon, default_sev = KIND_DEFAULTS.get(kind, ("•", "info"))
    sev = severity or default_sev
    sev_icon, log_lvl = SEVERITY_MAP.get(sev, ("ℹ️", logging.INFO))
    return icon, sev, sev_icon, log_lvl


# ═══════════════════════════════════════════════════════════════════
# SOCKETIO BROADCASTER (opt-in, falls registriert)
# ═══════════════════════════════════════════════════════════════════
_socketio_ref = None


def register_socketio(sio) -> None:
    """Wird von web/app.py aufgerufen — gibt uns die SocketIO-Instanz."""
    global _socketio_ref
    _socketio_ref = sio
    log.info("[ACTIVITY] SocketIO registriert — Live-Feed aktiv")


def _broadcast(evt: dict) -> None:
    """Sendet das Event via SocketIO (best effort)."""
    if _socketio_ref is None:
        return
    try:
        _socketio_ref.emit("activity", evt)
        # Per-guild room
        gid = evt.get("guild_id")
        if gid:
            _socketio_ref.emit("activity", evt, to=f"guild:{gid}")
    except Exception as e:
        log.debug(f"[ACTIVITY] broadcast failed: {e}")


# ═══════════════════════════════════════════════════════════════════
# DB PERSISTENCE
# ═══════════════════════════════════════════════════════════════════
def _persist(evt: dict) -> None:
    """Schreibt das Event async in die MongoDB (best effort)."""
    try:
        from bot.bot import BOT_REF
        if BOT_REF is None or not getattr(BOT_REF, "db", None):
            return
        loop = getattr(BOT_REF, "loop", None)
        if loop is None or not loop.is_running():
            return
        # Fire & forget — wir wollen nicht warten
        asyncio.run_coroutine_threadsafe(
            _async_persist(BOT_REF.db, evt), loop
        )
    except Exception as e:
        log.debug(f"[ACTIVITY] persist failed: {e}")


async def _async_persist(db, evt: dict) -> None:
    try:
        # Nutze die existierende guild_events Collection
        await db.guild_events.insert_one({
            "kind": evt["kind"],
            "text": evt["text"],
            "guild_id": evt.get("guild_id"),
            "guild_name": evt.get("guild_name"),
            "user_id": evt.get("user_id"),
            "user_name": evt.get("user_name"),
            "severity": evt.get("severity", "info"),
            "extra": evt.get("extra", {}),
            "timestamp": datetime.datetime.utcnow(),
        })
    except Exception as e:
        log.debug(f"[ACTIVITY] async persist failed: {e}")


# ═══════════════════════════════════════════════════════════════════
# HAUPT-API
# ═══════════════════════════════════════════════════════════════════
def track(
    kind: str,
    text: str,
    *,
    guild: Any = None,             # discord.Guild | int | None
    user: Any = None,              # discord.Member | discord.User | int | None
    severity: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    persist: bool = True,
    broadcast: bool = True,
    log_msg: bool = True,
) -> dict:
    """
    Loggt ein Event in den zentralen Activity-Bus.

    Args:
        kind: Event-Typ (siehe KIND_DEFAULTS) — z.B. "spam", "ban", "raid"
        text: Menschlich-lesbarer Text
        guild: discord.Guild-Objekt oder Guild-ID
        user: discord.Member/User-Objekt oder User-ID
        severity: "info"|"ok"|"warn"|"danger"|"critical"|"debug" (überschreibt Kind-Default)
        extra: Zusätzliche Daten (werden serialisiert)
        persist: In MongoDB schreiben?
        broadcast: Via SocketIO senden?
        log_msg: Im Logger ausgeben?

    Returns:
        Das Event-Dict
    """
    import time

    icon, sev, sev_icon, log_lvl = _kind_meta(kind, severity)

    # Normalize guild & user (Duck-Typing damit discord nicht required ist)
    gid: Optional[int] = None
    gname: Optional[str] = None
    if guild is not None:
        if hasattr(guild, "id") and hasattr(guild, "name"):
            gid, gname = guild.id, guild.name
        elif isinstance(guild, int):
            gid = guild

    uid: Optional[int] = None
    uname: Optional[str] = None
    if user is not None:
        if hasattr(user, "id"):
            uid = user.id
            uname = str(user)
        elif isinstance(user, int):
            uid = user

    now_unix = time.time()
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"

    evt: Dict[str, Any] = {
        "kind": kind,
        "icon": icon,
        "severity": sev,
        "sev_icon": sev_icon,
        "text": text,
        "guild_id": gid,
        "guild_name": gname,
        "user_id": uid,
        "user_name": uname,
        "extra": extra or {},
        "ts": now_iso,
        "_ts_unix": now_unix,
    }

    # 1. Ring-Buffer
    ACTIVITY.push(evt)

    # 2. Logger
    if log_msg:
        prefix = f"[{kind.upper()}]"
        if gname:
            prefix += f" [{gname}]"
        log.log(log_lvl, f"{prefix} {icon} {text}")

    # 3. Broadcast (best effort)
    if broadcast:
        _broadcast(evt)

    # 4. Persist (best effort)
    if persist:
        _persist(evt)

    return evt


# ═══════════════════════════════════════════════════════════════════
# CONVENIENCE WRAPPERS — kurze Aliase
# ═══════════════════════════════════════════════════════════════════
def info(kind: str, text: str, **kw) -> dict:
    return track(kind, text, severity="info", **kw)

def warn(kind: str, text: str, **kw) -> dict:
    return track(kind, text, severity="warn", **kw)

def danger(kind: str, text: str, **kw) -> dict:
    return track(kind, text, severity="danger", **kw)

def critical(kind: str, text: str, **kw) -> dict:
    return track(kind, text, severity="critical", **kw)

def ok(kind: str, text: str, **kw) -> dict:
    return track(kind, text, severity="ok", **kw)


# ═══════════════════════════════════════════════════════════════════
# BOOT MESSAGE
# ═══════════════════════════════════════════════════════════════════
log.info("[ACTIVITY] Bus initialisiert (Ring=%d events, Persistence=ON)", ACTIVITY.events.maxlen)
