# webapp/routes_admin.py
from fastapi import APIRouter, Request, Form, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, BaseLoader, TemplateNotFound
from services.db import get_db
from webapp.auth import (
    admin_required, create_admin_session, delete_admin_session,
    verify_admin_session, verify_admin_token
)
from webapp.dependencies import get_bot

router = APIRouter()

# ---------- Встроенный CSS (современный дизайн) ----------
CSS_CONTENT = '''
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #1a1a1a; color: #e0e0e0; display: flex; min-height: 100vh; }
.sidebar { width: 250px; background: #111; padding: 30px 20px; display: flex; flex-direction: column; gap: 8px; }
.sidebar a { color: #bbb; text-decoration: none; padding: 12px 16px; border-radius: 8px; font-weight: 500; transition: all 0.2s; }
.sidebar a:hover, .sidebar a.active { background: #ff4444; color: #fff; }
.main-content { flex: 1; padding: 40px; }
.card { background: #222; border-radius: 16px; padding: 30px; margin-bottom: 30px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
h1 { color: #ff4444; margin-bottom: 20px; font-size: 2em; }
h2 { color: #ddd; margin: 20px 0 10px; font-size: 1.5em; }
button { background: #ff4444; color: white; border: none; padding: 12px 24px; border-radius: 8px; font-size: 1em; cursor: pointer; transition: background 0.2s; }
button:hover { background: #e03333; }
input, textarea, select { background: #333; border: 1px solid #555; color: #ddd; padding: 12px; border-radius: 8px; width: 100%; margin-bottom: 15px; font-size: 1em; }
table { width: 100%; border-collapse: collapse; margin-top: 20px; }
th, td { padding: 12px; border-bottom: 1px solid #333; text-align: left; }
th { background: #2a2a2a; color: #ff4444; }
tr:hover { background: #2a2a2a; }
.error { color: #ff4444; margin-bottom: 15px; }
.success { color: #4caf50; margin-bottom: 15px; }
.top-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
.logout { background: transparent; border: 1px solid #ff4444; color: #ff4444; padding: 8px 20px; }
.logout:hover { background: #ff4444; color: #fff; }
'''

# ---------- Шаблоны ----------
BASE_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{% block title %}AutoPost Bot{% endblock %}</title>
<link rel="stylesheet" href="/admin/static/css/style.css"></head>
<body>
<div class="sidebar">
    <h2 style="color:#ff4444; margin-bottom:20px;">⚡ AutoPost</h2>
    <a href="/admin/dashboard" class="{{ 'active' if active_page == 'dashboard' }}">📊 Дашборд</a>
    <a href="/admin/broadcast" class="{{ 'active' if active_page == 'broadcast' }}">📣 Рассылка</a>
    <a href="/admin/users" class="{{ 'active' if active_page == 'users' }}">👥 Пользователи</a>
    <a href="/admin/promocodes" class="{{ 'active' if active_page == 'promocodes' }}">🎟 Купоны</a>
    <a href="/admin/store_delivery" class="{{ 'active' if active_page == 'delivery' }}">🚚 Доставка</a>
    <a href="/admin/test_promocodes" class="{{ 'active' if active_page == 'test_promo' }}">🎁 Промокоды (тест)</a>
</div>
<div class="main-content">
    {% block content %}{% endblock %}
</div>
</body>
</html>'''

LOGIN_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>Вход в админку</title>
<link rel="stylesheet" href="/admin/static/css/style.css"></head>
<body style="justify-content:center; align-items:center; background:#1a1a1a;">
<div class="card" style="width:400px; text-align:center;">
    <h1>⚡ AutoPost</h1>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <p style="margin-bottom:20px;">Войдите по одноразовой ссылке из бота (<code>/admin</code>)</p>
</div>
</body>
</html>'''

DASHBOARD_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Дашборд{% endblock %}
{% block content %}
<div class="top-bar"><h1>📊 Дашборд</h1></div>
<div class="card">
    <h2>Общая статистика</h2>
    <table>
        <tr><td>SaaS клиентов</td><td><strong>{{ saas }}</strong></td></tr>
        <tr><td>Блогеров</td><td><strong>{{ bloggers }}</strong></td></tr>
        <tr><td>Постов опубликовано</td><td><strong>{{ posts }}</strong></td></tr>
        <tr><td>Транзакций</td><td><strong>{{ tx }}</strong></td></tr>
        <tr><td>Баланс пользователей</td><td><strong>{{ balance }} ₽</strong></td></tr>
    </table>
</div>
{% endblock %}'''

BROADCAST_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Рассылка{% endblock %}
{% block content %}
<h1>📣 Массовая рассылка</h1>
<div class="card">
    {% if message %}<p class="success">{{ message }}</p>{% endif %}
    <form method="post" action="/admin/broadcast">
        <textarea name="text" rows="5" placeholder="Текст сообщения..." required></textarea>
        <select name="role">
            <option value="all">Всем пользователям</option>
            <option value="saas">Только SaaS</option>
            <option value="blogger">Только блогерам</option>
        </select>
        <button type="submit">Отправить</button>
    </form>
</div>
{% endblock %}'''

USERS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Пользователи{% endblock %}
{% block content %}
<h1>👥 Пользователи</h1>
<div class="card">
    <table>
        <tr><th>ID</th><th>Роль</th><th>Подписка до</th><th>Тариф</th><th>Баланс</th><th>Действия</th></tr>
        {% for u in users %}
        <tr>
            <td>{{ u['user_id'] }}</td>
            <td>{{ u['role'] }}</td>
            <td>{{ u['subscription_until'] or '—' }}</td>
            <td>{{ u['tariff_name'] or '—' }}</td>
            <td>{{ u['balance_available'] or 0 }} ₽</td>
            <td>
                <a href="/admin/users/edit/{{ u['user_id'] }}" style="color:#ff4444;">Изменить</a>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

USER_EDIT_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Редактирование пользователя{% endblock %}
{% block content %}
<h1>✏️ Пользователь #{{ user['user_id'] }}</h1>
<div class="card">
    <form method="post" action="/admin/users/edit/{{ user['user_id'] }}">
        <label>Роль:</label>
        <select name="role">
            <option value="saas" {{ 'selected' if user['role'] == 'saas' }}>SaaS</option>
            <option value="blogger" {{ 'selected' if user['role'] == 'blogger' }}>Блогер</option>
        </select>
        <label>Подписка до (UTC, в формате ГГГГ-ММ-ДД ЧЧ:ММ):</label>
        <input name="subscription_until" value="{{ user['subscription_until'] or '' }}" placeholder="2026-12-31 23:59">
        <label>Тариф:</label>
        <select name="tariff_id">
            <option value="0" {{ 'selected' if not user['tariff_id'] }}>Без тарифа</option>
            {% for t in tariffs %}
            <option value="{{ t['id'] }}" {{ 'selected' if user['tariff_id'] == t['id'] }}>{{ t['name'] }}</option>
            {% endfor %}
        </select>
        <label>Баланс доступный:</label>
        <input name="balance_available" value="{{ user['balance_available'] or 0 }}" type="number" step="0.01">
        <label>Баланс ожидающий:</label>
        <input name="balance_pending" value="{{ user['balance_pending'] or 0 }}" type="number" step="0.01">
        <button type="submit">Сохранить</button>
    </form>
</div>
{% endblock %}'''

PROMOCODES_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Купоны магазинов{% endblock %}
{% block content %}
<h1>🎟 Купоны магазинов</h1>
<div class="card">
    <h2>Добавить</h2>
    <form method="post" action="/admin/promocodes/add">
        <input name="store" placeholder="Магазин (название)" required>
        <input name="promocode" placeholder="Промокод" required>
        <input name="description" placeholder="Описание (необязательно)">
        <button type="submit">Добавить</button>
    </form>
</div>
<div class="card">
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
</div>
{% endblock %}'''

STORE_DELIVERY_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Доставка{% endblock %}
{% block content %}
<h1>🚚 Доставка</h1>
<div class="card">
    <h2>Обновить данные</h2>
    <form method="post" action="/admin/store_delivery/update">
        <input name="store" placeholder="Магазин" required>
        <input name="delivery_text" placeholder="Условия доставки" required>
        <button type="submit">Сохранить</button>
    </form>
</div>
<div class="card">
    <h2>Текущие данные</h2>
    <table>
        <tr><th>Магазин</th><th>Условия</th></tr>
        {% for d in deliveries %}
        <tr><td>{{ d['store'] }}</td><td>{{ d['delivery_text'] }}</td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

TEST_PROMOCODES_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Промокоды (тест){% endblock %}
{% block content %}
<h1>🎁 Промокоды (тестовый период)</h1>
<div class="card">
    <h2>Добавить</h2>
    <form method="post" action="/admin/test_promocodes/add">
        <input name="code" placeholder="Код (напр. TEST3)" required>
        <input name="days" placeholder="Дней (напр. 3)" required type="number">
        <button type="submit">Создать</button>
    </form>
</div>
<div class="card">
    <h2>Список</h2>
    <table>
        <tr><th>Код</th><th>Дней</th><th>Использован?</th><th></th></tr>
        {% for p in promos %}
        <tr>
            <td><code>{{ p['code'] }}</code></td>
            <td>{{ p['days'] }}</td>
            <td>{{ 'Да' if p['used'] else 'Нет' }}</td>
            <td><a href="/admin/test_promocodes/delete/{{ p['id'] }}" style="color:red;">Удалить</a></td>
        </tr>
        {% endfor %}
    </table>
</div>
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
    "admin_users.html": USERS_TEMPLATE,
    "admin_user_edit.html": USER_EDIT_TEMPLATE,
    "admin_promocodes.html": PROMOCODES_TEMPLATE,
    "admin_store_delivery.html": STORE_DELIVERY_TEMPLATE,
    "admin_test_promocodes.html": TEST_PROMOCODES_TEMPLATE,
}

env = Environment(loader=DictLoader(TEMPLATES))

def render(template_name: str, **kwargs):
    template = env.get_template(template_name)
    return HTMLResponse(template.render(**kwargs))

# ---------- Эндпоинты ----------
@router.get("/static/css/style.css", include_in_schema=False)
async def style_css():
    return Response(content=CSS_CONTENT, media_type="text/css")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, token: str = Query(None)):
    session_token = request.cookies.get("admin_session")
    if session_token and verify_admin_session(session_token):
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    if token:
        user_id = verify_admin_token(token)
        if user_id:
            session = create_admin_session(user_id)
            resp = RedirectResponse(url="/admin/dashboard", status_code=303)
            resp.set_cookie(key="admin_session", value=session, httponly=True, max_age=86400, secure=True, samesite='lax')
            return resp
        else:
            return render("login.html", error="Неверный или просроченный токен. Получите новую ссылку в боте.")
    return render("login.html")

@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("admin_session")
    if token:
        delete_admin_session(token)
    resp = RedirectResponse(url="/admin/login", status_code=303)
    resp.delete_cookie("admin_session")
    return resp

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        saas = conn.execute("SELECT COUNT(*) FROM users WHERE role='saas'").fetchone()[0]
        bloggers = conn.execute("SELECT COUNT(*) FROM users WHERE role='blogger'").fetchone()[0]
        posts = conn.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()[0]
        tx = conn.execute("SELECT COUNT(*) FROM admitad_transactions").fetchone()[0]
        balance = conn.execute("SELECT SUM(balance_available) FROM users").fetchone()[0] or 0
    finally:
        conn.close()
    return render("admin_dashboard.html", saas=saas, bloggers=bloggers, posts=posts, tx=tx, balance=balance, active_page='dashboard')

@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_form(request: Request, _: int = Depends(admin_required)):
    return render("admin_broadcast.html", active_page='broadcast')

@router.post("/broadcast", response_class=HTMLResponse)
async def broadcast_send(request: Request, text: str = Form(...), role: str = Form("all"),
                         _: int = Depends(admin_required)):
    bot = request.app.state.bot
    conn = get_db()
    try:
        users = conn.execute("SELECT user_id FROM users" if role == "all" else f"SELECT user_id FROM users WHERE role='{role}'").fetchall()
        success = 0
        for u in users:
            try:
                await bot.send_message(chat_id=u["user_id"], text=text)
                success += 1
            except:
                pass
        return render("admin_broadcast.html", message=f"Отправлено {success} из {len(users)}", active_page='broadcast')
    finally:
        conn.close()

# ---------- Управление пользователями ----------
@router.get("/users", response_class=HTMLResponse)
async def users_list(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        users = conn.execute("""
            SELECT u.user_id, u.role, u.subscription_until, u.tariff_id, t.name as tariff_name, u.balance_available
            FROM users u
            LEFT JOIN tariffs t ON u.tariff_id = t.id
            ORDER BY u.user_id
        """).fetchall()
    finally:
        conn.close()
    return render("admin_users.html", users=users, active_page='users')

@router.get("/users/edit/{user_id}", response_class=HTMLResponse)
async def user_edit_form(user_id: int, request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            return HTMLResponse("Пользователь не найден", status_code=404)
        tariffs = conn.execute("SELECT id, name FROM tariffs WHERE is_active = 1").fetchall()
    finally:
        conn.close()
    return render("admin_user_edit.html", user=user, tariffs=tariffs, active_page='users')

@router.post("/users/edit/{user_id}", response_class=HTMLResponse)
async def user_edit_save(user_id: int, request: Request,
                         role: str = Form(...),
                         subscription_until: str = Form(""),
                         tariff_id: int = Form(0),
                         balance_available: float = Form(0.0),
                         balance_pending: float = Form(0.0),
                         _: int = Depends(admin_required)):
    conn = get_db()
    try:
        # Если дата пустая – ставим NULL
        sub_until = subscription_until if subscription_until else None
        conn.execute("""
            UPDATE users
            SET role = ?, subscription_until = ?, tariff_id = ?,
                balance_available = ?, balance_pending = ?
            WHERE user_id = ?
        """, (role, sub_until, tariff_id, balance_available, balance_pending, user_id))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/admin/users", status_code=303)

# ---------- Промокоды (магазинные) ----------
@router.get("/promocodes", response_class=HTMLResponse)
async def promocodes_list(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        promos = conn.execute("SELECT * FROM store_promocodes ORDER BY store, promocode").fetchall()
    finally:
        conn.close()
    return render("admin_promocodes.html", promos=promos, active_page='promocodes')

@router.post("/promocodes/add", response_class=HTMLResponse)
async def promocode_add(store: str = Form(...), promocode: str = Form(...), description: str = Form(""),
                        _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("INSERT INTO store_promocodes (store, promocode, description) VALUES (?, ?, ?)", (store, promocode, description))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/promocodes", status_code=303)

@router.get("/promocodes/delete/{id}")
async def promocode_delete(id: int, _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("DELETE FROM store_promocodes WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/promocodes", status_code=303)

# ---------- Доставка ----------
@router.get("/store_delivery", response_class=HTMLResponse)
async def store_delivery_list(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        deliveries = conn.execute("SELECT * FROM store_delivery ORDER BY store").fetchall()
    finally:
        conn.close()
    return render("admin_store_delivery.html", deliveries=deliveries, active_page='delivery')

@router.post("/store_delivery/update", response_class=HTMLResponse)
async def store_delivery_update(store: str = Form(...), delivery_text: str = Form(...),
                                _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO store_delivery (store, delivery_text) VALUES (?, ?)", (store, delivery_text))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/store_delivery", status_code=303)

# ---------- Тестовые промокоды ----------
@router.get("/test_promocodes", response_class=HTMLResponse)
async def test_promocodes_list(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    promos = conn.execute("SELECT id, code, days, (SELECT COUNT(*) FROM promocode_activations WHERE UPPER(code) = UPPER(p.code)) as used_count FROM promocodes p ORDER BY id").fetchall()
    formatted = [{"id": p["id"], "code": p["code"], "days": p["days"], "used": p["used_count"] > 0} for p in promos]
    conn.close()
    return render("admin_test_promocodes.html", promos=formatted, active_page='test_promo')

@router.post("/test_promocodes/add", response_class=HTMLResponse)
async def test_promocode_add(code: str = Form(...), days: int = Form(...), _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("INSERT INTO promocodes (code, days) VALUES (?, ?)", (code.upper(), days))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/test_promocodes", status_code=303)

@router.get("/test_promocodes/delete/{id}")
async def test_promocode_delete(id: int, _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("DELETE FROM promocodes WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/test_promocodes", status_code=303)
