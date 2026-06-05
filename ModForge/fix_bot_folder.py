# -*- coding: utf-8 -*-
import os
import glob
import shutil

def cleanup():
    """Make sure all duplicate/unwanted files are removed."""
    unwanted = ['bot/run.py', 'bot/bot_patch.py']
    for u in unwanted:
        if os.path.exists(u):
            os.remove(u)
    # Handle glob patterns properly
    for pattern in ['bot/fix_*.py']:
        for f in glob.glob(pattern):
            os.remove(f)

cleanup()
print("Cleaned up bot directory.")
