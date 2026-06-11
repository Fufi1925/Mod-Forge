# -*- coding: utf-8 -*-
"""ModForge Logging Cog – Log-Kanal Commands inkl. /logs (alle in einen Kanal)."""
import discord
from discord.ext import commands
from discord import app_commands

from bot.config import COLOR_PRIMARY, COLOR_SUCCESS, COLOR_DANGER, COLOR_INFO, E, LOG_MODS, log
from bot.utils import create_embed


class LoggingCog(commands.Cog):
    """Log-Kanal Verwaltung – einfach und pro Modul."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="logs", description="Setzt EINEN Kanal für ALLE Logs (einfachste Variante)")
    @app_commands.describe(channel="Der Kanal in den alle Logs gesendet werden")
    @app_commands.default_permissions(administrator=True)
    async def slash_logs(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Punkt 4: /logs #kanal → alle Logs gehen in diesen Kanal."""
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["log_channel"] = channel.id
        # Setze auch alle Modul-Kanäle auf diesen einen Kanal
        modules = [
            "moderation", "antispam", "antinuke", "antiraid", "antimention",
            "antiscam", "automod", "antishortener", "voice", "members",
            "nicknames", "channels", "roles", "webhooks", "tickets",
            "verify", "warns", "cases", "backup", "welcome", "leave",
            "errors", "messages", "ghostping", "appeal", "permissions",
            "audit", "security", "default",
        ]
        log_channels = {}
        for mod in modules:
            log_channels[mod] = channel.id
        cfg["log_channels"] = log_channels
        await self.bot.db.set_config(interaction.guild.id, cfg)

        lines = [f"{E.OK} **Alle Logs** → {channel.mention}", ""]
        lines.append("Folgende Module werden geloggt:")
        for mod in modules:
            lines.append(f"  {E.DOT} {mod}")

        await interaction.response.send_message(embed=create_embed(
            f"{E.LOGS_CMD} Logs eingerichtet",
            "\n".join(lines[:30]),
            COLOR_SUCCESS))

        # Bestätigungsnachricht im Log-Kanal
        try:
            await channel.send(embed=create_embed(
                f"{E.LOGS_CMD} Log-Kanal aktiviert",
                f"Dieser Kanal empfängt jetzt **alle Logs** von ModForge.\n"
                f"Konfiguriert von {interaction.user.mention}\n\n"
                f"**{len(modules)} Module** aktiv.",
                COLOR_SUCCESS))
        except discord.Forbidden:
            pass

    @app_commands.command(name="logchannel", description="Setzt den Log-Kanal für EIN bestimmtes Modul")
    @app_commands.describe(module="Log-Modul (z.B. moderation, antispam, channels)", channel="Ziel-Kanal")
    @app_commands.default_permissions(administrator=True)
    async def slash_logchannel(self, interaction: discord.Interaction,
                                module: str, channel: discord.TextChannel):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg.setdefault("log_channels", {})[module.lower()] = channel.id
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Log-Kanal gesetzt", f"**{module}** → {channel.mention}", COLOR_SUCCESS))

    @app_commands.command(name="logchannels", description="Zeigt alle Log-Kanäle")
    @app_commands.default_permissions(administrator=True)
    async def slash_logchannels(self, interaction: discord.Interaction):
        cfg = self.bot.db.get_config(interaction.guild.id)
        log_channels = cfg.get("log_channels", {})
        fallback = cfg.get("log_channel")
        lines = []
        if fallback:
            lines.append(f"**{E.CHANNEL} Standard-Kanal:** <#{fallback}>")
            lines.append("")
        if log_channels:
            # Gruppiere nach Kanal
            by_channel = {}
            for mod, ch_id in sorted(log_channels.items()):
                by_channel.setdefault(ch_id, []).append(mod)
            for ch_id, mods in by_channel.items():
                lines.append(f"<#{ch_id}>: {', '.join(mods)}")
        if not lines:
            lines = [f"Keine Log-Kanäle konfiguriert.\n\nNutze **`/logs #kanal`** um alle Logs in einen Kanal zu senden."]
        await interaction.response.send_message(embed=create_embed(
            f"{E.LOGS_CMD} Log-Kanäle", "\n".join(lines), COLOR_PRIMARY))

    @app_commands.command(name="logchannel_remove", description="Entfernt den Log-Kanal für ein Modul")
    @app_commands.describe(module="Log-Modul")
    @app_commands.default_permissions(administrator=True)
    async def slash_logchannel_remove(self, interaction: discord.Interaction, module: str):
        cfg = self.bot.db.get_config(interaction.guild.id)
        log_channels = cfg.get("log_channels", {})
        if module.lower() in log_channels:
            del log_channels[module.lower()]
            cfg["log_channels"] = log_channels
            await self.bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK}", f"Log-Kanal für **{module}** entfernt.", COLOR_SUCCESS))
        else:
            await interaction.response.send_message(embed=create_embed(
                f"{E.FAIL}", f"Kein Log-Kanal für **{module}** gefunden.", COLOR_DANGER), ephemeral=True)

    @app_commands.command(name="logs_disable", description="Deaktiviert alle Logs")
    @app_commands.default_permissions(administrator=True)
    async def slash_logs_disable(self, interaction: discord.Interaction):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg["log_channel"] = None
        cfg["log_channels"] = {}
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Logs deaktiviert", "Alle Log-Kanäle wurden entfernt.", COLOR_WARNING))


async def setup(bot):
    await bot.add_cog(LoggingCog(bot))
