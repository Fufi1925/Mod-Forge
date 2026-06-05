import re

with open('web/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Remove Before/After Slider
html = re.sub(r'<!-- ══════ BEFORE / AFTER SLIDER \(NEU\) ══════ -->.*?<div class="divider"></div>\n', '', html, flags=re.DOTALL)
html = re.sub(r'/\* ════════════════════════════════════════════\n   23\. BEFORE/AFTER SLIDER\n═══════════════════════════════════════════════ \*/.*?\ninitBaSlider\(\);\n', '', html, flags=re.DOTALL)

# Remove Benchmark
html = re.sub(r'<!-- ══════ BENCHMARK \(NEU\) ══════ -->.*?<div class="divider"></div>\n', '', html, flags=re.DOTALL)
html = re.sub(r'/\* ════════════════════════════════════════════\n   24\. BENCHMARK\n═══════════════════════════════════════════════ \*/.*?\n\}\n', '', html, flags=re.DOTALL)

# Remove Security Calculator
html = re.sub(r'<!-- ══════ NEUES EIGENES FEATURE: SECURITY CALCULATOR ══════ -->.*?<div class="divider"></div>\n', '', html, flags=re.DOTALL)
html = re.sub(r'/\* ════════════════════════════════════════════\n   31\. SECURITY CALCULATOR \(NEUES EIGENES FEATURE\)\n═══════════════════════════════════════════════ \*/.*?\n\};\n', '', html, flags=re.DOTALL)

with open('web/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Stripped features from index.html.")
