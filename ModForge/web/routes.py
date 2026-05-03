from flask import render_template, request, redirect, url_for, session, jsonify, Response
import datetime, logging, urllib.parse, secrets, time, threading
from collections import defaultdict, deque

from .app import flask_app
from .auth import (
    _discord_api_call, _get_user_guilds_with_bot, _get_session_user, _user_can_manage_guild,
)
from .helpers import (
    _bot_stats, _get_guild_config, _build_overview, _build_module_form, _build_welcome_content,
)
from .config import (
    DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, OAUTH2_REDIRECT, ADMIN_USERNAME, ADMIN_PASSWORD,
)
from bot.bot import bot
from bot.config import (
    FEATURES, CMDS_PREVIEW, VERSIONS, LOG_MODS, log, ACTIVITY,
)
from bot.utils import _run_async

log = logging.getLogger("ModForge.Web.Routes")

# ────── Startseite ──────
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

# ────── weitere Routen (Status, Changelog, Legal, OAuth, Dashboard, Admin) ──────
# Füge hier die anderen Routen aus der vorherigen vollständigen Version ein,
# aber achte darauf, dass keine weitere Route existiert, die JSON zurückgibt.
