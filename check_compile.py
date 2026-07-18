import py_compile
import traceback

try:
    py_compile.compile('webapp/templates.py', doraise=True)
    with open('err.txt', 'w', encoding='utf-8') as f:
        f.write("OK: no syntax errors\n")
except Exception:
    with open('err.txt', 'w', encoding='utf-8') as f:
        f.write(traceback.format_exc())