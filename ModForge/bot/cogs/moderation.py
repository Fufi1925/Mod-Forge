# -*- coding: utf-8 -*-
"""ModForge Moderation Cog – Ban, Kick, Warn, Mute, etc."""
import datetime
from typing import Callable

import discord
from discord.ext import commands
from discord import app_commands

from bot.config import (
    COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER, E,
)
from bot.utils import create_embed, can_moderate, parse_duration
from bot.bot import _BOT_DEV_ID
from bot.embed_config import get_embed


class ModerationCog(commands.Cog):
    """Moderation Commands."""

    def __init__(self, bot):
        self.bot = bot

    async def create_case(self, guild_id: int, user_id: int, mod_id: int, action: str, reason: str, duration: int = None):
        """Erstellt einen Case in der Datenbank."""
        return await self.bot.db.acreate_case(guild_id, user_id, mod_id, action, reason, duration)

    @app_commands.command(name="ban", description="Bannt einen User")
    @app_commands.describe(user="Der zu bannende User", reason="Grund")
    @app_commands.default_permissions(ban_members=True)
    async def slash_ban(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Kein Grund"):
        if not can_moderate(interaction.user, user):
            return await interaction.response.send_message("❌ Du kannst diesen User nicht moderieren.", ephemeral=True)

        try:
            await user.ban(reason=reason)
            case_id = await self.create_case(interaction.guild.id, user.id, interaction.user.id, "ban", reason)
            
            embed = get_embed("ban", user=user, mod=interaction.user, reason=reason)
            await interaction.response.send_message(embed=embed)
            
            # Log
            await self.bot.db.arecord_guild_event(interaction.guild.id, interaction.guild.name, interaction.guild.member_count, f"ban:{user.id}")
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

    @app_commands.command(name="kick", description="Kickt einen User")
    @app_commands.describe(user="Der zu kickende User", reason="Grund")
    @app_commands.default_permissions(kick_members=True)
    async def slash_kick(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Kein Grund"):
        if not can_moderate(interaction.user, user):
            return await interaction.response.send_message("❌ Du kannst diesen User nicht moderieren.", ephemeral=True)

        try:
            await user.kick(reason=reason)
            case_id = await self.create_case(interaction.guild.id, user.id, interaction.user.id, "kick", reason)
            
            embed = get_embed("kick", user=user, mod=interaction.user, reason=reason)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

    @app_commands.command(name="warn", description="Verwarnt einen User")
    @app_commands.describe(user="Der zu warnende User", reason="Grund")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_warn(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Kein Grund"):
        if not can_moderate(interaction.user, user):
            return await interaction.response.send_message("❌ Du kannst diesen User nicht moderieren.", ephemeral=True)

        case_id = await self.create_case(interaction.guild.id, user.id, interaction.user.id, "warn", reason)
        embed = get_embed("warn", user=user, mod=interaction.user, reason=reason)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mute", description="Mutet einen User")
    @app_commands.describe(user="Der zu mutende User", duration="Dauer (z.B. 1h, 30m)", reason="Grund")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_mute(self, interaction: discord.Interaction, user: discord.Member, duration: str = "1h", reason: str = "Kein Grund"):
        if not can_moderate(interaction.user, user):
            return await interaction.response.send_message("❌ Du kannst diesen User nicht moderieren.", ephemeral=True)

        seconds = parse_duration(duration)
        if not seconds:
            return await interaction.response.send_message("❌ Ungültige Dauer.", ephemeral=True)

        try:
            until = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
            await user.edit(timed_out_until=until, reason=reason)
            case_id = await self.create_case(interaction.guild.id, user.id, interaction.user.id, "mute", reason, seconds)
            
            embed = get_embed("mute", user=user, mod=interaction.user, reason=reason, duration=duration)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)
