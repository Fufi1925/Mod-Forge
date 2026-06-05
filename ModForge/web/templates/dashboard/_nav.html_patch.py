import re

with open('web/templates/dashboard/_nav.html', 'r', encoding='utf-8') as f:
    text = f.read()

tv_link = '  <a href="/dashboard/{{ guild.id }}/tempvoice" {% if active == \'tempvoice\' %}class="active"{% endif %}>🎤 Temp-Voice</a>\n'

if 'tempvoice' not in text:
    text = text.replace('  <a href="/dashboard/{{ guild.id }}/tickets"', tv_link + '  <a href="/dashboard/{{ guild.id }}/tickets"')

with open('web/templates/dashboard/_nav.html', 'w', encoding='utf-8') as f:
    f.write(text)

with open('web/templates/dashboard/_base.html', 'r', encoding='utf-8') as f:
    text = f.read()

tv_link2 = '      <a href="/dashboard/{{ guild.id }}/tempvoice" {% if active==\'tempvoice\' %}class="active"{% endif %}><span class="nav-icon">🎤</span><span>Temp-Voice</span></a>\n'

if 'tempvoice' not in text:
    text = text.replace('      <a href="/dashboard/{{ guild.id }}/tickets"', tv_link2 + '      <a href="/dashboard/{{ guild.id }}/tickets"')

with open('web/templates/dashboard/_base.html', 'w', encoding='utf-8') as f:
    f.write(text)
print("Nav patched.")
