# -*- coding: utf-8 -*-
"""ModForge Tickets Cog"""
import discord
from discord.ext import commands
from discord import app_commands
from bot.embed_config import get_embed


class TicketsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ticket_panel", description="Sendet das Ticket-Panel")
    @app_commands.default_permissions(administrator=True)
    async def slash_ticket_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        ch = channel or interaction.channel
        embed = get_embed("ticket_panel", guild=interaction.guild, bot=self.bot)
        await ch.send(embed=embed)
        
        success_embed = get_embed("success", message=f"Ticket-Panel wurde in {ch.mention} gesendet.", user=interaction.user, bot=self.bot)
        await interaction.response.send_message(embed=success_embed, ephemeral=True)
