# -*- coding: utf-8 -*-
import os
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_FILE = os.path.join(SCRIPT_DIR, 'bot', 'bot.py')

with open(BOT_FILE, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace TempVoiceMenuView back with TempVoiceView
text = text.replace('self.add_view(TempVoiceMenuView(self))', 'self.add_view(TempVoiceView(self))')

with open(BOT_FILE, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed TempVoiceMenuView NameError.")
