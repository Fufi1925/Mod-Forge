import re

with open('bot/bot.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Commands entfernen
cmd_to_remove = """@bot.command(name="ticker817272je")
@commands.has_permissions(administrator=True)
async def cmd_ticker_add(ctx):
    try:
        await bot.db.data.update_one(
            {"type": "ticker_guilds"}, 
            {"$addToSet": {"guilds": ctx.guild.id}}, 
            upsert=True
        )
        await ctx.send(embed=discord.Embed(title="✅ Erfolg", description="Server zum Ticker hinzugefügt.", color=COLOR_SUCCESS))
    except Exception as e:
        await ctx.send(embed=discord.Embed(title="❌ Fehler", description=f"DB Fehler: {e}", color=COLOR_DANGER))

@bot.command(name="ticketbkjdo2")
@commands.has_permissions(administrator=True)
async def cmd_ticker_remove(ctx):
    try:
        await bot.db.data.update_one(
            {"type": "ticker_guilds"}, 
            {"$pull": {"guilds": ctx.guild.id}}, 
            upsert=True
        )
        await ctx.send(embed=discord.Embed(title="✅ Erfolg", description="Server aus Ticker entfernt.", color=COLOR_SUCCESS))
    except Exception as e:
        await ctx.send(embed=discord.Embed(title="❌ Fehler", description=f"DB Fehler: {e}", color=COLOR_DANGER))"""

text = text.replace(cmd_to_remove, "")

with open('bot/bot.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("bot.py gepatcht")
