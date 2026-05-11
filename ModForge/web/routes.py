# web/routes.py
from flask import render_template, request, redirect, url_for, session, jsonify, Response
import datetime
import logging
import time
import threading
from collections import defaultdict, deque
from functools import wraps

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
    return render_template("terms.html", title="Terms of Service", today=str(datetime.date.today()))

@flask_app.route("/privacy")
def privacy():
    return render_template("privacy.html", title="Privacy Policy", today=str(datetime.date.today()))

@flask_app.route("/imprint")
def imprint():
    return render_template("imprint.html", title="Impressum", today=str(datetime.date.today()))

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

# ---------- LOGIN PAGE (leitet zu OAuth2) ----------
@flask_app.route("/login")
def discord_login_page():
    """Einfache Login‑Seite, verlinkt auf den Discord‑OAuth2‑Flow."""
    cid = str(bot.user.id) if bot.user else str(DISCORD_CLIENT_ID or "")
    return render_template("login.html", cid=cid)

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
            acc = safe_async(bot.db.server_accounts.find_one({'guild_name': guild_name}))
            if acc and check_password_hash(acc['password_hash'], password):
                session['server_guild_id'] = str(acc['guild_id'])
                return redirect(url_for('user_dash_guild', guild_id=str(acc['guild_id']), section='overview'))
            error = 'Ungültige Zugangsdaten.'
    return render_template('server_login.html', error=error)

# ---------- LOGOUT ----------
@flask_app.route("/logout")
def logout():
    session.clear()
    # Auch den Auth‑Cookie löschen
    resp = redirect(url_for("home"))
    resp.delete_cookie("modforge_session")
    return resp

# ---------- DASHBOARD (geschützt mit require_auth) ----------
@flask_app.route("/dashboard")
@require_auth
def user_dash_home():
    """Dashboard‑Startseite – nur für eingeloggte Discord‑Nutzer."""
    user_session = get_session()
    if not user_session:
        return redirect(url_for("discord_login_page"))
    user = user_session["user"]
    raw_guilds = user_session.get("guilds", [])

    # Filtere Server, die der User verwalten kann UND auf denen der Bot ist
    manageable = []
    if bot.is_ready():
        bot_guild_ids = {str(g.id) for g in bot.guilds}
        for g in raw_guilds:
            permissions = int(g.get("permissions", 0))
            if g.get("owner") or (permissions & 0x8) or (permissions & 0x20):
                if str(g["id"]) in bot_guild_ids:
                    manageable.append({
                        "id": str(g["id"]),
                        "name": g["name"],
                        "icon": f"https://cdn.discordapp.com/icons/{g['id']}/{g.get('icon')}.png?size=128" if g.get("icon") else "https://cdn.discordapp.com/embed/avatars/0.png",
                        "member_count": None,
                    })
    cid = str(bot.user.id) if bot.user else str(DISCORD_CLIENT_ID or "")
    return render_template("dashboard_home.html", user=user, servers=manageable, cid=cid)

@flask_app.route("/dashboard/<guild_id>/<section>")
def user_dash_guild(guild_id, section):
    """Guild‑Detailseite – Zugriff über Discord‑Login oder Server‑Login."""
    user_session = get_session()

    # Server‑Login hat Vorrang
    if session.get('server_guild_id') and str(session['server_guild_id']) == guild_id:
        user = {"username": f"Server {guild_id}", "id": guild_id, "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png"}
    # Discord‑Login
    elif user_session and _user_can_manage_guild_in_session(user_session, guild_id):
        user = user_session["user"]
    else:
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
        user=user,
        guild_id=guild_id,
        guild_name=guild_name,
        section=section,
        overview_content=overview_content,
        welcome_content=welcome_content,
        module_content=module_content,
    )

def _user_can_manage_guild_in_session(user_session, guild_id):
    """Prüft, ob der Discord‑Benutzer eine bestimmte Guild verwalten darf."""
    if not user_session or not bot.is_ready():
        return False
    bot_guild_ids = {str(g.id) for g in bot.guilds}
    for g in user_session.get("guilds", []):
        if str(g["id"]) != str(guild_id):
            continue
        permissions = int(g.get("permissions", 0))
        if not (g.get("owner") or (permissions & 0x8) or (permissions & 0x20)):
            return False
        if str(g["id"]) not in bot_guild_ids:
            return False
        return True
    return False

@flask_app.route("/dashboard/<guild_id>/api/save", methods=["POST"])
def user_dash_save(guild_id):
    user_session = get_session()
    server_allowed = (str(session.get('server_guild_id')) == guild_id)
    discord_allowed = (user_session and _user_can_manage_guild_in_session(user_session, guild_id))

    if not (server_allowed or discord_allowed):
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
            if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
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
            "latency": bot.latency * 1000 if bot.latency else 0,
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
    from werkzeug.security import generate_password_hash, check_password_hash
    msg = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            guild_id = int(request.form.get('guild_id'))
            safe_async(bot.db.server_accounts.delete_one({'guild_id': guild_id}))
            msg = 'Account gelöscht.'
        else:
            guild_id = int(request.form.get('guild_id'))
            guild_name = (request.form.get('guild_name') or '').strip()
            password = request.form.get('password') or ''
            if not guild_name or not password:
                msg = 'Name und Passwort erforderlich.'
            else:
                pw_hash = generate_password_hash(password)
                safe_async(bot.db.server_accounts.update_one(
                    {'guild_id': guild_id},
                    {'$set': {'guild_id': guild_id, 'guild_name': guild_name, 'password_hash': pw_hash}},
                    upsert=True
                ))
                msg = 'Account gespeichert.'
    accounts = safe_async(bot.db.server_accounts.find().to_list(100)) or []
    return render_template('admin_accounts.html', accounts=accounts, msg=msg)

# ---------- LIVE ACTIVITY PAGE ----------
@flask_app.route('/live')
def live_activity():
    return render_template('live.html')

@flask_app.route('/live/api/activity')
def live_api_activity():
    return jsonify(ACTIVITY.snapshot(50))
