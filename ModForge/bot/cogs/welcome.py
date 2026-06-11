# -*- coding: utf-8 -*-
"""ModForge Welcome Cog – Welcome/Leave System, Auto-Roles, Sticky Roles."""
import discord
from discord.ext import commands
from discord import app_commands

from bot.config import COLOR_PRIMARY, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING, COLOR_INFO, E, log
from bot.utils import create_embed


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

        replacements = {
            "{mention}": member.mention,
            "{user}": str(member),
            "{server}": member.guild.name,
            "{count}": str(member.guild.member_count),
            "{username}": member.name,
        }

        title = welcome.get("embed_title", "👋 Willkommen!")
        desc = welcome.get("embed_description", "Willkommen {mention}!")
        for k, v in replacements.items():
            title = title.replace(k, v)
            desc = desc.replace(k, v)

        try:
            color_str = welcome.get("embed_color", "#22c55e")
            color = int(color_str.lstrip("#"), 16)
        except (ValueError, AttributeError):
            color = 0x22c55e

        if welcome.get("embed", True):
            embed = discord.Embed(title=title, description=desc, color=color)
            if welcome.get("embed_thumbnail") and member.display_avatar:
                embed.set_thumbnail(url=member.display_avatar.url)
            if welcome.get("embed_image"):
                embed.set_image(url=welcome["embed_image"])
            content = member.mention if welcome.get("mention") else None
            try:
                await channel.send(content=content, embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
        else:
            try:
                await channel.send(desc)
            except (discord.Forbidden, discord.HTTPException):
                pass

        # DM
        if welcome.get("dm_enabled") and welcome.get("dm_description"):
            dm_desc = welcome["dm_description"]
            for k, v in replacements.items():
                dm_desc = dm_desc.replace(k, v)
            try:
                from bot.bot import safe_dm
                embed = discord.Embed(title=f"👋 Willkommen auf {member.guild.name}!",
                                      description=dm_desc, color=color)
                await safe_dm(member, embed)
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

        replacements = {
            "{user}": str(member),
            "{server}": member.guild.name,
            "{count}": str(member.guild.member_count),
            "{username}": member.name,
        }

        title = leave.get("embed_title", "👋 Auf Wiedersehen!")
        desc = leave.get("embed_description", "**{user}** hat den Server verlassen.")
        for k, v in replacements.items():
            title = title.replace(k, v)
            desc = desc.replace(k, v)

        try:
            color_str = leave.get("embed_color", "#ef4444")
            color = int(color_str.lstrip("#"), 16)
        except (ValueError, AttributeError):
            color = 0xef4444

        if leave.get("embed", True):
            embed = discord.Embed(title=title, description=desc, color=color)
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
        cfg.setdefault("welcome", {})["channel_id"] = channel.id
        cfg["welcome"]["enabled"] = True
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Welcome-Kanal", f"Gesetzt auf {channel.mention}", COLOR_SUCCESS))

    @app_commands.command(name="leave_channel", description="Setzt den Leave-Kanal")
    @app_commands.describe(channel="Der Kanal")
    @app_commands.default_permissions(administrator=True)
    async def slash_leave_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = self.bot.db.get_config(interaction.guild.id)
        cfg.setdefault("leave", {})["channel_id"] = channel.id
        cfg["leave"]["enabled"] = True
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Leave-Kanal", f"Gesetzt auf {channel.mention}", COLOR_SUCCESS))

    @app_commands.command(name="autorole", description="Auto-Rolle bei Join setzen")
    @app_commands.describe(role="Die Rolle")
    @app_commands.default_permissions(administrator=True)
    async def slash_autorole(self, interaction: discord.Interaction, role: discord.Role):
        cfg = self.bot.db.get_config(interaction.guild.id)
        roles = cfg.get("welcome", {}).get("add_roles", [])
        if role.id not in roles:
            roles.append(role.id)
        cfg.setdefault("welcome", {})["add_roles"] = roles
        await self.bot.db.set_config(interaction.guild.id, cfg)
        await interaction.response.send_message(embed=create_embed(
            f"{E.OK} Auto-Role hinzugefügt", f"{role.mention}", COLOR_SUCCESS))

    @app_commands.command(name="stickyrole", description="Sticky-Rolle konfigurieren")
    @app_commands.describe(role="Die Rolle", action="add/remove/list")
    @app_commands.default_permissions(administrator=True)
    async def slash_stickyrole(self, interaction: discord.Interaction, action: str, role: discord.Role = None):
        cfg = self.bot.db.get_config(interaction.guild.id)
        sticky = cfg.get("sticky_roles", [])
        if action == "add" and role:
            if role.id not in sticky:
                sticky.append(role.id)
            cfg["sticky_roles"] = sticky
            await self.bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Sticky-Role", f"{role.mention} hinzugefügt.", COLOR_SUCCESS))
        elif action == "remove" and role:
            sticky = [r for r in sticky if r != role.id]
            cfg["sticky_roles"] = sticky
            await self.bot.db.set_config(interaction.guild.id, cfg)
            await interaction.response.send_message(embed=create_embed(
                f"{E.OK} Sticky-Role", f"{role.mention} entfernt.", COLOR_SUCCESS))
        elif action == "list":
            if not sticky:
                return await interaction.response.send_message(embed=create_embed(
                    f"{E.ROLE}", "Keine Sticky-Roles.", COLOR_INFO))
            roles_text = ", ".join(f"<@&{r}>" for r in sticky)
            await interaction.response.send_message(embed=create_embed(
                f"{E.ROLE} Sticky-Roles", roles_text, COLOR_PRIMARY))


async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
