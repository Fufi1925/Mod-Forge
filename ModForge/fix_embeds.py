import re

with open('bot/bot.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Ersetze await interaction.response.send_message(f"{E.FAIL} ...", ephemeral=True)
pattern_fail = r'await interaction\.response\.send_message\(\s*(f?"(?:\{E\.FAIL\}|❌)\s*(.*?)")\s*,\s*ephemeral=True\s*\)'
def repl_fail(m):
    msg = m.group(1)
    # The message itself is group 1
    return f'await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description={msg}, color=COLOR_DANGER), ephemeral=True)'

text = re.sub(pattern_fail, repl_fail, text)

# Ersetze f"{E.OK} ..."
pattern_ok = r'await interaction\.response\.send_message\(\s*(f?"(?:\{E\.OK\}|✅)\s*(.*?)")\s*,\s*ephemeral=True\s*\)'
def repl_ok(m):
    msg = m.group(1)
    return f'await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description={msg}, color=COLOR_SUCCESS), ephemeral=True)'

text = re.sub(pattern_ok, repl_ok, text)

with open('bot/bot.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
