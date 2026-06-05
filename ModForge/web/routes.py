"""
ModForge – Web Routes
Alle Routen sauber organisiert. Dateiname = URL-Pfad (z.B. /badges → badges.html).
"""

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    Response,
    abort,
)

import datetime
import logging
import json
import json as _json  # rückwärtskompatibel, falls Code noch _json benutzt
import time
import threading
import copy as _copy

from collections import defaultdict, deque
from functools import wraps

from .app import flask_app
from .auth import get_session, require_auth
from .helpers import (
    _bot_stats,
    _build_overview,
    _build_module_form,
    _build_welcome_content,
)

from .config import (
    DISCORD_CLIENT_ID,
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
)

from bot.bot import bot

from bot.config import (
    FEATURES,
    CMDS_PREVIEW,
    LOG_MODS,
    ACTIVITY,
)

from bot.utils import _run_async

log = logging.getLogger("ModForge.Web.Routes")

# ═══════════════════════════════════════════════════════════
# DIRECT DB ACCESS (works even when bot is offline)
#
# Verwendet die GLEICHE Collection wie die Bot-Datenbank
# (database/db.py → self.config = self.db["config"]).
# Frühere Version schrieb in "configs" (Plural) und der Bot
# hat die Änderungen daher nie gesehen. Behoben.
# ═══════════════════════════════════════════════════════════
_direct_db_client = None          # MongoDB-Database-Handle (Singleton)
_direct_db_tried = False          # True, sobald wir einen Verbindungsversuch gemacht haben
_direct_db_lock = threading.Lock()


def _get_direct_db():
    """Liefert das ``ModForge``-MongoDB-Database-Objekt oder ``None``.

    Ergebnis wird gecacht (auch ``None``), damit wir bei fehlendem
    ``MONGO_URL`` nicht bei jedem Request erneut versuchen zu verbinden.
    """
    global _direct_db_client, _direct_db_tried
    if _direct_db_tried:
        return _direct_db_client

    with _direct_db_lock:
        if _direct_db_tried:
            return _direct_db_client
        _direct_db_tried = True

        import os
        mongo_url = os.getenv("MONGO_URL")
        if not mongo_url:
            log.debug("Direct DB: MONGO_URL nicht gesetzt – kein Direkt-Zugriff.")
            return None
        try:
            from pymongo import MongoClient
            client = MongoClient(
                mongo_url,
                serverSelectionTimeoutMS=2000,
                connectTimeoutMS=2000,
                socketTimeoutMS=4000,
                tlsAllowInvalidCertificates=True,
            )
            # Verbindung sofort prüfen, damit wir Fehler hier abfangen.
            client.admin.command("ping")
            _direct_db_client = client["ModForge"]
            log.info("Direct DB: MongoDB-Verbindung steht (Dashboard-Fallback).")
        except Exception as e:
            log.warning(f"Direct DB connect failed: {e}")
            _direct_db_client = None
        return _direct_db_client


def _sanitize_cfg_for_mongo(cfg):
    """Entfernt nicht-JSON-serialisierbare Felder und Keys mit führendem ``_``."""
    cleaned = {}
    for k, v in (cfg or {}).items():
        if isinstance(k, str) and k.startswith("_") and k != "_id":
            continue
        try:
            json.dumps(v, default=str)
            cleaned[k] = v
        except (TypeError, ValueError):
            cleaned[k] = str(v)
    return cleaned


def _direct_save_config(guild_id, cfg):
    """Speichert die Guild-Konfiguration zuverlässig.

    Strategie (Single Source of Truth = MongoDB):
      1. Schreibe direkt in die Collection ``config`` (Bot nutzt dieselbe).
      2. Aktualisiere zusätzlich den In-Memory-Cache des laufenden Bots,
         damit Änderungen sofort wirken (sonst erst nach Cache-TTL = 5 min).
    Liefert ``True`` bei Erfolg, sonst ``False``.
    """
    gid = int(guild_id)
    cleaned = _sanitize_cfg_for_mongo(cfg)
    cleaned["_id"] = gid

    db = _get_direct_db()
    if db is None:
        # Letzter Versuch: über den Bot (z.B. lokale Entwicklung ohne MONGO_URL für die Web-App)
        try:
            from bot.bot import BOT_REF
            if BOT_REF is not None and getattr(BOT_REF, "db", None) is not None:
                _run_async(BOT_REF.db.aset_config(gid, {k: v for k, v in cleaned.items() if k != "_id"}))
                return True
        except Exception as e:
            log.error(f"Direct save (bot fallback) failed for {gid}: {e}")
        return False

    try:
        db.config.update_one({"_id": gid}, {"$set": cleaned}, upsert=True)
    except Exception as e:
        log.error(f"Direct DB save failed for {gid}: {e}")
        return False

    # Bot-Cache invalidieren / aktualisieren, falls Bot läuft
    try:
        from bot.bot import BOT_REF
        if (
            BOT_REF is not None
            and getattr(BOT_REF, "db", None) is not None
            and hasattr(BOT_REF.db, "_config_cache")
        ):
            cache_copy = _copy.deepcopy(cleaned)
            cache_copy.pop("_id", None)
            BOT_REF.db._config_cache[gid] = cache_copy
    except Exception as e:
        log.debug(f"Bot-Cache-Update nach Save fehlgeschlagen für {gid}: {e}")

    return True


def _direct_load_config(guild_id):
    """Lädt die Guild-Konfiguration.

    Reihenfolge: Bot-Cache → MongoDB direkt → DEFAULT_CONFIG.
    Liefert IMMER ein Dict (nie ``None``), damit Routen sicher arbeiten können.
    """
    gid = int(guild_id)

    # 1) Über den Bot (Cache + DB)
    try:
        from bot.bot import BOT_REF
        if BOT_REF is not None and getattr(BOT_REF, "db", None) is not None:
            cfg = BOT_REF.db.get_config(gid)
            if isinstance(cfg, dict) and len(cfg) > 3:
                return cfg
    except Exception as e:
        log.debug(f"Direct load via bot failed for {gid}: {e}")

    # 2) Direkter MongoDB-Read – richtige Collection: "config"
    try:
        db = _get_direct_db()
        if db is not None:
            doc = db.config.find_one({"_id": gid})
            if isinstance(doc, dict):
                doc.pop("_id", None)
                # Defaults auffüllen, damit das Dashboard alle Keys hat
                from bot.config import DEFAULT_CONFIG
                merged = _copy.deepcopy(DEFAULT_CONFIG)
                merged.update(doc)
                return merged
    except Exception as e:
        log.debug(f"Direct DB load failed: {e}")

    from bot.config import DEFAULT_CONFIG
    return _copy.deepcopy(DEFAULT_CONFIG)



@flask_app.route("/dashboard/<guild_id>/tempvoice")
@require_auth
def guild_tempvoice(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    categories = [{"id": str(c.id), "name": c.name} for c in g.categories] if g else []
    voice_channels = [{"id": str(c.id), "name": c.name} for c in g.voice_channels] if g else []

    return render_template(
        "dashboard/tempvoice.html",
        guild=g,
        cfg=cfg,
        user=us["user"],
        categories=categories,
        voice_channels=voice_channels,
        active="tempvoice"
    )

# =========================================================
# SAFE ASYNC
# =========================================================

def safe_async(coro, default=None):
    try:
        return _run_async(coro)
    except Exception as e:
        log.error(f"[ASYNC ERROR] {e}")
        return default


# =========================================================
# HELPERS
# =========================================================

def bot_ready():
    # Wichtig: discord.py-Bot überschreibt __bool__ nicht, aber wir bleiben
    # konsequent bei "is not None" – das löst die [COUNT ERROR]-Warnungen mit aus.
    try:
        return bot is not None and bot.is_ready()
    except Exception:
        return False


def get_bot_user():
    return getattr(bot, "user", None)


def get_client_id():
    user = get_bot_user()
    if user:
        return str(user.id)
    return str(DISCORD_CLIENT_ID or "")


def get_guild(guild_id):
    try:
        return bot.get_guild(int(guild_id))
    except Exception:
        return None


def safe_collection_count(collection, query=None):
    """Zählt Dokumente in einer Motor-/PyMongo-Collection.

    Wichtig: MotorCollection-Objekte werfen bei ``bool(col)``
    ``NotImplementedError`` (siehe alte Logs:
    ``Collection objects do not implement truth value testing``).
    Daher EXPLIZIT mit ``is None`` vergleichen.
    """
    if query is None:
        query = {}
    if collection is None:
        return 0
    try:
        return safe_async(collection.count_documents(query), 0) or 0
    except Exception as e:
        log.error(f"[COUNT ERROR] {e}")
        return 0


def get_db():
    return getattr(bot, "db", None)


def bot_latency():
    try:
        return round((bot.latency or 0) * 1000)
    except Exception:
        return 0


def _uptime_pct():
    """Berechnet den monatlichen Uptime-Prozentsatz."""
    _, _, uptime_seconds, _ = _bot_stats()
    now = time.time()
    month_start = datetime.datetime.utcnow().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    ).timestamp()
    total_month_seconds = max(1, now - month_start)
    return min(100.0, round((uptime_seconds / total_month_seconds) * 100, 3))


def _base_stats():
    """Gibt gc, mc, up, lat zurück – sicher."""
    try:
        return _bot_stats()
    except Exception as e:
        log.error(f"[BASE STATS ERROR] {e}")
        return 0, 0, 0, 0


# =========================================================
# ADMIN AUTH
# =========================================================

_admin_cache = {"data": None, "ts": 0}
_login_attempts = defaultdict(deque)
_login_lock = threading.Lock()


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


def _ip():
    return (
        request.headers.get("X-Forwarded-For", request.remote_addr or "?")
        .split(",")[0]
        .strip()
    )


def _blocked(ip):
    now = time.time()
    with _login_lock:
        dq = _login_attempts[ip]
        while dq and now - dq[0] > 300:
            dq.popleft()
        return len(dq) >= 8


def _fail(ip):
    with _login_lock:
        _login_attempts[ip].append(time.time())


# =========================================================
# ██████╗ ██╗   ██╗██████╗ ██╗     ██╗ ██████╗
# ██╔══██╗██║   ██║██╔══██╗██║     ██║██╔════╝
# ██████╔╝██║   ██║██████╔╝██║     ██║██║
# ██╔═══╝ ██║   ██║██╔══██╗██║     ██║██║
# ██║     ╚██████╔╝██████╔╝███████╗██║╚██████╗
# ╚═╝      ╚═════╝ ╚═════╝ ╚══════╝╚═╝ ╚═════╝
# =========================================================


# ─── HOME ─────────────────────────────────────────────────

@flask_app.route("/")
def home():
    gc, mc, up, lat = _base_stats()

    guilds_payload = []

    if bot_ready():
        for g in bot.guilds:
            try:
                online = getattr(g, "approximate_presence_count", 0) or 0
                security = 85

                try:
                    if g.verification_level.value >= 2:
                        security += 8
                except Exception:
                    pass

                try:
                    if getattr(g, "premium_subscription_count", 0) > 0:
                        security += 7
                except Exception:
                    pass

                security = min(security, 100)

                avatar_url = (
                    g.icon.url
                    if g.icon
                    else f"https://cdn.discordapp.com/embed/avatars/{g.id % 5}.png"
                )

                guilds_payload.append({
                    "id": str(g.id),
                    "name": g.name,
                    "members": g.member_count or 0,
                    "online": online,
                    "security": f"{security}%",
                    "avatar_url": avatar_url,
                })
            except Exception as e:
                log.error(f"[GUILD PARSE ERROR] {e}")

    guilds_payload.sort(key=lambda x: x["members"], reverse=True)
    
    if not guilds_payload:
        guilds_payload = [
            {'name':'ModForge Support', 'members':1, 'online':1, 'security':'100%', 'avatar_url':'https://cdn.discordapp.com/embed/avatars/0.png'}
        ]

    db = get_db()
    cases_total = 0
    warns_total = 0
    recent_cases_payload = []

    if bot_ready() and db:
        try:
            cases_total = safe_collection_count(db.cases)
            warns_total = safe_collection_count(getattr(db, "data", None), {"type": "warning"})
            
            raw_cases = safe_async(db.cases.find().sort("case_id", -1).limit(4).to_list(4), []) or []
            for c in raw_cases:
                action = c.get("action", "warn")
                color = "#ef4444" if action in ("ban", "kick") else "#fbbf24"
                if action == "mute": color = "#818cf8"
                badge = f"badge-{action}" if action in ("ban", "warn", "mute") else "badge-warn"
                
                # Fetch usernames if possible, otherwise use IDs
                user_id = str(c.get("user_id", "Unknown"))
                mod_id = str(c.get("mod_id", "System"))
                
                user_obj = bot.get_user(c.get("user_id", 0))
                if user_obj: user_id = str(user_obj)
                mod_obj = bot.get_user(c.get("mod_id", 0))
                if mod_obj: mod_id = str(mod_obj)
                
                date_str = "?"
                created_at = c.get("created_at")
                if created_at:
                    date_str = created_at.strftime('%d.%m.%Y %H:%M')
                    
                recent_cases_payload.append({
                    "id": f"#{c.get('case_id', '???')}",
                    "type": action,
                    "user": user_id,
                    "mod": mod_id,
                    "reason": c.get("reason", "Kein Grund"),
                    "date": date_str,
                    "color": color,
                    "badge": badge,
                    "log": ["Aktion ausgeführt", c.get("reason", "")]
                })
        except Exception as e:
            log.error(f"[GLOBAL STATS ERROR] {e}")

    # Fallback fake cases if the DB has none, just so the UI doesn't break and look empty
    if not recent_cases_payload:
        recent_cases_payload = [
            {'id':'#001','type':'ban','user':'dark_spam#0666','mod':'Admin_Lukas','reason':'Phishing-Link verbreitet','date':'08.05.2025 14:32','color':'#ef4444','badge':'badge-ban','log':['Link erkannt','Nachricht gelöscht','Nutzer gebannt','Case erstellt']},
            {'id':'#002','type':'warn','user':'rage_kid#1337','mod':'Mod_Sara','reason':'Massen-Erwähnungen','date':'07.05.2025 09:15','color':'#fbbf24','badge':'badge-warn','log':['Spam erkannt','Nachrichten entfernt','1. Verwarnung']},
            {'id':'#003','type':'mute','user':'troll99#4200','mod':'AutoMod','reason':'Wiederholte Beleidigungen','date':'06.05.2025 22:58','color':'#818cf8','badge':'badge-mute','log':['Beleidigung erkannt','60 Min. stummgeschaltet','DM gesendet']},
            {'id':'#004','type':'kick','user':'new_raider#0000','mod':'ModForge','reason':'Raid-Beteiligung','date':'05.05.2025 03:12','color':'#f59e0b','badge':'badge-warn','log':['Raid erkannt','Auto-Kick ausgeführt']}
        ]

    return render_template(
        "index.html",
        cid=get_client_id(),
        gc=f"{gc:,}",
        mc=f"{mc:,}",
        gc_raw=gc,
        mc_raw=mc,
        up=up,
        lat=round(lat or 0),
        features=FEATURES,
        log_mods=LOG_MODS,
        cmds_preview=CMDS_PREVIEW,
        guilds=guilds_payload,
        recent_cases=recent_cases_payload,
        raids="0",
        spam="0",
        phishing="0",
        cases=f"{cases_total:,}",
        warns=f"{warns_total:,}",
    )


# ─── STATUS ───────────────────────────────────────────────

@flask_app.route("/status")
def status_page():
    gc, mc, uptime_seconds, lat = _base_stats()
    uptime_pct = _uptime_pct()

    db = get_db()
    cases_count = 0
    archive_count = 0

    if bot_ready() and db:
        cases_count = safe_collection_count(getattr(db, "cases", None))
        archive_count = safe_collection_count(getattr(db, "message_archive", None))

    return render_template(
        "status.html",
        gc=gc,
        mc=mc,
        member_count=mc,
        cases_count=cases_count,
        archive_count=archive_count,
        up_s=uptime_seconds,
        lat=round(lat or 0),
        uptime_pct=f"{uptime_pct:.3f}",
        api_latency=round(lat or 0),
        guild_count=gc,
        shard_count=getattr(bot, "shard_count", None) or 1,
    )


# ─── LIVE ─────────────────────────────────────────────────

@flask_app.route("/live")
def live_activity():
    gc, mc, uptime_seconds, lat = _base_stats()
    uptime_pct = _uptime_pct()

    db = get_db()
    cases_count = 0
    archive_count = 0

    if bot_ready() and db:
        try:
            cases_count = safe_collection_count(getattr(db, "cases", None))
            archive_count = safe_collection_count(getattr(db, "message_archive", None))
        except Exception as e:
            log.error(f"[LIVE PAGE ERROR] {e}")

    shard_count = getattr(bot, "shard_count", 1) or 1

    recent_activities = []
    try:
        recent_activities = ACTIVITY.snapshot(20)
    except Exception as e:
        log.error(f"[ACTIVITY SNAPSHOT ERROR] {e}")

    return render_template(
        "live.html",
        uptime_pct=f"{uptime_pct:.3f}",
        api_latency=round(lat or 0),
        guild_count=gc,
        member_count=mc,
        shard_count=shard_count,
        cases_count=cases_count,
        archive_count=archive_count,
        recent_activities=recent_activities,
    )


@flask_app.route("/live/api/activity")
def live_api_activity():
    try:
        data = ACTIVITY.snapshot(50)
        if not isinstance(data, list):
            data = []
        return jsonify(data)
    except Exception as e:
        log.error(f"[LIVE API ERROR] {e}")
        return jsonify([])


# =========================================================
# PRODUKT-SEITEN
# =========================================================

@flask_app.route("/features")
def features():
    from bot.config import FEATURES
    return render_template("features.html", features=FEATURES)

@flask_app.route("/premium")
def premium():
    return render_template("premium.html")

@flask_app.route("/pricing")
def pricing():
    return render_template("pricing.html")

@flask_app.route("/partners")
def partners():
    return render_template("partners.html")

@flask_app.route("/terms")
def terms():
    return render_template(
        "terms.html",
        title="Terms of Service",
        today=str(datetime.date.today()),
    )


@flask_app.route("/privacy")
def privacy():
    return render_template(
        "privacy.html",
        title="Privacy Policy",
        today=str(datetime.date.today()),
    )


@flask_app.route("/imprint")
def imprint():
    return render_template(
        "imprint.html",
        title="Impressum",
        today=str(datetime.date.today()),
    )


@flask_app.route("/legal")
def legal():
    return render_template(
        "legal.html",
        title="Rechtliches",
        today=str(datetime.date.today()),
    )


# =========================================================
# LOGIN / LOGOUT / DASHBOARD
# =========================================================

@flask_app.route("/login")
def discord_login_page():
    return render_template("login.html", cid=get_client_id())


@flask_app.route("/logout")
def logout():
    session.clear()
    resp = redirect(url_for("home"))
    resp.delete_cookie("modforge_session")
    return resp


def _user_can_manage_guild_in_session(user_session, guild_id):
    if not user_session:
        return False
    try:
        for g in user_session.get("guilds", []):
            if str(g["id"]) != str(guild_id):
                continue
            permissions = int(g.get("permissions", 0))
            has_access = (
                g.get("owner")
                or (permissions & 0x8)   # ADMINISTRATOR
                or (permissions & 0x20)  # MANAGE_GUILD
            )
            return bool(has_access)
    except Exception as e:
        log.error(f"[PERMISSION CHECK ERROR] {e}")
    return False


@flask_app.route("/dashboard")
@require_auth
def user_dash_home():
    user_session = get_session()
    if not user_session:
        return redirect(url_for("discord_login_page"))

    user = user_session["user"]
    manageable = []

    bot_guild_ids = set()
    if bot_ready():
        bot_guild_ids = {str(g.id) for g in bot.guilds}
    for g in user_session.get("guilds", []):
        try:
            permissions = int(g.get("permissions", 0))
            allowed = (
                g.get("owner")
                or (permissions & 0x8)
                or (permissions & 0x20)
            )
            if not allowed:
                continue
            is_bot_guild = str(g["id"]) in bot_guild_ids
            manageable.append({
                "id": str(g["id"]),
                "name": g["name"],
                "icon": (
                    f"https://cdn.discordapp.com/icons/"
                    f"{g['id']}/{g.get('icon')}.png?size=128"
                    if g.get("icon")
                    else "https://cdn.discordapp.com/embed/avatars/0.png"
                ),
                "bot_active": is_bot_guild,
            })
        except Exception as e:
            log.error(f"[MANAGEABLE ERROR] {e}")

    # Sortierung: Bot-Server zuerst, dann Rest
    manageable.sort(key=lambda x: (not x["bot_active"], x["name"].lower()))

    return render_template(
        "dashboard_home.html",
        user=user,
        servers=manageable,
        cid=get_client_id(),
    )


# =========================================================
# HEALTH & METRICS (keine Templates)
# =========================================================

@flask_app.route("/healthz")
def healthz():
    return jsonify({
        "ok": True,
        "bot_ready": bot_ready(),
        "latency": bot_latency(),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    })


@flask_app.route("/metrics")
def metrics():
    gc, mc, up, lat = _base_stats()
    db = get_db()
    cases = 0
    archive = 0

    if bot_ready() and db:
        cases = safe_collection_count(getattr(db, "cases", None))
        archive = safe_collection_count(getattr(db, "message_archive", None))

    output = (
        f"modforge_uptime_seconds {up}\n"
        f"modforge_latency_ms {lat}\n"
        f"modforge_guilds {gc}\n"
        f"modforge_members {mc}\n"
        f"modforge_cases {cases}\n"
        f"modforge_archive_messages {archive}\n"
    )
    return Response(output, mimetype="text/plain")


# =========================================================
# ADMIN-PANEL
# =========================================================

@flask_app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    ip = _ip()

    if request.method == "POST":
        if _blocked(ip):
            return render_template(
                "admin/login.html",
                error="Zu viele Fehlversuche. Bitte warte 5 Minuten.",
            ), 429

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not ADMIN_PASSWORD:
            return render_template(
                "admin/login.html",
                error="Admin-Passwort nicht konfiguriert. Setze ADMIN_PASSWORD in den Umgebungsvariablen.",
            ), 503

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            session.permanent = True
            log.info(f"[ADMIN LOGIN] {ip}")
            return redirect(url_for("admin_dashboard"))

        _fail(ip)
        log.warning(f"[ADMIN FAIL] {ip} – falsche Credentials")
        return render_template(
            "admin/login.html",
            error="Benutzername oder Passwort falsch.",
        ), 401

    if session.get("admin"):
        return redirect(url_for("admin_dashboard"))

    return render_template("admin/login.html", error=None)


@flask_app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@flask_app.route("/admin")
@flask_app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    gc, mc, up, lat = _base_stats()
    db = get_db()
    cases_count = 0
    archive_count = 0

    if bot_ready() and db:
        cases_count = safe_collection_count(getattr(db, "cases", None))
        archive_count = safe_collection_count(getattr(db, "message_archive", None))

    return render_template(
        "admin/dashboard.html",
        gc=gc,
        mc=mc,
        up_s=up,
        lat=round(lat or 0),
        cases_count=cases_count,
        archive_count=archive_count,
        bot_ready=bot_ready(),
        shard_count=getattr(bot, "shard_count", None) or 1,
        bot_user=get_bot_user(),
    )


@flask_app.route("/admin/guilds")
@admin_required
def admin_guilds():
    guilds = []
    if bot_ready():
        for g in bot.guilds:
            try:
                guilds.append({
                    "id": str(g.id),
                    "name": g.name,
                    "members": g.member_count or 0,
                    "icon": g.icon.url if g.icon else None,
                    "owner_id": str(g.owner_id),
                })
            except Exception as e:
                log.error(f"[ADMIN GUILDS ERROR] {e}")
    guilds.sort(key=lambda x: x["members"], reverse=True)
    return render_template("admin/guilds.html", guilds=guilds)


@flask_app.route("/admin/guilds/<guild_id>")
@admin_required
def admin_guild_detail(guild_id):
    g = get_guild(guild_id)
    if not g:
        abort(404)

    db = get_db()
    cases = []
    if db:
        try:
            raw = safe_async(
                db.cases.find({"guild_id": str(guild_id)}).to_list(50),
                []
            ) or []
            cases = raw
        except Exception as e:
            log.error(f"[ADMIN GUILD DETAIL ERROR] {e}")

    cfg = _direct_load_config(guild_id)
    active_modules = sum(1 for k in ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"]
                         if cfg.get(k, {}).get("enabled"))
    try:
        config_json = _json.dumps(cfg, indent=2, default=str, ensure_ascii=False)
    except Exception:
        config_json = "{}"
    return render_template(
        "admin/guild_detail.html",
        guild=g,
        cases=cases,
        config=cfg,
        config_json=config_json,
        active_modules=active_modules,
    )


@flask_app.route("/admin/stats")
@admin_required
def admin_stats():
    gc, mc, up, lat = _base_stats()
    uptime_pct = _uptime_pct()
    db = get_db()
    cases_count = 0
    archive_count = 0

    if bot_ready() and db:
        cases_count = safe_collection_count(getattr(db, "cases", None))
        archive_count = safe_collection_count(getattr(db, "message_archive", None))

    return render_template(
        "admin/stats.html",
        gc=gc,
        mc=mc,
        up_s=up,
        lat=round(lat or 0),
        uptime_pct=f"{uptime_pct:.3f}",
        cases_count=cases_count,
        archive_count=archive_count,
        shard_count=getattr(bot, "shard_count", None) or 1,
    )

@flask_app.route("/dashboard/<guild_id>")
@require_auth
def guild_dashboard(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    # ── Guild-Basis-Stats ────────────────────────────────────────
    text_ch = voice_ch = cats = bots = humans = online_count = boosters = 0
    roles_count = emojis_count = 0
    created = ""
    owner_name = "?"
    owner_id   = 0
    boost_tier = boost_count = 0
    features_list = []
    verification  = "?"
    voice_active  = 0   # Mitglieder aktuell im Voice
    in_timeout    = 0   # Mitglieder mit aktivem Timeout

    if g:
        # Channels
        if hasattr(g, 'channels') and g.channels:
            text_ch  = sum(1 for c in g.channels if hasattr(c,'type') and str(c.type) == 'text')
            voice_ch = sum(1 for c in g.channels if hasattr(c,'type') and str(c.type) == 'voice')
        if hasattr(g, 'categories') and g.categories:
            cats = len(g.categories)

        # Members
        if hasattr(g, 'members') and g.members:
            bots         = sum(1 for m in g.members if m.bot)
            humans       = max((g.member_count or 0) - bots, 0)
            online_count = sum(1 for m in g.members
                               if hasattr(m, 'status') and str(m.status) != 'offline')
            voice_active = sum(1 for m in g.members
                               if hasattr(m, 'voice') and m.voice and m.voice.channel)
            in_timeout   = sum(1 for m in g.members
                               if hasattr(m, 'timed_out_until') and m.timed_out_until)

        # Roles / Emojis
        roles_count  = max(len(g.roles) - 1, 0) if hasattr(g, 'roles') and g.roles else 0
        emojis_count = len(g.emojis) if hasattr(g, 'emojis') and g.emojis else 0

        # Created / Owner
        if hasattr(g, 'created_at') and g.created_at:
            created = str(int(g.created_at.timestamp()))
        if hasattr(g, 'owner') and g.owner:
            owner_name = str(g.owner)
            owner_id   = g.owner.id
        elif hasattr(g, 'owner_id') and g.owner_id:
            owner_id = g.owner_id

        # Boosts
        boost_tier  = getattr(g, 'premium_tier', 0) or 0
        boost_count = getattr(g, 'premium_subscription_count', 0) or 0
        if hasattr(g, 'premium_subscribers') and g.premium_subscribers:
            boosters = len(g.premium_subscribers)

        # Features / Verification
        if hasattr(g, 'features') and g.features:
            features_list = list(g.features)[:12]
        if hasattr(g, 'verification_level') and g.verification_level is not None:
            verification = str(g.verification_level).replace("VerificationLevel.", "").title()

    # ── Config-Stats ─────────────────────────────────────────────
    SECURITY_MODULES = [
        ("anti_spam",           "🚫 Anti-Spam"),
        ("anti_nuke",           "💣 Anti-Nuke"),
        ("anti_raid",           "🛡️ Anti-Raid"),
        ("anti_mention",        "📢 Anti-Mention"),
        ("anti_scam",           "🎣 Anti-Scam"),
        ("anti_webhook",        "🔗 Anti-Webhook"),
        ("anti_ghost_ping",     "👻 Anti-Ghost-Ping"),
        ("anti_url_shortener",  "🔗 Anti-URL-Shortener"),
        ("anti_vpn",            "🌐 Anti-VPN"),
        ("automod",             "🤖 AutoMod"),
    ]
    active_mods  = [(label, cfg.get(key, {}).get("enabled", False))
                    for key, label in SECURITY_MODULES]
    active_count = sum(1 for _, e in active_mods if e)

    sec_level          = cfg.get("security_level", 0)
    log_channels_count = len(cfg.get("log_channels", {}) or {})
    has_default_log    = bool(cfg.get("log_channel"))
    webhook_logging    = cfg.get("webhook_logging", {}).get("enabled", False)
    prefix             = cfg.get("prefix", "!")
    no_prefix          = cfg.get("no_prefix", False)

    # Auto-Nickname
    an_cfg         = cfg.get("auto_nickname", {})
    an_enabled     = an_cfg.get("enabled", False)
    an_rules_count = len(an_cfg.get("rules", []))

    # Whitelist
    wl             = cfg.get("whitelist", {})
    wl_users       = len(wl.get("users", []))
    wl_roles       = len(wl.get("roles", []))

    # ── DB-Stats (echte Zahlen) ───────────────────────────────────
    cases_count = warns_count = 0
    recent_cases   = []
    active_bans    = 0
    active_mutes   = 0
    cases_7d       = 0   # Cases der letzten 7 Tage
    top_moderators = []  # Top 3 Mods by case count

    db = get_db()
    if db:
        import datetime as _dt
        gid_str  = str(guild_id)
        gid_int  = int(guild_id)
        week_ago = _dt.datetime.utcnow() - _dt.timedelta(days=7)

        try:
            cases_count = safe_collection_count(db.cases, {"guild_id": gid_str})
        except Exception:
            pass

        try:
            cases_7d = safe_collection_count(db.cases, {
                "guild_id":   gid_str,
                "created_at": {"$gte": week_ago}
            })
        except Exception:
            pass

        try:
            warns_count = safe_collection_count(
                db.data,
                {"type": "warning", "guild_id": gid_int}
            )
        except Exception:
            pass

        try:
            active_bans = safe_collection_count(
                db.tempactions,
                {"guild_id": gid_int, "action": "ban", "active": True}
            )
        except Exception:
            pass

        try:
            active_mutes = safe_collection_count(
                db.data,
                {"type": "mute", "guild_id": gid_int, "active": True}
            )
        except Exception:
            pass

        try:
            raw_cases = safe_async(
                db.cases.find({"guild_id": gid_str})
                        .sort("case_id", -1)
                        .to_list(6),
                []
            ) or []
            recent_cases = raw_cases
        except Exception:
            pass

        # Top Moderatoren (Aggregation nach mod_id)
        try:
            pipeline = [
                {"$match": {"guild_id": gid_str}},
                {"$group": {"_id": "$mod_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 3},
            ]
            top_mods_raw = safe_async(
                db.cases.aggregate(pipeline).to_list(3), []
            ) or []
            for tm in top_mods_raw:
                mod_id   = tm.get("_id", 0)
                mod_name = str(mod_id)
                if g and hasattr(g, 'get_member') and g.get_member(int(mod_id or 0)):
                    mod_name = g.get_member(int(mod_id)).display_name
                top_moderators.append({"name": mod_name, "count": tm["count"]})
        except Exception:
            pass

    # ── Security Score (erweitert & realistisch) ──────────────────
    score = 10  # Basis
    if active_count >= 1:  score += 10
    if active_count >= 3:  score += 10
    if active_count >= 6:  score += 10
    if active_count >= 8:  score += 10
    if has_default_log:    score += 8
    if log_channels_count >= 3: score += 7
    if sec_level >= 1:     score += 8
    if sec_level >= 2:     score += 7
    if webhook_logging:    score += 5
    if boost_tier >= 1:    score += 3
    if verification not in ("None", "none", "", "?"):
        score += 5
    if wl_users > 0 or wl_roles > 0:
        score += 5  # Hat Whitelist konfiguriert
    if an_enabled and an_rules_count > 0:
        score += 2
    score = min(score, 100)

    # Score-Label
    if score >= 80:
        score_label = "Sehr gut geschützt"
        score_color = "var(--green)"
    elif score >= 60:
        score_label = "Gut geschützt"
        score_color = "#86efac"
    elif score >= 40:
        score_label = "Ausbaufähig"
        score_color = "var(--amberl)"
    else:
        score_label = "Gefährdet"
        score_color = "var(--red)"

    # ── Aktivitäts-Prozentsätze für Mini-Bars ─────────────────────
    total_members = max((g.member_count if g and hasattr(g, 'member_count') and g.member_count else 0), 1)
    online_pct    = round((online_count / total_members) * 100)
    bot_pct       = round((bots / total_members) * 100)
    voice_pct     = round((voice_active / total_members) * 100) if total_members > 0 else 0

    return render_template(
        "dashboard/overview.html",
        guild=g, cfg=cfg, user=us["user"], active="overview",
        # Member stats
        text_ch=text_ch, voice_ch=voice_ch, cats=cats,
        bots=bots, humans=humans, online_count=online_count,
        voice_active=voice_active, in_timeout=in_timeout,
        roles_count=roles_count, emojis_count=emojis_count,
        # Server info
        created=created, owner_name=owner_name, owner_id=owner_id,
        boost_tier=boost_tier, boost_count=boost_count, boosters=boosters,
        features_list=features_list, verification=verification,
        # Security
        active_mods=active_mods, active_count=active_count,
        sec_level=sec_level, log_channels_count=log_channels_count,
        has_default_log=has_default_log, webhook_logging=webhook_logging,
        prefix=prefix, no_prefix=no_prefix,
        # Config extras
        an_enabled=an_enabled, an_rules_count=an_rules_count,
        wl_users=wl_users, wl_roles=wl_roles,
        # DB stats
        cases_count=cases_count, warns_count=warns_count,
        recent_cases=recent_cases, cases_7d=cases_7d,
        active_bans=active_bans, active_mutes=active_mutes,
        top_moderators=top_moderators,
        # Score
        score=score, score_label=score_label, score_color=score_color,
        # Prozente
        online_pct=online_pct, bot_pct=bot_pct, voice_pct=voice_pct,
        total_members=total_members,
            )



@flask_app.route("/dashboard/<guild_id>/welcome")
@require_auth
def guild_welcome(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    content = _build_welcome_content(cfg, guild_id)

    # Echte Daten für das überarbeitete Template
    channels = [{"id": str(ch.id), "name": ch.name} for ch in g.text_channels] if g and hasattr(g, "text_channels") else []
    guild_roles = [
        {"id": str(r.id), "name": r.name}
        for r in (g.roles if g and hasattr(g, "roles") and g.roles else [])
        if not r.is_default() and not getattr(r, "managed", False)
    ]
    bot_id = ""
    try:
        if bot_ready() and bot.user:
            bot_id = str(bot.user.id)
    except Exception:
        bot_id = ""

    return render_template(
        "dashboard/welcome.html",
        guild=g, cfg=cfg, content=content, user=us["user"], active="welcome",
        channels=channels, guild_roles=guild_roles, bot_id=bot_id,
    )


# =========================================================
# DASHBOARD API (Settings Toggle)

# =========================================================
# DASHBOARD: ALL SUB-PAGES
# =========================================================

def _dash_guard(guild_id):
    """Shared guard for all dashboard pages."""
    user_session = get_session()
    if not user_session:
        return None, None, None, redirect(url_for("discord_login_page"))
    if not _user_can_manage_guild_in_session(user_session, guild_id):
        return None, None, None, abort(403)
    g = get_guild(guild_id)
    # If bot is offline, create a mock guild from session data
    if not g:
        for sg in user_session.get("guilds", []):
            if str(sg["id"]) == str(guild_id):
                class _MockGuild:
                    def __init__(self, data):
                        self.id = int(data["id"])
                        self.name = data.get("name", "Server")
                        self.member_count = 0
                        self.icon = None
                        self.channels = []
                        self.text_channels = []
                        self.voice_channels = []
                        self.categories = []
                        self.roles = []
                        self.members = []
                        self.owner = None
                        self.owner_id = 0
                    def __getattr__(self, name):
                        return None
                g = _MockGuild(sg)
                break
    if not g:
        return None, None, None, abort(404)
    cfg = _direct_load_config(guild_id)
    return user_session, g, cfg, None


@flask_app.route("/dashboard/<guild_id>/automod")
@require_auth
def guild_automod(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    return render_template("dashboard/automod.html", guild=g, cfg=cfg, user=us["user"], active="automod")

@flask_app.route("/dashboard/<guild_id>/security")
@require_auth
def guild_security(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    # ── Modul-Definitionen mit Defaults ──────────────────────────
    MOD_DEFS = [
        {
            "key":   "anti_spam",
            "icon":  "⚡",
            "label": "Anti-Spam",
            "desc":  "Erkennt Spam, CAPS-Missbrauch, Emoji-Flooding und Duplikate. Bestraft automatisch.",
            "color": "#f59e0b",
            "params": [
                {"key": "msg_limit",        "label": "Nachrichten-Limit",    "type": "number", "min": 2,  "max": 30,    "default": 5,       "unit": "msgs"},
                {"key": "msg_window",       "label": "Zeitfenster",          "type": "number", "min": 3,  "max": 60,    "default": 5,       "unit": "s"},
                {"key": "caps_pct",         "label": "CAPS-Schwelle",        "type": "number", "min": 50, "max": 100,   "default": 70,      "unit": "%"},
                {"key": "emoji_max",        "label": "Max Emojis",           "type": "number", "min": 3,  "max": 50,    "default": 10,      "unit": ""},
                {"key": "duplicate_max",    "label": "Max Duplikate",        "type": "number", "min": 1,  "max": 10,    "default": 3,       "unit": ""},
                {"key": "timeout_duration", "label": "Timeout-Dauer",        "type": "number", "min": 10, "max": 86400, "default": 300,     "unit": "s"},
                {"key": "punishment",       "label": "Bestrafung",           "type": "select", "options": ["warn", "timeout", "kick", "ban"], "default": "timeout"},
            ],
        },
        {
            "key":   "anti_nuke",
            "icon":  "💣",
            "label": "Anti-Nuke",
            "desc":  "Schützt vor Massen-Bans, Channel-Löschungen und Rollen-Änderungen. Automatischer Lockdown + Owner-DM.",
            "color": "#ef4444",
            "params": [
                {"key": "threshold",    "label": "Aktions-Schwelle",  "type": "number", "min": 2,  "max": 20,  "default": 5,     "unit": ""},
                {"key": "window",       "label": "Zeitfenster",       "type": "number", "min": 5,  "max": 120, "default": 10,    "unit": "s"},
                {"key": "remove_roles", "label": "Rollen entfernen",  "type": "toggle", "default": True},
                {"key": "auto_lockdown","label": "Auto-Lockdown",     "type": "toggle", "default": True},
                {"key": "punishment",   "label": "Bestrafung",        "type": "select", "options": ["ban", "kick", "timeout"], "default": "ban"},
            ],
        },
        {
            "key":   "anti_raid",
            "icon":  "🚨",
            "label": "Anti-Raid",
            "desc":  "Erkennt Massen-Joins, filtert neue Accounts, aktiviert automatischen Lockdown.",
            "color": "#f97316",
            "params": [
                {"key": "join_threshold",       "label": "Join-Schwelle",           "type": "number", "min": 3,  "max": 50, "default": 10,    "unit": "/Zeitfenster"},
                {"key": "window",               "label": "Zeitfenster",             "type": "number", "min": 5,  "max": 120,"default": 10,    "unit": "s"},
                {"key": "min_account_age",      "label": "Min. Account-Alter",      "type": "number", "min": 0,  "max": 90, "default": 7,     "unit": "Tage"},
                {"key": "auto_kick",            "label": "Neue Accounts kicken",    "type": "toggle", "default": True},
                {"key": "lockdown",             "label": "Auto-Lockdown",           "type": "toggle", "default": True},
                {"key": "suspicious_name_check","label": "Verdächtige Namen prüfen","type": "toggle", "default": True},
            ],
        },
        {
            "key":   "anti_mention",
            "icon":  "🔔",
            "label": "Anti-Mention",
            "desc":  "Verhindert Mass-Mentions und @everyone/@here-Missbrauch.",
            "color": "#a78bfa",
            "params": [
                {"key": "mention_limit",    "label": "Max Mentions",    "type": "number", "min": 2,  "max": 30,    "default": 5,   "unit": ""},
                {"key": "window",           "label": "Zeitfenster",     "type": "number", "min": 3,  "max": 60,    "default": 10,  "unit": "s"},
                {"key": "timeout_duration", "label": "Timeout-Dauer",   "type": "number", "min": 10, "max": 86400, "default": 600, "unit": "s"},
                {"key": "punishment",       "label": "Bestrafung",      "type": "select", "options": ["warn", "timeout", "kick", "ban"], "default": "timeout"},
            ],
        },
        {
            "key":   "anti_scam",
            "icon":  "🎣",
            "label": "Anti-Scam",
            "desc":  "Erkennt Phishing-Links, Fake-Nitro und bekannte Scam-Domains automatisch.",
            "color": "#06b6d4",
            "params": [
                {"key": "punishment",    "label": "Bestrafung",     "type": "select", "options": ["warn", "timeout", "kick", "ban"], "default": "ban"},
                {"key": "delete_msg",    "label": "Nachricht löschen","type": "toggle", "default": True},
                {"key": "notify_user",   "label": "User benachrichtigen","type": "toggle", "default": True},
            ],
        },
        {
            "key":   "anti_webhook",
            "icon":  "🔌",
            "label": "Anti-Webhook",
            "desc":  "Erkennt verdächtige Webhook-Erstellungen und -Missbrauch.",
            "color": "#8b5cf6",
            "params": [
                {"key": "threshold", "label": "Schwelle",       "type": "number", "min": 1, "max": 10,  "default": 3,  "unit": ""},
                {"key": "window",    "label": "Zeitfenster",    "type": "number", "min": 5, "max": 120, "default": 30, "unit": "s"},
            ],
        },
        {
            "key":   "anti_ghost_ping",
            "icon":  "👻",
            "label": "Anti-Ghost-Ping",
            "desc":  "Erkennt gelöschte Mentions (Ghost-Pings) und loggt/bestraft diese.",
            "color": "#64748b",
            "params": [
                {"key": "punishment",  "label": "Bestrafung",     "type": "select", "options": ["log", "warn", "timeout"], "default": "warn"},
                {"key": "notify",      "label": "Im Chat anzeigen","type": "toggle", "default": True},
            ],
        },
        {
            "key":   "anti_url_shortener",
            "icon":  "🔗",
            "label": "Anti-URL-Shortener",
            "desc":  "Blockiert bekannte URL-Shortener (bit.ly, tinyurl, etc.) aus Sicherheitsgründen.",
            "color": "#10b981",
            "params": [
                {"key": "punishment",  "label": "Bestrafung",        "type": "select", "options": ["warn", "timeout", "kick", "ban"], "default": "warn"},
                {"key": "delete_msg",  "label": "Nachricht löschen", "type": "toggle", "default": True},
            ],
        },
        {
            "key":   "anti_vpn",
            "icon":  "🌐",
            "label": "Anti-VPN",
            "desc":  "Erkennt verdächtige VPN/Proxy-Verbindungen bei neuen Mitgliedern.",
            "color": "#0ea5e9",
            "params": [
                {"key": "action", "label": "Aktion", "type": "select", "options": ["log", "kick", "ban"], "default": "kick"},
            ],
        },
        {
            "key":   "automod",
            "icon":  "🤖",
            "label": "AutoMod",
            "desc":  "Wortfilter, Regex-Filter, Link- und Invite-Blocking mit Custom-Regeln.",
            "color": "#f472b6",
            "params": [
                {"key": "punishment",     "label": "Bestrafung",         "type": "select", "options": ["warn", "timeout", "kick", "ban"], "default": "warn"},
                {"key": "block_invites",  "label": "Invites blockieren", "type": "toggle", "default": True},
                {"key": "block_links",    "label": "Links blockieren",   "type": "toggle", "default": False},
                {"key": "log_only",       "label": "Nur loggen",         "type": "toggle", "default": False},
            ],
        },
    ]

    # ── Config-Werte einfüllen ────────────────────────────────────
    modules = []
    for mod_def in MOD_DEFS:
        mcfg = cfg.get(mod_def["key"], {}) or {}
        params = []
        for p in mod_def["params"]:
            p = dict(p)  # Copy
            raw = mcfg.get(p["key"])
            if raw is None:
                raw = p.get("default", "")
            # Booleans für toggles
            if p["type"] == "toggle":
                p["value"] = bool(raw)
            elif p["type"] == "number":
                try:
                    p["value"] = int(raw)
                except (ValueError, TypeError):
                    p["value"] = p.get("default", 0)
            else:
                p["value"] = str(raw)
            params.append(p)

        modules.append({
            "key":     mod_def["key"],
            "icon":    mod_def["icon"],
            "label":   mod_def["label"],
            "desc":    mod_def["desc"],
            "color":   mod_def["color"],
            "enabled": bool(mcfg.get("enabled", False)),
            "params":  params,
        })

    # ── Whitelist-Zähler ─────────────────────────────────────────
    wl_count = 0
    try:
        if bot_ready():
            wl = bot.db.get_whitelist(int(guild_id))
            wl_count = sum(len(v) for v in wl.values() if isinstance(v, list))
    except Exception:
        pass

    active_count  = sum(1 for m in modules if m["enabled"])
    security_level = int(cfg.get("security_level", 0))

    # Kanal-Liste für Log-Channel Auswahl
    text_channels = []
    if g and hasattr(g, "text_channels") and g.text_channels:
        text_channels = [
            {"id": str(c.id), "name": c.name}
            for c in sorted(g.text_channels, key=lambda c: c.position)
        ]

    return render_template(
        "dashboard/security.html",
        guild=g, cfg=cfg, user=us["user"],
        modules=modules,
        active_count=active_count,
        total_count=len(modules),
        wl_count=wl_count,
        security_level=security_level,
        text_channels=text_channels,
        active="security",
    )

# ═══════════════════════════════════════════════════════════════════
# LOGS
# ═══════════════════════════════════════════════════════════════════
@flask_app.route("/dashboard/<guild_id>/logs")
@require_auth
def guild_logs(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    text_channels = []
    if g and hasattr(g, 'text_channels') and g.text_channels:
        text_channels = [
            {"id": str(c.id), "name": c.name}
            for c in sorted(g.text_channels, key=lambda c: c.position)
        ]

    log_channels = cfg.get("log_channels", {}) or {}

    categories = {
        "🛡️ Security": [
            {"key": "antispam",      "icon": "⚡", "label": "Anti-Spam",       "desc": "Spam, CAPS, Duplikate"},
            {"key": "antinuke",      "icon": "💣", "label": "Anti-Nuke",       "desc": "Massen-Bans, Löschungen"},
            {"key": "antiraid",      "icon": "🚨", "label": "Anti-Raid",       "desc": "Massen-Joins, Lockdown"},
            {"key": "antimention",   "icon": "🔔", "label": "Anti-Mention",    "desc": "Mass-Mentions, @everyone"},
            {"key": "antiscam",      "icon": "🎣", "label": "Anti-Scam",       "desc": "Phishing, Fake-Nitro"},
            {"key": "antishortener", "icon": "🔗", "label": "URL-Shortener",   "desc": "bit.ly, tinyurl etc."},
            {"key": "antivpn",       "icon": "🌐", "label": "Anti-VPN",        "desc": "VPN/Proxy-Erkennung"},
        ],
        "⚖️ Moderation": [
            {"key": "moderation", "icon": "🛡️", "label": "Moderation",  "desc": "Ban, Kick, Mute, Warn"},
            {"key": "warns",      "icon": "⚠️", "label": "Warns",       "desc": "Verwarnungen"},
            {"key": "cases",      "icon": "📋", "label": "Cases",       "desc": "Moderation-Cases"},
            {"key": "automod",    "icon": "🤖", "label": "AutoMod",     "desc": "Wortfilter, Regex"},
            {"key": "appeal",     "icon": "📬", "label": "Ban-Appeal",  "desc": "Entbannungsanträge"},
        ],
        "👥 Server": [
            {"key": "members",     "icon": "👥", "label": "Members",       "desc": "Join, Leave, Update"},
            {"key": "nicknames",   "icon": "📝", "label": "Nicknames",     "desc": "Nickname-Änderungen"},
            {"key": "roles",       "icon": "🏷️", "label": "Rollen",        "desc": "Rollen-Änderungen"},
            {"key": "channels",    "icon": "📁", "label": "Kanäle",        "desc": "Erstellt/Gelöscht/Geändert"},
            {"key": "permissions", "icon": "🔐", "label": "Berechtigungen","desc": "Permission-Änderungen"},
            {"key": "webhooks",    "icon": "🔌", "label": "Webhooks",      "desc": "Webhook-Änderungen"},
        ],
        "🎤 Voice": [
            {"key": "voice", "icon": "🎤", "label": "Voice", "desc": "Join, Leave, Mute, Deaf, Stream"},
        ],
        "💬 Nachrichten": [
            {"key": "messages",      "icon": "💬", "label": "Nachrichten",  "desc": "Gelöscht/Bearbeitet"},
            {"key": "messages_sent", "icon": "📨", "label": "Gesendet",     "desc": "Alle Nachrichten"},
            {"key": "ghostping",     "icon": "👻", "label": "Ghost-Ping",   "desc": "Gelöschte Mentions"},
        ],
        "⚙️ System": [
            {"key": "default", "icon": "📌", "label": "Standard",      "desc": "Fallback alle Module"},
            {"key": "verify",  "icon": "✅", "label": "Verifizierung", "desc": "Captcha, One-Click"},
            {"key": "tickets", "icon": "🎫", "label": "Tickets",       "desc": "Erstellt/Geschlossen"},
            {"key": "welcome", "icon": "👋", "label": "Welcome",       "desc": "Begrüßungsnachrichten"},
            {"key": "leave",   "icon": "🚪", "label": "Leave",         "desc": "Abschiedsnachrichten"},
            {"key": "backup",  "icon": "💾", "label": "Backup",        "desc": "Backup-Ereignisse"},
            {"key": "audit",   "icon": "🔍", "label": "Audit",         "desc": "Audit-Log Einträge"},
            {"key": "errors",  "icon": "❌", "label": "Fehler",        "desc": "Bot-Fehler und Warnungen"},
        ],
    }

    total_modules    = sum(len(v) for v in categories.values())
    total_configured = sum(1 for v in log_channels.values() if v)
    default_channel  = cfg.get("log_channel")
    webhook_enabled  = cfg.get("webhook_logging", {}).get("enabled", False)

    return render_template(
        "dashboard/logs.html",
        guild=g, cfg=cfg, user=us["user"],
        channels=text_channels,
        log_channels=log_channels,
        categories=categories,
        total_modules=total_modules,
        total_configured=total_configured,
        default_channel=default_channel,
        webhook_enabled=webhook_enabled,
        active="logs",
    )

@flask_app.route("/dashboard/<guild_id>/cases")
@require_auth
def guild_cases(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    import datetime as _dt

    cases      = []
    stats      = {
        "total": 0, "ban": 0, "kick": 0, "warn": 0,
        "timeout": 0, "softban": 0, "tempban": 0, "other": 0,
    }
    cases_7d   = 0
    cases_30d  = 0

    db = get_db()
    if db:
        try:
            raw = safe_async(
                db.cases.find({"guild_id": str(guild_id)})
                        .sort("case_id", -1)
                        .to_list(500),
                []
            ) or []

            now      = _dt.datetime.utcnow()
            week_ago  = now - _dt.timedelta(days=7)
            month_ago = now - _dt.timedelta(days=30)

            for c in raw:
                # Timestamp formatieren
                ts = c.get("created_at") or c.get("timestamp")
                ts_str = ""
                ts_iso = ""
                if ts:
                    if isinstance(ts, _dt.datetime):
                        ts_str = ts.strftime("%d.%m.%Y %H:%M")
                        ts_iso = ts.isoformat()
                        if ts >= week_ago:
                            cases_7d += 1
                        if ts >= month_ago:
                            cases_30d += 1
                    else:
                        ts_str = str(ts)[:19]
                        ts_iso = str(ts)

                c["ts_str"] = ts_str
                c["ts_iso"] = ts_iso

                # _id entfernen (nicht JSON-serialisierbar)
                c.pop("_id", None)

                # User-Namen aus Guild auflösen wenn möglich
                uid = c.get("user_id")
                mid = c.get("mod_id") or c.get("moderator_id")

                c["user_name"] = ""
                c["mod_name"]  = ""

                if g and uid:
                    try:
                        member = g.get_member(int(uid))
                        if member:
                            c["user_name"] = member.display_name
                    except Exception:
                        pass

                if g and mid:
                    try:
                        mod = g.get_member(int(mid))
                        if mod:
                            c["mod_name"] = mod.display_name
                    except Exception:
                        pass

                # Stats zählen
                action = str(c.get("action", "other")).lower()
                if action in stats:
                    stats[action] += 1
                else:
                    stats["other"] += 1
                stats["total"] += 1

                cases.append(c)

        except Exception as e:
            log.error(f"[CASES PAGE] {e}")

    return render_template(
        "dashboard/cases.html",
        guild=g, cfg=cfg, user=us["user"],
        cases=cases,
        stats=stats,
        cases_7d=cases_7d,
        cases_30d=cases_30d,
        active="cases",
    )

# ═══════════════════════════════════════════════════════════════════
# WARNS
# ═══════════════════════════════════════════════════════════════════
@flask_app.route("/dashboard/<guild_id>/warns")
@require_auth
def guild_warns(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    import datetime as _dt

    ws         = cfg.get("warn_system", {}) or {}
    thresholds = ws.get("thresholds", {}) or {}
    decay      = cfg.get("warn_decay", {}) or {}

    # Thresholds sortiert
    sorted_th = sorted(
        [{"count": int(k), "action": v} for k, v in thresholds.items()],
        key=lambda x: x["count"]
    )

    # Echte Warn-Statistiken aus DB
    total_warns   = 0
    warns_7d      = 0
    top_warned    = []  # Top 5 User mit meisten Warns
    recent_warns  = []

    db = get_db()
    if db:
        gid_int  = int(guild_id)
        week_ago = _dt.datetime.utcnow() - _dt.timedelta(days=7)

        try:
            total_warns = safe_collection_count(
                db.data,
                {"type": "warning", "guild_id": gid_int}
            )
        except Exception:
            pass

        try:
            warns_7d = safe_collection_count(
                db.data,
                {"type": "warning", "guild_id": gid_int,
                 "timestamp": {"$gte": week_ago}}
            )
        except Exception:
            pass

        try:
            pipeline = [
                {"$match": {"type": "warning", "guild_id": gid_int}},
                {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 5},
            ]
            top_raw = safe_async(db.data.aggregate(pipeline).to_list(5), []) or []
            for item in top_raw:
                uid  = item.get("_id", 0)
                name = str(uid)
                if g and uid:
                    try:
                        m = g.get_member(int(uid))
                        if m:
                            name = m.display_name
                    except Exception:
                        pass
                top_warned.append({"id": uid, "name": name, "count": item["count"]})
        except Exception:
            pass

        try:
            raw_warns = safe_async(
                db.data.find({"type": "warning", "guild_id": gid_int})
                        .sort("timestamp", -1)
                        .to_list(10),
                []
            ) or []
            for w in raw_warns:
                w.pop("_id", None)
                ts = w.get("timestamp")
                w["ts_str"] = ts.strftime("%d.%m.%Y %H:%M") if isinstance(ts, _dt.datetime) else str(ts)[:19]
                uid = w.get("user_id", 0)
                w["user_name"] = ""
                if g and uid:
                    try:
                        m = g.get_member(int(uid))
                        if m:
                            w["user_name"] = m.display_name
                    except Exception:
                        pass
                recent_warns.append(w)
        except Exception:
            pass

    return render_template(
        "dashboard/warns.html",
        guild=g, cfg=cfg, user=us["user"],
        ws=ws,
        sorted_th=sorted_th,
        decay=decay,
        total_warns=total_warns,
        warns_7d=warns_7d,
        top_warned=top_warned,
        recent_warns=recent_warns,
        active="warns",
    )

@flask_app.route("/dashboard/<guild_id>/tickets")
@require_auth
def guild_tickets(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
    categories = [{"id":str(c.id),"name":c.name} for c in g.categories] if g else []
    return render_template("dashboard/tickets.html", guild=g, cfg=cfg, user=us["user"],
                           channels=channels, categories=categories, active="tickets")

@flask_app.route("/dashboard/<guild_id>/autoresponse")
@require_auth
def guild_autoresponse(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    return render_template("dashboard/autoresponse.html", guild=g, cfg=cfg, user=us["user"],
                           auto_responses=cfg.get("auto_responses",[]), active="autoresponse")

# ═══════════════════════════════════════════════════════════════════
# ROLES
# ═══════════════════════════════════════════════════════════════════
@flask_app.route("/dashboard/<guild_id>/roles")
@require_auth
def guild_roles(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    guild_roles = []
    if g and hasattr(g, 'roles') and g.roles:
        guild_roles = [
            {
                "id":    str(r.id),
                "name":  r.name,
                "color": str(r.color) if r.color and r.color.value else "",
                "pos":   r.position,
            }
            for r in sorted(g.roles, key=lambda r: r.position, reverse=True)
            if not r.is_default() and not r.managed
        ]

    role_map = {r["id"]: r["name"] for r in guild_roles}

    # Auto-Roles
    ar_ids    = cfg.get("auto_role", {}).get("roles", []) or []
    auto_roles = [
        {"id": str(rid), "name": role_map.get(str(rid), str(rid))}
        for rid in ar_ids
    ]

    # Sticky-Roles
    sr_ids       = cfg.get("sticky_roles", []) or []
    sticky_roles = [
        {"id": str(rid), "name": role_map.get(str(rid), str(rid))}
        for rid in sr_ids
    ]

    # Verify-Config
    vs = cfg.get("verify_system", {}) or {}

    # Text-Channels für Verify-Setup
    text_channels = []
    if g and hasattr(g, 'text_channels') and g.text_channels:
        text_channels = [
            {"id": str(c.id), "name": c.name}
            for c in sorted(g.text_channels, key=lambda c: c.position)
        ]

    return render_template(
        "dashboard/roles.html",
        guild=g, cfg=cfg, user=us["user"],
        guild_roles=guild_roles,
        auto_roles=auto_roles,
        sticky_roles=sticky_roles,
        vs=vs,
        text_channels=text_channels,
        active="roles",
    )

def _backups_col():
    """MongoDB-Collection für Server-Backups (Bot + Direct-DB-Fallback)."""
    db = get_db()
    if db is not None:
        try:
            return db.client["ModForge"]["backups"]
        except Exception:
            pass
    direct = _get_direct_db()
    if direct is not None:
        return direct["backups"]
    return None


def _public_backups_col():
    """MongoDB-Collection für öffentlich geteilte Backups."""
    db = get_db()
    if db is not None:
        try:
            return db.client["ModForge"]["public_backups"]
        except Exception:
            pass
    direct = _get_direct_db()
    if direct is not None:
        return direct["public_backups"]
    return None


def _ts(value):
    """datetime/str → Unix-Timestamp-String (oder '')."""
    if not value:
        return ""
    if hasattr(value, "timestamp"):
        try:
            return str(int(value.timestamp()))
        except Exception:
            return ""
    if isinstance(value, str):
        try:
            import datetime as _dt
            return str(int(_dt.datetime.fromisoformat(value.replace("Z", "")).timestamp()))
        except Exception:
            return ""
    return ""


def _enrich_backup_doc(doc):
    """Macht aus einem rohen Backup-DB-Dokument ein Template-fertiges Dict."""
    if not doc:
        return None
    payload = doc.get("data") or doc
    roles = payload.get("roles") or []
    channels = payload.get("channels") or []
    categories = payload.get("categories") or []
    emojis = payload.get("emojis") or []
    return {
        "id": doc.get("backup_id") or doc.get("id") or "?",
        "label": doc.get("label") or "Backup",
        "created_ts": _ts(doc.get("created_at") or doc.get("timestamp")),
        "created_by": str(doc.get("created_by") or "—"),
        "guild_name": doc.get("guild_name") or payload.get("guild_name") or "?",
        "guild_icon": doc.get("guild_icon_url") or payload.get("guild_icon_url") or "",
        "roles": len(roles) if isinstance(roles, list) else 0,
        "channels": len(channels) if isinstance(channels, list) else 0,
        "categories": len(categories) if isinstance(categories, list) else 0,
        "emojis": len(emojis) if isinstance(emojis, list) else 0,
        "has_password": bool(doc.get("password_hash") or doc.get("has_password")),
        "verification": payload.get("verification_level", 0),
    }


@flask_app.route("/dashboard/<guild_id>/backup")
@require_auth
def guild_backup(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    backups = []
    public_ids = set()
    col = _backups_col()
    if col is not None:
        try:
            # gilt für Motor (async) UND PyMongo (sync) — wir versuchen async zuerst
            try:
                raw = safe_async(
                    col.find({"guild_id": int(guild_id)}).sort("created_at", -1).to_list(50),
                    None,
                )
                if raw is None:
                    # PyMongo-Fallback
                    raw = list(col.find({"guild_id": int(guild_id)}).sort("created_at", -1).limit(50))
            except Exception:
                raw = list(col.find({"guild_id": int(guild_id)}).sort("created_at", -1).limit(50))

            for b in raw or []:
                enriched = _enrich_backup_doc(b)
                if enriched:
                    backups.append(enriched)
        except Exception as ex:
            log.debug(f"Backup load: {ex}")

    # Welche dieser Backups sind bereits public?
    pcol = _public_backups_col()
    if pcol is not None and backups:
        try:
            ids = [b["id"] for b in backups]
            try:
                pubs = safe_async(pcol.find({"backup_id": {"$in": ids}}).to_list(100), None)
                if pubs is None:
                    pubs = list(pcol.find({"backup_id": {"$in": ids}}))
            except Exception:
                pubs = list(pcol.find({"backup_id": {"$in": ids}}))
            public_ids = {p.get("backup_id") for p in (pubs or [])}
        except Exception:
            pass
    for b in backups:
        b["is_public"] = b["id"] in public_ids

    bs = cfg.get("backup_system", {}) or {}
    return render_template(
        "dashboard/backup.html", guild=g, cfg=cfg, user=us["user"],
        backups=backups, total_size=len(backups),
        auto_enabled=bs.get("auto_enabled", False),
        auto_interval=bs.get("auto_interval_hours", 24),
        auto_max=bs.get("auto_max_backups", 5),
        last_backup_ts=_ts(bs.get("auto_last_backup")),
        bot_ready=bot_ready(),
        active="backup",
    )


@flask_app.route("/dashboard/<guild_id>/templates")
@require_auth
def guild_templates(guild_id):
    """Community-Templates: eigene geteilte Backups + Importieren von anderen."""
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err

    my_shared = []
    all_public = []
    pcol = _public_backups_col()
    if pcol is not None:
        try:
            # Eigene geteilte
            try:
                mine_raw = safe_async(
                    pcol.find({"guild_id": str(guild_id)}).sort("shared_at", -1).to_list(50), None,
                )
                if mine_raw is None:
                    mine_raw = list(pcol.find({"guild_id": str(guild_id)}).sort("shared_at", -1).limit(50))
            except Exception:
                mine_raw = list(pcol.find({"guild_id": str(guild_id)}).sort("shared_at", -1).limit(50))
            # Alle öffentlichen (für Galerie)
            try:
                public_raw = safe_async(
                    pcol.find({}).sort([("downloads", -1), ("shared_at", -1)]).to_list(200), None,
                )
                if public_raw is None:
                    public_raw = list(pcol.find({}).sort([("downloads", -1), ("shared_at", -1)]).limit(200))
            except Exception:
                public_raw = list(pcol.find({}).sort([("downloads", -1), ("shared_at", -1)]).limit(200))
        except Exception as e:
            log.debug(f"templates load: {e}")
            mine_raw, public_raw = [], []
    else:
        mine_raw, public_raw = [], []

    def _shape(p):
        return {
            "id": p.get("backup_id", "?"),
            "name": p.get("name") or "Unbenannt",
            "description": p.get("description") or "",
            "category": (p.get("category") or "general").lower(),
            "guild_name": p.get("guild_name") or "?",
            "guild_icon": p.get("guild_icon") or "",
            "shared_by": str(p.get("shared_by") or "—"),
            "shared_ts": _ts(p.get("shared_at")),
            "roles": int(p.get("roles_count") or 0),
            "channels": int(p.get("channels_count") or 0),
            "categories": int(p.get("categories_count") or 0),
            "emojis": int(p.get("emojis_count") or 0),
            "downloads": int(p.get("downloads") or 0),
            "is_mine": str(p.get("guild_id")) == str(guild_id),
        }

    my_shared = [_shape(p) for p in (mine_raw or [])]
    all_public = [_shape(p) for p in (public_raw or [])]

    # Kategorie-Aufteilung für die Galerie
    categories = {}
    for tpl in all_public:
        categories.setdefault(tpl["category"], []).append(tpl)

    return render_template(
        "dashboard/templates.html",
        guild=g, cfg=cfg, user=us["user"], active="templates",
        my_shared=my_shared,
        all_public=all_public,
        categories=categories,
        bot_ready=bot_ready(),
    )

# ═══════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════
@flask_app.route("/dashboard/<guild_id>/settings")
@require_auth
def guild_settings(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    # Kanal-Listen
    text_channels = []
    categories    = []
    if g:
        if hasattr(g, 'text_channels') and g.text_channels:
            text_channels = [
                {"id": str(c.id), "name": c.name}
                for c in sorted(g.text_channels, key=lambda c: c.position)
            ]
        if hasattr(g, 'categories') and g.categories:
            categories = [
                {"id": str(c.id), "name": c.name}
                for c in g.categories
            ]

    # Config-Sektionen
    ws  = cfg.get("warn_system",      {}) or {}
    st  = cfg.get("server_tag",       {}) or {}
    ma  = cfg.get("message_archive",  {}) or {}
    wl  = cfg.get("webhook_logging",  {}) or {}
    ab  = cfg.get("auto_ban_appeal",  {}) or {}
    it  = cfg.get("invite_tracking",  {}) or {}
    bs  = cfg.get("backup_system",    {}) or {}
    vs  = cfg.get("verify_system",    {}) or {}

    return render_template(
        "dashboard/settings.html",
        guild=g, cfg=cfg, user=us["user"],
        channels=text_channels,
        categories=categories,
        ws=ws, st=st, ma=ma, wl=wl, ab=ab, it=it, bs=bs, vs=vs,
        active="settings",
    )


@flask_app.route("/dashboard/<guild_id>/design")
@require_auth
def guild_design(guild_id):
    """Dashboard-Design Tab – Theme / Akzentfarbe / Density / Animationen.

    Die Einstellungen leben rein im localStorage des Browsers (pro User/Gerät),
    es wird also nichts in der MongoDB persistiert. Das ist Absicht: Design ist
    eine Browser-Präferenz, kein Server-Setting.
    """
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    return render_template("dashboard/design.html", guild=g, cfg=cfg, user=us["user"], active="design")

# =========================================================

@flask_app.route("/dashboard/<guild_id>/embed")
@require_auth
def guild_embed(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
    return render_template("dashboard/embed.html", guild=g, cfg=cfg, user=us["user"], channels=channels, active="embed")

# PUBLIC PAGES (new)

@flask_app.route("/public-stats")
def public_stats():
    gc, mc, up, lat = _base_stats()
    uptime_pct = _uptime_pct()
    db = get_db()
    cases_count = 0
    if bot_ready() and db:
        cases_count = safe_collection_count(getattr(db, "cases", None))
    return render_template("public_stats.html", gc=gc, mc=mc, lat=round(lat or 0),
                           uptime_pct=f"{uptime_pct:.3f}", cases=cases_count,
                           shards=getattr(bot, "shard_count", 1))

# =========================================================
# ADMIN PAGES (new)
# =========================================================

@flask_app.route("/admin/logs")
@admin_required
def admin_logs():
    import logging
    entries = []
    # Gather recent log entries from the root logger handler buffers
    try:
        for handler in logging.getLogger().handlers:
            if hasattr(handler, 'buffer'):
                for record in handler.buffer[-200:]:
                    entries.append({
                        "timestamp": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                        "level": record.levelname,
                        "message": record.getMessage()[:500],
                    })
    except Exception:
        pass
    return render_template("admin/logs.html", log_entries=entries[-200:])

# =========================================================
# DASHBOARD API — Universal Config Endpoint
# =========================================================

@flask_app.route("/api/guild/<guild_id>/config", methods=["POST"])
@require_auth
def api_guild_config(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)

    # Handle special keys with _ prefix
    if "_reset" in data:
        from bot.config import DEFAULT_CONFIG
        import copy
        cfg = copy.deepcopy(DEFAULT_CONFIG)
    if "_security_level" in data:
        cfg["security_level"] = int(data["_security_level"])
    if "_log_channel" in data:
        cfg["log_channel"] = int(data["_log_channel"]) if data["_log_channel"] else None
    if "_log_channels" in data:
        cfg["log_channels"] = {k:int(v) for k,v in data["_log_channels"].items()}
    if "_prefix" in data:
        cfg["prefix"] = str(data["_prefix"])[:5] or "!"
    if "_no_prefix" in data:
        cfg["no_prefix"] = bool(data["_no_prefix"])
    if "_report_channel" in data:
        cfg["report_channel"] = int(data["_report_channel"]) if data["_report_channel"] else None
    if "_appeal_log_channel" in data:
        cfg["appeal_log_channel"] = int(data["_appeal_log_channel"]) if data["_appeal_log_channel"] else None
    if "_auto_ban_appeal" in data:
        cfg["auto_ban_appeal"] = data["_auto_ban_appeal"]
    if "_invite_tracking" in data:
        cfg["invite_tracking"] = data["_invite_tracking"]
    if "_message_archive" in data:
        ma = cfg.get("message_archive",{})
        ma["enabled"] = data["_message_archive"].get("enabled", False)
        cfg["message_archive"] = ma
    if "_temp_voice" in data:
        tv = cfg.get("temp_voice", {})
        for k, v in data["_temp_voice"].items():
            tv[k] = v
        cfg["temp_voice"] = tv
    if "_webhook_logging" in data:
        wl = cfg.get("webhook_logging", {"enabled": False, "webhooks": {}})
        wl["enabled"] = data["_webhook_logging"].get("enabled", False)
        cfg["webhook_logging"] = wl
    if "_server_tag" in data:
        st = cfg.get("server_tag", {})
        st["enabled"] = data["_server_tag"].get("enabled", False)
        if data["_server_tag"].get("tag"): st["tag"] = data["_server_tag"]["tag"]
        cfg["server_tag"] = st
    if "_warn_thresholds" in data:
        ws = cfg.get("warn_system",{})
        ws["thresholds"] = data["_warn_thresholds"]
        cfg["warn_system"] = ws
    if "_warn_thresholds_add" in data:
        ws = cfg.get("warn_system",{})
        th = ws.get("thresholds",{})
        th.update(data["_warn_thresholds_add"])
        ws["thresholds"] = th
        cfg["warn_system"] = ws
    if "_warn_thresholds_remove" in data:
        # Erwartet eine Liste von Threshold-Keys (z. B. ["3","5"])
        ws = cfg.get("warn_system", {})
        th = ws.get("thresholds", {}) or {}
        for key in (data["_warn_thresholds_remove"] or []):
            th.pop(str(key), None)
        ws["thresholds"] = th
        cfg["warn_system"] = ws
    if "_warn_decay" in data:
        cfg["warn_decay"] = data["_warn_decay"]
    if "_welcome" in data and isinstance(data["_welcome"], dict):
        wc = cfg.get("welcome", {}) or {}
        wc.update(data["_welcome"])
        cfg["welcome"] = wc
    if "_leave" in data and isinstance(data["_leave"], dict):
        lv = cfg.get("leave", {}) or {}
        lv.update(data["_leave"])
        cfg["leave"] = lv
    if "_verify_system" in data and isinstance(data["_verify_system"], dict):
        vs = cfg.get("verify_system", {}) or {}
        vs.update(data["_verify_system"])
        cfg["verify_system"] = vs
    if "_ticket_system" in data:
        ts = cfg.get("ticket_system",{})
        ts.update(data["_ticket_system"])
        cfg["ticket_system"] = ts

    # Raw config override (admin only)
    if "_raw" in data and isinstance(data["_raw"], dict):
        cfg = data["_raw"]

    # Handle module configs (anti_spam, anti_nuke, etc.)
    for key in ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"]:
        if key in data:
            mod = cfg.get(key, {})
            mod.update(data[key])
            cfg[key] = mod

    try:
        _direct_save_config(guild_id, cfg)
    except Exception as e:
        log.error(f"[CONFIG API ERROR] {e}")
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})

@flask_app.route("/api/guild/<guild_id>/automod", methods=["POST"])
@require_auth
def api_guild_automod(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    am = cfg.get("automod", {})
    action = data.get("action")
    if action == "add_word":
        words = am.get("bad_words", [])
        if data["value"] not in words: words.append(data["value"])
        am["bad_words"] = words
    elif action == "del_word":
        am["bad_words"] = [w for w in am.get("bad_words",[]) if w != data["value"]]
    elif action == "add_regex":
        rules = am.get("regex_rules", [])
        rules.append(data["value"])
        am["regex_rules"] = rules
    elif action == "del_regex":
        rules = am.get("regex_rules", [])
        idx = int(data.get("index", -1))
        if 0 <= idx < len(rules): rules.pop(idx)
        am["regex_rules"] = rules
    elif action == "add_domain":
        domains = am.get("allowed_domains", [])
        if data["value"] not in domains: domains.append(data["value"])
        am["allowed_domains"] = domains
    elif action == "del_domain":
        am["allowed_domains"] = [d for d in am.get("allowed_domains",[]) if d != data["value"]]
    cfg["automod"] = am
    try:
        _direct_save_config(guild_id, cfg)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})

@flask_app.route("/api/guild/<guild_id>/autoresponse", methods=["POST"])
@require_auth
def api_guild_autoresponse(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    ars = cfg.get("auto_responses", [])
    action = data.get("action")
    if action == "add":
        ars.append({"trigger": data["trigger"], "response": data["response"], "enabled": True})
    elif action == "del":
        idx = int(data.get("index", -1))
        if 0 <= idx < len(ars): ars.pop(idx)
    elif action == "toggle":
        idx = int(data.get("index", -1))
        if 0 <= idx < len(ars): ars[idx]["enabled"] = data.get("enabled", True)
    cfg["auto_responses"] = ars
    try:
        _direct_save_config(guild_id, cfg)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})

@flask_app.route("/api/guild/<guild_id>/roles", methods=["POST"])
@require_auth
def api_guild_roles(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    action = data.get("action")
    rid = int(data.get("role_id", 0))
    if action == "add_auto":
        ar = cfg.get("auto_role", {"enabled": True, "roles": []})
        if rid not in ar.get("roles",[]): ar.setdefault("roles",[]).append(rid)
        ar["enabled"] = True
        cfg["auto_role"] = ar
    elif action == "del_auto":
        ar = cfg.get("auto_role", {"roles":[]})
        ar["roles"] = [r for r in ar.get("roles",[]) if r != rid]
        cfg["auto_role"] = ar
    elif action == "add_sticky":
        sr = cfg.get("sticky_roles", [])
        if rid not in sr: sr.append(rid)
        cfg["sticky_roles"] = sr
    elif action == "del_sticky":
        cfg["sticky_roles"] = [r for r in cfg.get("sticky_roles",[]) if r != rid]
    try:
        _direct_save_config(guild_id, cfg)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@flask_app.route("/api/guild/<guild_id>/embed", methods=["POST"])
@require_auth
def api_guild_embed(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    channel_id = data.get("channel_id")
    embed_data = data.get("embed", {})
    if not channel_id or not embed_data:
        return jsonify({"error": "missing channel_id or embed"}), 400
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "guild not found"}), 404
    ch = g.get_channel(int(channel_id))
    if not ch:
        return jsonify({"error": "channel not found"}), 404
    import discord
    from bot.utils import _run_async
    try:
        color = embed_data.pop("color", 0x7c3aed)
        emb = discord.Embed(
            title=embed_data.get("title"),
            description=embed_data.get("description"),
            url=embed_data.get("url"),
            color=color,
        )
        if embed_data.get("author"):
            emb.set_author(name=embed_data["author"].get("name",""), icon_url=embed_data["author"].get("icon_url"))
        if embed_data.get("thumbnail"):
            emb.set_thumbnail(url=embed_data["thumbnail"]["url"])
        if embed_data.get("image"):
            emb.set_image(url=embed_data["image"]["url"])
        if embed_data.get("footer"):
            emb.set_footer(text=embed_data["footer"].get("text",""), icon_url=embed_data["footer"].get("icon_url"))
        if embed_data.get("timestamp"):
            emb.timestamp = datetime.datetime.utcnow()
        for field in embed_data.get("fields", []):
            emb.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
        _run_async(ch.send(embed=emb))
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"[EMBED API ERROR] {e}")
        return jsonify({"error": str(e)}), 500



# =========================================================
# DASHBOARD: MEMBERS PAGE
# =========================================================

@flask_app.route("/dashboard/<guild_id>/members")
@require_auth
def guild_members(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    members = []
    guild_owner_id = str(g.owner_id) if hasattr(g, 'owner_id') and g.owner_id else "0"
    if g and bot_ready():
        import datetime as _dt
        now = _dt.datetime.utcnow()
        bot_id = str(bot.user.id) if bot.user else "1491447622442160248"
        for m in g.members[:500]:
            try:
                age_days = (now - m.created_at.replace(tzinfo=None)).days if m.created_at else 999
                rc = len([r for r in m.roles if r != g.default_role])
                risk = 0
                if age_days < 7: risk += 30
                elif age_days < 30: risk += 10
                if not m.avatar: risk += 10
                if rc == 0 and not m.bot: risk += 15
                risk = min(risk, 100)

                # Tags + Sort Priority
                tag = ""; tag_color = ""; sp = 10
                if str(m.id) == "1303627964734246944":
                    tag = "Owner"; tag_color = "#f59e0b"; risk = 0; sp = 0
                elif str(m.id) == bot_id:
                    tag = "ModForge"; tag_color = "#7c3aed"; risk = 0; sp = 1
                elif str(m.id) == guild_owner_id:
                    tag = "Server Owner"; tag_color = "#22d3ee"; risk = 0; sp = 2
                elif m.bot:
                    tag = "Bot"; tag_color = "#3b82f6"; sp = 5

                # Timeout
                timeout_str = ""
                try:
                    if m.timed_out_until and m.timed_out_until.timestamp() > now.timestamp():
                        timeout_str = str(int(m.timed_out_until.timestamp()))
                except Exception:
                    pass

                # Voice
                voice_ch = ""
                voice_mute = False
                voice_deaf = False
                voice_stream = False
                if m.voice and m.voice.channel:
                    voice_ch = m.voice.channel.name
                    voice_mute = m.voice.mute or m.voice.self_mute
                    voice_deaf = m.voice.deaf or m.voice.self_deaf
                    voice_stream = getattr(m.voice, 'self_stream', False)

                # Top role
                top_role_name = ""
                top_role_color = ""
                if m.top_role and m.top_role != g.default_role:
                    top_role_name = m.top_role.name
                    top_role_color = str(m.top_role.color) if m.top_role.color.value else ""

                # Boost
                boost_since = ""
                if m.premium_since:
                    boost_since = str(int(m.premium_since.timestamp()))

                # Status
                status = str(m.status) if hasattr(m, 'status') else "offline"

                # Permissions summary
                is_admin = m.guild_permissions.administrator
                can_ban = m.guild_permissions.ban_members
                can_kick = m.guild_permissions.kick_members
                can_manage = m.guild_permissions.manage_guild

                # Cases/Warns count
                user_cases = 0
                user_warns = 0
                try:
                    db = get_db()
                    if db:
                        user_cases = safe_collection_count(db.cases, {"guild_id": str(g.id), "user_id": str(m.id)})
                        user_warns = safe_collection_count(getattr(db, "warnings", None), {"guild_id": str(g.id), "user_id": str(m.id)})
                        if user_cases: risk = min(risk + user_cases * 5, 100)
                        if user_warns: risk = min(risk + user_warns * 8, 100)
                except Exception:
                    pass

                members.append({
                    "id": str(m.id),
                    "cases": user_cases,
                    "warns": user_warns,
                    "name": str(m),
                    "display_name": m.display_name,
                    "nick": m.nick or "",
                    "bot": m.bot,
                    "avatar": m.display_avatar.url,
                    "risk": risk,
                    "new_account": age_days < 7,
                    "role_count": rc,
                    "roles": [{"name": r.name, "color": str(r.color) if r.color.value else ""} for r in m.roles if r != g.default_role][:20],
                    "roles_str": ", ".join([r.name for r in m.roles if r != g.default_role][:5]) or "Keine",
                    "tag": tag, "tag_color": tag_color,
                    "sort_priority": sp,
                    "age_days": age_days,
                    "timeout": timeout_str,
                    "voice_ch": voice_ch,
                    "voice_mute": voice_mute,
                    "voice_deaf": voice_deaf,
                    "voice_stream": voice_stream,
                    "joined": str(int(m.joined_at.timestamp())) if m.joined_at else "",
                    "created": str(int(m.created_at.timestamp())) if m.created_at else "",
                    "status": status,
                    "top_role": top_role_name,
                    "top_role_color": top_role_color,
                    "boost_since": boost_since,
                    "is_admin": is_admin,
                    "can_ban": can_ban,
                    "can_kick": can_kick,
                    "can_manage": can_manage,
                    "pending": getattr(m, 'pending', False),
                    "is_on_mobile": m.is_on_mobile() if hasattr(m, 'is_on_mobile') else False,
                    "desktop_status": str(getattr(m, 'desktop_status', 'offline')),
                    "web_status": str(getattr(m, 'web_status', 'offline')),
                    "mobile_status": str(getattr(m, 'mobile_status', 'offline')),
                    "activity": str(m.activity.name) if m.activity and hasattr(m.activity, 'name') else "",
                    "activity_type": str(m.activity.type.name) if m.activity and hasattr(m.activity, 'type') else "",
                    "banner_url": m.banner.url if hasattr(m, 'banner') and m.banner else "",
                    "guild_avatar_url": m.guild_avatar.url if hasattr(m, 'guild_avatar') and m.guild_avatar else "",
                    "accent_color": str(m.accent_color) if hasattr(m, 'accent_color') and m.accent_color else "",
                    "all_perms": {
                        "administrator": m.guild_permissions.administrator,
                        "manage_guild": m.guild_permissions.manage_guild,
                        "manage_roles": m.guild_permissions.manage_roles,
                        "manage_channels": m.guild_permissions.manage_channels,
                        "manage_messages": m.guild_permissions.manage_messages,
                        "ban_members": m.guild_permissions.ban_members,
                        "kick_members": m.guild_permissions.kick_members,
                        "moderate_members": m.guild_permissions.moderate_members,
                        "mention_everyone": m.guild_permissions.mention_everyone,
                        "manage_webhooks": m.guild_permissions.manage_webhooks,
                        "manage_nicknames": m.guild_permissions.manage_nicknames,
                        "manage_emojis": m.guild_permissions.manage_emojis_and_stickers if hasattr(m.guild_permissions, 'manage_emojis_and_stickers') else False,
                        "view_audit_log": m.guild_permissions.view_audit_log,
                        "send_messages": m.guild_permissions.send_messages,
                        "connect": m.guild_permissions.connect,
                        "speak": m.guild_permissions.speak,
                        "mute_members": m.guild_permissions.mute_members,
                        "deafen_members": m.guild_permissions.deafen_members,
                        "move_members": m.guild_permissions.move_members,
                    },
                    "role_ids": [str(r.id) for r in m.roles if r != g.default_role],
                })
            except Exception as ex:
                log.debug(f"Member parse error: {ex}")

        members.sort(key=lambda x: (x["sort_priority"], -x["risk"], x["name"].lower()))
    return render_template("dashboard/members.html", guild=g, cfg=cfg, user=us["user"], members=members, guild_owner_id=guild_owner_id, active="members")

# =========================================================
# PUBLIC SERVER PAGE
# =========================================================

@flask_app.route("/server/<guild_id>")
def public_server_page(guild_id):
    g = get_guild(guild_id)
    if not g:
        abort(404)
    cfg = _direct_load_config(guild_id)
    pp = cfg.get("public_page", {})
    # Build server info
    mods = ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"]
    active_modules = [m.replace("_"," ").title() for m in mods if cfg.get(m,{}).get("enabled")]
    sec = min(85 + len(active_modules) * 2, 100)
    server = {
        "name": g.name,
        "icon": g.icon.url if g.icon else None,
        "members": g.member_count or 0,
        "security": sec,
        "active_modules": len(active_modules),
        "modules": active_modules,
        "invite": pp.get("invite_url"),
    }
    return render_template("server_public.html", server=server)




# =========================================================
# DASHBOARD: STATS / WHITELIST / LIVEFEED
# =========================================================

@flask_app.route("/dashboard/<guild_id>/stats")
@require_auth
def guild_stats_page(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    import datetime as _dt
    cases_count = 0
    case_types = {}
    top_mods = []
    days_labels = []
    days_data = []
    db = get_db()
    if db:
        try:
            all_cases = safe_async(db.cases.find({"guild_id": str(guild_id)}).sort("case_id", -1).to_list(500), []) or []
            cases_count = len(all_cases)
            # Case types
            for cs in all_cases:
                a = cs.get("action", "other")
                case_types[a] = case_types.get(a, 0) + 1
            # Top mods
            from collections import Counter
            mod_counter = Counter(cs.get("moderator_id") for cs in all_cases if cs.get("moderator_id"))
            top_mods = [{"id": mid, "count": cnt} for mid, cnt in mod_counter.most_common(10)]
            # Cases per day (last 7 days)
            now = _dt.datetime.utcnow()
            for i in range(6, -1, -1):
                day = now - _dt.timedelta(days=i)
                label = day.strftime("%a")
                count = sum(1 for cs in all_cases if cs.get("timestamp") and
                    cs["timestamp"].date() == day.date())
                days_labels.append(label)
                days_data.append(count)
        except Exception as e:
            log.debug(f"Stats page error: {e}")

    # ── Member-Wachstum: kumulativer Verlauf seit Server-Erstellung ──
    # Wir nutzen die ``joined_at``-Daten aller momentan auf dem Server befindlichen
    # Mitglieder (das ist die einzige Information, die Discord uns ohne extra Logging
    # liefert). Das ergibt eine ehrliche Kurve "wie viele heutige Member waren wann
    # bereits drin?". Verlassene Member sind nicht enthalten – das ist eine bekannte
    # Discord-API-Limitation.
    growth_labels: list = []
    growth_data: list = []
    growth_total = 0
    growth_buckets = 0
    if g and hasattr(g, "members") and g.members and hasattr(g, "created_at") and g.created_at:
        try:
            created_at = g.created_at
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
            now_utc = _dt.datetime.utcnow()

            # Joins sammeln (datetime.date pro Member)
            join_dates = []
            for m in g.members:
                ja = getattr(m, "joined_at", None)
                if not ja:
                    continue
                if ja.tzinfo is not None:
                    ja = ja.replace(tzinfo=None)
                # Bot-Owner / very old accounts trotzdem reinrechnen, aber nicht vor created_at
                if ja < created_at:
                    ja = created_at
                join_dates.append(ja)

            join_dates.sort()
            total_members = len(join_dates)

            # Bucket-Auflösung wählen: max ~60 Datenpunkte
            span = now_utc - created_at
            span_days = max(1, span.days or 1)
            if span_days <= 60:
                bucket_seconds = 24 * 3600           # täglich
                fmt = "%d.%m."
            elif span_days <= 365 * 2:
                bucket_seconds = 7 * 24 * 3600        # wöchentlich
                fmt = "%d.%m.%y"
            elif span_days <= 365 * 6:
                bucket_seconds = 30 * 24 * 3600       # monatlich
                fmt = "%b %y"
            else:
                bucket_seconds = 90 * 24 * 3600       # quartalsweise
                fmt = "Q%m/%y"

            cursor = created_at
            idx = 0  # Position im sortierten join_dates-Array
            running = 0
            # Sicherheitsbremse, damit wir bei kaputten Zeitstempeln nicht endlos laufen
            max_buckets = 400
            while cursor <= now_utc and growth_buckets < max_buckets:
                bucket_end = cursor + _dt.timedelta(seconds=bucket_seconds)
                while idx < total_members and join_dates[idx] < bucket_end:
                    running += 1
                    idx += 1
                growth_labels.append(cursor.strftime(fmt))
                growth_data.append(running)
                growth_buckets += 1
                cursor = bucket_end

            # Endpunkt = aktueller Member-Count (für den Fall, dass Joins fehlen)
            if growth_data:
                growth_data[-1] = max(growth_data[-1], total_members)
            growth_total = total_members
        except Exception as ex:
            log.debug(f"member-growth error: {ex}")
            growth_labels, growth_data = [], []
    active_mods = sum(1 for k in ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"]
                      if cfg.get(k, {}).get("enabled"))
    channels_count = len(g.channels) if g and hasattr(g,'channels') else 0
    roles_count = len(g.roles)-1 if g and hasattr(g,'roles') and g.roles else 0
    text_ch = len([ch for ch in g.channels if hasattr(ch,'type') and str(ch.type)=='text']) if g and hasattr(g,'channels') else 0
    voice_ch = len([ch for ch in g.channels if hasattr(ch,'type') and str(ch.type)=='voice']) if g and hasattr(g,'channels') else 0
    bots = sum(1 for m in g.members if m.bot) if g and hasattr(g,'members') and g.members else 0
    humans = (g.member_count or 0) - bots if g else 0
    online = sum(1 for m in g.members if hasattr(m,'status') and str(m.status)!='offline') if g and hasattr(g,'members') and g.members else 0
    boosts = g.premium_subscription_count or 0 if g and hasattr(g,'premium_subscription_count') else 0
    warns_count = 0
    try:
        wc = getattr(db,'warnings',None) if db else None
        if wc: warns_count = safe_collection_count(wc, {"guild_id":str(guild_id)})
    except Exception:
        pass
    log_channels_count = len(cfg.get("log_channels",{}) or {})
    sec_level = cfg.get("security_level",0)

    server_created_ts = ""
    try:
        if g and hasattr(g, "created_at") and g.created_at:
            server_created_ts = str(int(g.created_at.timestamp()))
    except Exception:
        pass

    return render_template("dashboard/stats.html", guild=g, cfg=cfg, user=us["user"],
        cases_count=cases_count, case_types=case_types, top_mods=top_mods,
        active_mods=active_mods, channels_count=channels_count,
        days_labels=days_labels, days_data=days_data,
        roles_count=roles_count, text_ch=text_ch, voice_ch=voice_ch,
        bots=bots, humans=humans, online=online, boosts=boosts,
        warns_count=warns_count, log_channels_count=log_channels_count,
        sec_level=sec_level,
        growth_labels=growth_labels, growth_data=growth_data,
        growth_total=growth_total, server_created_ts=server_created_ts,
        active="stats")

# ═══════════════════════════════════════════════════════════════════
# WHITELIST
# ═══════════════════════════════════════════════════════════════════
@flask_app.route("/dashboard/<guild_id>/whitelist")
@require_auth
def guild_whitelist(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    wl = {}
    if bot_ready():
        try:
            wl = bot.db.get_whitelist(int(guild_id))
        except Exception:
            pass

    # Rollen + User-Namen aus Guild auflösen
    role_map   = {}
    member_map = {}
    if g:
        if hasattr(g, 'roles') and g.roles:
            role_map = {str(r.id): r.name for r in g.roles}
        if hasattr(g, 'members') and g.members:
            member_map = {str(m.id): m.display_name for m in g.members}

    # Kategorien anreichern
    cats = [
        {
            "key":         "users",
            "label":       "User",
            "icon":        "👤",
            "desc":        "Alle Security-Module werden für diese User deaktiviert",
            "placeholder": "User-ID eingeben…",
            "color":       "124,58,237",
            "entries": [
                {"id": str(uid), "name": member_map.get(str(uid), "")}
                for uid in wl.get("users", [])
            ],
        },
        {
            "key":         "roles",
            "label":       "Rollen",
            "icon":        "🏷️",
            "desc":        "Mitglieder mit diesen Rollen werden von allen Modulen ignoriert",
            "placeholder": "Rollen-ID eingeben…",
            "color":       "34,211,238",
            "entries": [
                {"id": str(rid), "name": role_map.get(str(rid), "")}
                for rid in wl.get("roles", [])
            ],
        },
        {
            "key":         "channels",
            "label":       "Kanäle",
            "icon":        "📁",
            "desc":        "In diesen Kanälen sind alle Security-Module inaktiv",
            "placeholder": "Kanal-ID eingeben…",
            "color":       "74,222,128",
            "entries": [
                {"id": str(cid), "name": ""}
                for cid in wl.get("channels", [])
            ],
        },
        {
            "key":         "bypass_antinuke",
            "label":       "Bypass Anti-Nuke",
            "icon":        "💣",
            "desc":        "Dürfen Massenaktionen durchführen ohne gesperrt zu werden",
            "placeholder": "User-ID eingeben…",
            "color":       "239,68,68",
            "entries": [
                {"id": str(uid), "name": member_map.get(str(uid), "")}
                for uid in wl.get("bypass_antinuke", [])
            ],
        },
        {
            "key":         "bypass_antispam",
            "label":       "Bypass Anti-Spam",
            "icon":        "⚡",
            "desc":        "Anti-Spam-Filter wird für diese User komplett ignoriert",
            "placeholder": "User-ID eingeben…",
            "color":       "245,158,11",
            "entries": [
                {"id": str(uid), "name": member_map.get(str(uid), "")}
                for uid in wl.get("bypass_antispam", [])
            ],
        },
    ]

    total_entries = sum(len(c["entries"]) for c in cats)

    # Rollen-Liste für Dropdown
    guild_roles = []
    if g and hasattr(g, 'roles') and g.roles:
        guild_roles = [
            {"id": str(r.id), "name": r.name}
            for r in sorted(g.roles, key=lambda r: r.position, reverse=True)
            if not r.is_default() and not r.managed
        ]

    # Kanal-Liste für Dropdown
    guild_channels = []
    if g and hasattr(g, 'text_channels') and g.text_channels:
        guild_channels = [
            {"id": str(c.id), "name": c.name}
            for c in sorted(g.text_channels, key=lambda c: c.position)
        ]

    return render_template(
        "dashboard/whitelist.html",
        guild=g, cfg=cfg, user=us["user"],
        whitelist=wl,
        cats=cats,
        total_entries=total_entries,
        guild_roles=guild_roles,
        guild_channels=guild_channels,
        active="whitelist",
    )

@flask_app.route("/dashboard/<guild_id>/livefeed")
@require_auth
def guild_livefeed(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    activities = []
    try:
        from bot.config import ACTIVITY
        raw = ACTIVITY.snapshot(30)
        if isinstance(raw, list):
            activities = [a for a in raw if str(a.get("guild_id","")) == str(guild_id)][:20]
    except Exception:
        pass
    return render_template("dashboard/livefeed.html", guild=g, cfg=cfg, user=us["user"],
        activities=activities, active="livefeed")

# =========================================================
# WHITELIST API
# =========================================================

@flask_app.route("/api/guild/<guild_id>/whitelist", methods=["POST"])
@require_auth
def api_guild_whitelist(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    action = data.get("action")
    cat = data.get("category", "users")
    item_id = data.get("id")
    if not action or not item_id:
        return jsonify({"error": "missing params"}), 400
    from bot.utils import _run_async
    try:
        wl = bot.db.get_whitelist(int(guild_id))
        if action == "add":
            items = wl.get(cat, [])
            try: item_id = int(item_id)
            except Exception:
                pass
            if item_id not in items:
                items.append(item_id)
            wl[cat] = items
        elif action == "del":
            try: item_id = int(item_id)
            except Exception:
                pass
            wl[cat] = [x for x in wl.get(cat, []) if str(x) != str(item_id)]
        try:
            _run_async(bot.db.whitelist_col.replace_one({"guild_id": int(guild_id)}, {"guild_id": int(guild_id), **wl}, upsert=True))
        except:
            bot.db._whitelist_cache[int(guild_id)] = wl
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500




# =========================================================
# ADMIN: Full Server Dashboard (same as user, no perm check)
# =========================================================

@flask_app.route("/admin/server/<guild_id>")
@flask_app.route("/admin/server/<guild_id>/<path:subpage>")
@admin_required
def admin_server_dashboard(guild_id, subpage=""):
    """Admin kann JEDEN Server im vollen Dashboard öffnen — ohne OAuth."""
    g = get_guild(guild_id)
    if not g:
        abort(404)
    cfg = _direct_load_config(guild_id)
    admin_user = {"id":"0","username":"Admin","avatar_url":"https://cdn.discordapp.com/embed/avatars/0.png"}

    # Route to the correct sub-page
    if not subpage or subpage == "overview":
        overview = _build_overview(cfg, guild_id)
        return render_template("dashboard/overview.html", guild=g, cfg=cfg, user=admin_user, overview=overview, active="overview")

    elif subpage == "security":
        # Security page needs full module list — reuse guild_security logic
        modules = []
        mod_defs = [
            ("anti_spam","⚡","Anti-Spam","Spam erkennen",[{"key":"msg_limit","label":"Limit","type":"number","min":2,"max":30},{"key":"punishment","label":"Strafe","type":"select","options":["warn","timeout","kick","ban"]}]),
            ("anti_nuke","💥","Anti-Nuke","Massenaktionen",[{"key":"threshold","label":"Schwelle","type":"number","min":2,"max":20},{"key":"punishment","label":"Strafe","type":"select","options":["warn","timeout","kick","ban"]}]),
            ("anti_raid","🚨","Anti-Raid","Massenjoins",[{"key":"join_threshold","label":"Join-Limit","type":"number","min":3,"max":50}]),
            ("anti_mention","🔔","Anti-Mention","Mass-Mentions",[{"key":"mention_limit","label":"Max","type":"number","min":2,"max":30}]),
            ("anti_scam","🎣","Anti-Scam","Phishing",[{"key":"punishment","label":"Strafe","type":"select","options":["warn","timeout","kick","ban"]}]),
            ("anti_webhook","🔌","Anti-Webhook","Webhooks",[]),
            ("anti_ghost_ping","👻","Ghost-Ping","Ghost-Pings",[]),
            ("anti_vpn","🌐","Anti-VPN","VPN-Erkennung",[]),
            ("automod","🤖","AutoMod","Filter",[{"key":"punishment","label":"Strafe","type":"select","options":["warn","timeout","kick","ban"]}]),
        ]
        for key,icon,label,desc,params in mod_defs:
            mcfg = cfg.get(key,{})
            for p in params: p["value"] = mcfg.get(p["key"],"")
            modules.append({"key":key,"icon":icon,"label":label,"desc":desc,"enabled":mcfg.get("enabled",False),"params":params})
        wl_count = 0
        try:
            wl = bot.db.get_whitelist(int(guild_id)) if bot_ready() else {}
            wl_count = sum(len(v) for v in wl.values() if isinstance(v,list))
        except Exception:
            pass
        return render_template("dashboard/security.html", guild=g, cfg=cfg, user=admin_user,
            modules=modules, active_count=sum(1 for m in modules if m["enabled"]), wl_count=wl_count, active="security")

    elif subpage == "automod":
        return render_template("dashboard/automod.html", guild=g, cfg=cfg, user=admin_user, active="automod")

    elif subpage == "logs":
        channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
        log_channels = cfg.get("log_channels",{})
        from bot.config import LOG_MODULES, LOG_MODULES_EXTRA
        icons = {"default":"📌","moderation":"🛡️","antispam":"⚡","antinuke":"💥","antiraid":"🚨","voice":"🎤","members":"👥","channels":"📁","roles":"🏷️","tickets":"🎫","cases":"📋","warns":"⚠️","welcome":"👋","errors":"❌","backup":"💾"}
        all_mods = list(LOG_MODULES) + list(LOG_MODULES_EXTRA)
        log_module_defs = [{"key":m,"icon":icons.get(m,"⚙️"),"label":m.replace("_"," ").title()} for m in all_mods]
        return render_template("dashboard/logs.html", guild=g, cfg=cfg, user=admin_user,
            channels=channels, log_channels=log_channels, log_modules=log_module_defs, active="logs")

    elif subpage == "cases":
        cases = []
        db = get_db()
        if db:
            try:
                raw = safe_async(db.cases.find({"guild_id":str(guild_id)}).sort("case_id",-1).to_list(200),[]) or []
                for cc in raw: cc["timestamp"] = str(cc.get("timestamp",""))[:19]
                cases = raw
            except Exception:
                pass
        return render_template("dashboard/cases.html", guild=g, cfg=cfg, user=admin_user, cases=cases, active="cases")

    elif subpage == "warns":
        return render_template("dashboard/warns.html", guild=g, cfg=cfg, user=admin_user, active="warns")

    elif subpage == "settings":
        channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
        return render_template("dashboard/settings.html", guild=g, cfg=cfg, user=admin_user, channels=channels, active="settings")

    elif subpage == "roles":
        guild_roles = [{"id":str(r.id),"name":r.name} for r in g.roles if not r.is_default() and not r.managed] if g else []
        return render_template("dashboard/roles.html", guild=g, cfg=cfg, user=admin_user,
            guild_roles=guild_roles, auto_roles=cfg.get("auto_role",{}).get("roles",[]), sticky_roles=cfg.get("sticky_roles",[]), active="roles")

    elif subpage == "welcome":
        content = _build_welcome_content(cfg, guild_id)
        return render_template("dashboard/welcome.html", guild=g, cfg=cfg, user=admin_user, content=content, active="welcome")

    elif subpage == "modules":
        section = request.args.get("section","antispam")
        form = _build_module_form(section, cfg, guild_id)
        return render_template("dashboard/modules.html", guild=g, cfg=cfg, user=admin_user, form=form, active="modules")

    elif subpage == "tickets":
        channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
        categories = [{"id":str(ct.id),"name":ct.name} for ct in g.categories] if g else []
        return render_template("dashboard/tickets.html", guild=g, cfg=cfg, user=admin_user, channels=channels, categories=categories, active="tickets")

    elif subpage == "backup":
        backups = []
        col = _backups_col()
        if col is not None:
            try:
                try:
                    raw = safe_async(col.find({"guild_id": int(guild_id)}).sort("created_at", -1).to_list(50), None)
                    if raw is None:
                        raw = list(col.find({"guild_id": int(guild_id)}).sort("created_at", -1).limit(50))
                except Exception:
                    raw = list(col.find({"guild_id": int(guild_id)}).sort("created_at", -1).limit(50))
                for b in raw or []:
                    enriched = _enrich_backup_doc(b)
                    if enriched:
                        backups.append(enriched)
            except Exception:
                pass
        bs = cfg.get("backup_system", {}) or {}
        return render_template(
            "dashboard/backup.html", guild=g, cfg=cfg, user=admin_user,
            backups=backups, total_size=len(backups),
            auto_enabled=bs.get("auto_enabled", False),
            auto_interval=bs.get("auto_interval_hours", 24),
            auto_max=bs.get("auto_max_backups", 5),
            last_backup_ts=_ts(bs.get("auto_last_backup")),
            bot_ready=bot_ready(),
            active="backup",
        )

    elif subpage == "templates":
        my_shared, all_public = [], []
        pcol = _public_backups_col()
        if pcol is not None:
            try:
                try:
                    mine_raw = safe_async(pcol.find({"guild_id": str(guild_id)}).sort("shared_at", -1).to_list(50), None)
                    if mine_raw is None:
                        mine_raw = list(pcol.find({"guild_id": str(guild_id)}).sort("shared_at", -1).limit(50))
                except Exception:
                    mine_raw = list(pcol.find({"guild_id": str(guild_id)}).sort("shared_at", -1).limit(50))
                try:
                    pub_raw = safe_async(pcol.find({}).sort([("downloads", -1), ("shared_at", -1)]).to_list(200), None)
                    if pub_raw is None:
                        pub_raw = list(pcol.find({}).sort([("downloads", -1), ("shared_at", -1)]).limit(200))
                except Exception:
                    pub_raw = list(pcol.find({}).sort([("downloads", -1), ("shared_at", -1)]).limit(200))
            except Exception:
                mine_raw, pub_raw = [], []
            def _shape(p):
                return {
                    "id": p.get("backup_id", "?"),
                    "name": p.get("name") or "Unbenannt",
                    "description": p.get("description") or "",
                    "category": (p.get("category") or "general").lower(),
                    "guild_name": p.get("guild_name") or "?",
                    "guild_icon": p.get("guild_icon") or "",
                    "shared_by": str(p.get("shared_by") or "—"),
                    "shared_ts": _ts(p.get("shared_at")),
                    "roles": int(p.get("roles_count") or 0),
                    "channels": int(p.get("channels_count") or 0),
                    "categories": int(p.get("categories_count") or 0),
                    "emojis": int(p.get("emojis_count") or 0),
                    "downloads": int(p.get("downloads") or 0),
                    "is_mine": str(p.get("guild_id")) == str(guild_id),
                }
            my_shared = [_shape(p) for p in (mine_raw or [])]
            all_public = [_shape(p) for p in (pub_raw or [])]
        categories = {}
        for tpl in all_public:
            categories.setdefault(tpl["category"], []).append(tpl)
        return render_template("dashboard/templates.html", guild=g, cfg=cfg, user=admin_user,
            my_shared=my_shared, all_public=all_public, categories=categories,
            bot_ready=bot_ready(), active="templates")

    elif subpage == "autoresponse":
        return render_template("dashboard/autoresponse.html", guild=g, cfg=cfg, user=admin_user, auto_responses=cfg.get("auto_responses",[]), active="autoresponse")

    elif subpage == "embed":
        channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
        return render_template("dashboard/embed.html", guild=g, cfg=cfg, user=admin_user, channels=channels, active="embed")

    elif subpage == "whitelist":
        wl = {}
        if bot_ready():
            try: wl = bot.db.get_whitelist(int(guild_id))
            except Exception:
                pass
        return render_template("dashboard/whitelist.html", guild=g, cfg=cfg, user=admin_user, whitelist=wl, active="whitelist")

    elif subpage == "stats":
        import datetime as _dt
        cases_count = 0; case_types = {}; top_mods = []; days_labels = []; days_data = []
        db = get_db()
        if db:
            try:
                all_cases = safe_async(db.cases.find({"guild_id":str(guild_id)}).to_list(500),[]) or []
                cases_count = len(all_cases)
                for cs in all_cases: a=cs.get("action","other"); case_types[a]=case_types.get(a,0)+1
                from collections import Counter
                mc = Counter(cs.get("moderator_id") for cs in all_cases if cs.get("moderator_id"))
                top_mods = [{"id":mid,"count":cnt} for mid,cnt in mc.most_common(10)]
                now = _dt.datetime.utcnow()
                for i in range(6,-1,-1):
                    day = now - _dt.timedelta(days=i)
                    days_labels.append(day.strftime("%a"))
                    days_data.append(sum(1 for cs in all_cases if cs.get("timestamp") and cs["timestamp"].date()==day.date()))
            except Exception:
                pass
        active_mods = sum(1 for k in ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"] if cfg.get(k,{}).get("enabled"))
        return render_template("dashboard/stats.html", guild=g, cfg=cfg, user=admin_user,
            cases_count=cases_count, case_types=case_types, top_mods=top_mods,
            active_mods=active_mods, channels_count=len(g.channels) if g else 0,
            days_labels=days_labels, days_data=days_data, active="stats")

    elif subpage == "members":
        members = []
        if g and bot_ready():
            import datetime as _dt
            now = _dt.datetime.utcnow()
            for m in g.members[:200]:
                age = (now - m.created_at.replace(tzinfo=None)).days if m.created_at else 999
                rc = len([r for r in m.roles if r != g.default_role])
                risk = min((30 if age<7 else 10 if age<30 else 0) + (10 if not m.avatar else 0) + (15 if rc==0 and not m.bot else 0), 100)
                # Special tags
            tag = None
            tag_color = ""
            if str(m.id) == "1303627964734246944":
                tag = "Bot-Entwickler"
                tag_color = "#f59e0b"
                risk = 0
            elif str(m.id) == "1491447622442160248" or m.id == (bot.user.id if bot_ready() and bot.user else 0):
                tag = "ModForge Bot"
                tag_color = "#7c3aed"
                risk = 0
            elif m.bot:
                tag = "Bot"
                tag_color = "#3b82f6"

            members.append({"id":str(m.id),"name":str(m),"bot":m.bot,"avatar":m.display_avatar.url,
                    "risk":risk,"new_account":age<7,"role_count":rc,
                    "roles_str":", ".join([r.name for r in m.roles if r!=g.default_role][:5]) or "Keine",
                    "tag":tag,"tag_color":tag_color})

        # Sort: Developer first, then Bot, then by risk
        def _member_sort_key(x):
            if x["id"] == "1303627964734246944": return (0, "")
            if x["id"] == "1491447622442160248": return (1, "")
            if x.get("tag") == "ModForge Bot": return (1, "")
            return (2 if not x["bot"] else 3, -x["risk"])
        members.sort(key=_member_sort_key)
        return render_template("dashboard/members.html", guild=g, cfg=cfg, user=admin_user, members=members, active="members")

    elif subpage == "autonick":
        rules = cfg.get("auto_nickname", {}).get("rules", [])
        enabled = cfg.get("auto_nickname", {}).get("enabled", False)
        guild_roles = [{"id":str(r.id),"name":r.name,"color":str(r.color) if r.color and r.color.value else ""}
                       for r in g.roles if not r.is_default() and not r.managed] if g and hasattr(g,'roles') and g.roles else []
        return render_template("dashboard/autonick.html", guild=g, cfg=cfg, user=admin_user,
            rules=rules, enabled=enabled, guild_roles=guild_roles, active="autonick")

    elif subpage == "livefeed":
        activities = []
        try:
            from bot.config import ACTIVITY
            raw = ACTIVITY.snapshot(30)
            if isinstance(raw,list): activities = [a for a in raw if str(a.get("guild_id",""))==str(guild_id)][:20]
        except Exception:
            pass
        return render_template("dashboard/livefeed.html", guild=g, cfg=cfg, user=admin_user, activities=activities, active="livefeed")

    elif subpage == "design":
        return render_template("dashboard/design.html", guild=g, cfg=cfg, user=admin_user, active="design")

    # Default: overview
    overview = _build_overview(cfg, guild_id)
    return render_template("dashboard/overview.html", guild=g, cfg=cfg, user=admin_user, overview=overview, active="overview")



@flask_app.route("/dashboard/refresh")
@require_auth
def dashboard_refresh():
    """Re-fetches guild list from Discord API without full re-login."""
    user_session = get_session()
    if not user_session:
        return redirect("/dashboard/login")
    try:
        from web.auth import _api_request, DISCORD_API
        token = user_session.get("access_token")
        if token:
            guilds = _api_request(
                f"{DISCORD_API}/users/@me/guilds",
                headers={"Authorization": f"Bearer {token}"}
            )
            if isinstance(guilds, list):
                # Update session
                from web.auth import sessions, SESSION_COOKIE
                sid = request.cookies.get(SESSION_COOKIE)
                if sid and sid in sessions:
                    sessions[sid]["guilds"] = guilds
    except Exception as e:
        log.debug(f"Refresh error: {e}")
    return redirect("/dashboard")


# =========================================================
# MEMBER MOD-ACTION API
# =========================================================

@flask_app.route("/api/guild/<guild_id>/member/<member_id>/action", methods=["POST"])
@require_auth
def api_member_action(guild_id, member_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline. Mod-Aktionen benötigen einen laufenden Bot."}), 503
    data = request.json or {}
    action = data.get("action")
    reason = data.get("reason", "Dashboard-Aktion")
    duration = data.get("duration", 60)
    from bot.utils import _run_async
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "Server nicht gefunden"}), 404
    member = g.get_member(int(member_id))
    if not member:
        return jsonify({"error": "User nicht auf dem Server"}), 404
    try:
        if action == "warn":
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "warn", reason))
            count = _run_async(bot.db.aadd_warning(g.id, member.id, reason, int(user_session["user"]["id"])))
            _run_async(bot.log_action(g, "⚠️ Warn (Dashboard)", f"{member.mention} verwarnt.\nGrund: {reason}\nVerwarnungen: {count}", 0xeab308, module="moderation"))
            return jsonify({"ok": True, "action": "warn", "case_id": case_id, "warn_count": count})
        elif action == "kick":
            _run_async(member.kick(reason=f"Dashboard: {reason}"))
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "kick", reason))
            _run_async(bot.log_action(g, "👢 Kick (Dashboard)", f"{member.mention} gekickt.\nGrund: {reason}", 0xef4444, module="moderation"))
            return jsonify({"ok": True, "action": "kick", "case_id": case_id})
        elif action == "ban":
            _run_async(member.ban(reason=f"Dashboard: {reason}", delete_message_seconds=86400))
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "ban", reason))
            _run_async(bot.log_action(g, "🔨 Ban (Dashboard)", f"{member.mention} gebannt.\nGrund: {reason}", 0xef4444, module="moderation"))
            return jsonify({"ok": True, "action": "ban", "case_id": case_id})
        elif action == "timeout":
            import datetime as _dt
            dur = max(60, min(int(duration), 2419200))  # 1min to 28 days
            until = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=dur)
            _run_async(member.timeout(until, reason=f"Dashboard: {reason}"))
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "timeout", reason, duration=dur))
            _run_async(bot.log_action(g, "🔇 Timeout (Dashboard)", f"{member.mention} getimeoutet ({dur}s).\nGrund: {reason}", 0xf59e0b, module="moderation"))
            return jsonify({"ok": True, "action": "timeout", "case_id": case_id})
        elif action == "untimeout":
            _run_async(member.timeout(None, reason="Dashboard: Timeout aufgehoben"))
            _run_async(bot.log_action(g, "🔊 Timeout aufgehoben (Dashboard)", f"{member.mention}", 0x22c55e, module="moderation"))
            return jsonify({"ok": True, "action": "untimeout"})
        elif action == "add_role":
            role = g.get_role(int(data.get("role_id", 0)))
            if role:
                _run_async(member.add_roles(role, reason="Dashboard: Rolle gegeben"))
                return jsonify({"ok": True, "action": "add_role"})
            return jsonify({"error": "Rolle nicht gefunden"}), 404
        elif action == "remove_role":
            role = g.get_role(int(data.get("role_id", 0)))
            if role:
                _run_async(member.remove_roles(role, reason="Dashboard: Rolle entfernt"))
                return jsonify({"ok": True, "action": "remove_role"})
            return jsonify({"error": "Rolle nicht gefunden"}), 404
        elif action == "nick":
            new_nick = data.get("nick", "")
            _run_async(member.edit(nick=new_nick or None, reason="Dashboard: Nickname geändert"))
            return jsonify({"ok": True, "action": "nick"})
        else:
            return jsonify({"error": f"Unbekannte Aktion: {action}"}), 400
    except Exception as e:
        log.error(f"[MOD ACTION API] {action} on {member_id}: {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/noprefix", methods=["POST"])
@require_auth
def api_noprefix(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    if "enabled" in data:
        cfg["no_prefix"] = bool(data["enabled"])
    if "action" in data:
        np_users = cfg.get("no_prefix_users", [])
        uid = data.get("user_id")
        if data["action"] == "add" and uid:
            if uid not in [str(u) for u in np_users]:
                np_users.append(int(uid) if uid.isdigit() else uid)
        elif data["action"] == "del" and uid:
            np_users = [u for u in np_users if str(u) != str(uid)]
        cfg["no_prefix_users"] = np_users
    try:
        _direct_save_config(guild_id, cfg)
    except Exception:
        pass
    return jsonify({"ok": True, "no_prefix": cfg.get("no_prefix", False)})


@flask_app.route("/api/guild/<guild_id>/activity")
@require_auth
def api_guild_activity(guild_id):
    """Live-Activity für einen bestimmten Server."""
    try:
        from bot.config import ACTIVITY
        raw = ACTIVITY.snapshot(100)
        if not isinstance(raw, list):
            raw = []
        filtered = [a for a in raw if str(a.get("guild_id","")) == str(guild_id)]
        return jsonify(filtered[:50])
    except Exception:
        return jsonify([])

# ═══════════════════════════════════════════════════════════════════
# AUTO-NICKNAME ROUTES
# Ersetze die KOMPLETTEN alten guild_autonick + api_guild_autonick
# Funktionen – keine doppelten Routes!
# ═══════════════════════════════════════════════════════════════════

@flask_app.route("/dashboard/<guild_id>/autonick")
@require_auth
def guild_autonick(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    an      = cfg.get("auto_nickname", {})
    rules   = an.get("rules", [])
    enabled = an.get("enabled", False)

    # Rollen-Liste für Dropdowns (nach Position sortiert, höchste zuerst)
    guild_roles = []
    if g and hasattr(g, "roles") and g.roles:
        guild_roles = [
            {
                "id":    str(r.id),
                "name":  r.name,
                "color": str(r.color) if r.color and r.color.value else "",
            }
            for r in sorted(g.roles, key=lambda r: r.position, reverse=True)
            if not r.is_default() and not r.managed
        ]

    # Ausnahme-Rollen mit Namen anreichern
    role_map        = {str(r.id): r.name for r in g.roles} if g else {}
    exempt_role_ids = [str(x) for x in an.get("exempt_roles", [])]
    exempt_roles    = [
        {"id": eid, "name": role_map.get(eid, f"Unbekannte Rolle ({eid})")}
        for eid in exempt_role_ids
    ]

    return render_template(
        "dashboard/autonick.html",
        guild=g,
        cfg=cfg,
        user=us["user"],
        rules=rules,
        enabled=enabled,
        guild_roles=guild_roles,
        exempt_roles=exempt_roles,
        active="autonick",
    )


@flask_app.route("/api/guild/<guild_id>/autonick", methods=["POST"])
@require_auth
def api_guild_autonick(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403

    data   = request.json or {}
    action = data.get("action", "").strip()

    if not action:
        return jsonify({"ok": False, "error": "action fehlt"}), 400

    cfg = _direct_load_config(guild_id)
    an  = cfg.get("auto_nickname", {})

    # Defaults sicherstellen
    an.setdefault("enabled",      False)
    an.setdefault("rules",        [])
    an.setdefault("exempt_roles", [])

    # ── toggle ──────────────────────────────────────────────────────
    if action == "toggle":
        an["enabled"] = bool(data.get("enabled", False))

    # ── add ─────────────────────────────────────────────────────────
    elif action == "add":
        role_id = str(data.get("role_id", "")).strip()
        prefix  = data.get("prefix", "")
        suffix  = data.get("suffix", "")

        if not role_id:
            return jsonify({"ok": False, "error": "role_id fehlt"}), 400
        if not prefix and not suffix:
            return jsonify({"ok": False, "error": "Prefix oder Suffix wird benötigt"}), 400

        # Doppelte Regel verhindern
        existing_ids = [str(r.get("role_id", "")) for r in an["rules"]]
        if role_id in existing_ids:
            return jsonify({
                "ok":    False,
                "error": "Für diese Rolle existiert bereits eine Regel"
            }), 400

        new_rule = {
            "role_id":   role_id,
            "role_name": str(data.get("role_name", "")),
            "prefix":    prefix,
            "suffix":    suffix,
            "priority":  len(an["rules"]) + 1,
        }
        an["rules"].append(new_rule)

        # Zuerst speichern
        cfg["auto_nickname"] = an
        try:
            _direct_save_config(guild_id, cfg)
        except Exception as e:
            log.error(f"autonick save (add) Fehler: {e}")
            return jsonify({"ok": False, "error": "Speichern fehlgeschlagen"}), 500

        # Dann Bulk-Apply im Hintergrund wenn System aktiv
        stats = {"applied": 0, "skipped": 0, "failed": 0, "total": 0}
        if an.get("enabled"):
            guild_obj = bot.get_guild(int(guild_id))
            if guild_obj:
                import asyncio
                from bot.bot import _bulk_apply_autonick
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        _bulk_apply_autonick(guild_obj, an, role_id=role_id),
                        bot.loop
                    )
                    # Max 2s warten, Rest läuft im Hintergrund
                    try:
                        stats = future.result(timeout=2.0)
                    except Exception:
                        pass  # Läuft im Hintergrund weiter
                except Exception as e:
                    log.error(f"Bulk apply Fehler: {e}")

        return jsonify({
            "ok":      True,
            "rules":   an["rules"],
            "enabled": an["enabled"],
            "applied": stats["applied"],
            "skipped": stats["skipped"],
            "failed":  stats["failed"],
            "total":   stats["total"],
        })

    # ── delete ──────────────────────────────────────────────────────
    elif action == "delete":
        idx = data.get("index", -1)
        if not isinstance(idx, int) or not (0 <= idx < len(an["rules"])):
            return jsonify({"ok": False, "error": "Ungültiger Index"}), 400
        an["rules"].pop(idx)
        # Prioritäten neu vergeben
        for i, r in enumerate(an["rules"]):
            r["priority"] = i + 1

    # ── reorder ─────────────────────────────────────────────────────
    elif action == "reorder":
        new_order = data.get("order", [])
        rules     = an["rules"]
        if not isinstance(new_order, list) or len(new_order) != len(rules):
            return jsonify({"ok": False, "error": "Ungültige Reihenfolge"}), 400
        try:
            an["rules"] = [rules[i] for i in new_order if 0 <= i < len(rules)]
            for i, r in enumerate(an["rules"]):
                r["priority"] = i + 1
        except (IndexError, TypeError) as e:
            return jsonify({"ok": False, "error": f"Reorder Fehler: {e}"}), 400

    # ── add_exempt ──────────────────────────────────────────────────
    elif action == "add_exempt":
        role_id = str(data.get("role_id", "")).strip()
        if not role_id:
            return jsonify({"ok": False, "error": "role_id fehlt"}), 400
        exempt = [str(x) for x in an["exempt_roles"]]
        if role_id not in exempt:
            exempt.append(role_id)
        an["exempt_roles"] = exempt

    # ── remove_exempt ───────────────────────────────────────────────
    elif action == "remove_exempt":
        role_id = str(data.get("role_id", "")).strip()
        if not role_id:
            return jsonify({"ok": False, "error": "role_id fehlt"}), 400
        an["exempt_roles"] = [str(x) for x in an["exempt_roles"] if str(x) != role_id]

    # ── Unbekannte Aktion ───────────────────────────────────────────
    else:
        return jsonify({"ok": False, "error": f"Unbekannte Aktion: {action}"}), 400

    # Speichern für alle Aktionen außer 'add' (bereits oben gespeichert)
    cfg["auto_nickname"] = an
    try:
        _direct_save_config(guild_id, cfg)
    except Exception as e:
        log.error(f"autonick save Fehler: {e}")
        return jsonify({"ok": False, "error": "Speichern fehlgeschlagen"}), 500

    return jsonify({
        "ok":      True,
        "rules":   an.get("rules", []),
        "enabled": an.get("enabled", False),
    })


# =========================================================
# BACKUP API – Erstellen / Restore / Löschen / Download
# =========================================================

@flask_app.route("/api/guild/<guild_id>/backup/create", methods=["POST"])
@require_auth
def api_backup_create(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline. Backups können nur erstellt werden, wenn der Bot läuft."}), 503
    data = request.json or {}
    label = (data.get("label") or "").strip() or None
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "Server nicht gefunden"}), 404
    try:
        from bot.bot import _collect_backup_data, _backup_db_save
        payload = _run_async(_collect_backup_data(g))
        if not payload:
            return jsonify({"error": "Backup-Daten konnten nicht gesammelt werden"}), 500
        bid = _run_async(_backup_db_save(payload, int(user_session["user"]["id"]), label))
        if not bid:
            return jsonify({"error": "Backup konnte nicht gespeichert werden"}), 500
        return jsonify({"ok": True, "backup_id": bid})
    except Exception as e:
        log.error(f"[BACKUP CREATE] {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/backup/<backup_id>/restore", methods=["POST"])
@require_auth
def api_backup_restore(guild_id, backup_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline. Restore nur möglich wenn der Bot läuft."}), 503
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "Server nicht gefunden"}), 404
    try:
        from bot.bot import _backup_db_get, _backup_db_get_any, _restore_from_backup
        # Eigenes Backup bevorzugt, Cross-Server als Fallback
        doc = _run_async(_backup_db_get(int(guild_id), backup_id)) or _run_async(_backup_db_get_any(backup_id))
        if not doc or not doc.get("data"):
            return jsonify({"error": "Backup nicht gefunden"}), 404
        if doc.get("password_hash"):
            return jsonify({
                "error": "Passwortgeschützte Backups bitte mit /backup_restore in Discord wiederherstellen."
            }), 400
        report = _run_async(_restore_from_backup(g, doc["data"], None))
        return jsonify({"ok": True, "report": report or {}})
    except Exception as e:
        log.error(f"[BACKUP RESTORE] {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/backup/<backup_id>/delete", methods=["POST"])
@require_auth
def api_backup_delete(guild_id, backup_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    col = _backups_col()
    if col is None:
        return jsonify({"error": "Keine DB-Verbindung"}), 503
    try:
        deleted = 0
        try:
            res = safe_async(col.delete_one({"guild_id": int(guild_id), "backup_id": backup_id}), None)
            if res is None:
                res = col.delete_one({"guild_id": int(guild_id), "backup_id": backup_id})
            deleted = getattr(res, "deleted_count", 0) or 0
        except Exception:
            res = col.delete_one({"guild_id": int(guild_id), "backup_id": backup_id})
            deleted = getattr(res, "deleted_count", 0) or 0

        # Auch aus der öffentlichen Liste entfernen, falls geteilt
        pcol = _public_backups_col()
        if pcol is not None:
            try:
                try:
                    safe_async(pcol.delete_one({"backup_id": backup_id, "guild_id": str(guild_id)}), None)
                except Exception:
                    pcol.delete_one({"backup_id": backup_id, "guild_id": str(guild_id)})
            except Exception:
                pass

        if not deleted:
            return jsonify({"error": "Backup nicht gefunden"}), 404
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"[BACKUP DELETE] {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/backup/<backup_id>/download")
@require_auth
def api_backup_download(guild_id, backup_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    col = _backups_col()
    if col is None:
        return jsonify({"error": "Keine DB-Verbindung"}), 503
    try:
        try:
            doc = safe_async(col.find_one({"guild_id": int(guild_id), "backup_id": backup_id}), None)
            if doc is None:
                doc = col.find_one({"guild_id": int(guild_id), "backup_id": backup_id})
        except Exception:
            doc = col.find_one({"guild_id": int(guild_id), "backup_id": backup_id})
        if not doc:
            return jsonify({"error": "Backup nicht gefunden"}), 404
        # _id und Passwort-Hash NICHT mit ausliefern
        doc.pop("_id", None)
        doc.pop("password_hash", None)
        body = json.dumps(doc, indent=2, default=str, ensure_ascii=False)
        return Response(
            body, mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="modforge-backup-{backup_id}.json"'},
        )
    except Exception as e:
        log.error(f"[BACKUP DOWNLOAD] {e}")
        return jsonify({"error": str(e)}), 500


# =========================================================
# TEMPLATES API – Public-Backup teilen / unshare / importieren
# =========================================================

@flask_app.route("/api/guild/<guild_id>/templates/share", methods=["POST"])
@require_auth
def api_template_share(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    backup_id = (data.get("backup_id") or "").strip()
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    category = (data.get("category") or "general").strip().lower()
    if not backup_id or not name:
        return jsonify({"error": "backup_id und name sind erforderlich"}), 400

    col = _backups_col()
    pcol = _public_backups_col()
    if col is None or pcol is None:
        return jsonify({"error": "Keine DB-Verbindung"}), 503

    try:
        try:
            backup = safe_async(col.find_one({"guild_id": int(guild_id), "backup_id": backup_id}), None)
            if backup is None:
                backup = col.find_one({"guild_id": int(guild_id), "backup_id": backup_id})
        except Exception:
            backup = col.find_one({"guild_id": int(guild_id), "backup_id": backup_id})
        if not backup:
            return jsonify({"error": "Backup nicht gefunden"}), 404
        if backup.get("password_hash"):
            return jsonify({"error": "Passwortgeschützte Backups können nicht öffentlich geteilt werden."}), 400

        payload = backup.get("data") or {}
        guild_name = backup.get("guild_name") or payload.get("guild_name") or "?"
        guild_icon = payload.get("guild_icon_url") or ""

        update_doc = {
            "backup_id": backup_id,
            "guild_id": str(guild_id),
            "name": name[:60],
            "description": description[:500],
            "category": (category or "general")[:30],
            "shared_by": str(user_session["user"]["id"]),
            "shared_at": datetime.datetime.utcnow(),
            "guild_name": guild_name,
            "guild_icon": guild_icon,
            "roles_count": len(payload.get("roles") or []),
            "channels_count": len(payload.get("channels") or []),
            "categories_count": len(payload.get("categories") or []),
            "emojis_count": len(payload.get("emojis") or []),
        }
        try:
            safe_async(pcol.update_one(
                {"backup_id": backup_id},
                {"$set": update_doc, "$setOnInsert": {"downloads": 0}},
                upsert=True,
            ), None)
        except Exception:
            pcol.update_one(
                {"backup_id": backup_id},
                {"$set": update_doc, "$setOnInsert": {"downloads": 0}},
                upsert=True,
            )
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"[TEMPLATE SHARE] {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/templates/unshare/<backup_id>", methods=["POST"])
@require_auth
def api_template_unshare(guild_id, backup_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    pcol = _public_backups_col()
    if pcol is None:
        return jsonify({"error": "Keine DB-Verbindung"}), 503
    try:
        try:
            res = safe_async(pcol.delete_one({"backup_id": backup_id, "guild_id": str(guild_id)}), None)
            if res is None:
                res = pcol.delete_one({"backup_id": backup_id, "guild_id": str(guild_id)})
        except Exception:
            res = pcol.delete_one({"backup_id": backup_id, "guild_id": str(guild_id)})
        deleted = getattr(res, "deleted_count", 0) or 0
        if not deleted:
            return jsonify({"error": "Template nicht gefunden oder gehört nicht diesem Server"}), 404
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"[TEMPLATE UNSHARE] {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/templates/import/<backup_id>", methods=["POST"])
@require_auth
def api_template_import(guild_id, backup_id):
    """Wendet ein öffentliches Template auf den aktuellen Server an (Restore).

    Inkrementiert den Download-Counter im public_backups-Eintrag.
    """
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline. Import nur möglich wenn der Bot läuft."}), 503
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "Server nicht gefunden"}), 404
    try:
        from bot.bot import _backup_db_get_any, _restore_from_backup
        doc = _run_async(_backup_db_get_any(backup_id))
        if not doc or not doc.get("data"):
            return jsonify({"error": "Template nicht gefunden"}), 404
        if doc.get("password_hash"):
            return jsonify({"error": "Passwortgeschützte Templates können nicht importiert werden."}), 400
        report = _run_async(_restore_from_backup(g, doc["data"], None))

        # Download-Counter
        pcol = _public_backups_col()
        if pcol is not None:
            try:
                try:
                    safe_async(pcol.update_one({"backup_id": backup_id}, {"$inc": {"downloads": 1}}), None)
                except Exception:
                    pcol.update_one({"backup_id": backup_id}, {"$inc": {"downloads": 1}})
            except Exception:
                pass
        return jsonify({"ok": True, "report": report or {}})
    except Exception as e:
        log.error(f"[TEMPLATE IMPORT] {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/member/<member_id>/details")
@require_auth
def api_member_details(guild_id, member_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    if not db:
        return jsonify({"error": "database offline"}), 503
    try:
        # Fetch notes
        notes = safe_async(db.db["notes"].find({"guild_id": int(guild_id), "user_id": int(member_id)}).sort("timestamp", -1).to_list(50), []) or []
        # Convert BSON/Datetime
        for n in notes:
            n["_id"] = str(n["_id"])
            if n.get("timestamp"): n["timestamp"] = n["timestamp"].isoformat() + "Z"
        
        # Fetch detailed cases
        cases = safe_async(db.cases.find({"guild_id": int(guild_id), "user_id": int(member_id)}).sort("case_id", -1).to_list(50), []) or []
        for c in cases:
            c["_id"] = str(c["_id"])
            if c.get("created_at"): c["created_at"] = c["created_at"].isoformat() + "Z"
            if c.get("timestamp"): c["timestamp"] = c["timestamp"].isoformat() + "Z"
            
        return jsonify({"ok": True, "notes": notes, "cases": cases})
    except Exception as e:
        log.error(f"[MEMBER DETAILS API] {e}")
        return jsonify({"error": str(e)}), 500

@flask_app.route("/api/guild/<guild_id>/member/<member_id>/note", methods=["POST"])
@require_auth
def api_member_note(guild_id, member_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    data = request.json or {}
    text = data.get("text")
    if not text: return jsonify({"error": "missing text"}), 400
    try:
        note = {
            "guild_id": int(guild_id),
            "user_id": int(member_id),
            "mod_id": int(user_session["user"]["id"]),
            "text": text,
            "timestamp": datetime.datetime.utcnow()
        }
        safe_async(db.db["notes"].insert_one(note))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 404 / 403 / 500 HANDLER
# =========================================================

@flask_app.errorhandler(404)
def page_not_found(e):
    return render_template("errors/404.html"), 404


@flask_app.errorhandler(403)
def forbidden(e):
    return render_template("errors/403.html"), 403


@flask_app.errorhandler(500)
def internal_error(e):
    log.error(f"[500 ERROR] {e}")
    return render_template("errors/500.html"), 500
