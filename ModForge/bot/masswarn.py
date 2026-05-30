import discord
from discord.ext import commands
from bot.config import COLOR_WARNING, E
from bot.utils import create_embed

async def execute_masswarn(bot, interaction, members, reason):
    count = 0
    for m in members:
        try:
            await bot.db.aadd_warning(interaction.guild.id, m.id, reason, interaction.user.id)
            count += 1
        except:
            pass
    return count
