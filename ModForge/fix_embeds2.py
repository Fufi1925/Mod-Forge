import re

with open('bot/bot.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Ersetze await interaction.response.send_message(f"Fehler: {e}", ephemeral=True)
pattern_fehler = r'await interaction\.response\.send_message\(\s*f"Fehler: \{[a-zA-Z0-9_]+\}"\s*,\s*ephemeral=True\s*\)'
def repl_fehler(m):
    return m.group(0).replace('f"Fehler:', 'embed=discord.Embed(title="❌ Fehler", description=f"Ein Fehler ist aufgetreten:').replace('", ephemeral', '", color=COLOR_DANGER), ephemeral')

text = re.sub(pattern_fehler, repl_fehler, text)

with open('bot/bot.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
