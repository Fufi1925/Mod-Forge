import re

with open('bot/bot.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Replace TempVoiceMenuView back with TempVoiceView
text = text.replace('self.add_view(TempVoiceMenuView(self))', 'self.add_view(TempVoiceView(self))')

with open('bot/bot.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed TempVoiceMenuView NameError.")
