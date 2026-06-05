import re

with open('bot/bot.py', 'r', encoding='utf-8') as f:
    text = f.read()

bad_string = '''            "`/ticket-setup` `/verify-setup` `/setup_tempvoice`
            `/logban` `/help`"'''

good_string = '''            "`/ticket-setup` `/verify-setup` `/setup_tempvoice`\\n"\n            "`/logban` `/help`"'''

if bad_string in text:
    text = text.replace(bad_string, good_string)

with open('bot/bot.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Syntax fixed")
