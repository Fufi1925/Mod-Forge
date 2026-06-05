import re

with open('bot/bot.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Replace any: await interaction.response.send_message(f"{E.OK}...", ephemeral=True)
pattern_ok = r'await interaction\.response\.send_message\(\s*(f?"(?:\{E\.OK\}|✅)\s*(.*?)")\s*,\s*ephemeral=(True|False)\s*\)'
def repl_ok(m):
    msg = m.group(1)
    eph = m.group(3)
    return f'await interaction.response.send_message(embed=discord.Embed(title="✅ Erfolg", description={msg}, color=COLOR_SUCCESS), ephemeral={eph})'

text = re.sub(pattern_ok, repl_ok, text)

# Replace any: await interaction.response.send_message(f"{E.FAIL}...", ephemeral=True)
pattern_fail = r'await interaction\.response\.send_message\(\s*(f?"(?:\{E\.FAIL\}|❌)\s*(.*?)")\s*,\s*ephemeral=(True|False)\s*\)'
def repl_fail(m):
    msg = m.group(1)
    eph = m.group(3)
    return f'await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description={msg}, color=COLOR_DANGER), ephemeral={eph})'

text = re.sub(pattern_fail, repl_fail, text)

# Replace any: await interaction.response.send_message(f"Fehler: ...", ephemeral=True)
pattern_err = r'await interaction\.response\.send_message\(\s*(f?"Fehler:.*?")\s*,\s*ephemeral=(True|False)\s*\)'
def repl_err(m):
    msg = m.group(1)
    eph = m.group(2)
    return f'await interaction.response.send_message(embed=discord.Embed(title="❌ Fehler", description={msg}, color=COLOR_DANGER), ephemeral={eph})'

text = re.sub(pattern_err, repl_err, text)

with open('bot/bot.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
