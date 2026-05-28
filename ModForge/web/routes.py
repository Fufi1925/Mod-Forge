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
        lat=round(lat),
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
        lat=round(lat),
        uptime_pct=f"{uptime_pct:.3f}",
        api_latency=round(lat),
        guild_count=gc,
        shard_count=getattr(bot, "shard_count", 1),
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
        api_latency=round(lat),
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
        api_latency=round(lat),
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
        lat=round(lat),
        cases_count=cases_count,
        archive_count=archive_count,
        bot_ready=bot_ready(),
        shard_count=getattr(bot, "shard_count", 1),
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

    return render_template(
        "admin/guild_detail.html",
        guild=g,
        cases=cases,
        config=_get_guild_config(guild_id),
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
        lat=round(lat),
        uptime_pct=f"{uptime_pct:.3f}",
        cases_count=cases_count,
        archive_count=archive_count,
        shard_count=getattr(bot, "shard_count", 1),
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

@flask_app.route("/api/guild/<guild_id>/noprefix", methods=["POST"])
@require_auth
def api_noprefix(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    from .helpers import _get_guild_config
    from bot.utils import _run_async
    cfg = _get_guild_config(guild_id)
    enabled = request.json.get("enabled", False)
    cfg["no_prefix"] = bool(enabled)
    try:
        _run_async(bot.db.set_config(int(guild_id), cfg))
    except Exception as e:
        log.error(f"[NOPREFIX API ERROR] {e}")
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "no_prefix": cfg["no_prefix"]})

@flask_app.route("/api/guild/<guild_id>/settings", methods=["GET"])
@require_auth
def api_guild_settings(guild_id):
    user_session = get_session()
    if not user_session or not _user_can_manage_guild_in_session(user_session, guild_id):
        return jsonify({"error": "forbidden"}), 403
    from .helpers import _get_guild_config
    cfg = _get_guild_config(guild_id)
    return jsonify({
        "no_prefix": cfg.get("no_prefix", False),
        "report_channel": cfg.get("report_channel"),
        "auto_responses": cfg.get("auto_responses", []),
        "warn_decay": cfg.get("warn_decay", {}),
        "invite_tracking": cfg.get("invite_tracking", {}),
    })

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
