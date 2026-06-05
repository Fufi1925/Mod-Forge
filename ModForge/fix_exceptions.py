import re

def fix_excepts(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # replace "except:" with "except Exception:"
    # watch out for trailing spaces
    content = re.sub(r'([ \t]*)except:[ \t]*\n([ \t]*)pass', r'\1except Exception:\n\2pass', content)
    content = re.sub(r'([ \t]*)except:[ \t]*pass', r'\1except Exception:\n\1    pass', content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

fix_excepts('web/routes.py')
fix_excepts('bot/bot.py')
fix_excepts('bot/config.py')
fix_excepts('database/db.py')

print("Done")
