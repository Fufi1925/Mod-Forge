import re

with open("bot/bot.py", "r", encoding="utf-8") as f:
    text = f.read()

# Make help command show /setup_tempvoice
help_tv = '`/setup_tempvoice`'
if help_tv not in text:
    text = text.replace('`/ticket-setup` `/verify-setup` `/logban` `/help`', '`/ticket-setup` `/verify-setup` `/setup_tempvoice`\n            `/logban` `/help`')

with open("bot/bot.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Help command patched.")
