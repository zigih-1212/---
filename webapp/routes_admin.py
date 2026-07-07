# webapp/routes_admin.py
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, BaseLoader, TemplateNotFound
from services.db import get_db
from webapp.auth import admin_required, create_admin_session, delete_admin_session, verify_admin_session
from webapp.dependencies import get_bot

router = APIRouter()

# ---------- Встроенный CSS ----------
CSS_CONTENT = '''body.dark-theme {
    background-color: #1a1a1a; color: #ccc; font-family: sans-serif; margin: 0; padding: 0;
}
nav { background: #111; padding: 10px; }
nav a { color: #ff4444; margin-right: 15px; text-decoration: none; }
nav a:hover { text-decoration: underline; }
.container { max-width: 1200px; margin: auto; padding: 20px; }
button { background: #ff4444; color: #fff; border: none; padding: 8px 16px; cursor: pointer; border-radius: 4px; }
input, textarea, select { background: #333; color: #ccc; border: 1px solid #555; padding: 5px; margin: 5px 0; border-radius: 3px; }
.error { color: #ff4444; }
table { width: 100%; border-collapse: collapse; margin-top: 10px; }
th, td { padding: 5px; border-bottom: 1px solid #333; text-align: left; }
th { background: #222; }
'''

# ---------- Шаблоны ----------
BASE_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>{% block title %}AutoPost Bot{% endblock %}</title>
<link rel="stylesheet" href="/admin/static/css/style.css"></head>
<body class="dark-theme">
    <nav>
        <a href="/admin/dashboard">Админ-панель</a> |
        <a href="/admin/broadcast">Рассылка</a> |
        <a href="/admin/promocodes">Промокоды</a> |
        <a href="/admin/store_delivery">Доставка</a> |
        <a href="/admin/logout" style="color: #ff4444;">Выйти</a>
    </nav>
    <div class="container">{% block content %}{% endblock %}</div>
</body>
</html>'''

LOGIN_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>Вход в админку</title>
<link rel="stylesheet" href="/admin/static/css/style.css"></head>
<body class="dark-theme">
<div class="container">
    <h1>Вход</h1>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <form method="post" action="/admin/login">
        <input type="password" name="password" placeholder="Пароль" required><br>
        <button type="submit">Войти</button>
    </form>
</div>
</body>
</html>'''

DASHBOARD_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Дашборд{% endblock %}
{% block content %}
<h1>Общая статистика</h1>
<ul>
    <li>SaaS клиентов: {{ saas }}</li>
    <li>Блогеров: {{ bloggers }}</li>
    <li>Постов опубликовано: {{ posts }}</li>
    <li>Транзакций: {{ tx }}</li>
    <li>Баланс пользователей: {{ balance }} ₽</li>
</ul>
{% endblock %}'''

BROADCAST_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Рассылка{% endblock %}
{% block content %}
<h1>📣 Массовая рассылка</h1>
{% if message %}<p style="color: lightgreen;">{{ message }}</p>{% endif %}
<form method="post" action="/admin/broadcast">
    <textarea name="text" rows="5" placeholder="Текст сообщения..." required></textarea><br>
    <select name="role">
        <option value="all">Всем пользователям</option>
        <option value="saas">Только SaaS</option>
        <option value="blogger">Только блогерам</option>
    </select><br>
    <button type="submit">Отправить</button>
</form>
{% endblock %}'''

PROMOCODES_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Управление промокодами{% endblock %}
{% block content %}
<h1>🎟 Промокоды</h1>
<h2>Добавить</h2>
<form method="post" action="/admin/promocodes/add">
    <input name="store" placeholder="Магазин (название)" required>
    <input name="promocode" placeholder="Промокод" required>
    <input name="description" placeholder="Описание (необязательно)">
    <button type="submit">Добавить</button>
</form>
<h2>Список</h2>
<table>
    <tr><th>Магазин</th><th>Промокод</th><th>Описание</th><th></th></tr>
    {% for p in promos %}
    <tr>
        <td>{{ p['store'] }}</td>
        <td><code>{{ p['promocode'] }}</code></td>
        <td>{{ p['description'] or '' }}</td>
        <td><a href="/admin/promocodes/delete/{{ p['id'] }}" style="color:red;">Удалить</a></td>
    </tr>
    {% endfor %}
</table>
{% endblock %}'''

STORE_DELIVERY_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Информация о доставке{% endblock %}
{% block content %}
<h1>🚚 Доставка</h1>
<h2>Обновить данные</h2>
<form method="post" action="/admin/store_delivery/update">
    <input name="store" placeholder="Магазин" required>
    <input name="delivery_text" placeholder="Условия доставки" required>
    <button type="submit">Сохранить</button>
</form>
<h2>Текущие данные</h2>
<table>
    <tr><th>Магазин</th><th>Условия</th></tr>
    {% for d in deliveries %}
    <tr>
        <td>{{ d['store'] }}</td>
        <td>{{ d['delivery_text'] }}</td>
    </tr>
    {% endfor %}
</table>
{% endblock %}'''

# ---------- Загрузчик шаблонов из словаря ----------
class DictLoader(BaseLoader):
    def __init__(self, mapping):
        self.mapping = mapping
    def get_source(self, environment, template):
        if template not in self.mapping:
            raise TemplateNotFound(template)
        return self.mapping[template], None, lambda: True

TEMPLATES = {
    "base.html": BASE_TEMPLATE,
    "login.html": LOGIN_TEMPLATE,
    "admin_dashboard.html": DASHBOARD_TEMPLATE,
    "admin_broadcast.html": BROADCAST_TEMPLATE,
    "admin_promocodes.html": PROMOCODES_TEMPLATE,
    "admin_store_delivery.html": STORE_DELIVERY_TEMPLATE,
}

env = Environment(loader=DictLoader(TEMPLATES))

def render(template_name: str, **kwargs):
    template = env.get_template(template_name)
    return HTMLResponse(template.render(**kwargs))

# ---------- Эндпоинт для CSS ----------
@router.get("/static/css/style.css", include_in_schema=False)
async def style_css():
    return Response(content=CSS_CONTENT, media_type="text/css")

# ---------- Аутентификация ----------
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    token = request.cookies.get("admin_session")
    if token and verify_admin_session(token):
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    return render("login.html")

@router.post("/login")
async def login(request: Request, password: str = Form(...)):
    from config import ADMIN_PASSWORD
    if password == ADMIN_PASSWORD:
        token = create_admin_session()
        resp = RedirectResponse(url="/admin/dashboard", status_code=303)
        resp.set_cookie(key="admin_session", value=token, httponly=True, max_age=86400)
        return resp
    return render("login.html", error="Неверный пароль")

@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("admin_session")
    if token:
        delete_admin_session(token)
    resp = RedirectResponse(url="/admin/login", status_code=303)
    resp.delete_cookie("admin_session")
    return resp

# ---------- Защищённые страницы ----------
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, _: bool = Depends(admin_required)):
    conn = get_db()
    try:
        saas = conn.execute("SELECT COUNT(*) FROM users WHERE role='saas'").fetchone()[0]
        bloggers = conn.execute("SELECT COUNT(*) FROM users WHERE role='blogger'").fetchone()[0]
        posts = conn.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()[0]
        tx = conn.execute("SELECT COUNT(*) FROM admitad_transactions").fetchone()[0]
        balance = conn.execute("SELECT SUM(balance_available) FROM users").fetchone()[0] or 0
    finally:
        conn.close()
    return render("admin_dashboard.html", saas=saas, bloggers=bloggers, posts=posts, tx=tx, balance=balance)

@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_form(request: Request, _: bool = Depends(admin_required)):
    return render("admin_broadcast.html")

@router.post("/broadcast", response_class=HTMLResponse)
async def broadcast_send(request: Request, text: str = Form(...), role: str = Form("all"),
                         _: bool = Depends(admin_required)):
    bot = request.app.state.bot
    conn = get_db()
    try:
        if role == "all":
            users = conn.execute("SELECT user_id FROM users").fetchall()
        else:
            users = conn.execute("SELECT user_id FROM users WHERE role=?", (role,)).fetchall()
        success = 0
        for u in users:
            try:
                await bot.send_message(chat_id=u["user_id"], text=text)
                success += 1
            except:
                pass
        return render("admin_broadcast.html", message=f"Отправлено {success} из {len(users)}")
    finally:
        conn.close()

@router.get("/promocodes", response_class=HTMLResponse)
async def promocodes_list(request: Request, _: bool = Depends(admin_required)):
    conn = get_db()
    try:
        promos = conn.execute("SELECT * FROM store_promocodes ORDER BY store, promocode").fetchall()
    finally:
        conn.close()
    return render("admin_promocodes.html", promos=promos)

@router.post("/promocodes/add", response_class=HTMLResponse)
async def promocode_add(store: str = Form(...), promocode: str = Form(...), description: str = Form(""),
                        _: bool = Depends(admin_required)):
    conn = get_db()
    try:
        conn.execute("INSERT INTO store_promocodes (store, promocode, description) VALUES (?, ?, ?)",
                     (store, promocode, description))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/admin/promocodes", status_code=303)

@router.get("/promocodes/delete/{id}")
async def promocode_delete(id: int, _: bool = Depends(admin_required)):
    conn = get_db()
    try:
        conn.execute("DELETE FROM store_promocodes WHERE id=?", (id,))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/admin/promocodes", status_code=303)

@router.get("/store_delivery", response_class=HTMLResponse)
async def store_delivery_list(request: Request, _: bool = Depends(admin_required)):
    conn = get_db()
    try:
        deliveries = conn.execute("SELECT * FROM store_delivery ORDER BY store").fetchall()
    finally:
        conn.close()
    return render("admin_store_delivery.html", deliveries=deliveries)

@router.post("/store_delivery/update", response_class=HTMLResponse)
async def store_delivery_update(store: str = Form(...), delivery_text: str = Form(...),
                                _: bool = Depends(admin_required)):
    conn = get_db()
    try:
        conn.execute("INSERT OR REPLACE INTO store_delivery (store, delivery_text) VALUES (?, ?)",
                     (store, delivery_text))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/admin/store_delivery", status_code=303)
