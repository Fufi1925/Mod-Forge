import re

with open('web/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Remove Drag & Drop
html = re.sub(r'<!-- ══════ DRAG & DROP MODULES \(NEU\) ══════ -->.*?<div class="divider"></div>\n', '', html, flags=re.DOTALL)
html = re.sub(r'/\* ════════════════════════════════════════════\n   20\. DRAG & DROP\n═══════════════════════════════════════════════ \*/.*?buildDnD\(\);\n', '', html, flags=re.DOTALL)

# Remove Replay
html = re.sub(r'<!-- ══════ REPLAY \(NEU\) ══════ -->.*?<div class="divider"></div>\n', '', html, flags=re.DOTALL)
html = re.sub(r'/\* ════════════════════════════════════════════\n   25\. REPLAY\n═══════════════════════════════════════════════ \*/.*?resetReplayVisual\(\)\}\n', '', html, flags=re.DOTALL)

# Remove Threat Map
html = re.sub(r'<!-- ══════ NEUES EIGENES FEATURE: LIVE THREAT MAP ══════ -->.*?<div class="divider"></div>\n', '', html, flags=re.DOTALL)
html = re.sub(r'/\* ════════════════════════════════════════════\n   30\. THREAT MAP \(NEUES EIGENES FEATURE\)\n═══════════════════════════════════════════════ \*/.*?\n\}\)\(\);\n', '', html, flags=re.DOTALL)

# Remove Roadmap
html = re.sub(r'<!-- ══════ ROADMAP \(NEU\) ══════ -->.*?<div class="divider"></div>\n', '', html, flags=re.DOTALL)
html = re.sub(r'/\* ════════════════════════════════════════════\n   28\. ROADMAP\n═══════════════════════════════════════════════ \*/.*?\n\}\)\(\);\n', '', html, flags=re.DOTALL)

with open('web/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Stripped sections.")
