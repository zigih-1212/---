"""Replace all non-ASCII characters in webapp/templates.py with HTML entities."""
import re

filepath = 'webapp/templates.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Add encoding declaration if missing
if not content.startswith('# -*- coding: utf-8 -*-'):
    content = '# -*- coding: utf-8 -*-\n' + content

# Replace all characters with codepoint > 127 (non-ASCII) with HTML entities
def replace_non_ascii(m):
    cp = ord(m.group())
    return '&#x{:X};'.format(cp)

# Regex to match individual non-ASCII characters
new_content = re.sub(r'[^\x00-\x7F]', replace_non_ascii, content)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_content)

# Count replacements
old_count = len(re.findall(r'[^\x00-\x7F]', content))
print('Fixed. Replaced {} non-ASCII characters with HTML entities.'.format(old_count))