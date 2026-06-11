# -*- coding: utf-8 -*-
"""ModForge Logging Cog – Log-Kanal Commands."""
import discord
from discord.ext import commands
from discord import app_commands

from bot.config import COLOR_PRIMARY, COLOR_SUCCESS, COLOR_DANGER, E, LOG_MODS, log
from bot.utils import create_embed


class LoggingCog(commands.Cog):
    """Log-Kanal Verwaltung pro Modul."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="logchannel", description="Setzt den Log-Kanal für ein Modul")
    @app_commands.describe(module="Log-Modul", channel="Ziel-Kanal")
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
            lines.append(f"**Fallback:** <#{fallback}>")
        for mod, ch_id in sorted(log_channels.items()):
            lines.append(f"**{mod}:** <#{ch_id}>")
        if not lines:
            lines = ["Keine Log-Kanäle konfiguriert. Nutze `/logchannel`."]
        await interaction.response.send_message(embed=create_embed(
            f"{E.CHANNEL} Log-Kanäle", "\n".join(lines), COLOR_PRIMARY))

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


async def setup(bot):
    await bot.add_cog(LoggingCog(bot))
