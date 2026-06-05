# -*- coding: utf-8 -*-
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_FILE = os.path.join(SCRIPT_DIR, 'bot', 'bot.py')

with open(BOT_FILE, 'r', encoding='utf-8') as f:
    text = f.read()

text = re.sub(r'class TempVoiceDropdown.*?view=None\)\n\n', '', text, flags=re.DOTALL)
text = re.sub(r'class TempVoiceMenuView\(discord\.ui\.View\):.*?ephemeral=True\)\n\n', '', text, flags=re.DOTALL)
text = re.sub(r'@bot\.tree\.command\(name="tempvoice_setup", description="Richtet temporäre Voice-Kanäle ein"\).*?module="moderation"\)\n', '', text, flags=re.DOTALL)

with open(BOT_FILE, 'w', encoding='utf-8') as f:
    f.write(text)
print("Old classes removed.")
