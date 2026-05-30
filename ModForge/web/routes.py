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
import time
import threading

from collections import defaultdict, deque
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

from .app import flask_app
from .auth import get_session, require_auth
from .helpers import (
    _bot_stats,
    _get_guild_config,
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
    VERSIONS,
    LOG_MODS,
    ACTIVITY,
)

from bot.utils import _run_async

log = logging.getLogger("ModForge.Web.Routes")


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
    return bool(bot and bot.is_ready())


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
    if query is None:
        query = {}
    try:
        if not collection:
            return 0
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
                    "security": security,
                    "avatar_url": avatar_url,
                })
            except Exception as e:
                log.error(f"[GUILD PARSE ERROR] {e}")

    guilds_payload.sort(key=lambda x: x["members"], reverse=True)

    db = get_db()
    cases_total = 0
    warns_total = 0

    if bot_ready() and db:
        try:
            cases_total = safe_collection_count(db.cases)
            warns_coll = getattr(db, "warnings", None) or getattr(db, "warns", None)
            warns_total = safe_collection_count(warns_coll)
        except Exception as e:
            log.error(f"[GLOBAL STATS ERROR] {e}")

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
    return render_template("features.html", features=FEATURES)


@flask_app.route("/commands")
def commands():
    return render_template("commands.html", cmds=CMDS_PREVIEW)


@flask_app.route("/ai")
def ai_features():
    return render_template("ai.html")


@flask_app.route("/economy")
def economy():
    return render_template("economy.html")


@flask_app.route("/badges")
def badges():
    return render_template("badges.html")


@flask_app.route("/security")
def security():
    return render_template("security.html")


@flask_app.route("/premium")
def premium():
    return render_template("premium.html")


@flask_app.route("/pricing")
def pricing():
    return render_template("pricing.html")


# =========================================================
# TOOLS & INTEGRATIONEN
# =========================================================

@flask_app.route("/templates")
def server_templates():
    return render_template("templates.html")


@flask_app.route("/integrations")
def integrations():
    return render_template("integrations.html")


@flask_app.route("/widgets")
def widgets():
    return render_template("widgets.html")


@flask_app.route("/migrate")
def migrate():
    return render_template("migrate.html")


@flask_app.route("/emojis")
def emojis():
    return render_template("emojis.html")


@flask_app.route("/api-docs")
def api_docs():
    return render_template("api-docs.html")


@flask_app.route("/branding")
def branding():
    return render_template("branding.html")


# =========================================================
# DOCS (Unterseiten)
# =========================================================

@flask_app.route("/docs")
def docs():
    return render_template("docs.html")


@flask_app.route("/docs/automod")
def docs_automod():
    return render_template("docs/automod.html")


@flask_app.route("/docs/tickets")
def docs_tickets():
    return render_template("docs/tickets.html")


@flask_app.route("/docs/music")
def docs_music():
    return render_template("docs/music.html")


@flask_app.route("/docs/moderation")
def docs_moderation():
    return render_template("docs/moderation.html")


@flask_app.route("/docs/setup")
def docs_setup():
    return render_template("docs/setup.html")


# =========================================================
# RESSOURCEN
# =========================================================

@flask_app.route("/tutorials")
def tutorials():
    return render_template("tutorials.html")


@flask_app.route("/faq")
def faq():
    return render_template("faq.html")


@flask_app.route("/changelog")
def changelog():
    return render_template("changelog.html", versions=VERSIONS)


@flask_app.route("/roadmap")
def roadmap():
    return render_template("roadmap.html")


@flask_app.route("/blog")
def blog():
    return render_template("blog.html")


@flask_app.route("/downloads")
def downloads():
    return render_template("downloads.html")


# =========================================================
# COMMUNITY
# =========================================================

@flask_app.route("/partners")
def partners():
    return render_template("partners.html")


@flask_app.route("/affiliate")
def affiliate():
    return render_template("affiliate.html")


@flask_app.route("/suggest")
def suggest():
    return render_template("suggest.html")


@flask_app.route("/contact")
def contact():
    return render_template("contact.html")


@flask_app.route("/showcase")
def showcase():
    return render_template("showcase.html")


@flask_app.route("/testimonials")
def testimonials():
    return render_template("testimonials.html")


@flask_app.route("/leaderboard")
def leaderboard():
    return render_template("leaderboard.html")


@flask_app.route("/team")
def team():
    return render_template("team.html")


@flask_app.route("/jobs")
def jobs():
    return render_template("jobs.html")


@flask_app.route("/events")
def events():
    return render_template("events.html")


# =========================================================
# SUPPORT & STATUS
# =========================================================

@flask_app.route("/support")
def support():
    return render_template("support.html")


@flask_app.route("/uptime")
def uptime():
    gc, mc, uptime_seconds, lat = _base_stats()
    uptime_pct = _uptime_pct()
    return render_template(
        "uptime.html",
        uptime_pct=f"{uptime_pct:.3f}",
        up_s=uptime_seconds,
        api_latency=round(lat or 0),
        guild_count=gc,
        member_count=mc,
    )


@flask_app.route("/status/incidents")
def status_incidents():
    return render_template("status/incidents.html")


@flask_app.route("/status/maintenance")
def status_maintenance():
    return render_template("status/maintenance.html")


# =========================================================
# RECHTLICHES
# =========================================================

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

    cfg = _get_guild_config(guild_id)
    active_modules = sum(1 for k in ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"]
                         if cfg.get(k, {}).get("enabled"))
    import json as _json
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


# =========================================================
# GUILD-DASHBOARD (Auth User)
# =========================================================

# =========================================================
# GUILD-DASHBOARD (Auth User)
# =========================================================

@flask_app.route("/dashboard/<guild_id>")
@require_auth
def guild_dashboard(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    import datetime as _dt

    # Server stats
    text_ch = voice_ch = cats = bots = humans = online_count = boosters = 0
    roles_count = emojis_count = 0
    created = ""
    owner_name = "?"
    boost_tier = 0
    boost_count = 0
    features_list = []
    verification = "?"
    
    if g and hasattr(g, 'channels') and g.channels:
        text_ch = len([c for c in g.channels if hasattr(c,'type') and str(c.type)=='text'])
        voice_ch = len([c for c in g.channels if hasattr(c,'type') and str(c.type)=='voice'])
        cats = len(g.categories) if hasattr(g,'categories') else 0
    if g and hasattr(g, 'members') and g.members:
        bots = sum(1 for m in g.members if m.bot)
        humans = (g.member_count or 0) - bots
        online_count = sum(1 for m in g.members if hasattr(m,'status') and str(m.status)!='offline')
    if g and hasattr(g, 'roles'):
        roles_count = len(g.roles) - 1 if g.roles else 0
    if g and hasattr(g, 'emojis'):
        emojis_count = len(g.emojis) if g.emojis else 0
    if g and hasattr(g, 'created_at') and g.created_at:
        created = str(int(g.created_at.timestamp()))
    if g and hasattr(g, 'owner') and g.owner:
        owner_name = str(g.owner)
    if g and hasattr(g, 'premium_tier'):
        boost_tier = g.premium_tier or 0
    if g and hasattr(g, 'premium_subscription_count'):
        boost_count = g.premium_subscription_count or 0
    if g and hasattr(g, 'premium_subscribers') and g.premium_subscribers:
        boosters = len(g.premium_subscribers)
    if g and hasattr(g, 'features') and g.features:
        features_list = list(g.features)[:10]
    if g and hasattr(g, 'verification_level'):
        verification = str(g.verification_level).replace("VerificationLevel.","").title()

    # ModForge stats from config
    security_modules = ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","anti_webhook","anti_ghost_ping","anti_url_shortener","anti_vpn","automod"]
    active_mods = [(m, cfg.get(m,{}).get("enabled",False)) for m in security_modules]
    active_count = sum(1 for _,e in active_mods if e)
    sec_level = cfg.get("security_level", 0)
    log_channels_count = len(cfg.get("log_channels",{}) or {})
    has_default_log = bool(cfg.get("log_channel"))
    webhook_logging = cfg.get("webhook_logging",{}).get("enabled",False)
    prefix = cfg.get("prefix","!")
    no_prefix = cfg.get("no_prefix",False)

    # DB stats
    cases_count = warns_count = 0
    recent_cases = []
    db = get_db()
    if db:
        try:
            cases_count = safe_collection_count(db.cases, {"guild_id": str(guild_id)})
        except: pass
        try:
            warns_coll = getattr(db, "warnings", None)
            if warns_coll:
                warns_count = safe_collection_count(warns_coll, {"guild_id": str(guild_id)})
        except: pass
        try:
            recent_cases = safe_async(db.cases.find({"guild_id":str(guild_id)}).sort("case_id",-1).to_list(5), []) or []
        except: pass

    # Security score
    score = 20  # base
    if active_count >= 3: score += 15
    if active_count >= 6: score += 15
    if has_default_log: score += 10
    if log_channels_count >= 3: score += 10
    if sec_level >= 1: score += 10
    if webhook_logging: score += 5
    if boost_tier >= 1: score += 5
    if verification not in ("None","none",""): score += 10
    score = min(score, 100)

    return render_template(
        "dashboard/overview.html",
        guild=g, cfg=cfg, user=us["user"], active="overview",
        text_ch=text_ch, voice_ch=voice_ch, cats=cats,
        bots=bots, humans=humans, online_count=online_count,
        roles_count=roles_count, emojis_count=emojis_count,
        created=created, owner_name=owner_name,
        boost_tier=boost_tier, boost_count=boost_count, boosters=boosters,
        features_list=features_list, verification=verification,
        active_mods=active_mods, active_count=active_count,
        sec_level=sec_level, log_channels_count=log_channels_count,
        has_default_log=has_default_log, webhook_logging=webhook_logging,
        prefix=prefix, no_prefix=no_prefix,
        cases_count=cases_count, warns_count=warns_count,
        recent_cases=recent_cases, score=score,
    )


@flask_app.route("/dashboard/<guild_id>/modules")
@require_auth
def guild_modules(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    section = request.args.get("section", "antispam")
    form = _build_module_form(section, cfg, guild_id)
    return render_template("dashboard/modules.html", guild=g, cfg=cfg, form=form, user=us["user"], active="modules")


@flask_app.route("/dashboard/<guild_id>/welcome")
@require_auth
def guild_welcome(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    content = _build_welcome_content(cfg, guild_id)
    return render_template("dashboard/welcome.html", guild=g, cfg=cfg, content=content, user=us["user"], active="welcome")


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
    cfg = _get_guild_config(guild_id)
    return user_session, g, cfg, None

@flask_app.route("/dashboard/<guild_id>/security")
@require_auth
def guild_security(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    modules = []
    mod_defs = [
        ("anti_spam", "⚡", "Anti-Spam", "Spam, CAPS, Emoji-Spam und Duplikate erkennen", [
            {"key":"msg_limit","label":"Nachrichten-Limit","type":"number","min":2,"max":30},
            {"key":"msg_window","label":"Zeitfenster (s)","type":"number","min":3,"max":60},
            {"key":"caps_pct","label":"CAPS-Schwelle (%)","type":"number","min":50,"max":100},
            {"key":"emoji_max","label":"Max Emojis","type":"number","min":3,"max":50},
            {"key":"duplicate_max","label":"Max Duplikate","type":"number","min":1,"max":10},
            {"key":"timeout_duration","label":"Timeout (s)","type":"number","min":10,"max":86400},
            {"key":"punishment","label":"Bestrafung","type":"select","options":["warn","timeout","kick","ban"]},
        ]),
        ("anti_nuke", "💥", "Anti-Nuke", "Massen-Bans, Channel-Löschungen, Rollen-Änderungen. Auto-Lockdown + Owner-DM", [
            {"key":"threshold","label":"Aktions-Schwelle","type":"number","min":2,"max":20},
            {"key":"window","label":"Zeitfenster (s)","type":"number","min":5,"max":120},
            {"key":"remove_roles","label":"Rollen entfernen","type":"select","options":["true","false"]},
            {"key":"punishment","label":"Bestrafung","type":"select","options":["warn","timeout","kick","ban"]},
        ]),
        ("anti_raid", "🚨", "Anti-Raid", "Massen-Joins erkennen, neue Accounts filtern, Lockdown", [
            {"key":"join_threshold","label":"Join-Schwelle","type":"number","min":3,"max":50},
            {"key":"window","label":"Zeitfenster (s)","type":"number","min":5,"max":120},
            {"key":"min_account_age","label":"Min Account-Alter (Tage)","type":"number","min":0,"max":90},
            {"key":"auto_kick","label":"Auto-Kick neue Accounts","type":"select","options":["true","false"]},
            {"key":"lockdown","label":"Auto-Lockdown","type":"select","options":["true","false"]},
            {"key":"suspicious_name_check","label":"Verdächtige Namen prüfen","type":"select","options":["true","false"]},
        ]),
        ("anti_mention", "🔔", "Anti-Mention", "Mass-Mentions und @everyone-Missbrauch", [
            {"key":"mention_limit","label":"Max Mentions","type":"number","min":2,"max":30},
            {"key":"window","label":"Zeitfenster (s)","type":"number","min":3,"max":60},
            {"key":"timeout_duration","label":"Timeout (s)","type":"number","min":10,"max":86400},
            {"key":"punishment","label":"Bestrafung","type":"select","options":["warn","timeout","kick","ban"]},
        ]),
        ("anti_scam", "🎣", "Anti-Scam", "Phishing, Fake-Nitro, bekannte Scam-Domains", [
            {"key":"punishment","label":"Bestrafung","type":"select","options":["warn","timeout","kick","ban"]},
        ]),
        ("anti_webhook", "🔌", "Anti-Webhook", "Erkennt verdächtige Webhook-Erstellungen", [
            {"key":"threshold","label":"Schwelle","type":"number","min":1,"max":10},
            {"key":"window","label":"Zeitfenster (s)","type":"number","min":5,"max":120},
        ]),
        ("anti_ghost_ping", "👻", "Anti-Ghost-Ping", "Erkennt gelöschte Mentions (Ghost-Pings)", []),
        ("anti_url_shortener", "🔗", "Anti-URL-Shortener", "Blockiert URL-Shortener (bit.ly, tinyurl etc.)", [
            {"key":"punishment","label":"Bestrafung","type":"select","options":["warn","timeout","kick","ban"]},
        ]),
        ("anti_vpn", "🌐", "Anti-VPN", "Verdächtige Accounts (VPN/Proxy-Heuristik) erkennen", [
            {"key":"action","label":"Aktion","type":"select","options":["kick","ban","log"]},
        ]),
        ("automod", "🤖", "AutoMod", "Wortfilter, Regex, Link/Invite-Filter", [
            {"key":"punishment","label":"Bestrafung","type":"select","options":["warn","timeout","kick","ban"]},
        ]),
    ]
    for key, icon, label, desc, params in mod_defs:
        mcfg = cfg.get(key, {})
        for p in params:
            p["value"] = mcfg.get(p["key"], "")
        modules.append({"key":key,"icon":icon,"label":label,"desc":desc,"enabled":mcfg.get("enabled",False),"params":params})
    wl = bot.db.get_whitelist(int(guild_id)) if bot_ready() else {}
    wl_count = sum(len(v) for v in wl.values() if isinstance(v, list))
    active_count = sum(1 for m in modules if m["enabled"])
    total_modules = len(modules)
    return render_template("dashboard/security.html", guild=g, cfg=cfg, user=us["user"],
                           modules=modules, active_count=active_count, wl_count=wl_count, active="security")

@flask_app.route("/dashboard/<guild_id>/automod")
@require_auth
def guild_automod(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    return render_template("dashboard/automod.html", guild=g, cfg=cfg, user=us["user"], active="automod")

@flask_app.route("/dashboard/<guild_id>/logs")
@require_auth
def guild_logs(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
    log_channels = cfg.get("log_channels", {}) or {}
    from bot.config import LOG_MODULES, LOG_MODULES_EXTRA

    # Module mit Kategorien, Beschreibungen, Icons
    categories = {
        "Security": [
            {"key":"antispam","icon":"⚡","label":"Anti-Spam","desc":"Spam-Erkennung, CAPS, Duplikate"},
            {"key":"antinuke","icon":"💥","label":"Anti-Nuke","desc":"Massen-Bans, Channel-Löschungen"},
            {"key":"antiraid","icon":"🚨","label":"Anti-Raid","desc":"Massen-Joins, Lockdown"},
            {"key":"antimention","icon":"🔔","label":"Anti-Mention","desc":"Mass-Mentions, @everyone"},
            {"key":"antiscam","icon":"🎣","label":"Anti-Scam","desc":"Phishing, Fake-Nitro"},
            {"key":"antishortener","icon":"🔗","label":"URL-Shortener","desc":"bit.ly, tinyurl blockiert"},
        ],
        "Moderation": [
            {"key":"moderation","icon":"🛡️","label":"Moderation","desc":"Ban, Kick, Mute, Warn"},
            {"key":"warns","icon":"⚠️","label":"Warns","desc":"Verwarnungen"},
            {"key":"cases","icon":"📋","label":"Cases","desc":"Moderation-Cases"},
            {"key":"automod","icon":"🤖","label":"AutoMod","desc":"Wortfilter, Regex, Links"},
            {"key":"appeal","icon":"📬","label":"Ban-Appeal","desc":"Entbannungsanträge"},
        ],
        "Server": [
            {"key":"members","icon":"👥","label":"Members","desc":"Join, Leave, Update"},
            {"key":"nicknames","icon":"📝","label":"Nicknames","desc":"Nickname-Änderungen"},
            {"key":"roles","icon":"🏷️","label":"Rollen","desc":"Rollen-Änderungen"},
            {"key":"channels","icon":"📁","label":"Kanäle","desc":"Kanal erstellt/gelöscht/geändert"},
            {"key":"permissions","icon":"🔐","label":"Berechtigungen","desc":"Permission-Änderungen"},
            {"key":"webhooks","icon":"🔌","label":"Webhooks","desc":"Webhook-Änderungen"},
        ],
        "Voice": [
            {"key":"voice","icon":"🎤","label":"Voice","desc":"Join, Leave, Mute, Deaf, Stream"},
        ],
        "Nachrichten": [
            {"key":"messages","icon":"💬","label":"Nachrichten","desc":"Gelöschte/Bearbeitete Nachrichten"},
            {"key":"messages_sent","icon":"📨","label":"Gesendete","desc":"Alle gesendeten Nachrichten"},
            {"key":"ghostping","icon":"👻","label":"Ghost-Ping","desc":"Gelöschte Mentions"},
        ],
        "System": [
            {"key":"default","icon":"📌","label":"Standard","desc":"Fallback für alle Module"},
            {"key":"verify","icon":"✅","label":"Verifizierung","desc":"Captcha, One-Click"},
            {"key":"tickets","icon":"🎫","label":"Tickets","desc":"Ticket erstellt/geschlossen"},
            {"key":"welcome","icon":"👋","label":"Welcome","desc":"Begrüßungsnachrichten"},
            {"key":"leave","icon":"🚪","label":"Leave","desc":"Abschiedsnachrichten"},
            {"key":"backup","icon":"💾","label":"Backup","desc":"Backup erstellt/wiederhergestellt"},
            {"key":"audit","icon":"🔍","label":"Audit","desc":"Audit-Log Einträge"},
            {"key":"errors","icon":"❌","label":"Fehler","desc":"Bot-Fehler und Warnungen"},
        ],
    }

    # Status berechnen
    total_configured = sum(1 for v in log_channels.values() if v)
    default_channel = cfg.get("log_channel")
    webhook_enabled = cfg.get("webhook_logging", {}).get("enabled", False)

    return render_template("dashboard/logs.html", guild=g, cfg=cfg, user=us["user"],
                           channels=channels, log_channels=log_channels,
                           categories=categories,
                           total_configured=total_configured,
                           default_channel=default_channel,
                           webhook_enabled=webhook_enabled,
                           active="logs")

@flask_app.route("/dashboard/<guild_id>/cases")
@require_auth
def guild_cases(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    cases = []
    db = get_db()
    if db:
        try:
            raw = safe_async(db.cases.find({"guild_id":str(guild_id)}).sort("case_id",-1).to_list(200), []) or []
            for c in raw:
                c["timestamp"] = str(c.get("timestamp",""))[:19]
            cases = raw
        except Exception as e:
            log.error(f"[CASES PAGE] {e}")
    return render_template("dashboard/cases.html", guild=g, cfg=cfg, user=us["user"], cases=cases, active="cases")

@flask_app.route("/dashboard/<guild_id>/warns")
@require_auth
def guild_warns(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    return render_template("dashboard/warns.html", guild=g, cfg=cfg, user=us["user"], active="warns")

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

@flask_app.route("/dashboard/<guild_id>/roles")
@require_auth
def guild_roles(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    guild_roles = [{"id":str(r.id),"name":r.name} for r in g.roles if not r.is_default() and not r.managed] if g else []
    ar = cfg.get("auto_role",{}).get("roles",[])
    sr = cfg.get("sticky_roles",[])
    return render_template("dashboard/roles.html", guild=g, cfg=cfg, user=us["user"],
                           guild_roles=guild_roles, auto_roles=ar, sticky_roles=sr, active="roles")

@flask_app.route("/dashboard/<guild_id>/backup")
@require_auth
def guild_backup(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    backups = []
    db = get_db()
    if db:
        try:
            backups = safe_async(db.backups.find({"guild_id":str(guild_id)}).sort("created_at",-1).to_list(20),[]) or []
        except Exception:
            pass
    return render_template("dashboard/backup.html", guild=g, cfg=cfg, user=us["user"], backups=backups, active="backup")

@flask_app.route("/dashboard/<guild_id>/settings")
@require_auth
def guild_settings(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
    return render_template("dashboard/settings.html", guild=g, cfg=cfg, user=us["user"], channels=channels, active="settings")

# =========================================================

@flask_app.route("/dashboard/<guild_id>/embed")
@require_auth
def guild_embed(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
    return render_template("dashboard/embed.html", guild=g, cfg=cfg, user=us["user"], channels=channels, active="embed")

# PUBLIC PAGES (new)

@flask_app.route("/demo")
def demo():
    return render_template("demo.html")

@flask_app.route("/server-check")
def server_check():
    return render_template("server_check.html")


# =========================================================

@flask_app.route("/compare")
def compare():
    return render_template("compare.html")

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
    cfg = _get_guild_config(guild_id)
    from bot.utils import _run_async

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
    if "_warn_decay" in data:
        cfg["warn_decay"] = data["_warn_decay"]
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
        _run_async(bot.db.set_config(int(guild_id), cfg))
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
    cfg = _get_guild_config(guild_id)
    from bot.utils import _run_async
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
        _run_async(bot.db.set_config(int(guild_id), cfg))
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
    cfg = _get_guild_config(guild_id)
    from bot.utils import _run_async
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
        _run_async(bot.db.set_config(int(guild_id), cfg))
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
    cfg = _get_guild_config(guild_id)
    from bot.utils import _run_async
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
        _run_async(bot.db.set_config(int(guild_id), cfg))
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
                except: pass

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
                except:
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
    cfg = _get_guild_config(guild_id)
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
    active_mods = sum(1 for k in ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"]
                      if cfg.get(k, {}).get("enabled"))
    channels_count = len(g.channels) if g else 0
    return render_template("dashboard/stats.html", guild=g, cfg=cfg, user=us["user"],
        cases_count=cases_count, case_types=case_types, top_mods=top_mods,
        active_mods=active_mods, channels_count=channels_count,
        days_labels=days_labels, days_data=days_data, active="stats")

@flask_app.route("/dashboard/<guild_id>/whitelist")
@require_auth
def guild_whitelist(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    wl = {}
    if bot_ready():
        try: wl = bot.db.get_whitelist(int(guild_id))
        except: pass
    return render_template("dashboard/whitelist.html", guild=g, cfg=cfg, user=us["user"],
        whitelist=wl, active="whitelist")

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
    except: pass
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
            except: pass
            if item_id not in items:
                items.append(item_id)
            wl[cat] = items
        elif action == "del":
            try: item_id = int(item_id)
            except: pass
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
    cfg = _get_guild_config(guild_id)
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
        except: pass
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
            except: pass
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
        db = get_db()
        if db:
            try: backups = safe_async(db.backups.find({"guild_id":str(guild_id)}).sort("created_at",-1).to_list(20),[]) or []
            except: pass
        return render_template("dashboard/backup.html", guild=g, cfg=cfg, user=admin_user, backups=backups, active="backup")

    elif subpage == "autoresponse":
        return render_template("dashboard/autoresponse.html", guild=g, cfg=cfg, user=admin_user, auto_responses=cfg.get("auto_responses",[]), active="autoresponse")

    elif subpage == "embed":
        channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
        return render_template("dashboard/embed.html", guild=g, cfg=cfg, user=admin_user, channels=channels, active="embed")

    elif subpage == "whitelist":
        wl = {}
        if bot_ready():
            try: wl = bot.db.get_whitelist(int(guild_id))
            except: pass
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
            except: pass
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
        except: pass
        return render_template("dashboard/livefeed.html", guild=g, cfg=cfg, user=admin_user, activities=activities, active="livefeed")

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
            _run_async(bot.log_action(g, f"⚠️ Warn (Dashboard)", f"{member.mention} verwarnt.\nGrund: {reason}\nVerwarnungen: {count}", 0xeab308, module="moderation"))
            return jsonify({"ok": True, "action": "warn", "case_id": case_id, "warn_count": count})
        elif action == "kick":
            _run_async(member.kick(reason=f"Dashboard: {reason}"))
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "kick", reason))
            _run_async(bot.log_action(g, f"👢 Kick (Dashboard)", f"{member.mention} gekickt.\nGrund: {reason}", 0xef4444, module="moderation"))
            return jsonify({"ok": True, "action": "kick", "case_id": case_id})
        elif action == "ban":
            _run_async(member.ban(reason=f"Dashboard: {reason}", delete_message_seconds=86400))
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "ban", reason))
            _run_async(bot.log_action(g, f"🔨 Ban (Dashboard)", f"{member.mention} gebannt.\nGrund: {reason}", 0xef4444, module="moderation"))
            return jsonify({"ok": True, "action": "ban", "case_id": case_id})
        elif action == "timeout":
            import datetime as _dt
            dur = max(60, min(int(duration), 2419200))  # 1min to 28 days
            until = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=dur)
            _run_async(member.timeout(until, reason=f"Dashboard: {reason}"))
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "timeout", reason, duration=dur))
            _run_async(bot.log_action(g, f"🔇 Timeout (Dashboard)", f"{member.mention} getimeoutet ({dur}s).\nGrund: {reason}", 0xf59e0b, module="moderation"))
            return jsonify({"ok": True, "action": "timeout", "case_id": case_id})
        elif action == "untimeout":
            _run_async(member.timeout(None, reason=f"Dashboard: Timeout aufgehoben"))
            _run_async(bot.log_action(g, f"🔊 Timeout aufgehoben (Dashboard)", f"{member.mention}", 0x22c55e, module="moderation"))
            return jsonify({"ok": True, "action": "untimeout"})
        elif action == "add_role":
            role = g.get_role(int(data.get("role_id", 0)))
            if role:
                _run_async(member.add_roles(role, reason=f"Dashboard: Rolle gegeben"))
                return jsonify({"ok": True, "action": "add_role"})
            return jsonify({"error": "Rolle nicht gefunden"}), 404
        elif action == "remove_role":
            role = g.get_role(int(data.get("role_id", 0)))
            if role:
                _run_async(member.remove_roles(role, reason=f"Dashboard: Rolle entfernt"))
                return jsonify({"ok": True, "action": "remove_role"})
            return jsonify({"error": "Rolle nicht gefunden"}), 404
        elif action == "nick":
            new_nick = data.get("nick", "")
            _run_async(member.edit(nick=new_nick or None, reason=f"Dashboard: Nickname geändert"))
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
    cfg = _get_guild_config(guild_id)
    from bot.utils import _run_async
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
        _run_async(bot.db.set_config(int(guild_id), cfg))
    except:
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
    except Exception as e:
        return jsonify([])


@flask_app.route("/dashboard/<guild_id>/autonick")
@require_auth
def guild_autonick(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    rules = cfg.get("auto_nickname", {}).get("rules", [])
    enabled = cfg.get("auto_nickname", {}).get("enabled", False)
    guild_roles = []
    if g and hasattr(g, 'roles') and g.roles:
        guild_roles = [{"id": str(r.id), "name": r.name, "color": str(r.color) if r.color and r.color.value else ""}
                       for r in g.roles if not r.is_default() and not r.managed]
    return render_template("dashboard/autonick.html", guild=g, cfg=cfg, user=us["user"],
        rules=rules, enabled=enabled, guild_roles=guild_roles, active="autonick")

@flask_app.route("/api/guild/<guild_id>/autonick", methods=["POST"])
@require_auth
def api_guild_autonick(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _get_guild_config(guild_id)
    from bot.utils import _run_async
    an = cfg.get("auto_nickname", {"enabled": False, "rules": []})
    action = data.get("action")

    if action == "toggle":
        an["enabled"] = bool(data.get("enabled", False))
        # Preserve existing rules
        if "rules" not in an:
            an["rules"] = []
    elif action == "add":
        rule = {
            "role_id": data.get("role_id"),
            "role_name": data.get("role_name", ""),
            "prefix": data.get("prefix", ""),
            "suffix": data.get("suffix", ""),
            "priority": data.get("priority", len(an.get("rules", [])) + 1),
        }
        if rule["role_id"]:
            an.setdefault("rules", []).append(rule)
    elif action == "delete":
        idx = data.get("index", -1)
        rules = an.get("rules", [])
        if 0 <= idx < len(rules):
            rules.pop(idx)
        an["rules"] = rules
    elif action == "reorder":
        new_order = data.get("order", [])
        rules = an.get("rules", [])
        if len(new_order) == len(rules):
            an["rules"] = [rules[i] for i in new_order if 0 <= i < len(rules)]
    elif action == "save_all":
        an["enabled"] = data.get("enabled", an.get("enabled", False))
        an["rules"] = data.get("rules", an.get("rules", []))

    cfg["auto_nickname"] = an
    try:
        _run_async(bot.db.set_config(int(guild_id), cfg))
    except: pass
    return jsonify({"ok": True, "rules": an.get("rules", []), "enabled": an.get("enabled", False)})

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
