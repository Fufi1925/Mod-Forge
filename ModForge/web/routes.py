from flask import render_template, request, redirect, url_for, session, jsonify, Response
import datetime
import logging
import urllib.parse
import secrets
import asyncio
import time
import threading
from collections import defaultdict, deque

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
    log,
)
from bot.utils import _run_async

from bot.config import ACTIVITY   # ← das muss so heißen; prüfen Sie den genauen Namen in bot/config.py

log = logging.getLogger("ModForge.Web.Routes")

# ---------- Public Pages ----------
@flask_app.route("/")
def home():
    gc, mc, up, lat = _bot_stats()
    cid = str(bot.user.id) if bot.user else ""
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
    content = """<details open><summary>1. Geltungsbereich</summary><div class="detail-body">
    <p>Diese Nutzungsbedingungen gelten für die Nutzung des Discord-Bots „ModForge". Mit der Einladung erklärt der Administrator sein Einverständnis.</p></div></details>
    <details><summary>2. Erlaubte Nutzung</summary><div class="detail-body">
    <p>ModForge darf ausschließlich für legale Moderations- und Sicherheitszwecke genutzt werden. Jede Form des Missbrauchs ist untersagt.</p></div></details>
    <details><summary>3. Datenspeicherung</summary><div class="detail-body">
    <p>ModForge speichert ausschließlich für den Betrieb notwendige Daten. Details in der <a href="/privacy" style="color:var(--p)">Privacy Policy</a>.</p></div></details>
    <details><summary>4. Haftungsausschluss</summary><div class="detail-body">
    <p>Der Betreiber übernimmt keine Haftung für Schäden durch den Einsatz des Bots.</p></div></details>
    <details><summary>5. Änderungen</summary><div class="detail-body">
    <p>Wir behalten vor, diese Terms jederzeit zu ändern. Fortgesetzte Nutzung = Zustimmung.</p></div></details>"""
    return render_template("terms.html", title="Terms of Service", today=str(datetime.date.today()), content=content)

@flask_app.route("/privacy")
def privacy():
    content = """<details open><summary>1. Verantwortlicher</summary><div class="detail-body">
    <p>Betreiber: ModForge / BotForge. Kontakt über <a href="https://discord.gg/gwryX3dbkt" style="color:var(--p)" target="_blank">Support-Server</a>.</p></div></details>
    <details><summary>2. Gespeicherte Daten</summary><div class="detail-body">
    <p><strong>Server-Konfiguration:</strong> Guild-ID, Einstellungen, Rollen-/Kanal-IDs.<br>
    <strong>Moderationsdaten:</strong> User-ID, Moderator-ID, Zeitstempel, Gründe, Case-IDs.<br>
    <strong>Opt-in Nachrichten-Archiv:</strong> Inhalte max. 48 Stunden (TTL-Index).<br>
    <strong>OAuth2:</strong> Discord Username und Avatar für Dashboard-Session (nur im RAM).</p></div></details>
    <details><summary>3. Rechte der Nutzer</summary><div class="detail-body">
    <p>Auskunft, Berichtigung, Löschung, Einschränkung und Widerspruch. Anfragen via Discord.</p></div></details>
    <details><summary>4. Sicherheit</summary><div class="detail-body">
    <p>MongoDB Atlas, TLS 1.3, Server in EU. Keine Weitergabe an Dritte.</p></div></details>"""
    return render_template("privacy.html", title="Privacy Policy", today=str(datetime.date.today()), content=content)

@flask_app.route("/imprint")
def imprint():
    content = """<h2>Diensteanbieter</h2>
    <p><strong>ModForge Security</strong><br>c/o BotForge · Deutschland</p>
    <h2>Kontakt</h2>
    <p>Discord: <a href="https://discord.gg/gwryX3dbkt" target="_blank" style="color:var(--p)">ModForge Support-Server</a></p>
    <h2>EU-Streitschlichtung</h2>
    <p><a href="https://ec.europa.eu/consumers/odr/" target="_blank" style="color:var(--p)">https://ec.europa.eu/consumers/odr/</a></p>"""
    return render_template("imprint.html", title="Impressum", content=content)

@flask_app.route("/healthz")
def healthz():
    from bot.bot import bot
    return jsonify({"ok": True, "bot_ready": bot.is_ready(), "ts": datetime.datetime.utcnow().isoformat() + "Z"})

@flask_app.route("/metrics")
def metrics():
    gc, mc, up, lat = _bot_stats()
    ct = _run_async(bot.db.cases.count_documents({})) if bot.is_ready() else 0
    at = _run_async(bot.db.message_archive.count_documents({})) if bot.is_ready() else 0
    return Response(
        f"modforge_uptime_seconds {up}\nmodforge_latency_ms {lat}\n"
        f"modforge_guilds {gc}\nmodforge_members {mc}\n"
        f"modforge_cases {ct}\nmodforge_archive_messages {at}\n",
        mimetype="text/plain",
    )

# ---------- Discord OAuth2 ----------
@flask_app.route("/login")
def discord_login_page():
    if not DISCORD_CLIENT_ID:
        return render_template("login.html", error="CLIENT_ID nicht konfiguriert.", info=None, admin_available=bool(ADMIN_PASSWORD))
    if not DISCORD_CLIENT_SECRET or not OAUTH2_REDIRECT:
        return render_template("login.html", error="CLIENT_SECRET oder OAUTH2_REDIRECT fehlt.", info=None, admin_available=bool(ADMIN_PASSWORD))
    return render_template("login.html", error=None, info=None, admin_available=bool(ADMIN_PASSWORD))

@flask_app.route("/auth/discord")
def auth_discord():
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET or not OAUTH2_REDIRECT:
        return redirect(url_for("discord_login_page"))
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
    if not code or state != session.get("oauth_state"):
        return redirect(url_for("discord_login_page"))
    token_data = _discord_api_call("/oauth2/token", method="POST", data={
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": OAUTH2_REDIRECT,
    })
    if not token_data or "access_token" not in token_data:
        return render_template("login.html", error="OAuth2 fehlgeschlagen.", info=None, admin_available=bool(ADMIN_PASSWORD))
    access_token = token_data["access_token"]
    user = _discord_api_call("/users/@me", token=access_token)
    guilds = _discord_api_call("/users/@me/guilds", token=access_token) or []
    if not user or "id" not in user:
        return render_template("login.html", error="Nutzerdaten konnten nicht abgerufen werden.", info=None, admin_available=bool(ADMIN_PASSWORD))
    session.permanent = True
    session["discord_user"] = user
    session["user_guilds"] = guilds
    session["access_token"] = access_token
    ACTIVITY.push("oauth_login", f"Discord-Login: {user.get('username', '?')} ({user.get('id', '')})")
    return redirect(url_for("user_dash_home"))

@flask_app.route("/logout")
def logout():
    session.pop("discord_user", None)
    session.pop("user_guilds", None)
    session.pop("access_token", None)
    return redirect(url_for("home"))

# ---------- User Dashboard ----------
@flask_app.route("/dashboard")
def user_dash_home():
    user = _get_session_user()
    if not user:
        return redirect(url_for("discord_login_page"))
    servers = _get_user_guilds_with_bot(session.get("user_guilds", []))
    cid = str(bot.user.id) if bot.user else ""
    return render_template("dashboard_home.html", user=user, servers=servers, cid=cid)

@flask_app.route("/dashboard/<guild_id>")
def user_dash_guild_redir(guild_id):
    return redirect(url_for("user_dash_guild", guild_id=guild_id, section="overview"))

@flask_app.route("/dashboard/<guild_id>/<section>")
def user_dash_guild(guild_id, section):
    user = _get_session_user()
    if not user or not _user_can_manage_guild(guild_id):
        return redirect(url_for("user_dash_home"))
    cfg = _get_guild_config(guild_id)
    guild_name = f"Server {guild_id}"
    if bot.is_ready():
        g = bot.get_guild(int(guild_id))
        if g:
            guild_name = g.name
    titles = {
        "overview": "Übersicht", "welcome": "Welcome & Leave",
        "antispam": "Anti-Spam", "antinuke": "Anti-Nuke", "antiraid": "Anti-Raid",
        "antimention": "Anti-Mention", "antiscam": "Anti-Scam", "automod": "AutoMod",
        "verify": "Verifizierung", "tickets": "Ticket-System", "autorole": "Auto-Rolle",
        "logs": "Log-Kanäle", "warns": "Warn-System",
    }
    page_title = titles.get(section, section.title())
    overview_content = _build_overview(cfg, guild_id) if section == "overview" else ""
    welcome_content = _build_welcome_content(cfg, guild_id) if section == "welcome" else ""
    module_content = _build_module_form(section, cfg, guild_id) if section not in ("overview", "welcome") else ""
    return render_template(
        "dashboard_guild.html",
        user=user,
        guild_id=guild_id,
        guild_name=guild_name,
        section=section,
        page_title=page_title,
        overview_content=overview_content,
        welcome_content=welcome_content,
        module_content=module_content,
    )

@flask_app.route("/dashboard/<guild_id>/api/save", methods=["POST"])
def user_dash_save(guild_id):
    if not _user_can_manage_guild(guild_id):
        return jsonify({"error": "Insufficient permissions"}), 403
    data = request.get_json()
    module = data.get("module")
    settings = data.get("settings")
    if not module or not isinstance(settings, dict):
        return jsonify({"error": "Invalid data"}), 400
    if bot.is_ready():
        try:
            cfg = _run_async(bot.db.aget_config(int(guild_id))) or {}
            if module in cfg and isinstance(cfg[module], dict):
                cfg[module].update(settings)
            else:
                cfg[module] = settings
            _run_async(bot.db.set_config(int(guild_id), cfg))
            return jsonify({"ok": True})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500
    return jsonify({"error": "Bot not ready"}), 503

# ---------- Admin Panel ----------
_login_attempts = defaultdict(deque)
_login_lock = threading.Lock()

def _ip():
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip())

def _rate_blocked(ip):
    now = time.time()
    with _login_lock:
        dq = _login_attempts[ip]
        while dq and now - dq[0] > 300:
            dq.popleft()
        return len(dq) >= 8

def _record_fail(ip):
    with _login_lock:
        _login_attempts[ip].append(time.time())

@flask_app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not ADMIN_PASSWORD:
        return render_template("admin_login.html", error="ADMIN_PASSWORD nicht gesetzt.")
    err = None
    ip = _ip()
    if request.method == "POST":
        if _rate_blocked(ip):
            err = "Zu viele Versuche. Bitte 5 Minuten warten."
        else:
            u = (request.form.get("username") or "").strip()
            p = (request.form.get("password") or "")
            if secrets.compare_digest(u, ADMIN_USERNAME) and secrets.compare_digest(p, ADMIN_PASSWORD):
                session.permanent = True
                session["admin"] = True
                ACTIVITY.push("admin_login", f"Admin-Login von {ip}")
                return redirect(url_for("admin_dashboard"))
            else:
                _record_fail(ip)
                err = "Falsche Zugangsdaten."
    return render_template("admin_login.html", error=err)

@flask_app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

@flask_app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    return render_template("admin_dashboard.html")

@flask_app.route("/admin/api/state")
def admin_api_state():
    if not session.get("admin") or not bot.is_ready():
        return jsonify({})
    guilds_payload = []
    mt = 0
    for g in bot.guilds:
        mt += g.member_count or 0
        guilds_payload.append({
            "id": g.id, "name": g.name, "member_count": g.member_count or 0,
            "owner": str(g.owner) if g.owner else str(g.owner_id),
            "created": g.created_at.strftime("%Y-%m-%d") if g.created_at else "",
        })
    guilds_payload.sort(key=lambda x: x["member_count"], reverse=True)
    ct = _run_async(bot.db.cases.count_documents({})) or 0
    at = _run_async(bot.db.message_archive.count_documents({})) or 0
    raw_cases = _run_async(bot.db.cases.find({}).sort("created_at", -1).limit(20).to_list(20)) or []
    recent_cases = [{
        "case_id": c.get("case_id"), "guild_id": c.get("guild_id"),
        "user_id": c.get("user_id"), "action": c.get("action"),
        "reason": (c.get("reason") or "")[:160],
        "created_at": c["created_at"].strftime("%Y-%m-%d %H:%M:%S") if c.get("created_at") else "",
    } for c in raw_cases]
    raw_msgs = _run_async(bot.db.message_archive.find({}).sort("timestamp", -1).limit(25).to_list(25)) or []
    recent_messages = [{
        "guild_id": m.get("guild_id"), "channel_id": m.get("channel_id"),
        "user_id": m.get("user_id"), "content": (m.get("content") or ""),
        "deleted": bool(m.get("deleted")),
        "timestamp": m["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if m.get("timestamp") else "",
    } for m in raw_msgs]
    raw_ev = _run_async(bot.db.aget_recent_guild_events(limit=30)) or []
    guild_events = [{
        "guild_name": e.get("guild_name", "?"), "event": e.get("event"),
        "timestamp": e["timestamp"].strftime("%H:%M:%S") if e.get("timestamp") else "",
    } for e in raw_ev]
    return jsonify({
        "stats": {
            "guild_count": len(guilds_payload),
            "member_total": mt,
            "uptime_s": (time.time() - bot.start_time),
            "latency_ms": round(bot.latency * 1000, 1),
            "cases_total": ct,
            "archive_total": at,
        },
        "guilds": guilds_payload[:50],
        "guild_events": guild_events,
        "activity": ACTIVITY.snapshot(100),
        "recent_messages": recent_messages,
        "recent_cases": recent_cases,
    })
