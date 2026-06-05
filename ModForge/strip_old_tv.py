import re

with open('bot/bot.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = re.sub(r'class TempVoiceDropdown.*?view=None\)\n\n', '', text, flags=re.DOTALL)
text = re.sub(r'class TempVoiceMenuView\(discord\.ui\.View\):.*?ephemeral=True\)\n\n', '', text, flags=re.DOTALL)
text = re.sub(r'@bot\.tree\.command\(name="tempvoice_setup", description="Richtet temporäre Voice-Kanäle ein"\).*?module="moderation"\)\n', '', text, flags=re.DOTALL)

with open('bot/bot.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Old classes removed.")
