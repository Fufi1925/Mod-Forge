# -*- coding: utf-8 -*-
"""
ModForge AutoMod Cog – Erweiterte Filter (Features 162-230)
Leetspeak, Homoglyph, Zero-Width, Copypasta, Image-Spam, Crypto-Scam,
Token-Grabber, Fake-Nitro, Doxxing, Self-Harm, Impersonation, etc.
"""
import re
import time
import unicodedata
from collections import defaultdict, deque
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

from bot.config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER,
    COLOR_INFO, E, log,
)
from bot.utils import create_embed, normalize_text

# ═══════════════════════════════════════════════════════════════
# IN-MEMORY TRACKER
# ═══════════════════════════════════════════════════════════════
_image_spam: dict = defaultdict(lambda: defaultdict(deque))
_gif_spam: dict = defaultdict(lambda: defaultdict(deque))
_sticker_spam: dict = defaultdict(lambda: defaultdict(deque))
_embed_spam: dict = defaultdict(lambda: defaultdict(deque))
_link_spam: dict = defaultdict(lambda: defaultdict(deque))
_cross_channel_spam: dict = defaultdict(lambda: defaultdict(deque))
_copypasta_hashes: dict = defaultdict(lambda: defaultdict(deque))

# Homoglyph-Map (Feature 166)
HOMOGLYPHS = {
    'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'у': 'y', 'х': 'x',
    'і': 'i', 'ј': 'j', 'ѕ': 's', 'ω': 'w', 'ν': 'v', 'Ь': 'b',
    'ℓ': 'l', '𝐚': 'a', '𝐛': 'b', '𝐜': 'c', '𝐝': 'd', '𝐞': 'e',
    'ⅰ': 'i', 'ⅱ': 'ii', 'ⅲ': 'iii', 'ⅳ': 'iv', 'ⅴ': 'v',
}

# Crypto-Scam keywords (Feature 212)
CRYPTO_SCAM = [
    "free bitcoin", "free btc", "free eth", "crypto airdrop", "nft giveaway",
    "double your crypto", "send btc", "send eth", "metamask wallet",
    "trust wallet seed", "seed phrase", "private key",
]

# Gambling keywords (Feature 213)
GAMBLING_KEYWORDS = ["csgo gambling", "skin gambling", "casino bot", "free spins", "bet now"]

# Token-Grabber patterns (Feature 222)
TOKEN_GRABBER_PATTERNS = [
    r'grab(?:ber|bing)\s*token', r'token\s*steal', r'token\s*log(?:ger)?',
    r'discord\s*token\s*grab', r'stealer\.exe', r'rat\.exe',
]

# IP-Logger domains (Feature 223)
IP_LOGGER_DOMAINS = [
    "grabify.link", "iplogger.org", "2no.co", "iplogger.com", "iplogger.ru",
    "yip.su", "ipgrabber.ru", "ipgraber.ru", "blasze.tk", "ps3cfw.com",
]

# Fake-Nitro patterns (Feature 221)
FAKE_NITRO_PATTERNS = [
    r'discord[\-\.]?gift', r'free\s*nitro', r'nitro\s*for\s*free',
    r'steam\s*gift\s*card', r'gift\s*card\s*generator',
]

# Self-harm keywords (Feature 186)
SELF_HARM_KEYWORDS = [
    "kill myself", "suicide", "want to die", "end my life",
    "self harm", "cutting myself", "ich will sterben", "umbringen",
]


class AutoModCog(commands.Cog):
    """Erweiterte AutoMod-Filter: Leetspeak, Homoglyph, Scam, etc."""

    def __init__(self, bot):
        self.bot = bot

    def _normalize_homoglyphs(self, text: str) -> str:
        """Ersetzt Homoglyphen durch ASCII-Äquivalente (Feature 166)."""
        return ''.join(HOMOGLYPHS.get(c, c) for c in text)

    def _strip_invisible(self, text: str) -> str:
        """Entfernt Zero-Width und unsichtbare Zeichen (Feature 167, 168)."""
        invisible = {'\u200b', '\u200c', '\u200d', '\u200e', '\u200f',
                     '\u2060', '\u2061', '\u2062', '\u2063', '\u2064',
                     '\ufeff', '\u180e', '\u00ad'}
        return ''.join(c for c in text if c not in invisible and unicodedata.category(c) != 'Cf')

    def _detect_char_repeat(self, text: str, max_repeat: int) -> bool:
        """Feature 202: Character-Repetition-Filter."""
        if max_repeat <= 0:
            return False
        count = 1
        for i in range(1, len(text)):
            if text[i] == text[i-1]:
                count += 1
                if count > max_repeat:
                    return True
            else:
                count = 1
        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        if self.bot.is_whitelisted(message.author, "bypass_antispam"):
            return

        guild = message.guild
        member = message.author
        cfg = self.bot.db.get_config(guild.id)
        ext = cfg.get("automod_extended", {})
        content = message.content or ""
        now = time.time()

        # ── Zero-Width / Invisible-Char Filter (167, 168) ──
        if ext.get("zero_width_filter") or ext.get("invisible_char_filter"):
            cleaned = self._strip_invisible(content)
            if len(cleaned) < len(content) * 0.5 and len(content) > 20:
                try:
                    await message.delete()
                except Exception:
                    pass
                await self.bot.punish(member, "warn", "AutoMod: Unsichtbare Zeichen")
                await self.bot.log_action(guild, f"{E.BADWORD} Unsichtbare Zeichen",
                    f"{member.mention} – {len(content) - len(cleaned)} unsichtbare Zeichen entfernt.",
                    COLOR_WARNING, user=member, module="automod")
                return

        # ── Homoglyph Filter (166) ──
        if ext.get("homoglyph_filter"):
            normalized = self._normalize_homoglyphs(content.lower())
            automod_cfg = cfg.get("automod", {})
            for word in automod_cfg.get("bad_words", []):
                if word.lower() in normalized and word.lower() not in content.lower():
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, automod_cfg.get("punishment", "warn"),
                        "AutoMod: Homoglyph-Umgehung erkannt")
                    await self.bot.log_action(guild, f"{E.BADWORD} Homoglyph-Umgehung",
                        f"{member.mention} hat versucht Wortfilter zu umgehen.",
                        COLOR_DANGER, user=member, module="automod")
                    return

        # ── Leetspeak Filter (165) ──
        if ext.get("leetspeak_filter"):
            leet_normalized = normalize_text(content)
            automod_cfg = cfg.get("automod", {})
            for word in automod_cfg.get("bad_words", []):
                if word.lower() in leet_normalized and word.lower() not in content.lower():
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, automod_cfg.get("punishment", "warn"),
                        "AutoMod: Leetspeak-Umgehung")
                    return

        # ── Spoiler-Tag-Missbrauch (169) ──
        if ext.get("spoiler_abuse_filter"):
            spoiler_count = content.count("||")
            if spoiler_count > 10:
                try:
                    await message.delete()
                except Exception:
                    pass
                await self.bot.punish(member, "warn", "AutoMod: Spoiler-Missbrauch")
                return

        # ── Code-Block-Missbrauch (170) ──
        if ext.get("codeblock_abuse_filter"):
            codeblock_count = content.count("```")
            if codeblock_count > 6:
                try:
                    await message.delete()
                except Exception:
                    pass
                await self.bot.punish(member, "warn", "AutoMod: Code-Block-Missbrauch")
                return

        # ── Markdown-Spam (171) ──
        if ext.get("markdown_spam_filter"):
            md_chars = sum(1 for c in content if c in '*_~`>')
            if md_chars > len(content) * 0.4 and len(content) > 30:
                try:
                    await message.delete()
                except Exception:
                    pass
                await self.bot.punish(member, "warn", "AutoMod: Markdown-Spam")
                return

        # ── ASCII-Art-Spam (172) ──
        if ext.get("ascii_art_filter"):
            lines = content.split('\n')
            if len(lines) > 15:
                non_alpha = sum(1 for c in content if not c.isalnum() and c not in ' \n')
                if non_alpha > len(content) * 0.5:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "warn", "AutoMod: ASCII-Art-Spam")
                    return

        # ── Copypasta-Erkennung (173) ──
        if ext.get("copypasta_filter"):
            min_len = ext.get("copypasta_min_length", 500)
            if len(content) >= min_len:
                import hashlib
                content_hash = hashlib.md5(content.lower().encode()).hexdigest()
                dq = _copypasta_hashes[guild.id][content_hash]
                dq.append(now)
                while dq and now - dq[0] > 3600:
                    dq.popleft()
                if len(dq) >= 3:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "warn", "AutoMod: Copypasta erkannt")
                    return

        # ── Image/GIF/Sticker/Embed-Spam (175-178) ──
        if message.attachments:
            images = [a for a in message.attachments if a.content_type and 'image' in a.content_type]
            if images and ext.get("image_spam_limit", 5) > 0:
                dq = _image_spam[guild.id][member.id]
                dq.append(now)
                while dq and now - dq[0] > ext.get("image_spam_window", 30):
                    dq.popleft()
                if len(dq) > ext.get("image_spam_limit", 5):
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "timeout", "AutoMod: Bilder-Spam", 30)
                    return

        if message.stickers and ext.get("sticker_spam_limit", 5) > 0:
            dq = _sticker_spam[guild.id][member.id]
            dq.append(now)
            while dq and now - dq[0] > 30:
                dq.popleft()
            if len(dq) > ext.get("sticker_spam_limit", 5):
                try:
                    await message.delete()
                except Exception:
                    pass
                await self.bot.punish(member, "timeout", "AutoMod: Sticker-Spam", 30)
                return

        # ── Link-Spam erweitert (179) ──
        from bot.config import URL_REGEX
        urls = URL_REGEX.findall(content)
        if urls and ext.get("link_spam_limit", 3) > 0:
            dq = _link_spam[guild.id][member.id]
            for _ in urls:
                dq.append(now)
            while dq and now - dq[0] > ext.get("link_spam_window", 10):
                dq.popleft()
            if len(dq) > ext.get("link_spam_limit", 3):
                try:
                    await message.delete()
                except Exception:
                    pass
                await self.bot.punish(member, "timeout", "AutoMod: Link-Spam", 60)
                return

        # ── Crypto-Scam (212) ──
        if ext.get("crypto_scam_filter"):
            lower = content.lower()
            for kw in CRYPTO_SCAM:
                if kw in lower:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "ban", f"AutoMod: Crypto-Scam ({kw})")
                    await self.bot.log_action(guild, f"{E.SCAM} Crypto-Scam",
                        f"{member.mention}", COLOR_DANGER, user=member, module="antiscam")
                    return

        # ── Gambling-Filter (213) ──
        if ext.get("gambling_filter"):
            lower = content.lower()
            for kw in GAMBLING_KEYWORDS:
                if kw in lower:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "warn", "AutoMod: Gambling-Link")
                    return

        # ── Token-Grabber-Filter (222) ──
        if ext.get("token_grabber_filter"):
            for pattern in TOKEN_GRABBER_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "ban", "AutoMod: Token-Grabber erkannt")
                    await self.bot.log_action(guild, f"{E.NUKE} Token-Grabber",
                        f"{member.mention} hat Token-Grabber-Inhalte gepostet!",
                        COLOR_DANGER, user=member, module="antiscam")
                    return

        # ── IP-Logger-Filter (223) ──
        if ext.get("ip_logger_filter"):
            lower = content.lower()
            for domain in IP_LOGGER_DOMAINS:
                if domain in lower:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "ban", f"AutoMod: IP-Logger ({domain})")
                    await self.bot.log_action(guild, f"{E.NUKE} IP-Logger erkannt",
                        f"{member.mention} – Domain: `{domain}`",
                        COLOR_DANGER, user=member, module="antiscam")
                    return

        # ── Fake-Nitro-Filter (221) ──
        if ext.get("fake_nitro_filter"):
            for pattern in FAKE_NITRO_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "ban", "AutoMod: Fake-Nitro-Link")
                    await self.bot.log_action(guild, f"{E.SCAM} Fake-Nitro",
                        f"{member.mention}", COLOR_DANGER, user=member, module="antiscam")
                    return

        # ── Typosquatting-Filter (230) ──
        if ext.get("typosquat_filter"):
            typo_domains = ["dlscord.com", "discrod.com", "discordapp.co", "dlscordapp.com",
                           "discord.gg.com", "steamcommunlty.com", "steampowerd.com"]
            for domain in typo_domains:
                if domain in content.lower():
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "ban", f"AutoMod: Typosquatting ({domain})")
                    return

        # ── Self-Harm-Erkennung (186, 187) ──
        if ext.get("self_harm_filter"):
            lower = content.lower()
            for kw in SELF_HARM_KEYWORDS:
                if kw in lower:
                    response = ext.get("self_harm_response",
                        "Wenn du Hilfe brauchst: Telefonseelsorge 0800 111 0 111")
                    try:
                        await message.channel.send(
                            f"{member.mention} {response}", delete_after=60)
                    except Exception:
                        pass
                    await self.bot.log_action(guild, f"❤️ Self-Harm Erkennung",
                        f"{member.mention} hat möglicherweise Hilfe nötig.",
                        0xff6b6b, user=member, module="automod")
                    break

        # ── Doxxing-Filter (184) ──
        if ext.get("doxxing_filter"):
            doxx_patterns = [
                r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',  # Phone numbers
                r'\b[A-Z]{1,2}\d{1,2}\s?\d[A-Z]{2}\b',  # UK postal
                r'\b\d{5}(?:-\d{4})?\b',  # US ZIP
            ]
            for pattern in doxx_patterns:
                matches = re.findall(pattern, content)
                if len(matches) >= 2:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "timeout", "AutoMod: Mögliches Doxxing", 300)
                    await self.bot.log_action(guild, f"🚨 Doxxing verdacht",
                        f"{member.mention} hat persönliche Daten gepostet.",
                        COLOR_DANGER, user=member, module="automod")
                    return

        # ── Character-Repetition-Filter (202) ──
        max_repeat = ext.get("char_repeat_max", 20)
        if max_repeat > 0 and self._detect_char_repeat(content, max_repeat):
            try:
                await message.delete()
            except Exception:
                pass
            await self.bot.punish(member, "warn", "AutoMod: Zeichenwiederholung")
            return

        # ── Word-Repetition-Filter (203) ──
        word_repeat_max = ext.get("word_repeat_max", 10)
        if word_repeat_max > 0:
            words = content.lower().split()
            if words:
                from collections import Counter
                most_common = Counter(words).most_common(1)[0]
                if most_common[1] > word_repeat_max:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "warn", "AutoMod: Wortwiederholung")
                    return

        # ── Message-Length-Filter (201) ──
        max_len = ext.get("message_length_max", 0)
        if max_len > 0 and len(content) > max_len:
            try:
                await message.delete()
            except Exception:
                pass
            await self.bot.punish(member, "warn", f"AutoMod: Nachricht zu lang ({len(content)}/{max_len})")
            return

        # ── Cross-Channel-Spam (206) ──
        if ext.get("cross_channel_spam_limit", 5) > 0:
            dq = _cross_channel_spam[guild.id][member.id]
            dq.append((message.channel.id, now))
            window = ext.get("cross_channel_spam_window", 10)
            while dq and now - dq[0][1] > window:
                dq.popleft()
            unique_channels = len(set(ch_id for ch_id, _ in dq))
            if unique_channels >= ext.get("cross_channel_spam_limit", 5):
                await self.bot.punish(member, "timeout", "AutoMod: Cross-Channel-Spam", 60)
                await self.bot.log_action(guild, f"{E.SPAM} Cross-Channel-Spam",
                    f"{member.mention} – {unique_channels} Kanäle in {window}s",
                    COLOR_WARNING, user=member, module="antispam")

        # ── Ad-Filter (210) ──
        if ext.get("ad_filter"):
            lower = content.lower()
            for kw in ext.get("ad_keywords", []):
                if kw.lower() in lower:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "warn", f"AutoMod: Werbung ({kw})")
                    return

        # ── Impersonation-Filter (219) ──
        if ext.get("impersonation_filter") and guild.owner:
            if (member.id != guild.owner_id and
                member.display_name.lower().replace(" ", "") == guild.owner.display_name.lower().replace(" ", "")):
                await self.bot.log_action(guild, f"⚠️ Impersonation verdacht",
                    f"{member.mention} hat einen ähnlichen Namen wie der Owner.",
                    COLOR_WARNING, user=member, module="automod")

        # ── Fake-Giveaway-Filter (220) ──
        if ext.get("fake_giveaway_filter"):
            fake_patterns = [r'(?:free|win)\s*(?:nitro|robux|vbucks|gift\s*card)', r'claim\s*your\s*(?:prize|reward)']
            for pattern in fake_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self.bot.punish(member, "ban", "AutoMod: Fake-Giveaway")
                    return


async def setup(bot):
    await bot.add_cog(AutoModCog(bot))
