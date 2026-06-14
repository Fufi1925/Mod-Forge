# -*- coding: utf-8 -*-
"""ModForge Welcome Cog – Welcome/Leave System, Auto-Roles, Sticky Roles."""
import discord
from discord.ext import commands
from discord import app_commands

from bot.config import log
from bot.embed_config import get_embed


class WelcomeCog(commands.Cog):
    """Welcome/Leave Nachrichten, Auto-Roles, Sticky Roles."""

    def __init__(self, bot):
        self.bot = bot

    async def send_welcome(self, member: discord.Member):
        """Sendet die Welcome-Nachricht (aufgerufen vom Events-Cog)."""
        cfg = self.bot.db.get_config(member.guild.id)
        welcome = cfg.get("welcome", {})
        if not welcome.get("enabled") or not welcome.get("channel_id"):
            return

        channel = member.guild.get_channel(welcome["channel_id"])
        if not channel:
            return

        # Zentrales Embed verwenden
        embed = get_embed("welcome", guild=member.guild, user=member, bot=self.bot)
        
        # Custom Override aus Config
        if welcome.get("embed_title"):
            embed.title = welcome["embed_title"].replace("{mention}", member.mention).replace("{user}", str(member))
        if welcome.get("embed_description"):
            embed.description = welcome["embed_description"].replace("{mention}", member.mention).replace("{user}", str(member))

        try:
            content = member.mention if welcome.get("mention") else None
            await channel.send(content=content, embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

        # DM
        if welcome.get("dm_enabled") and welcome.get("dm_description"):
            dm_desc = welcome["dm_description"].replace("{mention}", member.mention).replace("{user}", str(member))
            try:
                from bot.bot import safe_dm
                dm_embed = get_embed("welcome_dm", guild=member.guild, user=member, bot=self.bot)
                await safe_dm(member, dm_embed)
            except Exception:
                pass

        # Auto-Roles
        add_roles = welcome.get("add_roles", [])
        for role_id in add_roles:
            role = member.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto-Role bei Join")
                except (discord.Forbidden, discord.HTTPException):
                    pass

    async def send_leave(self, member: discord.Member):
        """Sendet die Leave-Nachricht."""
        cfg = self.bot.db.get_config(member.guild.id)
        leave = cfg.get("leave", {})
        if not leave.get("enabled") or not leave.get("channel_id"):
            return

        channel = member.guild.get_channel(leave["channel_id"])
        if not channel:
            return

        embed = get_embed("leave", guild=member.guild, user=member, bot=self.bot)
        
        if leave.get("embed_title"):
            embed.title = leave["embed_title"].replace("{user}", str(member))
        if leave.get("embed_description"):
            embed.description = leave["embed_description"].replace("{user}", str(member))

        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def restore_sticky_roles(self, member: discord.Member):
        """Stellt Sticky-Roles wieder her."""
        cfg = self.bot.db.get_config(member.guild.id)
        sticky = cfg.get("sticky_roles", [])
        if not sticky:
            return
        try:
            doc = await self.bot.db.data.find_one(
                {"guild_id": member.guild.id, "user_id": member.id, "type": "sticky_roles"})
            if doc and doc.get("roles"):
                for role_id in doc["roles"]:
                    if role_id in sticky:
                        role = member.guild.get_role(role_id)
                        if role:
                            try:
                                await member.add_roles(role, reason="Sticky-Role wiederhergestellt")
                            except (discord.Forbidden, discord.HTTPException):
                                pass
        except Exception as e:
            log.debug(f"Sticky-Role restore error: {e}")

    # ── COMMANDS ──
    @app_commands.command(name="welcome_channel", description="Setzt den Welcome-Kanal")
    @app_commands.describe(channel="Der Kanal")
    @app_commands.default_permissions(administrator=True)
    async def slash_welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = self.bot.db.get_config(interaction.guild.id)
        welcome = cfg.setdefault("welcome", {})
        welcome["channel_id"] = channel.id
        welcome["enabled"] = True
        await self.bot.db.aset_config(interaction.guild.id, cfg)
        await interaction.response.send_message(f"✅ Welcome-Kanal auf {channel.mention} gesetzt.", ephemeral=True)
