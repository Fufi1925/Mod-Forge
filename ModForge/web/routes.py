from flask import render_template, request, redirect, url_for, session, jsonify, Response
import datetime
import logging
import urllib.parse
import secrets
import time
import threading
from collections import defaultdict, deque
from functools import wraps

from werkzeug.security import check_password_hash, generate_password_hash

from .app import flask_app
from .auth import (
    _discord_api_call,
    _get_user_guilds_with_bot,
    _get_session_user,
    _user_can_manage_guild,
)
from .helpers import (
    _bot_stats,
    _get_guild_config,
    _build_overview,
    _build_module_form,
    _build_welcome_content,
)
from .config import (
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    OAUTH2_REDIRECT,
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
    log,
)
from bot.utils import _run_async

log = logging.getLogger("ModForge.Web.Routes")

# ---------- SAFE ASYNC ----------
def safe_async(coro, default=None):
    try:
        return _run_async(coro)
    except Exception as e:
        log.error(f"Async error: {e}")
        return default

# ---------- CACHE ----------
_admin_cache = {"data": None, "ts": 0}

# ---------- ADMIN CHECK ----------
def admin_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return decorated

# ---------- Public Pages ----------
@flask_app.route("/")
def home():
    gc, mc, up, lat = _bot_stats()
    cid = str(bot.user.id) if bot.user else str(DISCORD_CLIENT_ID or "")
    return render_template(
        "index.html",
        cid=cid,
        gc=f"{gc:,}",
        mc=f"{mc:,}",
        gc_raw=gc,
        mc_raw=mc,
        up=up,
        lat=round(lat),
        features=FEATURES,
        log_mods=LOG_MODS,
        cmds_preview=CMDS_PREVIEW,
    )

@flask_app.route("/status")
def status_page():
    gc, mc, up, lat = _bot_stats()
    return render_template("status.html", gc=gc, mc=mc, up_s=up, lat=round(lat))

@flask_app.route("/changelog")
def changelog():
    return render_template("changelog.html", versions=VERSIONS)

@flask_app.route("/terms")
def terms():
    return render_template("terms.html", title="Terms of Service", today=str(datetime.date.today()), content="Terms...")

@flask_app.route("/privacy")
def privacy():
    return render_template("privacy.html", title="Privacy Policy", today=str(datetime.date.today()), content="Privacy...")

@flask_app.route("/imprint")
def imprint():
    return render_template("imprint.html", title="Impressum", content="Imprint...")

@flask_app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "bot_ready": bot.is_ready(), "ts": datetime.datetime.utcnow().isoformat() + "Z"})

@flask_app.route("/metrics")
def metrics():
    gc, mc, up, lat = _bot_stats()
    try:
        ct = safe_async(bot.db.cases.count_documents({})) if bot.is_ready() and bot.db else 0
        at = safe_async(bot.db.message_archive.count_documents({})) if bot.is_ready() and bot.db else 0
    except Exception:
        ct, at = 0, 0

    return Response(
        f"modforge_uptime_seconds {up}\n"
        f"modforge_latency_ms {lat}\n"
        f"modforge_guilds {gc}\n"
        f"modforge_members {mc}\n"
        f"modforge_cases {ct}\n"
        f"modforge_archive_messages {at}\n",
        mimetype="text/plain",
    )

# ---------- OAuth ----------
@flask_app.route("/login")
def discord_login_page():
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET or not OAUTH2_REDIRECT:
        return render_template("login.html", error="OAuth nicht konfiguriert.", info=None, admin_available=bool(ADMIN_PASSWORD))
    return render_template("login.html", error=None, info=None, admin_available=bool(ADMIN_PASSWORD))

@flask_app.route("/auth/discord")
def auth_discord():
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    params = urllib.parse.urlencode({
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": OAUTH2_REDIRECT,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
    })
    return redirect(f"https://discord.com/oauth2/authorize?{params}")

@flask_app.route("/callback")
def oauth_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    session_state = session.pop("oauth_state", None)

    if not code or state != session_state:
        return redirect(url_for("discord_login_page"))

    token_data = _discord_api_call("/oauth2/token", method="POST", data={
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": OAUTH2_REDIRECT,
    })

    if not token_data or "access_token" not in token_data:
        return render_template("login.html", error="OAuth fehlgeschlagen.", info=None, admin_available=bool(ADMIN_PASSWORD))

    access_token = token_data["access_token"]
    user = _discord_api_call("/users/@me", token=access_token)
    guilds = _discord_api_call("/users/@me/guilds", token=access_token) or []

    if not user or "id" not in user:
        return render_template("login.html", error="User fetch failed.", info=None, admin_available=bool(ADMIN_PASSWORD))

    session.permanent = True
    session["discord_user"] = user
    session["user_guilds"] = guilds
    session["access_token"] = access_token

    ACTIVITY.push("oauth_login", f"{user.get('username')} ({user.get('id')})")

    return redirect(url_for("user_dash_home"))

# ---------- SERVER LOGIN (eigenes System) ----------
@flask_app.route('/server-login', methods=['GET', 'POST'])
def server_login():
    error = None
    if request.method == 'POST':
        guild_name = (request.form.get('guild_name') or '').strip()
        password = request.form.get('password') or ''
        if not guild_name or not password:
            error = 'Bitte Server‑Name und Passwort eingeben.'
        else:
            acc = safe_async(bot.db.db.server_accounts.find_one({'guild_name': guild_name}))
            if acc and check_password_hash(acc['password_hash'], password):
                session['server_guild_id'] = acc['guild_id']
                return redirect(url_for('user_dash_guild', guild_id=str(acc['guild_id']), section='overview'))
            error = 'Ungültige Zugangsdaten.'
    return render_template('server_login.html', error=error)

# ---------- Logout ----------
@flask_app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# ---------- Dashboard ----------
@flask_app.route("/dashboard")
def user_dash_home():
    # Nur für Discord Login
    user = _get_session_user()
    if not user:
        return redirect(url_for("discord_login_page"))

    servers = _get_user_guilds_with_bot(session.get("user_guilds", []))
    cid = str(bot.user.id) if bot.user else str(DISCORD_CLIENT_ID or "")

    return render_template("dashboard_home.html", user=user, servers=servers, cid=cid)

@flask_app.route("/dashboard/<guild_id>/<section>")
def user_dash_guild(guild_id, section):
    # Zugriff via Server-Login oder Discord-Login prüfen
    user = _get_session_user()
    if session.get('server_guild_id') and str(session['server_guild_id']) == guild_id:
        # Server-Login: Zugriff gewähren, user aus Session holen (kann None sein)
        user = session.get("discord_user")  # kann auch None sein, dann ohne Discord-User
    elif user and _user_can_manage_guild(guild_id):
        # Discord-Login mit Manage-Server-Recht
        pass
    else:
        # Keine Berechtigung -> zum Login
        if session.get('server_guild_id'):
            return redirect(url_for('server_login'))
        return redirect(url_for("discord_login_page"))

    cfg = _get_guild_config(guild_id)

    guild_name = f"Server {guild_id}"
    if bot.is_ready():
        g = bot.get_guild(int(guild_id))
        if g:
            guild_name = g.name

    overview_content = _build_overview(cfg, guild_id) if section == "overview" else ""
    welcome_content = _build_welcome_content(cfg, guild_id) if section == "welcome" else ""
    module_content = _build_module_form(section, cfg, guild_id) if section not in ("overview", "welcome") else ""

    return render_template(
        "dashboard_guild.html",
        user=user or {"username": guild_name, "id": guild_id},
        guild_id=guild_id,
        guild_name=guild_name,
        section=section,
        overview_content=overview_content,
        welcome_content=welcome_content,
        module_content=module_content,
    )

@flask_app.route("/dashboard/<guild_id>/api/save", methods=["POST"])
def user_dash_save(guild_id):
    # Berechtigung wie oben prüfen
    user = _get_session_user()
    if not (session.get('server_guild_id') == guild_id or (user and _user_can_manage_guild(guild_id))):
        return jsonify({"error": "no permission"}), 403

    data = request.get_json()
    module = data.get("module")
    settings = data.get("settings")

    if not module or not isinstance(settings, dict):
        return jsonify({"error": "invalid"}), 400

    if bot.is_ready() and bot.db:
        try:
            cfg = safe_async(bot.db.aget_config(int(guild_id))) or {}
            cfg[module] = {**cfg.get(module, {}), **settings}
            safe_async(bot.db.set_config(int(guild_id), cfg))
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "bot offline"}), 503

# ---------- Admin ----------
_login_attempts = defaultdict(deque)
_login_lock = threading.Lock()

def _ip():
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip())

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

@flask_app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not ADMIN_PASSWORD:
        return "Admin disabled"

    ip = _ip()
    err = None

    if request.method == "POST":
        if _blocked(ip):
            err = "Too many tries"
        else:
            u = request.form.get("username", "")
            p = request.form.get("password", "")

            if secrets.compare_digest(u, ADMIN_USERNAME) and secrets.compare_digest(p, ADMIN_PASSWORD):
                session["admin"] = True
                return redirect(url_for("admin_dashboard"))
            else:
                _fail(ip)
                err = "Wrong login"

    return render_template("admin_login.html", error=err)

@flask_app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    return render_template("admin_dashboard.html")

def build_admin_data():
    guilds_payload = []
    mt = 0

    for g in bot.guilds:
        mt += g.member_count or 0
        guilds_payload.append({
            "id": g.id,
            "name": g.name,
            "member_count": g.member_count or 0,
        })

    ct = safe_async(bot.db.cases.count_documents({}))
    at = safe_async(bot.db.message_archive.count_documents({}))

    return {
        "stats": {
            "guild_count": len(guilds_payload),
            "member_total": mt,
            "uptime": time.time() - bot.start_time,
            "latency": bot.latency * 1000,
            "cases": ct,
            "archive": at,
        },
        "guilds": guilds_payload[:50],
    }

@flask_app.route("/admin/api/state")
def admin_api_state():
    if not session.get("admin") or not bot.is_ready():
        return jsonify({})

    if time.time() - _admin_cache["ts"] < 5:
        return jsonify(_admin_cache["data"])

    data = build_admin_data()
    _admin_cache["data"] = data
    _admin_cache["ts"] = time.time()

    return jsonify(data)

# ---------- ADMIN: Server-Accounts verwalten ----------
@flask_app.route('/admin/accounts', methods=['GET', 'POST'])
@admin_required
def admin_accounts():
    msg = None
    if request.method == 'POST':
        if request.form.get('action') == 'delete':
            guild_id = int(request.form.get('guild_id'))
            await bot.db.db.server_accounts.delete_one({'guild_id': guild_id})
            msg = 'Account gelöscht.'
        else:
            guild_id = int(request.form.get('guild_id'))
            guild_name = (request.form.get('guild_name') or '').strip()
            password = request.form.get('password') or ''
            if not guild_name or not password:
                msg = 'Name und Passwort erforderlich.'
            else:
                pw_hash = generate_password_hash(password)
                await bot.db.db.server_accounts.update_one(
                    {'guild_id': guild_id},
                    {'$set': {'guild_id': guild_id, 'guild_name': guild_name, 'password_hash': pw_hash}},
                    upsert=True
                )
                msg = 'Account gespeichert.'
    accounts = safe_async(bot.db.db.server_accounts.find().to_list(100)) or []
    return render_template('admin_accounts.html', accounts=accounts, msg=msg)
