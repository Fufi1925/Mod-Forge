import os
import time
import secrets
from urllib.parse import urlencode

import httpx
from flask import Blueprint, request, redirect, make_response, current_app

# Umgebungsvariablen – KEIN Secret im Code
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "http://mod-forge.up.railway.app").rstrip("/")

REDIRECT_URI = f"{DASHBOARD_BASE_URL}/dashboard/auth/callback"
DISCORD_API = "https://discord.com/api/v10"
SESSION_COOKIE = "modforge_session"

# Einfacher In‑Memory Session Store (für Produktion ggf. Redis verwenden)
sessions = {}

auth_bp = Blueprint("auth", __name__, template_folder="templates")


def _make_session_id():
    return secrets.token_hex(32)


@auth_bp.route("/dashboard/login")
def login():
    """Leitet den Benutzer zu Discord OAuth2 weiter."""
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        return "Dashboard auth is not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET env vars.", 503

    state = secrets.token_urlsafe(16)
    # Optional: State‑Validierung (kann später ergänzt werden)
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
async def callback():
    """Tauscht den Code gegen ein Token, lädt Profil & Guilds und erstellt eine Session."""
    code = request.args.get("code")
    if not code:
        return redirect("/dashboard?error=missing_code")

    # Token abrufen
    async with httpx.AsyncClient() as client:
        resp = await client.post(
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
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return redirect(f"/dashboard?error=token_exchange_failed&detail={e.response.status_code}")

        token_data = resp.json()
        access_token = token_data["access_token"]

        # Benutzerprofil laden
        user_resp = await client.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_resp.raise_for_status()
        user = user_resp.json()

        # Guilds laden
        guild_resp = await client.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        guild_resp.raise_for_status()
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

    response = make_response(redirect("/dashboard"))
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        secure=False,          # in Produktion mit HTTPS auf True setzen
        max_age=7 * 24 * 3600,
    )
    return response


@auth_bp.route("/dashboard/logout")
def logout():
    """Session zerstören und Cookie löschen."""
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        sessions.pop(session_id, None)
    response = make_response(redirect("/"))
    response.delete_cookie(SESSION_COOKIE)
    return response


def get_session():
    """Aktuelle Session aus dem Cookie auslesen."""
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    session = sessions.get(sid)
    if session and time.time() - session["created_at"] < 7 * 24 * 3600:
        return session
    # Session abgelaufen
    sessions.pop(sid, None)
    return None


def require_auth(f):
    """Dekorator, der unauthentifizierte Benutzer weiterleitet."""
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        session = get_session()
        if not session:
            return redirect("/dashboard/login")
        return f(*args, **kwargs)

    return wrapper
