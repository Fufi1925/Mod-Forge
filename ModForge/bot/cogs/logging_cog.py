# -*- coding: utf-8 -*-
"""ModForge Logging Cog – einfache und modulare Log-Kanal-Verwaltung."""
import discord
from discord.ext import commands
from discord import app_commands

from bot.config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING,
    E, LOG_MODULES, LOG_MODULES_EXTRA, dev_print,
)
from bot.utils import create_embed
from bot.embed_config import get_embed


ALL_LOG_MODULES = tuple(dict.fromkeys(
    list(LOG_MODULES)
    + list(LOG_MODULES_EXTRA)
    + ["security", "permissions", "antivpn"]
))

MODULE_ALIASES = {
    "anti_spam": "antispam",
    "anti_nuke": "antinuke",
    "anti_raid": "antiraid",
    "anti_mention": "antimention",
    "anti_scam": "antiscam",
    "anti_shortener": "antishortener",
    "anti_url_shortener": "antishortener",
    "url_shortener": "antishortener",
    "ghost_ping": "ghostping",
    "message": "messages",
    "member": "members",
    "role": "roles",
    "channel": "channels",
}


class LoggingCog(commands.Cog):
    """Log-Kanal Verwaltung – ein Command für alles oder genau pro Modul."""

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def _normalize_module(module: str) -> str:
        key = (module or "default").lower().replace("-", "_").replace(" ", "_")
        return MODULE_ALIASES.get(key, key)

    async def _set_all_logs(self, guild_id: int, channel_id: int) -> dict:
        cfg = self.bot.db.get_config(guild_id)
        cfg["log_channel"] = channel_id
        cfg["log_channels"] = {module: channel_id for module in ALL_LOG_MODULES}
        await self.bot.db.set_config(guild_id, cfg)
        try:
            await self.bot.db.log_channels_snapshot(guild_id, cfg["log_channels"])
        except Exception:
            pass
        return cfg

    async def _handle_all_logs(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self._handle_all_logs(interaction, channel)

    async def _module_autocomplete(self, interaction: discord.Interaction, current: str):
        cur = (current or "").lower()
        matches = [m for m in ALL_LOG_MODULES if cur in m.lower()]
        return [app_commands.Choice(name=m, value=m) for m in matches[:25]]

    @app_commands.command(name="log", description="Setzt EINEN Kanal für ALLE Logs")
    @app_commands.describe(channel="Kanal, in den alle Logs gesendet werden")
    @app_commands.default_permissions(administrator=True)
    async def slash_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self._set_all_logs(interaction.guild.id, channel.id)
        dev_print(
            f"Alle Log-Module für {interaction.guild.name} → #{channel.name}",
            "success",
            "Logging",
        )
        embed = create_embed(
            f"{E.LOGS_CMD} Logs eingerichtet",
            f"Alle **{len(ALL_LOG_MODULES)} Log-Module** senden jetzt nach {channel.mention}.\n\n"
            "Du kannst später einzelne Module mit `/logchannel` in eigene Kanäle verschieben.",
            COLOR_SUCCESS,
            [("Standard-Kanal", channel.mention, True), ("Module", str(len(ALL_LOG_MODULES)), True)],
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        try:
            await channel.send(embed=create_embed(
                f"{E.LOGS_CMD} Log-Kanal aktiv",
                f"Dieser Kanal empfängt ab jetzt alle ModForge-Logs.\nKonfiguriert von {interaction.user.mention}.",
                COLOR_SUCCESS,
            ))
        except discord.Forbidden:
            pass

    @app_commands.command(name="logs", description="Alias: setzt EINEN Kanal für ALLE Logs")
    @app_commands.describe(channel="Kanal, in den alle Logs gesendet werden")
    @app_commands.default_permissions(administrator=True)
    async def slash_logs(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self._handle_all_logs(interaction, channel)

    @app_commands.command(name="logchannel", description="Setzt den Log-Kanal für EIN bestimmtes Modul")
    @app_commands.describe(module="Log-Modul (z.B. moderation, antispam, channels)", channel="Ziel-Kanal")
    @app_commands.default_permissions(administrator=True)
    async def slash_logchannel(self, interaction: discord.Interaction,
                               module: str, channel: discord.TextChannel):
        module_key = self._normalize_module(module)
        if module_key not in ALL_LOG_MODULES:
            return await interaction.response.send_message(
                embed=create_embed(
                    f"{E.FAIL} Unbekanntes Modul",
                    f"`{module}` ist kein gültiges Log-Modul. Nutze `/logmodules` für die Liste.",
                    COLOR_DANGER,
                ),
                ephemeral=True,
            )
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg.setdefault("log_channels", {})[module_key] = channel.id
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Modul-Log gesetzt",
            f"**{module_key}** sendet jetzt nach {channel.mention}.",
            COLOR_SUCCESS,
        ), ephemeral=True)

    slash_logchannel.autocomplete("module")(_module_autocomplete)

    @app_commands.command(name="logchannels", description="Zeigt alle Log-Kanäle")
    @app_commands.default_permissions(administrator=True)
    async def slash_logchannels(self, interaction: discord.Interaction):
        cfg = self.bot.db.get_config(interaction.guild.id)
        log_channels = cfg.get("log_channels", {}) or {}
        fallback = cfg.get("log_channel")
        lines = []
        if fallback:
            lines.append(f"**{E.CHANNEL} Standard:** <#{fallback}>")
            lines.append("")
        if log_channels:
            by_channel = {}
            disabled = []
            for mod, ch_id in sorted(log_channels.items()):
                if str(ch_id) == "0":
                    disabled.append(mod)
                elif ch_id:
                    by_channel.setdefault(ch_id, []).append(mod)
            for ch_id, mods in by_channel.items():
                shown = ", ".join(mods[:12])
                more = f" (+{len(mods) - 12})" if len(mods) > 12 else ""
                lines.append(f"<#{ch_id}>: {shown}{more}")
            if disabled:
                lines.append(f"\n**Deaktiviert:** {', '.join(disabled[:20])}")
        if not lines:
            lines = ["Keine Log-Kanäle konfiguriert. Nutze `/log #kanal`."]
        await interaction.response.send_message(embed=create_embed(
            f"{E.LOGS_CMD} Log-Kanäle",
            "\n".join(lines)[:4000],
            COLOR_PRIMARY,
        ), ephemeral=True)

    @app_commands.command(name="logchannel_remove", description="Entfernt den Log-Kanal für ein Modul")
    @app_commands.describe(module="Log-Modul")
    @app_commands.default_permissions(administrator=True)
    async def slash_logchannel_remove(self, interaction: discord.Interaction, module: str):
        module_key = self._normalize_module(module)
        cfg = self.bot.db.get_config(interaction.guild.id)
        log_channels = cfg.get("log_channels", {}) or {}
        if module_key in log_channels:
            del log_channels[module_key]
            cfg["log_channels"] = log_channels
            await self.bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Modul zurückgesetzt",
                f"**{module_key}** nutzt wieder den Standard-Log-Kanal.",
                COLOR_SUCCESS,
            ), ephemeral=True)
        else:
            await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL} Nicht gesetzt",
                f"Für **{module_key}** war kein eigener Kanal gesetzt.",
                COLOR_DANGER,
            ), ephemeral=True)

    slash_logchannel_remove.autocomplete("module")(_module_autocomplete)

    @app_commands.command(name="log_test", description="Sendet Test-Logs in alle konfigurierten Log-Kanäle")
    @app_commands.default_permissions(administrator=True)
    async def slash_log_test(self, interaction: discord.Interaction):
        cfg = self.bot.db.get_config(interaction.guild.id)
        configured = cfg.get("log_channels", {}) or {}
        targets = {}
        if cfg.get("log_channel"):
            targets["default"] = cfg.get("log_channel")
        for module, channel_id in configured.items():
            if channel_id and str(channel_id) != "0":
                targets[module] = channel_id
        if not targets:
            return await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL} Keine Logs eingerichtet", "Nutze zuerst `/log #kanal`.", COLOR_DANGER
            ), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        ok = 0; failed = []
        for module, channel_id in sorted(targets.items()):
            ch = interaction.guild.get_channel(int(channel_id))
            if not ch:
                failed.append(f"{module}: Kanal nicht gefunden")
                continue
            try:
                await ch.send(embed=create_embed(
                    f"{E.LOGS_CMD} Test-Log · {module}",
                    f"Dieser Test wurde von {interaction.user.mention} ausgelöst. Modul **{module}** funktioniert.",
                    COLOR_SUCCESS, user=interaction.user,
                ))
                ok += 1
            except discord.Forbidden:
                failed.append(f"{module}: keine Schreibrechte")
            except discord.HTTPException as e:
                failed.append(f"{module}: {e}")
        await interaction.followup.send(embed=create_embed(
            f"{E.LOGS_CMD} Log-Test fertig",
            f"✅ Erfolgreich: **{ok}**\n❌ Fehler: **{len(failed)}**",
            COLOR_SUCCESS if not failed else COLOR_WARNING,
            [("Fehler", "\n".join(failed[:10]) or "Keine", False)]
        ), ephemeral=True)

    @app_commands.command(name="logmodules", description="Zeigt alle verfügbaren Log-Module")
    @app_commands.default_permissions(administrator=True)
    async def slash_logmodules(self, interaction: discord.Interaction):
        chunks = []
        current = []
        for module in ALL_LOG_MODULES:
            current.append(f"`{module}`")
            if len(", ".join(current)) > 900:
                chunks.append(", ".join(current))
                current = []
        if current:
            chunks.append(", ".join(current))
        fields = [(f"Module {i + 1}", chunk, False) for i, chunk in enumerate(chunks[:4])]
        await interaction.response.send_message(embed=create_embed(
            f"{E.LOGS_CMD} Log-Module ({len(ALL_LOG_MODULES)})",
            "Nutze `/logchannel <modul> #kanal` für einzelne Module oder `/log #kanal` für alles.",
            COLOR_PRIMARY,
            fields,
        ), ephemeral=True)

    @app_commands.command(name="logs_disable", description="Deaktiviert alle Logs")
    @app_commands.default_permissions(administrator=True)
    async def slash_logs_disable(self, interaction: discord.Interaction):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["log_channel"] = None
        cfg["log_channels"] = {}
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Logs deaktiviert",
            "Alle Log-Kanäle wurden entfernt. Aktiviere sie wieder mit `/log #kanal`.",
            COLOR_WARNING,
        ), ephemeral=True)


async def setup(bot):
    await bot.add_cog(LoggingCog(bot))
