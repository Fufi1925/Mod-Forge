# -*- coding: utf-8 -*-
import asyncio
import logging
from collections import deque
import io
import random
import string
import re
import datetime
from typing import Optional, Tuple, Any, Union, List, Callable, Awaitable
import discord
import aiohttp
from PIL import Image, ImageDraw, ImageFont

from bot.config import COLOR_PRIMARY, FOOTER_TEXT, FOOTER_ICON, log

# Zentrales Rate-Limit-System
# Lazy-Init: Semaphore wird erst beim ersten Aufruf erstellt, damit es im richtigen Event-Loop ist
_GLOBAL_API_SEMAPHORE = None


def _get_semaphore():
    global _GLOBAL_API_SEMAPHORE
    if _GLOBAL_API_SEMAPHORE is None:
        _GLOBAL_API_SEMAPHORE = asyncio.Semaphore(5)
    return _GLOBAL_API_SEMAPHORE


async def rate_limited(
    coro_func: Callable[..., Awaitable[Any]],
    *args: Any,
    delay: float = 0.6,
    max_retries: int = 3,
    **kwargs: Any,
) -> Any:
    attempts = 0
    while True:
        async with _get_semaphore():
            try:
                result = await coro_func(*args, **kwargs)
                if delay > 0:
                    await asyncio.sleep(delay)
                return result
            except discord.HTTPException as exc:
                if exc.status == 429 and attempts < max_retries:
                    retry_after = 5.0
                    try:
                        retry_after = float(exc.response.headers.get("Retry-After", 5))
                    except (AttributeError, TypeError, ValueError):
                        pass
                    log.warning(f"Rate-Limit (429) – warte {retry_after:.1f}s")
                    await asyncio.sleep(retry_after)
                    attempts += 1
                    continue
                raise


def utcnow() -> datetime.datetime:
    """Gibt eine timezone-aware UTC-Zeit zurück (kompatibel mit discord.py)."""
    return datetime.datetime.now(datetime.timezone.utc)


def to_aware_utc(value: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """Normalisiert naive/aware Datetimes auf aware UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def age_since(value: Optional[datetime.datetime]) -> datetime.timedelta:
    """Alter seit einem Zeitpunkt; bei None wird 0 zurückgegeben."""
    dt = to_aware_utc(value)
    if dt is None:
        return datetime.timedelta(0)
    return utcnow() - dt


def create_embed(
    title: str,
    description: str = "",
    color: int = COLOR_PRIMARY,
    fields: Optional[List[tuple]] = None,
    thumbnail: Optional[str] = None,
    image: Optional[str] = None,
    author_name: Optional[str] = None,
    author_icon: Optional[str] = None,
    user: Optional[Union[discord.Member, discord.User]] = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=utcnow(),
    )
    embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    if fields:
        for field in fields[:25]:
            try:
                name, value, inline = field
            except ValueError:
                continue
            embed.add_field(name=str(name)[:256], value=(str(value) or "—")[:1024], inline=bool(inline))
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    if author_name:
        embed.set_author(
            name=author_name, icon_url=author_icon or discord.utils.MISSING
        )
    if user:
        embed.set_author(name=f"{user.name}", icon_url=user.display_avatar.url)
    return embed


def generate_captcha(difficulty: str = "medium") -> Tuple[str, io.BytesIO]:
    length = 6 if difficulty == "medium" else (4 if difficulty == "easy" else 8)
    code = "".join(random.choices(string.ascii_uppercase + string.digits, k=length))
    width, height = 250, 100
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    font = None
    font_paths = [
        "arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        try:
            font = ImageFont.truetype(path, 40)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()
    d.text((width // 4, height // 3), code, fill=(0, 0, 0), font=font)
    noise_level = (
        100 if difficulty == "easy" else (300 if difficulty == "medium" else 600)
    )
    for _ in range(noise_level):
        d.point(
            (random.randint(0, width), random.randint(0, height)),
            fill=(
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255),
            ),
        )
    if difficulty == "hard":
        for _ in range(5):
            d.line(
                (
                    random.randint(0, width),
                    random.randint(0, height),
                    random.randint(0, width),
                    random.randint(0, height),
                ),
                fill=(0, 0, 0),
                width=2,
            )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return code, buf



def normalize_text(text: str) -> str:
    """Normalisiert Text für AutoMod (Leetspeak, Spam, Trennzeichen)."""
    leet = {"4": "a", "3": "e", "1": "i", "0": "o", "5": "s", "@": "a", "$": "s", "7": "t", "8": "b"}
    text = "".join(leet.get(c, c) for c in text.lower())
    text = re.sub(r"(.)\1{2,}", r"\1", text)
    text = re.sub(r"[\s.\-_]+", "", text)
    return text

async def check_phishing_url(url: str, session=None) -> bool:
    import os as _os
    scam_keywords = [
        "discord-nitro", "free-nitro", "gift-nitro", "steam-promo", "discord-gift",
        "discordgift", "nitro-free", "dlscord", "discrod", "steamcommuniuty",
    ]
    if any(kw in url.lower() for kw in scam_keywords):
        return True
    api_key = _os.getenv("PHISHTANK_API_KEY")
    if api_key and session:
        try:
            timeout = aiohttp.ClientTimeout(total=3)
            async with session.post("https://checkurl.phishtank.com/checkurl/", data={"url": url, "format": "json", "app_key": api_key}, timeout=timeout) as resp:
                data = await resp.json()
                return data.get("results", {}).get("in_database", False)
        except Exception:
            pass
    return False


def can_moderate(
    actor: discord.Member, target: discord.Member, bot_member: discord.Member
) -> Tuple[bool, str]:
    if target.id == actor.guild.owner_id:
        return False, "Der Server-Owner kann nicht moderiert werden."
    if target.id == bot_member.id:
        return False, "Ich kann mich nicht selbst moderieren."
    if target.id == actor.id:
        return False, "Du kannst dich nicht selbst moderieren."
    if actor.id != actor.guild.owner_id and actor.top_role <= target.top_role:
        return False, "Deine höchste Rolle ist nicht über der des Ziels."
    if bot_member.top_role <= target.top_role:
        return False, "Meine höchste Rolle ist nicht über der des Ziels."
    return True, ""


def parse_duration(text: str) -> Optional[int]:
    if not text:
        return None
    text = text.strip().lower()
    m = re.match(r"^(\d+)\s*([smhdw]?)$", text)
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2) or "s"
    MAX_SECONDS = 60 * 60 * 24 * 28  # = 2419200 (28 Tage)
    return min(val * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit], MAX_SECONDS)


def _run_async(coro, timeout: float = 8.0):
    """Führt eine Coroutine threadsafe aus (für Flask)."""
    from bot.bot import BOT_REF as bot_ref

    try:
        loop = bot_ref.loop if bot_ref is not None else None
    except Exception:
        loop = None
    try:
        running = bool(loop is not None and loop.is_running())
    except Exception:
        running = False
    if not running:
        return None
    try:
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)
    except Exception as ex:
        log.debug(f"_run_async: {ex}")
        return None


class RingLogHandler(logging.Handler):
    """Speichert die letzten `max_entries` Logs in einer Liste."""

    def __init__(self, max_entries=200):
        super().__init__()
        self.max_entries = max_entries
        self.entries = deque(maxlen=max_entries)

    def emit(self, record):
        msg = self.format(record)
        self.entries.append(
            {
                "time": datetime.datetime.utcnow().strftime("%H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "msg": msg,
            }
        )


# Globalen Handler erstellen und zum Root-Logger hinzufügen
_live_handler = RingLogHandler(max_entries=200)
_live_handler.setFormatter(logging.Formatter("%(message)s"))
_live_handler.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_live_handler)


def get_live_logs():
    return list(_live_handler.entries)
