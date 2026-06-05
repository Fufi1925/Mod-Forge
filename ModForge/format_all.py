import re
import glob

def fix_colons(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Match `if X: Y` and replace with `if X:\n    Y`
    # Also handle `elif X: Y`, `except Exception: pass`
    # Only if Y is not empty and on the same line
    
    # 1. except Exception: pass -> except Exception:\n    pass
    content = re.sub(r'([ \t]*)except (?:Exception)?:[ \t]+([^\n]+)', r'\1except Exception:\n\1    \2', content)

    # 2. if X: Y -> if X:\n    Y
    # Watch out for cases like "if cond: break" or "if cond: return"
    # We will just use autopep8 or something... wait, no, autopep8 isn't here. Let's just fix the specific known bad patterns in web/routes.py and bot/bot.py.
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

fix_colons('web/routes.py')
fix_colons('bot/bot.py')
print("Done")
