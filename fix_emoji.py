"""Replace all supplementary-plane Unicode characters (U+10000+) 
in webapp/templates.py with HTML entities."""
import re

filepath = 'webapp/templates.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Add encoding declaration if missing
if not content.startswith('# -*- coding: utf-8 -*-'):
    content = '# -*- coding: utf-8 -*-\n' + content

# Replace all characters with codepoint > U+FFFF with HTML entities
def replace_supplementary(m):
    cp = ord(m.group())
    return '&#x{:X};'.format(cp)

new_content = re.sub(r'[\U00010000-\U0010FFFF]', replace_supplementary, content)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_content)

# Count replacements
old_count = len(re.findall(r'[\U00010000-\U0010FFFF]', content))
print('Fixed. Replaced {} supplementary-plane characters with HTML entities.'.format(old_count))