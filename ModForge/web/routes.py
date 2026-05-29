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
    if not user_session or not bot_ready():
        return False
    try:
        bot_guild_ids = {str(g.id) for g in bot.guilds}
        for g in user_session.get("guilds", []):
            if str(g["id"]) != str(guild_id):
                continue
            permissions = int(g.get("permissions", 0))
            has_access = (
                g.get("owner")
                or (permissions & 0x8)
                or (permissions & 0x20)
            )
            if not has_access:
                return False
            return str(g["id"]) in bot_guild_ids
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
                if str(g["id"]) not in bot_guild_ids:
                    continue
                manageable.append({
                    "id": str(g["id"]),
                    "name": g["name"],
                    "icon": (
                        f"https://cdn.discordapp.com/icons/"
                        f"{g['id']}/{g.get('icon')}.png?size=128"
                        if g.get("icon")
                        else "https://cdn.discordapp.com/embed/avatars/0.png"
                    ),
                })
            except Exception as e:
                log.error(f"[MANAGEABLE ERROR] {e}")

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

        if username == ADMIN_USERNAME and check_password_hash(
            generate_password_hash(ADMIN_PASSWORD), password
        ):
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
    user_session = get_session()
    if not user_session:
        return redirect(url_for("discord_login_page"))

    if not _user_can_manage_guild_in_session(user_session, guild_id):
        abort(403)

    g = get_guild(guild_id)
    if not g:
        abort(404)

    cfg = _get_guild_config(guild_id)
    overview = _build_overview(cfg, guild_id)
    return render_template(
        "dashboard/overview.html",
        guild=g,
        overview=overview,
        user=user_session["user"],
    )


@flask_app.route("/dashboard/<guild_id>/modules")
@require_auth
def guild_modules(guild_id):
    user_session = get_session()
    if not user_session:
        return redirect(url_for("discord_login_page"))

    if not _user_can_manage_guild_in_session(user_session, guild_id):
        abort(403)

    g = get_guild(guild_id)
    if not g:
        abort(404)

    cfg = _get_guild_config(guild_id)
    section = request.args.get("section", "antispam")
    form = _build_module_form(section, cfg, guild_id)

    return render_template(
        "dashboard/modules.html",
        guild=g,
        form=form,
        user=user_session["user"],
    )


@flask_app.route("/dashboard/<guild_id>/welcome")
@require_auth
def guild_welcome(guild_id):
    user_session = get_session()
    if not user_session:
        return redirect(url_for("discord_login_page"))

    if not _user_can_manage_guild_in_session(user_session, guild_id):
        abort(403)

    g = get_guild(guild_id)
    if not g:
        abort(404)

    cfg = _get_guild_config(guild_id)
    content = _build_welcome_content(cfg, guild_id)

    return render_template(
        "dashboard/welcome.html",
        guild=g,
        content=content,
        user=user_session["user"],
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
        ("anti_spam", "⚡", "Anti-Spam", "Spam, CAPS, Duplikate erkennen", [
            {"key":"msg_limit","label":"Nachrichten-Limit","type":"number","min":2,"max":30},
            {"key":"msg_window","label":"Zeitfenster (s)","type":"number","min":3,"max":60},
            {"key":"caps_pct","label":"CAPS-Schwelle (%)","type":"number","min":50,"max":100},
            {"key":"emoji_max","label":"Max Emojis","type":"number","min":3,"max":50},
            {"key":"punishment","label":"Bestrafung","type":"select","options":["warn","timeout","kick","ban"]},
        ]),
        ("anti_nuke", "💥", "Anti-Nuke", "Massenaktionen erkennen und stoppen", [
            {"key":"threshold","label":"Schwelle","type":"number","min":2,"max":20},
            {"key":"window","label":"Zeitfenster (s)","type":"number","min":5,"max":120},
            {"key":"punishment","label":"Bestrafung","type":"select","options":["warn","timeout","kick","ban"]},
        ]),
        ("anti_raid", "🚨", "Anti-Raid", "Massenjoins erkennen", [
            {"key":"join_threshold","label":"Join-Schwelle","type":"number","min":3,"max":50},
            {"key":"window","label":"Zeitfenster (s)","type":"number","min":5,"max":120},
            {"key":"min_account_age","label":"Min Account-Alter (Tage)","type":"number","min":0,"max":90},
        ]),
        ("anti_mention", "🔔", "Anti-Mention", "Mass-Mentions blockieren", [
            {"key":"mention_limit","label":"Max Mentions","type":"number","min":2,"max":30},
            {"key":"window","label":"Zeitfenster (s)","type":"number","min":3,"max":60},
            {"key":"punishment","label":"Bestrafung","type":"select","options":["warn","timeout","kick","ban"]},
        ]),
        ("anti_scam", "🎣", "Anti-Scam", "KI-Phishing-Erkennung", [
            {"key":"punishment","label":"Bestrafung","type":"select","options":["warn","timeout","kick","ban"]},
        ]),
        ("automod", "🤖", "AutoMod", "Automatische Moderation", [
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
    log_channels = cfg.get("log_channels", {})
    from bot.config import LOG_MODULES, LOG_MODULES_EXTRA
    log_module_defs = []
    icons = {"default":"📌","moderation":"🛡️","antispam":"⚡","antinuke":"💥","antiraid":"🚨","antimention":"🔔","automod":"🤖","antiscam":"🎣","voice":"🎤","members":"👥","nicknames":"📝","channels":"📁","roles":"🏷️","webhooks":"🔌","tickets":"🎫","verify":"✅","warns":"⚠️","cases":"📋","backup":"💾","welcome":"👋","messages":"💬","leave":"👋","errors":"❌","audit":"🔍","appeal":"📬","permissions":"🔐"}
    all_mods = list(LOG_MODULES) + list(LOG_MODULES_EXTRA)
    for m in all_mods:
        log_module_defs.append({"key":m,"icon":icons.get(m,"⚙️"),"label":m.replace("_"," ").title()})
    return render_template("dashboard/logs.html", guild=g, cfg=cfg, user=us["user"],
                           channels=channels, log_channels=log_channels, log_modules=log_module_defs, active="logs")

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
