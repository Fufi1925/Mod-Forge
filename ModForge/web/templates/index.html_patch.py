import re

with open('web/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Remove Live Logs
html = re.sub(r'<!-- ══════ DEMO TABS ══════ -->.*?<div class="divider"></div>\n', '', html, flags=re.DOTALL)
html = re.sub(r'/\* ── 12\. DEMO TABS \+ LIVE LOG RENDERER ── \*/.*?\n\n', '\n', html, flags=re.DOTALL)

with open('web/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("index.html gepatcht")
