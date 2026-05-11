
# web/auth.py
import os
import time
import json
import secrets
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from functools import wraps

from flask import Blueprint, request, redirect, make_response, session as flask_session

# Umgebungsvariablen
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "http://mod-forge.up.railway.app").rstrip("/")

REDIRECT_URI = f"{DASHBOARD_BASE_URL}/dashboard/auth/callback"
DISCORD_API = "https://discord.com/api/v10"
SESSION_COOKIE = "modforge_session"

# In‑Memory Sessions
sessions = {}

auth_bp = Blueprint("auth", __name__, template_folder="templates")


def _make_session_id():
    return secrets.token_hex(32)


def _api_request(url, method="GET", data=None, headers=None):
    headers = headers or {}
    if data is not None:
        data = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        raise Exception(f"HTTP {e.code}: {error_body[:200]}")
    except URLError as e:
        raise Exception(f"URL error: {e.reason}")


@auth_bp.route("/dashboard/login")
def login():
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        return "Dashboard auth not configured.", 503

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
    return redirect(auth_url, code=302)


@auth_bp.route("/dashboard/auth/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")
    session_state = flask_session.pop("oauth_state", None)

    if not code or state != session_state:
        return redirect("/dashboard/login?error=invalid_state")

    try:
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
        access_token = token_data["access_token"]

        user = _api_request(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        guilds = _api_request(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except Exception as e:
        return redirect(f"/dashboard/login?error=api_error&detail={e}")

    avatar_hash = user.get("avatar")
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar_hash}.png?size=128"
        if avatar_hash
        else "https://cdn.discordapp.com/embed/avatars/0.png"
    )

    session_id = _make_session_id()
    sessions[session_id] = {
        "access_token": access_token,
        "created_at": time.time(),
        "user": {
            "id": user["id"],
            "username": user.get("username", "Discord User"),
            "global_name": user.get("global_name"),
            "avatar_url": avatar_url,
        },
        "guilds": guilds,
    }

    resp = make_response(redirect("/dashboard"))
    resp.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        path="/",          # ← HIER WAR DER FEHLER! Cookie für gesamte Domain
        secure=False,
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


# ---------- Hilfsfunktionen ----------
def get_session():
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    session = sessions.get(sid)
    if not session or time.time() - session["created_at"] > 7 * 24 * 3600:
        if sid in sessions:
            del sessions[sid]
        return None
    return session


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_session():
            return redirect("/dashboard/login")
        return f(*args, **kwargs)
    return wrapper
