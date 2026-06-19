"""
admin_panel.py — Расширенная веб-админка AutoPost
Режим бога: дашборд, управление пользователями, очередями, карантином, каналами.
"""

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from aiogram import Bot
import logging

logger = logging.getLogger("autopost_bot.admin_panel")

# ------------------------------------------------
# Вспомогательная БД (совместима с main.py)
# ------------------------------------------------
DB_PATH = "/app/data/autopost.db"

def get_db():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL;")
    return db

# ------------------------------------------------
# Главная функция создания приложения
# ------------------------------------------------
def create_fastapi_app(bot: Bot) -> FastAPI:
    app = FastAPI(title="AutoPost Admin Panel", docs_url=None, redoc_url=None)
    ADMIN_PASSWORD = "40370802"  # или из os.getenv
    active_sessions = {}

    # --- Аутентификация ---
    def is_authenticated(request: Request):
        token = request.cookies.get("admin_token")
        if not token or token not in active_sessions:
            raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
        return True

    @app.get("/")
    async def root():
        return RedirectResponse("/admin/login")

    @app.get("/admin/login", response_class=HTMLResponse)
    async def login_page():
        return """
        <!DOCTYPE html><html><head><meta charset="utf-8"><title>Вход</title>
        <style>body{font-family:Arial;background:#0f1117;color:#fff;padding:50px;}</style>
        </head><body>
        <h2>🔑 Вход в AutoPost Admin</h2>
        <form action="/admin/login" method="post">
            <input type="password" name="password" placeholder="Пароль" style="padding:10px;font-size:16px;width:300px;"><br><br>
            <button type="submit" style="padding:10px 20px;font-size:16px;">Войти</button>
        </form>
        </body></html>"""

    @app.post("/admin/login")
    async def login_post(password: str = Form(...)):
        if password == ADMIN_PASSWORD:
            token = secrets.token_hex(32)
            active_sessions[token] = True
            resp = RedirectResponse("/admin/dashboard", status_code=302)
            resp.set_cookie(key="admin_token", value=token, httponly=True,
                            secure=True, samesite="strict", max_age=3600*12)
            return resp
        return HTMLResponse("<h3>❌ Неверный пароль</h3><a href='/admin/login'>Назад</a>")

    @app.get("/admin/logout")
    async def logout():
        resp = RedirectResponse("/admin/login")
        resp.delete_cookie("admin_token")
        return resp

      # =====================================================================
    # === ДАШБОРД ==========================================================
    # =====================================================================
    @app.get("/admin/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            saas_active = conn.execute("""
                SELECT COUNT(*) as cnt FROM users
                WHERE role='saas' AND is_active=1
                AND (subscription_until IS NULL OR subscription_until > datetime('now'))
            """).fetchone()["cnt"]
            bloggers_active = conn.execute("""
                SELECT COUNT(*) as cnt FROM users
                WHERE role='blogger' AND is_active=1
            """).fetchone()["cnt"]
            posts_today = conn.execute("""
                SELECT COUNT(*) as cnt FROM posts
                WHERE status='published'
                AND published_at >= datetime('now', 'start of day')
            """).fetchone()["cnt"]
            posts_week = conn.execute("""
                SELECT COUNT(*) as cnt FROM posts
                WHERE status='published'
                AND published_at >= datetime('now', '-7 days')
            """).fetchone()["cnt"]
            pending_payouts = conn.execute("""
                SELECT COUNT(*) as cnt, COALESCE(SUM(amount_blogger), 0) as total
                FROM payouts WHERE status='pending'
            """).fetchone()
            errors_today = conn.execute("""
                SELECT COUNT(*) as cnt FROM posts
                WHERE status='error'
                AND created_at >= datetime('now', 'start of day')
            """).fetchone()["cnt"]

            # очереди
            night_q = conn.execute("SELECT COUNT(*) as cnt FROM night_queue").fetchone()["cnt"]
            saas_q = conn.execute("SELECT COUNT(*) as cnt FROM saas_queue").fetchone()["cnt"]
            quarantine = conn.execute("SELECT COUNT(*) as cnt FROM posts WHERE status='quarantine'").fetchone()["cnt"]

            # последние 5 пользователей
            last_users = conn.execute("""
                SELECT user_id, username, role, subscription_until, is_active
                FROM users ORDER BY created_at DESC LIMIT 5
            """).fetchall()

            # последние 5 постов
            last_posts = conn.execute("""
                SELECT p.id, p.status, p.published_at, p.donor_post_id, u.username
                FROM posts p LEFT JOIN users u ON p.user_id = u.user_id
                ORDER BY p.id DESC LIMIT 5
            """).fetchall()
        finally:
            conn.close()

        # HTML-шаблон дашборда
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>AutoPost Admin Dashboard</title>
    <style>
        body {{font-family: 'Segoe UI', Arial, sans-serif; background:#0f1117; color:#e0e0e8; padding:20px;}}
        h1,h2 {{color:#fff;}}
        .card-grid {{display:grid; grid-template-columns: repeat(auto-fill, minmax(160px,1fr)); gap:12px; margin-bottom:24px;}}
        .card {{background:#1a1d27; border:1px solid #2a2d3a; border-radius:10px; padding:16px; text-align:center;}}
        .card .num {{font-size:32px; font-weight:700; color:#fff;}}
        .card .lbl {{font-size:12px; color:#888; margin-top:4px;}}
        .card.warn .num {{color:#e74c3c;}}
        .card.ok .num {{color:#2ecc71;}}
        table {{width:100%; border-collapse:collapse; margin:20px 0;}}
        th,td {{padding:10px; border:1px solid #333; text-align:left;}}
        th {{background:#1a1d27;}}
        a {{color:#3498db; text-decoration:none;}}
        .section {{background:#1a1d27; padding:20px; border-radius:8px; margin-bottom:25px;}}
    </style>
</head>
<body>
    <h1>AutoPost Admin Dashboard</h1>
    <a href="/admin/logout" style="color:#e74c3c;">Выход</a>

    <div class="card-grid">
        <div class="card ok"><div class="num">{saas_active}</div><div class="lbl">SaaS активных</div></div>
        <div class="card ok"><div class="num">{bloggers_active}</div><div class="lbl">Блогеров</div></div>
        <div class="card"><div class="num">{posts_today}</div><div class="lbl">Постов сегодня</div></div>
        <div class="card"><div class="num">{posts_week}</div><div class="lbl">Постов за 7 дней</div></div>
        <div class="card warn"><div class="num">{errors_today}</div><div class="lbl">Ошибок сегодня</div></div>
        <div class="card warn"><div class="num">{pending_payouts['cnt']}</div><div class="lbl">Выплат ожидает</div></div>
    </div>

    <div class="section">
        <h2>📦 Очереди</h2>
        <p>🌙 Ночная очередь: <b>{night_q}</b> | 🅰️ SaaS-очередь: <b>{saas_q}</b> | 🚨 Карантин: <b>{quarantine}</b></p>
    </div>

    <div class="section">
        <h2>👥 Последние пользователи</h2>
        <table>
            <tr><th>ID</th><th>Username</th><th>Роль</th><th>Подписка до</th><th>Статус</th><th></th></tr>
            {"".join(f"<tr><td>{u['user_id']}</td><td>@{u['username'] or '—'}</td><td>{u['role']}</td>"
                     f"<td>{str(u['subscription_until'])[:10] if u['subscription_until'] else '—'}</td>"
                     f"<td>{'🟢' if u['is_active'] else '🔴'}</td>"
                     f"<td><a href='/admin/user/{u['user_id']}'>Карточка</a></td></tr>" for u in last_users)}
        </table>
        <a href="/admin/users">Все пользователи →</a>
    </div>

    <div class="section">
        <h2>📬 Последние посты</h2>
        <table>
            <tr><th>ID</th><th>Пользователь</th><th>Донор</th><th>Статус</th><th>Дата</th></tr>
            {"".join(f"<tr><td>{p['id']}</td><td>@{p['username'] or '—'}</td>"
                     f"<td>{str(p['donor_post_id'])[:30]}</td><td>{p['status']}</td>"
                     f"<td>{str(p['published_at'])[:16] if p['published_at'] else '—'}</td></tr>" for p in last_posts)}
        </table>
        <a href="/admin/posts">Все посты →</a>
    </div>
</body>
</html>"""
        return HTMLResponse(html)

      # =====================================================================
    # === СПИСОК ВСЕХ ПОЛЬЗОВАТЕЛЕЙ =======================================
    # =====================================================================
    @app.get("/admin/users", response_class=HTMLResponse)
    async def users_list(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            users = conn.execute("""
                SELECT user_id, username, role, subscription_until, channel_title, is_active
                FROM users ORDER BY created_at DESC
            """).fetchall()
        finally:
            conn.close()

        rows = ""
        for u in users:
            sub = str(u["subscription_until"])[:10] if u["subscription_until"] else "—"
            active = "🟢" if u["is_active"] else "🔴"
            role_color = "#3498db" if u["role"] == "saas" else "#2ecc71"
            rows += f"""
            <tr>
                <td>{u['user_id']}</td>
                <td>@{u['username'] or '—'}</td>
                <td><span style="color:{role_color}">{u['role']}</span></td>
                <td>{u['channel_title'] or '—'}</td>
                <td>{sub}</td>
                <td>{active}</td>
                <td><a href='/admin/user/{u['user_id']}' style='color:#3498db'>Карточка</a></td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Все пользователи</title>
<style>
    body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}
    table{{width:100%;border-collapse:collapse;margin-top:20px;}}
    th,td{{padding:10px;border:1px solid #333;text-align:left;}}
    th{{background:#1a1d27;}}
    a{{color:#3498db;text-decoration:none;}}
</style></head>
<body>
    <h1>👥 Все пользователи</h1>
    <a href="/admin/dashboard">← Дашборд</a>
    <table>
        <tr><th>ID</th><th>Username</th><th>Роль</th><th>Канал</th><th>Подписка до</th><th>Активен</th><th></th></tr>
        {rows}
    </table>
</body></html>"""
        return HTMLResponse(html)

    # =====================================================================
    # === КАРТОЧКА ПОЛЬЗОВАТЕЛЯ ===========================================
    # =====================================================================
    @app.get("/admin/user/{user_id}", response_class=HTMLResponse)
    async def user_card(request: Request, user_id: int):
        is_authenticated(request)
        conn = get_db()
        try:
            user = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not user:
                return HTMLResponse("<h3>❌ Пользователь не найден</h3>", status_code=404)

            channels = conn.execute("SELECT * FROM channels WHERE user_id=?", (user_id,)).fetchall()
            posts = conn.execute("""
                SELECT * FROM posts WHERE user_id=?
                ORDER BY id DESC LIMIT 20
            """, (user_id,)).fetchall()

            # Финансы (если блогер)
            earned = 0.0
            withdrawn = 0.0
            pending = 0.0
            if user["role"] == "blogger":
                earned_row = conn.execute(
                    "SELECT COALESCE(SUM(payout), 0.0) as total FROM transactions WHERE sub_id=?",
                    (user["sub_id"],)
                ).fetchone()
                withdrawn_row = conn.execute(
                    "SELECT COALESCE(SUM(amount_blogger), 0.0) as total FROM payouts WHERE user_id=? AND status='completed'",
                    (user_id,)
                ).fetchone()
                pending_row = conn.execute(
                    "SELECT COALESCE(SUM(amount_blogger), 0.0) as total FROM payouts WHERE user_id=? AND status='pending'",
                    (user_id,)
                ).fetchone()
                earned = round(float(earned_row["total"] or 0), 2)
                withdrawn = round(float(withdrawn_row["total"] or 0), 2)
                pending = round(float(pending_row["total"] or 0), 2)
        finally:
            conn.close()

        # Строки таблиц
        channel_rows = ""
        for ch in channels:
            active_icon = "🟢" if ch["is_active"] else "🔴"
            channel_rows += f"<tr><td>{active_icon}</td><td><code>{ch['channel_id']}</code></td><td>{ch['channel_title'] or '—'}</td></tr>"

        post_rows = ""
        for p in posts:
            pub = str(p["published_at"])[:16] if p["published_at"] else "—"
            post_rows += f"<tr><td>{p['id']}</td><td>{p['status']}</td><td>{p['donor_post_id'][:30]}</td><td>{pub}</td></tr>"

        # Блок финансов для блогера
        finance_block = ""
        if user["role"] == "blogger":
            available = round(earned - withdrawn - pending, 2)
            finance_block = f"""
            <h2>💰 Финансы</h2>
            <table>
                <tr><th>Заработано</th><th>Выведено</th><th>Ожидает</th><th style="color:#2ecc71">Доступно</th></tr>
                <tr><td>{earned} ₽</td><td>{withdrawn} ₽</td><td style="color:#f39c12">{pending} ₽</td><td style="color:#2ecc71"><b>{available} ₽</b></td></tr>
            </table>"""

        # Статус подписки
        sub_until = user["subscription_until"]
        if sub_until:
            try:
                end_dt = datetime.fromisoformat(sub_until.replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc)
                if now_dt < end_dt:
                    diff = end_dt - now_dt
                    sub_status = f"✅ Активна • {diff.days} дн. {diff.seconds // 3600} ч."
                else:
                    sub_status = "❌ Истекла"
            except:
                sub_status = "⚠️ Ошибка даты"
        else:
            sub_status = "♾️ Бессрочно" if user["role"] == "blogger" else "❌ Не активирована"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Пользователь {user_id}</title>
<style>
    body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}
    h1,h2{{color:#fff;}}
    table{{width:100%;border-collapse:collapse;margin:15px 0;}}
    th,td{{padding:10px;border:1px solid #333;text-align:left;}}
    th{{background:#1a1d27;}}
    .row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #2a2d3a;}}
    .lbl{{color:#888;}}
    code{{background:#0f1117;padding:2px 6px;border-radius:4px;}}
    form{{margin:10px 0;}}
    button{{padding:6px 12px;background:#3498db;border:none;color:#fff;border-radius:4px;cursor:pointer;}}
    button.danger{{background:#e74c3c;}}
</style></head>
<body>
    <a href="/admin/users">← Все пользователи</a> | <a href="/admin/dashboard">Дашборд</a>
    <h1>👤 @{user['username'] or user_id} <span style="font-size:14px;color:#888">(ID: {user_id})</span></h1>

    <div class="row"><span class="lbl">Роль:</span> <span>{user['role']}</span></div>
    <div class="row"><span class="lbl">Статус:</span> <span style="color:{'#2ecc71' if user['is_active'] else '#e74c3c'}">{'✅ Активен' if user['is_active'] else '⛔ Забанен'}</span></div>
    <div class="row"><span class="lbl">Подписка:</span> <span>{sub_status}</span></div>
    <div class="row"><span class="lbl">Канал:</span> <span>{user['channel_title'] or '—'} (<code>{user['channel_id'] or '—'}</code>)</span></div>
    <div class="row"><span class="lbl">API-ключ:</span> <span><code>{user['api_key'][:4] + '****' if user['api_key'] else '—'}</code></span></div>
    <div class="row"><span class="lbl">ERID override:</span> <span><code>{user['client_erid_override'] or '—'}</code></span></div>
    <div class="row"><span class="lbl">Фильтры:</span> <span>WB: {'✅' if user['filter_wb'] else '❌'} | Ozon: {'✅' if user['filter_ozon'] else '❌'}</span></div>
    <div class="row"><span class="lbl">Автозакреп:</span> <span>{'✅' if user['auto_pin'] else '❌'}</span></div>
    <div class="row"><span class="lbl">Режим:</span> <span>{user.get('blogger_mode', '—')}</span></div>

    {finance_block}

    <!-- Быстрое редактирование -->
    <h2>⚙️ Быстрые действия</h2>
    <form action="/admin/user/{user_id}/extend" method="post" style="display:inline">
        <input type="number" name="days" placeholder="Дней" value="30" style="width:70px">
        <button>Продлить подписку</button>
    </form>
    <form action="/admin/user/{user_id}/toggle_ban" method="post" style="display:inline">
        <button class="{'danger' if user['is_active'] else ''}">{'⛔ Забанить' if user['is_active'] else '✅ Разбанить'}</button>
    </form>
    <form action="/admin/user/{user_id}/update_field" method="post">
        <input type="text" name="field" placeholder="Поле (api_key, client_erid_override)">
        <input type="text" name="value" placeholder="Новое значение">
        <button>Обновить</button>
    </form>

    <h2>📢 Каналы ({len(channels)})</h2>
    <table>
        <tr><th>Статус</th><th>ID</th><th>Название</th></tr>
        {channel_rows if channel_rows else "<tr><td colspan='3'>Нет каналов</td></tr>"}
    </table>

    <h2>📝 Последние посты (20)</h2>
    <table>
        <tr><th>ID</th><th>Статус</th><th>Донор</th><th>Дата</th></tr>
        {post_rows if post_rows else "<tr><td colspan='4'>Нет постов</td></tr>"}
    </table>
</body></html>"""
        return HTMLResponse(html)

    # =====================================================================
    # === POST-ЭНДПОИНТЫ ДЛЯ КАРТОЧКИ ПОЛЬЗОВАТЕЛЯ ========================
    # =====================================================================
    @app.post("/admin/user/{user_id}/extend")
    async def extend_user_subscription(request: Request, user_id: int, days: int = Form(...)):
        is_authenticated(request)
        conn = get_db()
        try:
            new_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            conn.execute("UPDATE users SET subscription_until=?, is_active=1 WHERE user_id=?",
                        (new_date, user_id))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse(f"/admin/user/{user_id}", status_code=302)

    @app.post("/admin/user/{user_id}/toggle_ban")
    async def toggle_ban_user(request: Request, user_id: int):
        is_authenticated(request)
        conn = get_db()
        try:
            current = conn.execute("SELECT is_active FROM users WHERE user_id=?", (user_id,)).fetchone()
            new_status = 0 if current and current["is_active"] else 1
            conn.execute("UPDATE users SET is_active=? WHERE user_id=?", (new_status, user_id))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse(f"/admin/user/{user_id}", status_code=302)

    @app.post("/admin/user/{user_id}/update_field")
    async def update_user_field(request: Request, user_id: int, field: str = Form(...), value: str = Form(...)):
        is_authenticated(request)
        allowed_fields = {"api_key", "client_erid_override", "payout_card"}
        if field not in allowed_fields:
            return HTMLResponse("<h3>❌ Недопустимое поле</h3>", status_code=400)
        conn = get_db()
        try:
            conn.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value.strip() or None, user_id))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse(f"/admin/user/{user_id}", status_code=302)

      # =====================================================================
    # === ВСЕ ПОСТЫ С ФИЛЬТРАЦИЕЙ =========================================
    # =====================================================================
    @app.get("/admin/posts", response_class=HTMLResponse)
    async def all_posts(request: Request, status: str = "", user_id: str = ""):
        is_authenticated(request)
        conn = get_db()
        try:
            query = """
                SELECT p.*, u.username FROM posts p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE 1=1
            """
            params = []
            if status:
                query += " AND p.status = ?"
                params.append(status)
            if user_id:
                query += " AND p.user_id = ?"
                params.append(int(user_id))
            query += " ORDER BY p.id DESC LIMIT 100"
            posts = conn.execute(query, params).fetchall()

            # Статистика статусов
            status_counts = conn.execute("""
                SELECT status, COUNT(*) as cnt FROM posts GROUP BY status
            """).fetchall()
        finally:
            conn.close()

        # Фильтр-панель
        filter_html = '<div style="margin-bottom:15px">'
        filter_html += f'<a href="/admin/posts" style="color:#3498db">Все</a> '
        for sc in status_counts:
            filter_html += f'| <a href="/admin/posts?status={sc["status"]}" style="color:#888">{sc["status"]} ({sc["cnt"]})</a> '
        filter_html += '</div>'

        rows = ""
        for p in posts:
            pub = str(p["published_at"])[:16] if p["published_at"] else "—"
            rows += f"""
            <tr>
                <td>{p['id']}</td>
                <td>@{p['username'] or p['user_id']}</td>
                <td>{p['donor_post_id'][:30]}</td>
                <td>{p['status']}</td>
                <td>{p.get('quarantine_reason', '')[:30]}</td>
                <td>{pub}</td>
                <td><a href="/admin/user/{p['user_id']}">👤</a></td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Все посты</title>
<style>
    body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}
    h1{{color:#fff;}}
    table{{width:100%;border-collapse:collapse;margin-top:15px;}}
    th,td{{padding:8px;border:1px solid #333;text-align:left;font-size:13px;}}
    th{{background:#1a1d27;}}
    a{{color:#3498db;text-decoration:none;}}
</style></head>
<body>
    <a href="/admin/dashboard">← Дашборд</a>
    <h1>📬 Все посты</h1>
    {filter_html}
    <table>
        <tr><th>ID</th><th>Пользователь</th><th>Донор</th><th>Статус</th><th>Причина</th><th>Дата</th><th></th></tr>
        {rows if rows else "<tr><td colspan='7'>Нет постов</td></tr>"}
    </table>
</body></html>"""
        return HTMLResponse(html)

      # =====================================================================
    # === УПРАВЛЕНИЕ ДОНОРСКИМИ КАНАЛАМИ ==================================
    # =====================================================================
    @app.get("/admin/donors", response_class=HTMLResponse)
    async def donors_page(request: Request):
        is_authenticated(request)
        import os
        channels_raw = os.getenv("SAAS_DONOR_CHANNELS", "")
        donor_list = [c.strip() for c in channels_raw.split(",") if c.strip()]
        
        rows = ""
        for ch in donor_list:
            rows += f"""
            <tr>
                <td>@{ch}</td>
                <td>
                    <a href="/admin/donors/preview?channel={ch}" style="color:#3498db">🔍 Просмотреть</a>
                </td>
                <td>
                    <form action="/admin/donors/remove" method="post" style="display:inline">
                        <input type="hidden" name="channel" value="{ch}">
                        <button style="padding:4px 8px;background:#e74c3c;border:none;color:#fff;border-radius:4px;cursor:pointer">Удалить</button>
                    </form>
                </td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Каналы-доноры</title>
<style>
    body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}
    h1{{color:#fff;}}
    table{{width:100%;border-collapse:collapse;margin-top:15px;}}
    th,td{{padding:8px;border:1px solid #333;text-align:left;}}
    th{{background:#1a1d27;}}
    a{{color:#3498db;text-decoration:none;}}
</style></head>
<body>
    <a href="/admin/dashboard">← Дашборд</a>
    <h1>📡 Каналы-доноры</h1>
    <form action="/admin/donors/add" method="post" style="margin-bottom:15px">
        <input type="text" name="channel" placeholder="@username канала" required>
        <button>Добавить</button>
    </form>
    <table>
        <tr><th>Канал</th><th>Действие</th><th></th></tr>
        {rows if rows else "<tr><td colspan='3'>Нет каналов</td></tr>"}
    </table>
</body></html>"""
        return HTMLResponse(html)

    @app.post("/admin/donors/add")
    async def add_donor(request: Request, channel: str = Form(...)):
        is_authenticated(request)
        import os
        channel = channel.strip().lstrip("@")
        current = os.getenv("SAAS_DONOR_CHANNELS", "")
        donors = [c.strip() for c in current.split(",") if c.strip()]
        if channel not in donors:
            donors.append(channel)
        # Сохраняем в .env или переменную окружения (здесь упрощённо – только в памяти на сессию)
        os.environ["SAAS_DONOR_CHANNELS"] = ",".join(donors)
        return RedirectResponse("/admin/donors", status_code=302)

    @app.post("/admin/donors/remove")
    async def remove_donor(request: Request, channel: str = Form(...)):
        is_authenticated(request)
        import os
        channel = channel.strip().lstrip("@")
        current = os.getenv("SAAS_DONOR_CHANNELS", "")
        donors = [c.strip() for c in current.split(",") if c.strip() if c.strip() != channel]
        os.environ["SAAS_DONOR_CHANNELS"] = ",".join(donors)
        return RedirectResponse("/admin/donors", status_code=302)

    @app.get("/admin/donors/preview", response_class=HTMLResponse)
    async def preview_donor(request: Request, channel: str = ""):
        is_authenticated(request)
        from parser import fetch_telegram_channel_posts
        try:
            posts = await fetch_telegram_channel_posts(channel)
        except Exception as e:
            return HTMLResponse(f"<p>Ошибка: {e}</p>")

        rows = ""
        for p in posts[:10]:
            text_preview = (p.get("text", "") or "")[:80]
            rows += f"""
            <tr>
                <td>{p['id']}</td>
                <td>{text_preview}</td>
                <td>{'📷' if p.get('image_url') else '—'}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Донор @{channel}</title>
<style>
    body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}
    h1{{color:#fff;}}
    table{{width:100%;border-collapse:collapse;margin-top:15px;}}
    th,td{{padding:8px;border:1px solid #333;text-align:left;}}
    th{{background:#1a1d27;}}
</style></head>
<body>
    <a href="/admin/donors">← Каналы-доноры</a>
    <h1>📡 @{channel} — последние посты</h1>
    <table>
        <tr><th>ID</th><th>Текст</th><th>Фото</th></tr>
        {rows if rows else "<tr><td colspan='3'>Нет постов</td></tr>"}
    </table>
</body></html>"""
        return HTMLResponse(html)

    # =====================================================================
    # === СТРАНИЦА ВЫПЛАТ =================================================
    # =====================================================================
    @app.get("/admin/payouts", response_class=HTMLResponse)
    async def payouts_page(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            payouts = conn.execute("""
                SELECT py.*, u.username FROM payouts py
                LEFT JOIN users u ON py.user_id = u.user_id
                ORDER BY py.created_at DESC LIMIT 50
            """).fetchall()
        finally:
            conn.close()

        rows = ""
        for py in payouts:
            created = str(py["created_at"])[:16]
            status_color = "#2ecc71" if py["status"] == "completed" else "#f39c12" if py["status"] == "pending" else "#e74c3c"
            rows += f"""
            <tr>
                <td>#{py['id']}</td>
                <td>@{py['username'] or py['user_id']}</td>
                <td><code>{py['card']}</code></td>
                <td><b>{py['amount_blogger']:.2f} ₽</b></td>
                <td>{py['amount_to_withdraw']:.2f} ₽</td>
                <td style="color:{status_color}">{py['status']}</td>
                <td>{created}</td>
                <td>
                    {"<form action='/admin/payout_done' method='post' style='display:inline'><input type='hidden' name='payout_id' value='"+str(py['id'])+"'><input type='hidden' name='blogger_id' value='"+str(py['user_id'])+"'><button>✅</button></form>" if py['status'] == 'pending' else ""}
                </td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Выплаты</title>
<style>
    body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}
    h1{{color:#fff;}}
    table{{width:100%;border-collapse:collapse;margin-top:15px;}}
    th,td{{padding:8px;border:1px solid #333;text-align:left;}}
    th{{background:#1a1d27;}}
</style></head>
<body>
    <a href="/admin/dashboard">← Дашборд</a>
    <h1>💸 Выплаты</h1>
    <table>
        <tr><th>#</th><th>Блогер</th><th>Карта</th><th>Блогеру</th><th>Вывести</th><th>Статус</th><th>Дата</th><th></th></tr>
        {rows if rows else "<tr><td colspan='8'>Нет выплат</td></tr>"}
    </table>
</body></html>"""
        return HTMLResponse(html)

      # =====================================================================
    # === ГЛОБАЛЬНЫЕ НАСТРОЙКИ ПЛАТФОРМЫ ==================================
    # =====================================================================
    @app.get("/admin/settings", response_class=HTMLResponse)
    async def global_settings(request: Request):
        is_authenticated(request)
        import os
        night_start = os.getenv("NIGHT_START", "23:00")
        night_end = os.getenv("NIGHT_END", "08:00")
        run_interval = os.getenv("RUN_INTERVAL_SECONDS", "900")
        min_payout = os.getenv("MIN_PAYOUT", "2000")
        fixed_fee = os.getenv("PAYOUT_FIXED_FEE", "35")
        bank_pct = os.getenv("PAYOUT_BANK_PCT", "0.043")
        deepinfra_key = os.getenv("DEEPINFRA_API_KEY", "")
        master_token = os.getenv("TAKPRODAM_MASTER_TOKEN", "")

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Глобальные настройки</title>
<style>
    body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}
    h1,h2{{color:#fff;}}
    .row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #2a2d3a;}}
    .lbl{{color:#888;}}
    form{{margin:15px 0;}}
    input{{background:#1e2130;border:1px solid #444;color:#fff;padding:6px;border-radius:4px;width:200px;}}
    button{{padding:8px 16px;background:#3498db;border:none;color:#fff;border-radius:4px;cursor:pointer;}}
</style></head>
<body>
    <a href="/admin/dashboard">← Дашборд</a>
    <h1>⚙️ Глобальные настройки платформы</h1>
    <p style="color:#888"><i>Изменения вступают в силу после перезапуска бота.</i></p>

    <h2>Ночной режим</h2>
    <div class="row"><span class="lbl">Начало ночного режима</span><span>{night_start}</span></div>
    <div class="row"><span class="lbl">Конец ночного режима</span><span>{night_end}</span></div>

    <h2>Расписание</h2>
    <div class="row"><span class="lbl">Интервал сканирования (сек)</span><span>{run_interval}</span></div>

    <h2>Финансы</h2>
    <div class="row"><span class="lbl">Минимальная выплата (₽)</span><span>{min_payout}</span></div>
    <div class="row"><span class="lbl">Фикс. комиссия (₽)</span><span>{fixed_fee}</span></div>
    <div class="row"><span class="lbl">Банковский %</span><span>{bank_pct}</span></div>

    <h2>API-ключи</h2>
    <div class="row"><span class="lbl">DeepInfra</span><span><code>{deepinfra_key[:8]}***</code></span></div>
    <div class="row"><span class="lbl">ТакПродам мастер-токен</span><span><code>{master_token[:8]}***</code></span></div>
</body></html>"""
        return HTMLResponse(html)

    # =====================================================================
    # === ПРОСМОТР ЛОГОВ ==================================================
    # =====================================================================
    @app.get("/admin/logs", response_class=HTMLResponse)
    async def view_logs(request: Request):
        is_authenticated(request)
        try:
            with open("bot.log", "r") as f:
                lines = f.readlines()[-100:]  # последние 100 строк
            log_content = "".join(lines)
        except:
            log_content = "Файл логов не найден."

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Логи</title>
<style>
    body{{font-family:monospace;background:#0f1117;color:#e0e0e8;padding:20px;}}
    pre{{background:#1a1d27;padding:15px;border-radius:8px;overflow-x:auto;font-size:12px;}}
</style></head>
<body>
    <a href="/admin/dashboard">← Дашборд</a>
    <h2>📄 Последние 100 строк bot.log</h2>
    <pre>{log_content}</pre>
</body></html>"""
        return HTMLResponse(html)

    # =====================================================================
    # === ВОЗВРАЩАЕМ ПРИЛОЖЕНИЕ ===========================================
    # =====================================================================
    # =====================================================================
    # === ШПИОНСКИЙ РЕЖИМ: УПРАВЛЕНИЕ КАНАЛАМИ ============================
    # =====================================================================
    from channel_manager import (
        get_full_channel_report,
        channel_quick_action,
        safe_publish_to_channel
    )

    @app.get("/admin/channel/{channel_id}", response_class=HTMLResponse)
    async def channel_card(request: Request, channel_id: str):
        is_authenticated(request)
        report = await get_full_channel_report(bot, channel_id)
        info = report["info"]
        rights = report["rights"]
        posts = report["recent_posts"]
        admins = report["administrators"]

        # Статус бота
        if rights["error"]:
            status_color = "#e74c3c"
            status_text = f"❌ Ошибка: {rights['error']}"
        elif rights["status"] == "creator":
            status_color = "#2ecc71"
            status_text = "👑 Создатель"
        elif rights["is_admin"]:
            status_color = "#2ecc71"
            status_text = "✅ Администратор"
        else:
            status_color = "#f39c12"
            status_text = f"⚠️ Не админ (статус: {rights['status']})"

        # Таблица администраторов
        admin_rows = ""
        for a in admins:
            admin_rows += f"<tr><td>{'👑' if a['status']=='creator' else '👤'}</td><td>@{a['username'] or a['user_id']}</td><td>{a['status']}</td><td>{'✅' if a['can_post'] else '❌'}</td></tr>"

        # Последние посты
        post_rows = ""
        for p in posts:
            text_preview = (p["text"] or "")[:100]
            post_rows += f"<tr><td>{p['message_id']}</td><td>{p['date']}</td><td>{text_preview}</td></tr>"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Канал {channel_id}</title>
<style>
    body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}
    h1,h2{{color:#fff;}}
    table{{width:100%;border-collapse:collapse;margin:15px 0;}}
    th,td{{padding:10px;border:1px solid #333;text-align:left;}}
    th{{background:#1a1d27;}}
    .row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #2a2d3a;}}
    .lbl{{color:#888;}}
    button{{padding:6px 12px;background:#3498db;border:none;color:#fff;border-radius:4px;cursor:pointer;}}
    input,textarea{{background:#1e2130;border:1px solid #444;color:#fff;padding:6px;border-radius:4px;width:100%;}}
</style></head>
<body>
    <a href="/admin/dashboard">← Дашборд</a>
    <h1>📢 Канал: {info.get('title', channel_id)}</h1>
    <p style="color:{status_color}"><b>Статус бота:</b> {status_text}</p>

    <div class="row"><span class="lbl">ID:</span> <code>{info.get('id', '—')}</code></div>
    <div class="row"><span class="lbl">Username:</span> <span>@{info.get('username', '—')}</span></div>
    <div class="row"><span class="lbl">Подписчиков:</span> <span>{info.get('member_count', '—')}</span></div>
    <div class="row"><span class="lbl">Описание:</span> <span>{info.get('description', '—')}</span></div>

    {"<h2>👥 Администраторы</h2><table><tr><th></th><th>Пользователь</th><th>Роль</th><th>Публикация</th></tr>" + admin_rows + "</table>" if admins else ""}

    {"<h2>📝 Последние посты</h2><table><tr><th>ID</th><th>Дата</th><th>Текст</th></tr>" + post_rows + "</table>" if posts else ""}

    {"<h2>🚀 Тестовая публикация</h2>"
     "<form action='/admin/channel/" + channel_id + "/publish' method='post'>"
     "<textarea name='text' placeholder='Текст поста' rows=3></textarea><br><br>"
     "<input type='text' name='photo_url' placeholder='URL фото (необязательно)'><br><br>"
     "<button>Опубликовать</button></form>" if rights["can_post"] else ""}

    {"<h2>⚙️ Изменить описание</h2>"
     "<form action='/admin/channel/" + channel_id + "/description' method='post'>"
     "<input type='text' name='description' placeholder='Новое описание' value='" + (info.get('description') or '') + "'>"
     "<button>Сохранить</button></form>" if rights["can_post"] else ""}

    {"<h2>🖼 Сменить аватар</h2>"
     "<form action='/admin/channel/" + channel_id + "/photo' method='post'>"
     "<input type='text' name='photo_url' placeholder='Прямая ссылка на фото'>"
     "<button>Установить</button></form>" if rights["can_post"] else ""}
</body></html>"""
        return HTMLResponse(html)

    # === ЭНДПОИНТЫ ДЕЙСТВИЙ С КАНАЛОМ ===
    @app.post("/admin/channel/{channel_id}/publish")
    async def channel_publish(request: Request, channel_id: str, text: str = Form(...), photo_url: str = Form("")):
        is_authenticated(request)
        msg_id = await safe_publish_to_channel(bot, channel_id, text, photo_url or None)
        if msg_id:
            return RedirectResponse(f"/admin/channel/{channel_id}", status_code=302)
        return HTMLResponse("<h3>❌ Ошибка публикации</h3>", status_code=500)

    @app.post("/admin/channel/{channel_id}/description")
    async def channel_set_description(request: Request, channel_id: str, description: str = Form(...)):
        is_authenticated(request)
        await channel_quick_action(bot, channel_id, "set_description", description=description)
        return RedirectResponse(f"/admin/channel/{channel_id}", status_code=302)

    @app.post("/admin/channel/{channel_id}/photo")
    async def channel_set_photo(request: Request, channel_id: str, photo_url: str = Form(...)):
        is_authenticated(request)
        await channel_quick_action(bot, channel_id, "set_photo", photo_url=photo_url)
        return RedirectResponse(f"/admin/channel/{channel_id}", status_code=302)
    
    return app
    
