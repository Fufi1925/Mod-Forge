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


    def get_smart_mute_duration(self, guild_id: int, user_id: int) -> str:
        """Schlägt eine intelligente Mute-Dauer basierend auf vorherigen Cases vor."""
        try:
            cases = safe_async(self.bot.db.aget_recent_cases(guild_id, 20), [])
            user_cases = [c for c in cases if c.get("user_id") == user_id]
            
            if not user_cases:
                return "1h"  # Standard bei erstem Verstoß
            
            # Zähle vorherige Verstöße
            mute_count = len([c for c in user_cases if c.get("action") == "mute"])
            warn_count = len([c for c in user_cases if c.get("action") == "warn"])
            
            # Staff Application System (Bewerbungen über Dashboard + Review)
            if mute_count >= 3:
                return "7d"  # 3+ Mutes = 7 Tage
            elif mute_count >= 2:
                return "3d"  # 2 Mutes = 3 Tage
            elif mute_count >= 1:
                return "24h"  # 1 Mute = 24 Stunden
            elif warn_count >= 3:
                return "12h"
            else:
                return "1h"
        except:
            return "1h"


    async def create_case(self, guild_id: int, user_id: int, mod_id: int, action: str, reason: str, duration: int = None):
        """Erstellt einen Case in der Datenbank."""
        return await self.bot.db.acreate_case(guild_id, user_id, mod_id, action, reason, duration)

    async def _send_dm(self, user: discord.Member, embed_name: str, **kwargs):
        """Sendet ein DM-Embed an den User."""
        try:
            embed = get_embed(embed_name, **kwargs)
            await user.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @app_commands.command(name="ban", description="Bannt einen User")
    @app_commands.describe(user="Der zu bannende User", reason="Grund")
    @app_commands.default_permissions(ban_members=True)
    async def slash_ban(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Kein Grund"):
        if not can_moderate(interaction.user, user):
            embed = get_embed("error", message="Du kannst diesen User nicht moderieren.", user=interaction.user, bot=self.bot)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        try:
            await user.ban(reason=reason)
            case_id = await self.create_case(interaction.guild.id, user.id, interaction.user.id, "ban", reason)
            
            embed = get_embed("ban", user=user, mod=interaction.user, reason=reason, guild=interaction.guild, bot=self.bot)
            await interaction.response.send_message(embed=embed)
            
            await self._send_dm(user, "ban", user=user, mod=interaction.user, reason=reason, guild=interaction.guild, bot=self.bot)
            
            await self.bot.db.arecord_guild_event(interaction.guild.id, interaction.guild.name, interaction.guild.member_count, f"ban:{user.id}")
        except Exception as e:
            embed = get_embed("error", message=f"Fehler: {e}", user=interaction.user, bot=self.bot)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="kick", description="Kickt einen User")
    @app_commands.describe(user="Der zu kickende User", reason="Grund")
    @app_commands.default_permissions(kick_members=True)
    async def slash_kick(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Kein Grund"):
        if not can_moderate(interaction.user, user):
            embed = get_embed("error", message="Du kannst diesen User nicht moderieren.", user=interaction.user, bot=self.bot)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        try:
            await user.kick(reason=reason)
            case_id = await self.create_case(interaction.guild.id, user.id, interaction.user.id, "kick", reason)
            
            embed = get_embed("kick", user=user, mod=interaction.user, reason=reason, guild=interaction.guild, bot=self.bot)
            await interaction.response.send_message(embed=embed)
            
            await self._send_dm(user, "kick", user=user, mod=interaction.user, reason=reason, guild=interaction.guild, bot=self.bot)
        except Exception as e:
            embed = get_embed("error", message=f"Fehler: {e}", user=interaction.user, bot=self.bot)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="warn", description="Verwarnt einen User")
    @app_commands.describe(user="Der zu warnende User", reason="Grund")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_warn(self, interaction: discord.Interaction, user: discord.Member, reason: str = "Kein Grund"):
        if not can_moderate(interaction.user, user):
            embed = get_embed("error", message="Du kannst diesen User nicht moderieren.", user=interaction.user, bot=self.bot)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        case_id = await self.create_case(interaction.guild.id, user.id, interaction.user.id, "warn", reason)
        
        embed = get_embed("warn", user=user, mod=interaction.user, reason=reason, guild=interaction.guild, bot=self.bot)
        await interaction.response.send_message(embed=embed)
        
        await self._send_dm(user, "warn", user=user, mod=interaction.user, reason=reason, guild=interaction.guild, bot=self.bot)

    @app_commands.command(name="mute", description="Mutet einen User")
    @app_commands.describe(user="Der zu mutende User", duration="Dauer (z.B. 1h, 30m)", reason="Grund")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_mute(self, interaction: discord.Interaction, user: discord.Member, duration: str = "1h", reason: str = "Kein Grund"):
        if not can_moderate(interaction.user, user):
            embed = get_embed("error", message="Du kannst diesen User nicht moderieren.", user=interaction.user, bot=self.bot)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        seconds = parse_duration(duration)
        if not seconds:
            embed = get_embed("error", message="Ungültige Dauer.", user=interaction.user, bot=self.bot)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        try:
            until = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
            await user.edit(timed_out_until=until, reason=reason)
            case_id = await self.create_case(interaction.guild.id, user.id, interaction.user.id, "mute", reason, seconds)
            
            embed = get_embed("mute", user=user, mod=interaction.user, reason=reason, duration=duration, guild=interaction.guild, bot=self.bot)
            await interaction.response.send_message(embed=embed)
            
            await self._send_dm(user, "mute", user=user, mod=interaction.user, reason=reason, duration=duration, guild=interaction.guild, bot=self.bot)
        except Exception as e:
            embed = get_embed("error", message=f"Fehler: {e}", user=interaction.user, bot=self.bot)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="unmute", description="Entfernt den Timeout eines Users")
    @app_commands.describe(user="Der User")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_unmute(self, interaction: discord.Interaction, user: discord.Member):
        if not can_moderate(interaction.user, user):
            embed = get_embed("error", message="Du kannst diesen User nicht moderieren.", user=interaction.user, bot=self.bot)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        try:
            await user.edit(timed_out_until=None, reason="Timeout entfernt")
            
            embed = get_embed("success", message=f"Timeout von {user.mention} wurde entfernt.", user=user, bot=self.bot)
            await interaction.response.send_message(embed=embed)
            
            await self._send_dm(user, "success", message="Dein Timeout wurde entfernt.", user=user, bot=self.bot)
        except Exception as e:
            embed = get_embed("error", message=f"Fehler: {e}", user=interaction.user, bot=self.bot)
            await interaction.response.send_message(embed=embed, ephemeral=True)
