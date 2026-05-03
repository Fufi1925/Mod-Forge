import urllib.request, urllib.parse, json
import logging
from flask import session
from typing import List, Optional
from bot.bot import BOT_REF

log = logging.getLogger("ModForge.Web.Auth")
DISCORD_API = "https://discord.com/api/v10"

def _discord_api_call(path: str, token: str = None, method: str = "GET", data: dict = None):
    url = f"{DISCORD_API}{path}"
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as ex:
        log.error(f"Discord API {path}: {ex.code}")
        try:
            return json.loads(ex.read())
        except:
            return None
    except Exception as ex:
        log.error(f"Discord API {path}: {ex}")
        return None

def _get_user_guilds_with_bot(user_guilds: list) -> list:
    if not BOT_REF:
        return []
    bot_guild_ids = {g.id for g in BOT_REF.guilds}
    result = []
    for g in user_guilds:
        perms = g.get("permissions", 0)
        try:
            perms = int(perms)
        except:
            perms = 0
        if (perms & 0x20) and int(g["id"]) in bot_guild_ids:
            bg = BOT_REF.get_guild(int(g["id"]))
            result.append({
                "id": g["id"],
                "name": g["name"],
                "icon": g.get("icon", ""),
                "member_count": bg.member_count if bg else 0,
                "has_bot": True
            })
    return result

def _get_session_user():
    return session.get("discord_user")

def _user_can_manage_guild(guild_id: str) -> bool:
    ug = session.get("user_guilds", [])
    for g in ug:
        if g.get("id") == guild_id:
            perms = int(g.get("permissions", 0))
            return bool(perms & 0x20)
    return False
