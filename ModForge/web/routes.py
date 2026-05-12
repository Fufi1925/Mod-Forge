# web/routes.py

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    Response,
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


# =========================================================
# ADMIN
# =========================================================

_admin_cache = {
    "data": None,
    "ts": 0,
}

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
        request.headers.get(
            "X-Forwarded-For",
            request.remote_addr or "?"
        ).split(",")[0].strip()
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
# PUBLIC
# =========================================================

@flask_app.route("/")
def home():

    gc, mc, up, lat = _bot_stats()

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

    guilds_payload.sort(
        key=lambda x: x["members"],
        reverse=True
    )

    db = get_db()

    cases_total = 0
    warns_total = 0

    if bot_ready() and db:

        try:

            cases_total = safe_collection_count(db.cases)

            warns_coll = (
                getattr(db, "warnings", None)
                or getattr(db, "warns", None)
            )

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


# =========================================================
# STATUS
# =========================================================

@flask_app.route("/status")
def status_page():

    gc, mc, uptime_seconds, lat = _bot_stats()

    now = time.time()

    month_start = datetime.datetime.utcnow().replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).timestamp()

    total_month_seconds = max(1, now - month_start)

    uptime_pct = min(
        100.0,
        round((uptime_seconds / total_month_seconds) * 100, 3)
    )

    db = get_db()

    cases_count = 0
    archive_count = 0

    if bot_ready() and db:

        cases_count = safe_collection_count(
            getattr(db, "cases", None)
        )

        archive_count = safe_collection_count(
            getattr(db, "message_archive", None)
        )

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


# =========================================================
# STATIC PAGES
# =========================================================

@flask_app.route("/changelog")
def changelog():
    return render_template(
        "changelog.html",
        versions=VERSIONS
    )


@flask_app.route("/terms")
def terms():
    return render_template(
        "terms.html",
        title="Terms of Service",
        today=str(datetime.date.today())
    )


@flask_app.route("/privacy")
def privacy():
    return render_template(
        "privacy.html",
        title="Privacy Policy",
        today=str(datetime.date.today())
    )


@flask_app.route("/imprint")
def imprint():
    return render_template(
        "imprint.html",
        title="Impressum",
        today=str(datetime.date.today())
    )


# =========================================================
# HEALTH
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

    gc, mc, up, lat = _bot_stats()

    db = get_db()

    cases = 0
    archive = 0

    if bot_ready() and db:

        cases = safe_collection_count(
            getattr(db, "cases", None)
        )

        archive = safe_collection_count(
            getattr(db, "message_archive", None)
        )

    output = (
        f"modforge_uptime_seconds {up}\n"
        f"modforge_latency_ms {lat}\n"
        f"modforge_guilds {gc}\n"
        f"modforge_members {mc}\n"
        f"modforge_cases {cases}\n"
        f"modforge_archive_messages {archive}\n"
    )

    return Response(
        output,
        mimetype="text/plain"
    )


# =========================================================
# LOGIN
# =========================================================

@flask_app.route("/login")
def discord_login_page():

    return render_template(
        "login.html",
        cid=get_client_id()
    )


@flask_app.route("/logout")
def logout():

    session.clear()

    resp = redirect(url_for("home"))

    resp.delete_cookie("modforge_session")

    return resp


# =========================================================
# USER DASHBOARD
# =========================================================

def _user_can_manage_guild_in_session(user_session, guild_id):

    if not user_session or not bot_ready():
        return False

    try:

        bot_guild_ids = {
            str(g.id)
            for g in bot.guilds
        }

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

        bot_guild_ids = {
            str(g.id)
            for g in bot.guilds
        }

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
                    )
                    if g.get("icon")
                    else "https://cdn.discordapp.com/embed/avatars/0.png",
                })

            except Exception as e:
                log.error(f"[MANAGEABLE ERROR] {e}")

    return render_template(
        "dashboard_home.html",
        user=user,
        servers=manageable,
        cid=get_client_id(),
    )
