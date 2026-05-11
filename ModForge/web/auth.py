# web/auth.py
import os
import time
import secrets
from urllib.parse import urlencode
from functools import wraps

import requests
from flask import Blueprint, request, redirect, make_response, session as flask_session

# Umgebungsvariablen
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "http://mod-forge.up.railway.app").rstrip("/")

REDIRECT_URI = f"{DASHBOARD_BASE_URL}/dashboard/auth/callback"
DISCORD_API = "https://discord.com/api/v10"
SESSION_COOKIE = "modforge_session"

# Session-Store
sessions = {}

auth_bp = Blueprint("auth", __name__, template_folder="templates")


def _make_session_id():
    return secrets.token_hex(32)


@auth_bp.route("/dashboard/login")
def login():
    """Weiterleitung zu Discord OAuth2."""
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        return "Dashboard auth not configured.", 503

    state = secrets.token_urlsafe(16)
    flask_session["oauth_state"] = state  # optional State-Check
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
    """Code gegen Token tauschen, Profil & Guilds laden, Session erstellen."""
    code = request.args.get("code")
    state = request.args.get("state")
    session_state = flask_session.pop("oauth_state", None)

    if not code or state != session_state:
        return redirect("/dashboard?error=invalid_state_or_missing_code")

    # Token holen
    token_resp = requests.post(
        f"{DISCORD_API}/oauth2/token",
        data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if token_resp.status_code != 200:
        return redirect(f"/dashboard?error=token_exchange_failed&detail={token_resp.status_code}")

    token_data = token_resp.json()
    access_token = token_data["access_token"]

    # Benutzer laden
    user_resp = requests.get(
        f"{DISCORD_API}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if user_resp.status_code != 200:
        return redirect("/dashboard?error=user_fetch_failed")
    user = user_resp.json()

    # Guilds laden
    guild_resp = requests.get(
        f"{DISCORD_API}/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if guild_resp.status_code != 200:
        guilds = []
    else:
        guilds = guild_resp.json()

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
        secure=False,  # auf True setzen, sobald HTTPS genutzt wird
        max_age=7 * 24 * 3600,
    )
    return resp


@auth_bp.route("/dashboard/logout")
def logout():
    """Session beenden und Cookie entfernen."""
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        sessions.pop(sid, None)
    resp = make_response(redirect("/"))
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---------- Hilfsfunktionen für andere Routen ----------
def get_session():
    """Aktuelle Session aus dem Cookie holen."""
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
    """Decorator, der unauthentifizierte Nutzer zum Login schickt."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_session():
            return redirect("/dashboard/login")
        return f(*args, **kwargs)
    return wrapper
