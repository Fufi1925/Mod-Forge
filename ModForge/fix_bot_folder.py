import os
import shutil

# Make sure all duplicate/unwanted files are removed.
def cleanup():
    unwanted = ['bot/run.py', 'bot/bot_patch.py', 'bot/fix_*.py']
    for u in unwanted:
        if os.path.exists(u):
            os.remove(u)
cleanup()
print("Cleaned up bot directory.")
