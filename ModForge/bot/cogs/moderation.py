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


def has_mod_perms() -> Callable:
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.kick_members:
            return True
        cfg = ctx.bot.db.get_config(ctx.guild.id)
        mod_role_id = cfg.get("mod_role")
        return mod_role_id and discord.utils.get(ctx.author.roles, id=mod_role_id) is not None
    return commands.check(predicate)

def has_admin_perms() -> Callable:
    async def predicate(ctx: commands.Context) -> bool:
        return ctx.author.guild_permissions.administrator or ctx.author.id == _BOT_DEV_ID
    return commands.check(predicate)


class ModerationCog(commands.Cog):
    """Ban, Kick, Warn, Mute und weitere Moderations-Commands."""
    
    def __init__(self, bot):
        self.bot = bot

    # ── PREFIX COMMANDS ──
    @commands.command(name="ban")
    @has_mod_perms()
    async def prefix_ban(self, ctx, member: discord.Member, *, reason: str = "Kein Grund angegeben"):
        ok, why = can_moderate(ctx.author, member, ctx.guild.me)
        if not ok:
            return await ctx.send(embed=create_embed(f"{E.FAIL} Fehler", why, COLOR_DANGER))
        case_id = await self.bot.punish(member, "ban", reason, moderator_id=ctx.author.id)
        await ctx.send(embed=create_embed(f"{E.OK} Gebannt", f"{member.mention} – {reason}\nCase: #{case_id}", COLOR_SUCCESS))

    @commands.command(name="kick")
    @has_mod_perms()
    async def prefix_kick(self, ctx, member: discord.Member, *, reason: str = "Kein Grund angegeben"):
        ok, why = can_moderate(ctx.author, member, ctx.guild.me)
        if not ok:
            return await ctx.send(embed=create_embed(f"{E.FAIL} Fehler", why, COLOR_DANGER))
        case_id = await self.bot.punish(member, "kick", reason, moderator_id=ctx.author.id)
        await ctx.send(embed=create_embed(f"{E.OK} Gekickt", f"{member.mention} – {reason}\nCase: #{case_id}", COLOR_SUCCESS))

    @commands.command(name="warn")
    @has_mod_perms()
    async def prefix_warn(self, ctx, member: discord.Member, *, reason: str = "Kein Grund angegeben"):
        ok, why = can_moderate(ctx.author, member, ctx.guild.me)
        if not ok:
            return await ctx.send(embed=create_embed(f"{E.FAIL} Fehler", why, COLOR_DANGER))
        case_id = await self.bot.punish(member, "warn", reason, moderator_id=ctx.author.id)
        await ctx.send(embed=create_embed(f"{E.WARN} Verwarnt", f"{member.mention} – {reason}\nCase: #{case_id}", COLOR_WARNING))

    @commands.command(name="mute")
    @has_mod_perms()
    async def prefix_mute(self, ctx, member: discord.Member, duration: int = 60, *, reason: str = "Kein Grund"):
        ok, why = can_moderate(ctx.author, member, ctx.guild.me)
        if not ok:
            return await ctx.send(embed=create_embed(f"{E.FAIL} Fehler", why, COLOR_DANGER))
        case_id = await self.bot.punish(member, "timeout", reason, duration=duration, moderator_id=ctx.author.id)
        await ctx.send(embed=create_embed(f"{E.MUTE} Gemutet", f"{member.mention} für {duration}s – {reason}\nCase: #{case_id}", COLOR_WARNING))

    @commands.command(name="unmute")
    @has_mod_perms()
    async def prefix_unmute(self, ctx, member: discord.Member):
        try:
            await member.timeout(None, reason=f"Entmutet von {ctx.author}")
            await ctx.send(embed=create_embed(f"{E.UNMUTE} Entmutet", f"{member.mention}", COLOR_SUCCESS))
        except discord.Forbidden:
            await ctx.send(embed=create_embed(f"{E.FAIL} Fehler", "Keine Berechtigung.", COLOR_DANGER))

    @commands.command(name="clear")
    @has_mod_perms()
    async def prefix_clear(self, ctx, amount: int = 10):
        try:
            deleted = await ctx.channel.purge(limit=min(amount + 1, 101))
            await ctx.send(embed=create_embed(f"{E.OK} Gelöscht", f"{len(deleted) - 1} Nachrichten entfernt.", COLOR_SUCCESS), delete_after=5)
        except discord.Forbidden:
            await ctx.send(embed=create_embed(f"{E.FAIL} Fehler", "Keine Berechtigung.", COLOR_DANGER))

    @commands.command(name="slowmode")
    @has_mod_perms()
    async def prefix_slowmode(self, ctx, seconds: int = 0):
        await ctx.channel.edit(slowmode_delay=min(max(seconds, 0), 21600))
        await ctx.send(embed=create_embed(f"{E.SLOW} Slowmode", f"Auf {seconds}s gesetzt.", COLOR_SUCCESS))

    @commands.command(name="lock")
    @has_mod_perms()
    async def prefix_lock(self, ctx):
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False, reason=f"Gesperrt von {ctx.author}")
        await ctx.send(embed=create_embed(f"{E.LOCK} Gesperrt", f"{ctx.channel.mention} ist gesperrt.", COLOR_WARNING))

    @commands.command(name="unlock")
    @has_mod_perms()
    async def prefix_unlock(self, ctx):
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None, reason=f"Entsperrt von {ctx.author}")
        await ctx.send(embed=create_embed(f"{E.UNLOCK} Entsperrt", f"{ctx.channel.mention} ist entsperrt.", COLOR_SUCCESS))

    @commands.command(name="warnings")
    @has_mod_perms()
    async def prefix_warnings(self, ctx, member: discord.Member):
        cfg = self.bot.db.get_config(ctx.guild.id)
        warns = cfg.get("warns", {}).get(str(member.id), [])
        if not warns:
            return await ctx.send(embed=create_embed(f"{E.OK} Keine Verwarnungen", f"{member.mention} hat keine Verwarnungen.", COLOR_SUCCESS))
        lines = [f"`{i+1}.` {w.get('reason', '—')}" for i, w in enumerate(warns)]
        await ctx.send(embed=create_embed(f"{E.WARN} Verwarnungen ({len(warns)})", "\n".join(lines), COLOR_WARNING))

    @commands.command(name="clearwarnings")
    @has_mod_perms()
    async def prefix_clearwarnings(self, ctx, member: discord.Member):
        cfg = self.bot.db.get_config(ctx.guild.id)
        cfg.setdefault("warns", {})[str(member.id)] = []
        await self.bot.db.set_config(ctx.guild.id, cfg)
        await ctx.send(embed=create_embed(f"{E.OK} Verwarnungen gelöscht", f"{member.mention}", COLOR_SUCCESS))

    @commands.command(name="unban")
    @has_mod_perms()
    async def prefix_unban(self, ctx, user_id: int):
        try:
            await ctx.guild.unban(discord.Object(id=user_id), reason=f"Entbannt von {ctx.author}")
            await ctx.send(embed=create_embed(f"{E.OK} Entbannt", f"User `{user_id}` entbannt.", COLOR_SUCCESS))
        except discord.NotFound:
            await ctx.send(embed=create_embed(f"{E.FAIL} Fehler", "User nicht gebannt.", COLOR_DANGER))

    @commands.command(name="nick")
    @has_mod_perms()
    async def prefix_nick(self, ctx, member: discord.Member, *, nickname: str = None):
        try:
            await member.edit(nick=nickname, reason=f"Von {ctx.author}")
            await ctx.send(embed=create_embed(f"{E.OK} Nickname geändert", f"{member.mention} → {nickname or '*Zurückgesetzt*'}", COLOR_SUCCESS))
        except discord.Forbidden:
            await ctx.send(embed=create_embed(f"{E.FAIL} Fehler", "Keine Berechtigung.", COLOR_DANGER))

    # ── SLASH COMMANDS ──
    @app_commands.command(name="ban", description="Bannt einen Nutzer vom Server")
    @app_commands.describe(member="Der Nutzer", reason="Grund", delete_days="Nachrichten löschen (Tage)")
    @app_commands.default_permissions(ban_members=True)
    async def slash_ban(self, interaction: discord.Interaction, member: discord.Member,
                        reason: str = "Kein Grund", delete_days: int = 1):
        ok, why = can_moderate(interaction.user, member, interaction.guild.me)
        if not ok:
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Fehler", why, COLOR_DANGER), ephemeral=True)
        case_id = await self.bot.punish(member, "ban", reason, moderator_id=interaction.user.id)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Gebannt",
            f"{member.mention} – {reason}\nCase: #{case_id}", COLOR_SUCCESS))
        await self.bot.log_action(interaction.guild, f"{E.BAN} Ban", f"{member.mention} von {interaction.user.mention}\nGrund: {reason}",
            COLOR_DANGER, user=member, module="moderation")

    @app_commands.command(name="kick", description="Kickt einen Nutzer vom Server")
    @app_commands.describe(member="Der Nutzer", reason="Grund")
    @app_commands.default_permissions(kick_members=True)
    async def slash_kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund"):
        ok, why = can_moderate(interaction.user, member, interaction.guild.me)
        if not ok:
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Fehler", why, COLOR_DANGER), ephemeral=True)
        case_id = await self.bot.punish(member, "kick", reason, moderator_id=interaction.user.id)
        await interaction.response.send_message(embed=create_embed(f"{E.OK} Gekickt",
            f"{member.mention} – {reason}\nCase: #{case_id}", COLOR_SUCCESS))

    @app_commands.command(name="warn", description="Verwarnt einen Nutzer")
    @app_commands.describe(member="Der Nutzer", reason="Grund")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Kein Grund"):
        ok, why = can_moderate(interaction.user, member, interaction.guild.me)
        if not ok:
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Fehler", why, COLOR_DANGER), ephemeral=True)
        case_id = await self.bot.punish(member, "warn", reason, moderator_id=interaction.user.id)
        cfg = self.bot.db.get_config(interaction.guild.id)
        warns = cfg.get("warns", {}).get(str(member.id), [])
        await interaction.response.send_message(embed=create_embed(f"{E.WARN} Verwarnt",
            f"{member.mention} – {reason}\nCase: #{case_id}\nVerwarnungen: {len(warns)}", COLOR_WARNING))

    @app_commands.command(name="mute", description="Mutet einen Nutzer (Timeout)")
    @app_commands.describe(member="Der Nutzer", duration="Dauer in Sekunden", reason="Grund")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_mute(self, interaction: discord.Interaction, member: discord.Member,
                         duration: int = 60, reason: str = "Kein Grund"):
        ok, why = can_moderate(interaction.user, member, interaction.guild.me)
        if not ok:
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Fehler", why, COLOR_DANGER), ephemeral=True)
        case_id = await self.bot.punish(member, "timeout", reason, duration=duration, moderator_id=interaction.user.id)
        await interaction.response.send_message(embed=create_embed(f"{E.MUTE} Gemutet",
            f"{member.mention} für {duration}s – {reason}\nCase: #{case_id}", COLOR_WARNING))

    @app_commands.command(name="unmute", description="Entmutet einen Nutzer")
    @app_commands.describe(member="Der Nutzer")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_unmute(self, interaction: discord.Interaction, member: discord.Member):
        try:
            await member.timeout(None, reason=f"Entmutet von {interaction.user}")
            await interaction.response.send_message(embed=create_embed(f"{E.UNMUTE} Entmutet", f"{member.mention}", COLOR_SUCCESS))
        except discord.Forbidden:
            await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Fehler", "Keine Berechtigung.", COLOR_DANGER), ephemeral=True)

    @app_commands.command(name="clear", description="Löscht Nachrichten im Kanal")
    @app_commands.describe(amount="Anzahl der Nachrichten")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_clear(self, interaction: discord.Interaction, amount: int = 10):
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=min(amount, 100))
            await interaction.followup.send(embed=create_embed(f"{E.OK} Gelöscht", f"{len(deleted)} Nachrichten.", COLOR_SUCCESS))
        except discord.Forbidden:
            await interaction.followup.send(embed=create_embed(f"{E.FAIL} Fehler", "Keine Berechtigung.", COLOR_DANGER))

    @app_commands.command(name="warnings", description="Zeigt Verwarnungen eines Nutzers")
    @app_commands.describe(member="Der Nutzer")
    @app_commands.default_permissions(manage_messages=True)
    async def slash_warnings(self, interaction: discord.Interaction, member: discord.Member):
        cfg = self.bot.db.get_config(interaction.guild.id)
        warns = cfg.get("warns", {}).get(str(member.id), [])
        if not warns:
            return await interaction.response.send_message(embed=create_embed(f"{E.OK}", f"{member.mention} hat keine Verwarnungen.", COLOR_SUCCESS))
        lines = [f"`{i+1}.` {w.get('reason', '—')}" for i, w in enumerate(warns)]
        await interaction.response.send_message(embed=create_embed(f"{E.WARN} Verwarnungen ({len(warns)})", "\n".join(lines), COLOR_WARNING))

    @app_commands.command(name="softban", description="Ban+Unban (löscht Nachrichten)")
    @app_commands.describe(member="Der Nutzer", reason="Grund", days="Tage Nachrichten löschen")
    @app_commands.default_permissions(ban_members=True)
    async def slash_softban(self, interaction: discord.Interaction, member: discord.Member,
                            reason: str = "Softban", days: int = 1):
        ok, why = can_moderate(interaction.user, member, interaction.guild.me)
        if not ok:
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL} Fehler", why, COLOR_DANGER), ephemeral=True)
        try:
            await member.ban(reason=f"Softban: {reason}", delete_message_seconds=days * 86400)
            await interaction.guild.unban(member, reason="Softban (auto-unban)")
            case_id = await self.bot.db.acreate_case(interaction.guild.id, member.id, interaction.user.id, "softban", reason)
            await interaction.response.send_message(embed=create_embed(f"{E.OK} Softban",
                f"{member.mention} – {reason}\nCase: #{case_id}", COLOR_SUCCESS))
        except discord.Forbidden:
            await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Keine Berechtigung.", COLOR_DANGER), ephemeral=True)

    @app_commands.command(name="tempban", description="Bannt einen Nutzer temporär")
    @app_commands.describe(member="Der Nutzer", duration="Dauer (z.B. 1d, 2h, 30m)", reason="Grund")
    @app_commands.default_permissions(ban_members=True)
    async def slash_tempban(self, interaction: discord.Interaction, member: discord.Member,
                            duration: str = "1d", reason: str = "Tempban"):
        ok, why = can_moderate(interaction.user, member, interaction.guild.me)
        if not ok:
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", why, COLOR_DANGER), ephemeral=True)
        seconds = parse_duration(duration)
        if not seconds:
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Ungültige Dauer.", COLOR_DANGER), ephemeral=True)
        try:
            await member.ban(reason=f"Tempban ({duration}): {reason}", delete_message_seconds=86400)
            end_time = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
            await self.bot.db.tempactions.insert_one({
                "guild_id": interaction.guild.id, "user_id": member.id, "action": "tempban",
                "end_time": end_time, "reason": reason, "mod_id": interaction.user.id, "active": True})
            case_id = await self.bot.db.acreate_case(interaction.guild.id, member.id, interaction.user.id, "tempban", reason, duration=seconds)
            await interaction.response.send_message(embed=create_embed(f"{E.OK} Tempban",
                f"{member.mention} für {duration} – {reason}\nCase: #{case_id}", COLOR_SUCCESS))
        except discord.Forbidden:
            await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Keine Berechtigung.", COLOR_DANGER), ephemeral=True)

    @app_commands.command(name="tempmute", description="Persistenter Timeout (überlebt Neustart)")
    @app_commands.describe(member="Der Nutzer", duration="Dauer (z.B. 1d, 2h)", reason="Grund")
    @app_commands.default_permissions(moderate_members=True)
    async def slash_tempmute(self, interaction: discord.Interaction, member: discord.Member,
                             duration: str = "1h", reason: str = "Tempmute"):
        ok, why = can_moderate(interaction.user, member, interaction.guild.me)
        if not ok:
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", why, COLOR_DANGER), ephemeral=True)
        seconds = parse_duration(duration)
        if not seconds:
            return await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Ungültige Dauer.", COLOR_DANGER), ephemeral=True)
        try:
            end_time = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
            await member.timeout(end_time, reason=reason)
            await self.bot.db.tempactions.insert_one({
                "guild_id": interaction.guild.id, "user_id": member.id, "action": "tempmute",
                "end_time": end_time, "reason": reason, "mod_id": interaction.user.id, "active": True})
            case_id = await self.bot.db.acreate_case(interaction.guild.id, member.id, interaction.user.id, "tempmute", reason, duration=seconds)
            await interaction.response.send_message(embed=create_embed(f"{E.MUTE} Tempmute",
                f"{member.mention} für {duration} – {reason}\nCase: #{case_id}", COLOR_WARNING))
        except discord.Forbidden:
            await interaction.response.send_message(embed=create_embed(f"{E.FAIL}", "Keine Berechtigung.", COLOR_DANGER), ephemeral=True)


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
