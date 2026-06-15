# -*- coding: utf-8 -*-
"""ModForge TempVoice Cog"""
import discord
from discord.ext import commands
from discord import app_commands
from bot.embed_config import get_embed


class TempVoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tempvoice_panel", description="Sendet das TempVoice-Panel")
    @app_commands.default_permissions(administrator=True)
    async def slash_tempvoice_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        embed = get_embed("tempvoice_panel", guild=interaction.guild, bot=self.bot)
        await ch.send(embed=embed)
        
        success_embed = get_embed("success", message=f"TempVoice-Panel wurde in {ch.mention} gesendet.", user=interaction.user, bot=self.bot)
        await interaction.response.send_message(embed=success_embed, ephemeral=True)
