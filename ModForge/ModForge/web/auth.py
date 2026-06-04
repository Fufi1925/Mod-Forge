# web/auth.py
import os
import time
import json
import secrets
import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from functools import wraps

from flask import Blueprint, request, redirect, make_response, session as flask_session

log = logging.getLogger("ModForge.Auth")

# Umgebungsvariablen
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DASHBOARD_BASE_URL = os.getenv(
    "DASHBOARD_BASE_URL", "http://mod-forge.up.railway.app"
).rstrip("/")

REDIRECT_URI = f"{DASHBOARD_BASE_URL}/dashboard/auth/callback"
DISCORD_API = "https://discord.com/api/v10"
SESSION_COOKIE = "modforge_session"

# In-Memory Session Store
sessions = {}

auth_bp = Blueprint("auth", __name__, template_folder="templates")


def _make_session_id():
    return secrets.token_hex(32)


def _api_request(url, method="GET", data=None, headers=None):
    """HTTP-Request mit User-Agent (Discord blockiert ohne)."""
    headers = headers or {}
    headers["User-Agent"] = "ModForge-Dashboard (https://mod-forge.up.railway.app, 2.0)"

    body = None
    if data is not None:
        body = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        log.error(f"Discord API {e.code}: {error_body[:500]}")
        raise Exception(f"HTTP {e.code}: {error_body[:200]}")
    except URLError as e:
        log.error(f"URL Error: {e.reason}")
        raise Exception(f"URL error: {e.reason}")


@auth_bp.route("/dashboard/login")
def login():
    """Leitet zu Discord OAuth2 weiter."""
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        log.error(
            f"OAuth not configured: ID={bool(DISCORD_CLIENT_ID)} SECRET={bool(DISCORD_CLIENT_SECRET)}"
        )
        return (
            "Dashboard auth not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET.",
            503,
        )

    state = secrets.token_urlsafe(16)
    flask_session["oauth_state"] = state

    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "prompt": "consent",
        "state": state,
    }
    auth_url = f"https://discord.com/oauth2/authorize?{urlencode(params)}"
    log.info(f"OAuth2 login redirect → {auth_url[:120]}...")
    return redirect(auth_url, code=302)


@auth_bp.route("/dashboard/auth/callback")
def callback():
    """Verarbeitet den OAuth2-Callback von Discord."""
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    error_desc = request.args.get("error_description", "")
    session_state = flask_session.pop("oauth_state", None)

    # User hat abgelehnt
    if error:
        log.warning(f"OAuth2 denied: {error} – {error_desc}")
        return redirect(f"/login?error=Login abgebrochen: {error_desc or error}")

    # State-Prüfung
    if not code:
        log.warning("OAuth2 callback: kein code")
        return redirect(
            "/login?error=Kein Autorisierungs-Code erhalten. Bitte erneut versuchen."
        )

    if state != session_state:
        log.warning(f"OAuth2 state mismatch: got={state}, expected={session_state}")
        return redirect("/login?error=Session abgelaufen. Bitte erneut versuchen.")

    # --- Token abrufen ---
    try:
        log.info(f"Token exchange: redirect_uri={REDIRECT_URI}")
        token_data = _api_request(
            f"{DISCORD_API}/oauth2/token",
            method="POST",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        )
    except Exception as e:
        log.error(f"Token exchange failed: {e}")
        return redirect(f"/login?error=Token-Fehler: {str(e)[:100]}")

    access_token = token_data.get("access_token")
    if not access_token:
        log.error(f"No access_token in response: {token_data}")
        err_desc = token_data.get(
            "error_description", token_data.get("error", "Unbekannt")
        )
        return redirect(f"/login?error=Discord Token-Fehler: {err_desc}")

    # --- User-Profil laden ---
    try:
        user = _api_request(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except Exception as e:
        log.error(f"User fetch failed: {e}")
        return redirect("/login?error=Profil konnte nicht geladen werden.")

    # --- Serverliste laden ---
    try:
        guilds = _api_request(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except Exception as e:
        log.warning(f"Guilds fetch failed (continuing without): {e}")
        guilds = []

    # Avatar-URL
    avatar_hash = user.get("avatar")
    user_id = user.get("id", "0")
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"
        if avatar_hash
        else f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"
    )

    # Session erstellen
    session_id = _make_session_id()
    sessions[session_id] = {
        "access_token": access_token,
        "created_at": time.time(),
        "user": {
            "id": user_id,
            "username": user.get("username", "Discord User"),
            "global_name": user.get("global_name"),
            "avatar_url": avatar_url,
        },
        "guilds": guilds if isinstance(guilds, list) else [],
    }

    log.info(
        f"Login OK: {user.get('username')} ({user_id}), {len(guilds) if isinstance(guilds, list) else 0} guilds"
    )

    # Cookie setzen
    resp = make_response(redirect("/dashboard"))
    resp.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        path="/",
        secure=request.is_secure,
        max_age=7 * 24 * 3600,
    )
    return resp


@auth_bp.route("/dashboard/logout")
def logout():
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        sessions.pop(sid, None)
    resp = make_response(redirect("/"))
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


def get_session():
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    session = sessions.get(sid)
    if not session or time.time() - session["created_at"] > 7 * 24 * 3600:
        sessions.pop(sid, None)
        return None
    return session


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_session():
            return redirect("/dashboard/login")
        return f(*args, **kwargs)

    return wrapper
