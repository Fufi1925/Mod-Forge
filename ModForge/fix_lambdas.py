
def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if 'check_fn = lambda m: m.author.bot' in line:
            new_lines.append('        def check_fn(m): return m.author.bot\n')
        elif 'check_fn = lambda m: "http" in m.content.lower()' in line:
            new_lines.append('        def check_fn(m): return "http" in m.content.lower()\n')
        elif 'check_fn = lambda m: len(m.attachments) > 0' in line:
            new_lines.append('        def check_fn(m): return len(m.attachments) > 0\n')
        elif 'check_fn = lambda m: m.author.id == uid' in line:
            new_lines.append('        def check_fn(m): return m.author.id == uid\n')
        elif 'check_fn = lambda m: True' in line:
            new_lines.append('        def check_fn(m): return True\n')
        else:
            new_lines.append(line)
        i += 1
            
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

fix_file('bot/bot.py')
