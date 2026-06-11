# -*- coding: utf-8 -*-
"""ModForge TempVoice Cog – Temporäre Voice-Kanäle Commands."""
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from bot.config import COLOR_PRIMARY, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING, COLOR_INFO, E, log
from bot.utils import create_embed
from bot.bot import TempVoiceView


class TempVoiceCog(commands.Cog):
    """Temporäre Voice-Kanäle Setup und Verwaltung."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup_tempvoice", description="Richtet das Temp-Voice System ein")
    @app_commands.default_permissions(administrator=True)
    async def slash_setup_tempvoice(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild = interaction.guild
        cfg = self.bot.db.get_config(guild.id)
        tv = cfg.get("temp_voice", {})

        # Create category if needed
        category = None
        if tv.get("category_id"):
            category = guild.get_channel(tv["category_id"])
        if not category:
            category = await guild.create_category("🔊 Temp Voice", reason="TempVoice Setup")
            tv["category_id"] = category.id

        # Create hub channel if needed
        hub = None
        if tv.get("hub_channel_id"):
            hub = guild.get_channel(tv["hub_channel_id"])
        if not hub:
            hub = await guild.create_voice_channel("➕ Kanal erstellen", category=category, reason="TempVoice Hub")
            tv["hub_channel_id"] = hub.id

        tv["enabled"] = True
        cfg["temp_voice"] = tv
        await self.bot.db.set_config(guild.id, cfg)

        # Create panel message
        panel_ch = None
        if tv.get("panel_channel_id"):
            panel_ch = guild.get_channel(tv["panel_channel_id"])
        if not panel_ch:
            panel_ch = await guild.create_text_channel("🎛️ voice-panel", category=category, reason="TempVoice Panel")
            tv["panel_channel_id"] = panel_ch.id

        embed = create_embed(
            "🔊 Temp-Voice Panel",
            "Tritt dem Hub-Kanal bei um deinen eigenen Voice-Kanal zu erstellen.\n"
            "Nutze das Dropdown unten um deinen Kanal zu verwalten.",
            COLOR_PRIMARY)
        view = TempVoiceView(self.bot)
        msg = await panel_ch.send(embed=embed, view=view)
        tv["panel_message_id"] = msg.id
        cfg["temp_voice"] = tv
        await self.bot.db.set_config(guild.id, cfg)

        await interaction.followup.send(embed=create_embed(
            f"{E.OK} Temp-Voice eingerichtet",
            f"**Hub:** {hub.mention}\n**Panel:** {panel_ch.mention}\n**Kategorie:** {category.name}",
            COLOR_SUCCESS))

    @app_commands.command(name="tempvoice", description="Temp-Voice Kanal verwalten")
    @app_commands.describe(action="info/claim", user="Für claim: der aktuelle Owner")
    async def slash_tempvoice(self, interaction: discord.Interaction, action: str,
                               user: Optional[discord.Member] = None):
        if action == "info":
            if not interaction.user.voice or not interaction.user.voice.channel:
                return await interaction.response.send_message(
                    embed=create_embed(f"{E.FAIL}", "Du bist in keinem Voice-Kanal.", COLOR_DANGER), ephemeral=True)
            ch = interaction.user.voice.channel
            doc = await self.bot.db.tempvoice_channels.find_one(
                {"guild_id": interaction.guild.id, "channel_id": ch.id})
            if not doc:
                return await interaction.response.send_message(
                    embed=create_embed(f"{E.FAIL}", "Das ist kein Temp-Voice Kanal.", COLOR_DANGER), ephemeral=True)
            owner = interaction.guild.get_member(doc.get("user_id"))
            await interaction.response.send_message(embed=create_embed(
                "🔊 Temp-Voice Info",
                f"**Kanal:** {ch.mention}\n**Owner:** {owner.mention if owner else '?'}\n"
                f"**Mitglieder:** {len(ch.members)}\n**Limit:** {ch.user_limit or '∞'}",
                COLOR_INFO), ephemeral=True)

    @app_commands.command(name="tvreset", description="[Admin] Setzt Temp-Voices eines Users zurück")
    @app_commands.describe(user="Der User")
    @app_commands.default_permissions(administrator=True)
    async def slash_tvreset(self, interaction: discord.Interaction, user: discord.Member):
        result = await self.bot.db.tempvoice_channels.delete_many(
            {"guild_id": interaction.guild.id, "user_id": user.id})
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} TempVoice Reset",
            f"{result.deleted_count} Einträge für {user.mention} gelöscht.", COLOR_SUCCESS))


async def setup(bot):
    await bot.add_cog(TempVoiceCog(bot))
