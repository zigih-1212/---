"""
admin_panel.py — Полная веб-админка AutoPost
Режим бога: дашборд, пользователи, очереди, карантин, промокоды, тарифы, аналитика, аудит, шпионский режим.
"""

import secrets
import sqlite3
import os
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from aiogram import Bot
import logging

logger = logging.getLogger("autopost_bot.admin_panel")

DB_PATH = "/app/data/autopost.db"

def get_db():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL;")
    return db

def create_fastapi_app(bot: Bot) -> FastAPI:
    app = FastAPI(title="AutoPost Admin Panel", docs_url=None, redoc_url=None)
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
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
            # Сохраняем ID первого админа для аудита (можно заменить на реальный механизм)
            admin_ids_str = os.getenv("ADMIN_IDS", "")
            first_admin = admin_ids_str.split(",")[0].strip() if admin_ids_str else "0"
            resp.set_cookie(key="admin_user_id", value=first_admin)
            return resp
        return HTMLResponse("<h3>❌ Неверный пароль</h3><a href='/admin/login'>Назад</a>")

    @app.get("/admin/logout")
    async def logout():
        resp = RedirectResponse("/admin/login")
        resp.delete_cookie("admin_token")
        resp.delete_cookie("admin_user_id")
        return resp

    # =============================================================================
    # === ДАШБОРД =================================================================
    # =============================================================================
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

            night_q = conn.execute("SELECT COUNT(*) as cnt FROM night_queue").fetchone()["cnt"]
            saas_q = conn.execute("SELECT COUNT(*) as cnt FROM saas_queue").fetchone()["cnt"]
            quarantine = conn.execute("SELECT COUNT(*) as cnt FROM posts WHERE status='quarantine'").fetchone()["cnt"]

            last_users = conn.execute("""
                SELECT user_id, username, role, subscription_until, is_active
                FROM users ORDER BY created_at DESC LIMIT 5
            """).fetchall()

            last_posts = conn.execute("""
                SELECT p.id, p.status, p.published_at, p.donor_post_id, u.username
                FROM posts p LEFT JOIN users u ON p.user_id = u.user_id
                ORDER BY p.id DESC LIMIT 5
            """).fetchall()
        finally:
            conn.close()

        html = f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>AutoPost Admin Dashboard</title>
<style>
    body{{font-family: 'Segoe UI', Arial, sans-serif; background:#0f1117; color:#e0e0e8; padding:20px;}}
    h1,h2{{color:#fff;}}
    .card-grid{{display:grid; grid-template-columns: repeat(auto-fill, minmax(160px,1fr)); gap:12px; margin-bottom:24px;}}
    .card{{background:#1a1d27; border:1px solid #2a2d3a; border-radius:10px; padding:16px; text-align:center;}}
    .card .num{{font-size:32px; font-weight:700; color:#fff;}}
    .card .lbl{{font-size:12px; color:#888; margin-top:4px;}}
    .card.warn .num{{color:#e74c3c;}}
    .card.ok .num{{color:#2ecc71;}}
    table{{width:100%; border-collapse:collapse; margin:20px 0;}}
    th,td{{padding:10px; border:1px solid #333; text-align:left;}}
    th{{background:#1a1d27;}}
    a{{color:#3498db; text-decoration:none;}}
    .section{{background:#1a1d27; padding:20px; border-radius:8px; margin-bottom:25px;}}
</style></head>
<body>
    <h1>AutoPost Admin Dashboard</h1>
    <a href="/admin/logout" style="color:#e74c3c;">Выход</a> |
    <a href="/admin/promocodes">🎁 Промокоды</a> |
    <a href="/admin/audit">📜 Аудит</a> |
    <a href="/admin/analytics">📈 Аналитика</a> |
    <a href="/admin/top-channels">🏆 Топы</a> |
    <a href="/admin/bulk-actions" style="color:#f39c12;">👥 Массовые действия</a> |
    <a href="/admin/settings-edit">⚙️ Глобальные настройки</a> |
    <a href="/admin/tariffs">💎 Тарифы</a>

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
        <p>🌙 <a href="/admin/night-queue">Ночная очередь</a>: <b>{night_q}</b> | 
        🅰️ <a href="/admin/saas-queue">SaaS-очередь</a>: <b>{saas_q}</b> | 
        🚨 <a href="/admin/quarantine">Карантин</a>: <b>{quarantine}</b></p>
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
</body></html>"""
        return HTMLResponse(html)

    # =============================================================================
    # === СПИСОК ПОЛЬЗОВАТЕЛЕЙ ====================================================
    # =============================================================================
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

        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Все пользователи</title>
<style>
    body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}
    table{{width:100%;border-collapse:collapse;margin-top:20px;}}
    th,td{{padding:10px;border:1px solid #333;text-align:left;}}
    th{{background:#1a1d27;}} a{{color:#3498db;text-decoration:none;}}
</style></head>
<body>
    <h1>👥 Все пользователи</h1>
    <a href="/admin/dashboard">← Дашборд</a>
    <table>
        <tr><th>ID</th><th>Username</th><th>Роль</th><th>Канал</th><th>Подписка до</th><th>Активен</th><th></th></tr>
        {rows}
    </table>
</body></html>""")

    # =============================================================================
    # === КАРТОЧКА ПОЛЬЗОВАТЕЛЯ ====================================================
    # =============================================================================
    @app.get("/admin/user/{user_id}", response_class=HTMLResponse)
    async def user_card(request: Request, user_id: int):
        is_authenticated(request)
        conn = get_db()
        try:
            user = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not user:
                return HTMLResponse("<h3>❌ Пользователь не найден</h3>", status_code=404)

# Вот здесь должен быть запрос счётчика
            catalog_count = conn.execute("SELECT COUNT(*) as cnt FROM gdeslon_catalog WHERE user_id = ? AND used = 0", (user_id,)).fetchone()["cnt"]
            channels = conn.execute("SELECT * FROM channels WHERE user_id=?", (user_id,)).fetchall()
            posts = conn.execute("SELECT * FROM posts WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()

            earned = 0.0
            withdrawn = 0.0
            pending = 0.0
            catalog_count = conn.execute("SELECT COUNT(*) as cnt FROM gdeslon_catalog WHERE user_id = ?", (user_id,)).fetchone()["cnt"]
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

        channel_rows = "".join(
            f"<tr><td>{'🟢' if ch['is_active'] else '🔴'}</td><td><code>{ch['channel_id']}</code></td><td>{ch['channel_title'] or '—'}</td></tr>"
            for ch in channels
        )
        post_rows = "".join(
            f"<tr><td>{p['id']}</td><td>{p['status']}</td><td>{p['donor_post_id'][:30]}</td><td>{str(p['published_at'])[:16] if p['published_at'] else '—'}</td></tr>"
            for p in posts
        )

        finance_block = ""
        if user["role"] == "blogger":
            available = round(earned - withdrawn - pending, 2)
            finance_block = f"""
            <h2>💰 Финансы</h2>
            <table>
                <tr><th>Заработано</th><th>Выведено</th><th>Ожидает</th><th style="color:#2ecc71">Доступно</th></tr>
                <tr><td>{earned} ₽</td><td>{withdrawn} ₽</td><td style="color:#f39c12">{pending} ₽</td><td style="color:#2ecc71"><b>{available} ₽</b></td></tr>
            </table>"""

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
    <div class="row"><span class="lbl">Режим:</span> <span>{user['blogger_mode'] if 'blogger_mode' in user.keys() else '—'}</span></div>

    {finance_block}

    <h2>⚙️ Быстрые действия</h2>
    <form action="/admin/user/{user_id}/extend" method="post" style="display:inline">
        <input type="number" name="days" placeholder="Дней" value="30" style="width:70px">
        <button>Продлить подписку</button>
    </form>
    <form action="/admin/user/{user_id}/toggle_ban" method="post" style="display:inline">
        <button class="{'danger' if user['is_active'] else ''}">{'⛔ Забанить' if user['is_active'] else '✅ Разбанить'}</button>
    </form>
    <a href="/admin/refill-catalog/{user_id}"><button>🔄 Пополнить каталог GdeSlon</button></a>
    <div class="row"><span class="lbl">Товаров в каталоге GdeSlon:</span> <span>{catalog_count}</span></div>
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

    # =============================================================================
    # === POST-ЭНДПОИНТЫ ДЛЯ КАРТОЧКИ ПОЛЬЗОВАТЕЛЯ ================================
    # =============================================================================
    @app.post("/admin/user/{user_id}/extend")
    async def extend_user_subscription(request: Request, user_id: int, days: int = Form(...)):
        is_authenticated(request)
        conn = get_db()
        try:
            new_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            conn.execute("UPDATE users SET subscription_until=?, is_active=1 WHERE user_id=?", (new_date, user_id))
            conn.commit()
            # Аудит
            from main import log_admin_action
            admin_id = int(request.cookies.get("admin_user_id", 0))
            log_admin_action(admin_id, "extend_subscription", f"user {user_id} +{days} days")
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
            from main import log_admin_action
            admin_id = int(request.cookies.get("admin_user_id", 0))
            log_admin_action(admin_id, "toggle_ban", f"user {user_id} new_status={new_status}")
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
            from main import log_admin_action
            admin_id = int(request.cookies.get("admin_user_id", 0))
            log_admin_action(admin_id, "update_field", f"user {user_id} {field}={value}")
        finally:
            conn.close()
        return RedirectResponse(f"/admin/user/{user_id}", status_code=302)

    # =============================================================================
    # === ВСЕ ПОСТЫ ================================================================
    # =============================================================================
    @app.get("/admin/posts", response_class=HTMLResponse)
    async def all_posts(request: Request, status: str = "", user_id: str = ""):
        is_authenticated(request)
        conn = get_db()
        try:
            query = """SELECT p.*, u.username FROM posts p LEFT JOIN users u ON p.user_id = u.user_id WHERE 1=1"""
            params = []
            if status:
                query += " AND p.status = ?"
                params.append(status)
            if user_id:
                query += " AND p.user_id = ?"
                params.append(int(user_id))
            query += " ORDER BY p.id DESC LIMIT 100"
            posts = conn.execute(query, params).fetchall()
            status_counts = conn.execute("SELECT status, COUNT(*) as cnt FROM posts GROUP BY status").fetchall()
        finally:
            conn.close()

        filter_html = '<div style="margin-bottom:15px">'
        filter_html += f'<a href="/admin/posts" style="color:#3498db">Все</a> '
        for sc in status_counts:
            filter_html += f'| <a href="/admin/posts?status={sc["status"]}" style="color:#888">{sc["status"]} ({sc["cnt"]})</a> '
        filter_html += '</div>'

        rows = "".join(
            f"""<tr><td>{p['id']}</td><td>@{p['username'] or p['user_id']}</td><td>{p['donor_post_id'][:30]}</td>
            <td>{p['status']}</td><td>{(p['quarantine_reason'] or '')[:30] if 'quarantine_reason' in p.keys() else ''}</td>
            <td>{str(p['published_at'])[:16] if p['published_at'] else '—'}</td><td><a href="/admin/user/{p['user_id']}">👤</a></td></tr>"""
            for p in posts
        )

        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Все посты</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin-top:15px;}}th,td{{padding:8px;border:1px solid #333;text-align:left;font-size:13px;}}
th{{background:#1a1d27;}}a{{color:#3498db;text-decoration:none;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>📬 Все посты</h1>{filter_html}
<table><tr><th>ID</th><th>Пользователь</th><th>Донор</th><th>Статус</th><th>Причина</th><th>Дата</th><th></th></tr>
{rows if rows else "<tr><td colspan='7'>Нет постов</td></tr>"}</table></body></html>""")

    # =============================================================================
    # === УПРАВЛЕНИЕ ДОНОРСКИМИ КАНАЛАМИ ============================================
    # =============================================================================
    @app.get("/admin/donors", response_class=HTMLResponse)
    async def donors_page(request: Request):
        is_authenticated(request)
        channels_raw = os.getenv("SAAS_DONOR_CHANNELS", "")
        donor_list = [c.strip() for c in channels_raw.split(",") if c.strip()]
        rows = "".join(
            f"""<tr><td>@{ch}</td><td><a href="/admin/donors/preview?channel={ch}" style="color:#3498db">🔍 Просмотреть</a></td>
            <td><form action="/admin/donors/remove" method="post" style="display:inline"><input type="hidden" name="channel" value="{ch}">
            <button style="padding:4px 8px;background:#e74c3c;border:none;color:#fff;border-radius:4px;cursor:pointer">Удалить</button></form></td></tr>"""
            for ch in donor_list
        )
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Каналы-доноры</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin-top:15px;}}th,td{{padding:8px;border:1px solid #333;text-align:left;}}
th{{background:#1a1d27;}}a{{color:#3498db;text-decoration:none;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>📡 Каналы-доноры</h1>
<form action="/admin/donors/add" method="post" style="margin-bottom:15px"><input type="text" name="channel" placeholder="@username канала" required><button>Добавить</button></form>
<table><tr><th>Канал</th><th>Действие</th><th></th></tr>{rows if rows else "<tr><td colspan='3'>Нет каналов</td></tr>"}</table></body></html>""")

    @app.post("/admin/donors/add")
    async def add_donor(request: Request, channel: str = Form(...)):
        is_authenticated(request)
        channel = channel.strip().lstrip("@")
        current = os.getenv("SAAS_DONOR_CHANNELS", "")
        donors = [c.strip() for c in current.split(",") if c.strip()]
        if channel not in donors:
            donors.append(channel)
        os.environ["SAAS_DONOR_CHANNELS"] = ",".join(donors)
        return RedirectResponse("/admin/donors", status_code=302)

    @app.post("/admin/donors/remove")
    async def remove_donor(request: Request, channel: str = Form(...)):
        is_authenticated(request)
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
        rows = "".join(
            f"<tr><td>{p['id']}</td><td>{(p.get('text', '') or '')[:80]}</td><td>{'📷' if p.get('image_url') else '—'}</td></tr>"
            for p in posts[:10]
        )
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Донор @{channel}</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin-top:15px;}}th,td{{padding:8px;border:1px solid #333;text-align:left;}}
th{{background:#1a1d27;}}</style></head>
<body><a href="/admin/donors">← Каналы-доноры</a><h1>📡 @{channel} — последние посты</h1>
<table><tr><th>ID</th><th>Текст</th><th>Фото</th></tr>{rows if rows else "<tr><td colspan='3'>Нет постов</td></tr>"}</table></body></html>""")

    # =============================================================================
    # === ПРОМОКОДЫ ================================================================
    # =============================================================================
    @app.get("/admin/promocodes", response_class=HTMLResponse)
    async def promocodes_page(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            promos = conn.execute("""
                SELECT p.code, p.days, p.created_at, a.user_id, a.channel_id, a.activated_at, u.username
                FROM promocodes p LEFT JOIN promocode_activations a ON p.code = a.code
                LEFT JOIN users u ON a.user_id = u.user_id ORDER BY p.created_at DESC
            """).fetchall()
        finally:
            conn.close()
        rows = "".join(
            f"""<tr><td><code>{p['code']}</code></td><td>{p['days']}</td>
            <td>{'✅ Использован' if p['activated_at'] else '🆕 Свободен'}</td>
            <td>{f"@{p['username']}" if p['username'] else p['user_id'] if p['activated_at'] else '—'}</td>
            <td>{str(p['activated_at'])[:16] if p['activated_at'] else '—'}</td>
            <td><form action="/admin/promocodes/delete" method="post" style="display:inline"><input type="hidden" name="code" value="{p['code']}">
            <button style="padding:4px 8px;background:#e74c3c;border:none;color:#fff;border-radius:4px;cursor:pointer">🗑</button></form></td></tr>"""
            for p in promos
        )
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Промокоды</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin-top:15px;}}th,td{{padding:8px;border:1px solid #333;text-align:left;}}
th{{background:#1a1d27;}}a{{color:#3498db;text-decoration:none;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>🎁 Промокоды</h1>
<div style="margin-bottom:15px">
<form action="/admin/promocodes/generate" method="post" style="display:inline"><input type="text" name="code" placeholder="Один код" required><input type="number" name="days" value="2" style="width:60px"><button>Создать один</button></form>
<form action="/admin/promocodes/generate_bulk" method="post" style="display:inline;margin-left:10px"><input type="number" name="count" placeholder="Кол-во" required style="width:70px"><input type="number" name="days" value="2" style="width:60px"><button>Сгенерировать массово</button></form>
</div>
<table><tr><th>Код</th><th>Дней</th><th>Статус</th><th>Кем активирован</th><th>Дата активации</th><th></th></tr>
{rows if rows else "<tr><td colspan='6'>Нет промокодов</td></tr>"}</table></body></html>""")

    @app.post("/admin/promocodes/generate")
    async def generate_promocode(request: Request, code: str = Form(...), days: int = Form(2)):
        is_authenticated(request)
        conn = get_db()
        try:
            conn.execute("INSERT INTO promocodes (code, days) VALUES (?, ?)", (code.strip().upper(), days))
            conn.commit()
        except:
            pass
        finally:
            conn.close()
        return RedirectResponse("/admin/promocodes", status_code=302)

    @app.post("/admin/promocodes/generate_bulk")
    async def generate_bulk_promocodes(request: Request, count: int = Form(...), days: int = Form(2)):
        is_authenticated(request)
        conn = get_db()
        try:
            for _ in range(count):
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                try:
                    conn.execute("INSERT INTO promocodes (code, days) VALUES (?, ?)", (code, days))
                except:
                    pass
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/promocodes", status_code=302)

    @app.post("/admin/promocodes/delete")
    async def delete_promocode(request: Request, code: str = Form(...)):
        is_authenticated(request)
        conn = get_db()
        try:
            conn.execute("DELETE FROM promocodes WHERE code = ?", (code,))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/promocodes", status_code=302)

    # =============================================================================
    # === НОЧНАЯ ОЧЕРЕДЬ ===========================================================
    # =============================================================================
    @app.get("/admin/night-queue", response_class=HTMLResponse)
    async def night_queue_page(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            rows = conn.execute("SELECT nq.*, u.username FROM night_queue nq LEFT JOIN users u ON nq.user_id = u.user_id ORDER BY nq.created_at DESC LIMIT 200").fetchall()
        finally:
            conn.close()
        items = "".join(
            f"""<tr><td>{r['id']}</td><td>@{r['username'] or r['user_id']}</td><td>{r['video_id'][:30]}</td><td>{r['sku'] or '—'}</td><td>{str(r['created_at'])[:16]}</td>
            <td><form action="/admin/night-queue/publish/{r['id']}" method="post" style="display:inline"><button style="background:#2ecc71;color:#fff;border:none;border-radius:4px;padding:4px 8px;cursor:pointer;">▶</button></form>
            <form action="/admin/night-queue/delete/{r['id']}" method="post" style="display:inline" onsubmit="return confirm('Удалить?')"><button style="background:#e74c3c;color:#fff;border:none;border-radius:4px;padding:4px 8px;cursor:pointer;">🗑</button></form></td></tr>"""
            for r in rows
        )
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Ночная очередь</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin-top:15px;}}th,td{{padding:8px;border:1px solid #333;text-align:left;}}th{{background:#1a1d27;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>🌙 Ночная очередь</h1>
<table><tr><th>ID</th><th>Пользователь</th><th>Видео</th><th>SKU</th><th>Дата</th><th>Действия</th></tr>
{items if items else "<tr><td colspan='6'>Очередь пуста</td></tr>"}</table></body></html>""")

    @app.post("/admin/night-queue/publish/{item_id}")
    async def night_queue_publish(request: Request, item_id: int):
        is_authenticated(request)
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM night_queue WHERE id = ?", (item_id,)).fetchone()
            if row:
                from parser import process_new_video
                await process_new_video(bot=bot, user_id=row["user_id"], video_id=row["video_id"],
                                        description=row["description"] or "", sku=row["sku"],
                                        photo_url=row["photo_url"], marketplace=row["marketplace"] or "wb")
                conn.execute("DELETE FROM night_queue WHERE id = ?", (item_id,))
                conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/night-queue", status_code=302)

    @app.post("/admin/night-queue/delete/{item_id}")
    async def night_queue_delete(request: Request, item_id: int):
        is_authenticated(request)
        conn = get_db()
        try:
            conn.execute("DELETE FROM night_queue WHERE id = ?", (item_id,))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/night-queue", status_code=302)

    # =============================================================================
    # === SAAS-ОЧЕРЕДЬ =============================================================
    # =============================================================================
    @app.get("/admin/saas-queue", response_class=HTMLResponse)
    async def saas_queue_page(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            rows = conn.execute("SELECT sq.*, u.username FROM saas_queue sq LEFT JOIN users u ON sq.user_id = u.user_id ORDER BY sq.created_at DESC LIMIT 200").fetchall()
        finally:
            conn.close()
        items = "".join(
            f"""<tr><td>{r['id']}</td><td>@{r['username'] or r['user_id']}</td><td>{r['channel_id']}</td><td>{r['donor_post_id'][:30]}</td>
            <td>{r['sku'] or '—'}</td><td>{str(r['created_at'])[:16]}</td>
            <td><form action="/admin/saas-queue/flush/{r['user_id']}" method="post" style="display:inline"><button style="background:#3498db;color:#fff;border:none;border-radius:4px;padding:4px 8px;cursor:pointer;">Опубликовать все</button></form></td></tr>"""
            for r in rows
        )
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>SaaS-очередь</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin-top:15px;}}th,td{{padding:8px;border:1px solid #333;text-align:left;}}th{{background:#1a1d27;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>🅰️ SaaS-очередь</h1>
<table><tr><th>ID</th><th>Пользователь</th><th>Канал</th><th>Пост</th><th>SKU</th><th>Дата</th><th>Действия</th></tr>
{items if items else "<tr><td colspan='7'>Очередь пуста</td></tr>"}</table></body></html>""")

    @app.post("/admin/saas-queue/flush/{user_id}")
    async def saas_queue_flush(request: Request, user_id: int):
        is_authenticated(request)
        from main import flush_saas_queue_for_user
        await flush_saas_queue_for_user(bot, user_id)
        return RedirectResponse("/admin/saas-queue", status_code=302)

    # =============================================================================
    # === КАРАНТИН ================================================================
    # =============================================================================
    @app.get("/admin/quarantine", response_class=HTMLResponse)
    async def quarantine_page(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            rows = conn.execute("SELECT p.*, u.username FROM posts p LEFT JOIN users u ON p.user_id = u.user_id WHERE p.status = 'quarantine' ORDER BY p.id DESC LIMIT 100").fetchall()
        finally:
            conn.close()
        items = "".join(
            f"""<tr><td>{r['id']}</td><td>@{r['username'] or r['user_id']}</td><td>{r['donor_post_id'][:30]}</td><td>{r['sku'] or '—'}</td>
            <td>{(r['quarantine_reason'] or '') if 'quarantine_reason' in r.keys() else ''}</td><td>{str(r['created_at'])[:16]}</td>
            <td><form action="/admin/quarantine/approve/{r['id']}" method="post" style="display:inline"><input type="text" name="erid" placeholder="ERID" required style="width:100px;"><input type="text" name="advertiser" placeholder="Рекламодатель" required style="width:120px;"><button style="background:#2ecc71;color:#fff;border:none;border-radius:4px;padding:4px 8px;cursor:pointer;">Одобрить</button></form>
            <form action="/admin/quarantine/delete/{r['id']}" method="post" style="display:inline" onsubmit="return confirm('Удалить пост из карантина?')"><button style="background:#e74c3c;color:#fff;border:none;border-radius:4px;padding:4px 8px;cursor:pointer;">🗑</button></form></td></tr>"""
            for r in rows
        )
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Карантин</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin-top:15px;}}th,td{{padding:8px;border:1px solid #333;text-align:left;}}th{{background:#1a1d27;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>🚨 Карантин</h1>
<table><tr><th>ID</th><th>Пользователь</th><th>Пост</th><th>SKU</th><th>Причина</th><th>Дата</th><th>Действия</th></tr>
{items if items else "<tr><td colspan='7'>Карантин пуст</td></tr>"}</table></body></html>""")

    @app.post("/admin/quarantine/approve/{post_id}")
    async def quarantine_approve(request: Request, post_id: int, erid: str = Form(...), advertiser: str = Form(...)):
        is_authenticated(request)
        conn = get_db()
        try:
            conn.execute("UPDATE posts SET erid = ?, status = 'published', quarantine_reason = 'Одобрен вручную' WHERE id = ?", (erid, post_id))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/quarantine", status_code=302)

    @app.post("/admin/quarantine/delete/{post_id}")
    async def quarantine_delete(request: Request, post_id: int):
        is_authenticated(request)
        conn = get_db()
        try:
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/quarantine", status_code=302)

    # =============================================================================
    # === МАССОВЫЕ ДЕЙСТВИЯ =======================================================
    # =============================================================================
    @app.get("/admin/bulk-actions", response_class=HTMLResponse)
    async def bulk_actions_page(request: Request):
        is_authenticated(request)
        return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Массовые действия</title>
<style>body{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}h1{color:#fff;}
label{display:block;margin:10px 0 5px;color:#ccc;}
select, input{background:#1e2130;border:1px solid #444;color:#fff;padding:8px;border-radius:4px;width:300px;}
button{padding:10px 20px;background:#3498db;border:none;color:#fff;border-radius:4px;cursor:pointer;margin-top:15px;}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>👥 Массовые действия</h1>
<form action="/admin/bulk-actions/execute" method="post" onsubmit="return confirm('Вы уверены?')">
<label>Группа пользователей:</label><select name="group">
<option value="all">Все пользователи</option><option value="saas">Только SaaS</option><option value="blogger">Только блогеры</option>
<option value="active">Активные (is_active=1)</option><option value="banned">Забаненные (is_active=0)</option><option value="expired">Истекшая подписка (SaaS)</option></select>
<label>Действие:</label><select name="action">
<option value="extend">Продлить подписку</option><option value="ban">Забанить</option><option value="unban">Разбанить</option><option value="delete">Удалить полностью</option></select>
<div id="days_block"><label>Количество дней (для продления):</label><input type="number" name="days" value="30" min="1"></div>
<button type="submit">Выполнить</button></form></body></html>""")

    @app.post("/admin/bulk-actions/execute")
    async def bulk_actions_execute(request: Request, group: str = Form(...), action: str = Form(...), days: int = Form(30)):
        is_authenticated(request)
        conn = get_db()
        try:
            conditions = {"all": "1=1", "saas": "role='saas'", "blogger": "role='blogger'",
                          "active": "is_active=1", "banned": "is_active=0",
                          "expired": "role='saas' AND (subscription_until IS NULL OR subscription_until < datetime('now'))"}
            where = conditions.get(group, "1=1")
            if action == "extend":
                new_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
                conn.execute(f"UPDATE users SET subscription_until = ?, is_active = 1 WHERE {where}", (new_date,))
            elif action == "ban":
                conn.execute(f"UPDATE users SET is_active = 0 WHERE {where}")
            elif action == "unban":
                conn.execute(f"UPDATE users SET is_active = 1 WHERE {where}")
            elif action == "delete":
                conn.execute(f"DELETE FROM channels WHERE user_id IN (SELECT user_id FROM users WHERE {where})")
                conn.execute(f"DELETE FROM posts WHERE user_id IN (SELECT user_id FROM users WHERE {where})")
                conn.execute(f"DELETE FROM payouts WHERE user_id IN (SELECT user_id FROM users WHERE {where})")
                conn.execute(f"DELETE FROM night_queue WHERE user_id IN (SELECT user_id FROM users WHERE {where})")
                conn.execute(f"DELETE FROM saas_queue WHERE user_id IN (SELECT user_id FROM users WHERE {where})")
                conn.execute(f"DELETE FROM promocode_activations WHERE user_id IN (SELECT user_id FROM users WHERE {where})")
                conn.execute(f"DELETE FROM users WHERE {where}")
            conn.commit()
            from main import log_admin_action
            admin_id = int(request.cookies.get("admin_user_id", 0))
            log_admin_action(admin_id, "bulk_action", f"{action} on group {group}")
        finally:
            conn.close()
        return RedirectResponse("/admin/dashboard", status_code=302)

    # =============================================================================
    # === ГЛОБАЛЬНЫЕ НАСТРОЙКИ (РЕДАКТИРОВАНИЕ) ===================================
    # =============================================================================
    @app.get("/admin/settings-edit", response_class=HTMLResponse)
    async def settings_edit_page(request: Request):
        is_authenticated(request)
        from main import load_settings
        s = load_settings()
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Настройки</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1{{color:#fff;}}
label{{display:block;margin:10px 0 5px;color:#ccc;}}input{{background:#1e2130;border:1px solid #444;color:#fff;padding:8px;border-radius:4px;width:200px;}}
button{{padding:10px 20px;background:#3498db;border:none;color:#fff;border-radius:4px;cursor:pointer;margin-top:15px;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>⚙️ Глобальные настройки</h1>
<form action="/admin/settings-edit/save" method="post">
<label>Начало ночи (ЧЧ:ММ)</label><input type="text" name="NIGHT_START" value="{s['NIGHT_START']}">
<label>Конец ночи (ЧЧ:ММ)</label><input type="text" name="NIGHT_END" value="{s['NIGHT_END']}">
<label>Интервал сканирования (сек)</label><input type="number" name="RUN_INTERVAL_SECONDS" value="{s['RUN_INTERVAL_SECONDS']}">
<label>Минимальная выплата (₽)</label><input type="number" name="MIN_PAYOUT" value="{s['MIN_PAYOUT']}" step="0.01">
<label>Фикс. комиссия (₽)</label><input type="number" name="PAYOUT_FIXED_FEE" value="{s['PAYOUT_FIXED_FEE']}" step="0.01">
<label>Банковский %</label><input type="text" name="PAYOUT_BANK_PCT" value="{s['PAYOUT_BANK_PCT']}">
<button type="submit">Сохранить</button></form></body></html>""")

    @app.post("/admin/settings-edit/save")
    async def settings_edit_save(request: Request, NIGHT_START: str = Form(...), NIGHT_END: str = Form(...),
                                 RUN_INTERVAL_SECONDS: int = Form(...), MIN_PAYOUT: float = Form(...),
                                 PAYOUT_FIXED_FEE: float = Form(...), PAYOUT_BANK_PCT: str = Form(...)):
        is_authenticated(request)
        conn = get_db()
        try:
            for key, value in [("NIGHT_START", NIGHT_START), ("NIGHT_END", NIGHT_END),
                               ("RUN_INTERVAL_SECONDS", str(RUN_INTERVAL_SECONDS)),
                               ("MIN_PAYOUT", str(MIN_PAYOUT)), ("PAYOUT_FIXED_FEE", str(PAYOUT_FIXED_FEE)),
                               ("PAYOUT_BANK_PCT", PAYOUT_BANK_PCT)]:
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
            from main import settings, load_settings, log_admin_action
            new_settings = load_settings()
            settings.update(new_settings)
            admin_id = int(request.cookies.get("admin_user_id", 0))
            log_admin_action(admin_id, "settings_changed", "Global settings updated")
        finally:
            conn.close()
        return HTMLResponse("<h3>✅ Настройки сохранены. Некоторые изменения потребуют перезапуска бота.</h3><a href='/admin/dashboard'>Назад</a>")

    # =============================================================================
    # === АНАЛИТИКА: ОБЩАЯ ДИНАМИКА ===============================================
    # =============================================================================
    @app.get("/admin/analytics", response_class=HTMLResponse)
    async def analytics_page(request: Request, days: int = 30):
        is_authenticated(request)
        conn = get_db()
        try:
            posts_by_day = conn.execute("SELECT DATE(published_at) as day, COUNT(*) as cnt FROM posts WHERE status='published' AND published_at >= datetime('now', ?) GROUP BY day ORDER BY day", (f'-{days} days',)).fetchall()
            users_by_day = conn.execute("SELECT DATE(created_at) as day, COUNT(*) as cnt FROM users WHERE created_at >= datetime('now', ?) GROUP BY day ORDER BY day", (f'-{days} days',)).fetchall()
            sales_by_day = conn.execute("SELECT DATE(created_at) as day, COUNT(*) as cnt, COALESCE(SUM(payout),0) as total FROM transactions WHERE created_at >= datetime('now', ?) GROUP BY day ORDER BY day", (f'-{days} days',)).fetchall()
        finally:
            conn.close()
        posts_rows = "".join(f"<tr><td>{r['day']}</td><td>{r['cnt']}</td></tr>" for r in posts_by_day)
        users_rows = "".join(f"<tr><td>{r['day']}</td><td>{r['cnt']}</td></tr>" for r in users_by_day)
        sales_rows = "".join(f"<tr><td>{r['day']}</td><td>{r['cnt']}</td><td>{r['total']:.2f} ₽</td></tr>" for r in sales_by_day)
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Аналитика</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1,h2{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin:15px 0;}}th,td{{padding:8px;border:1px solid #333;text-align:left;}}th{{background:#1a1d27;}}a{{color:#3498db;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>📈 Аналитика за последние {days} дней</h1>
<p><a href="?days=7">7 дней</a> | <a href="?days=30">30 дней</a> | <a href="?days=90">90 дней</a></p>
<h2>📬 Посты по дням</h2><table><tr><th>Дата</th><th>Количество</th></tr>{posts_rows or "<tr><td colspan='2'>Нет данных</td></tr>"}</table>
<h2>👥 Новые пользователи</h2><table><tr><th>Дата</th><th>Количество</th></tr>{users_rows or "<tr><td colspan='2'>Нет данных</td></tr>"}</table>
<h2>💰 Продажи по дням</h2><table><tr><th>Дата</th><th>Продаж</th><th>Сумма</th></tr>{sales_rows or "<tr><td colspan='3'>Нет данных</td></tr>"}</table>
</body></html>""")

    # =============================================================================
    # === АНАЛИТИКА: ТОП КАНАЛОВ / БЛОГЕРОВ =======================================
    # =============================================================================
    @app.get("/admin/top-channels", response_class=HTMLResponse)
    async def top_channels_page(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            top_channels = conn.execute("SELECT c.channel_title, c.channel_id, COUNT(p.id) as post_count FROM posts p JOIN channels c ON p.channel_id = c.channel_id WHERE p.status = 'published' GROUP BY p.channel_id ORDER BY post_count DESC LIMIT 20").fetchall()
            top_bloggers = conn.execute("SELECT u.username, u.user_id, COALESCE(SUM(t.payout), 0.0) as earned FROM users u LEFT JOIN transactions t ON u.sub_id = t.sub_id WHERE u.role = 'blogger' GROUP BY u.user_id ORDER BY earned DESC LIMIT 20").fetchall()
        finally:
            conn.close()
        ch_rows = "".join(f"<tr><td>{r['channel_title'] or r['channel_id']}</td><td>{r['post_count']}</td></tr>" for r in top_channels)
        bl_rows = "".join(f"<tr><td>@{r['username'] or r['user_id']}</td><td>{r['earned']:.2f} ₽</td></tr>" for r in top_bloggers)
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Топ</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1,h2{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin:15px 0;}}th,td{{padding:8px;border:1px solid #333;text-align:left;}}th{{background:#1a1d27;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>🏆 Топы</h1>
<h2>📢 Топ каналов по постам</h2><table><tr><th>Канал</th><th>Постов</th></tr>{ch_rows or "<tr><td colspan='2'>Нет данных</td></tr>"}</table>
<h2>💰 Топ блогеров по заработку</h2><table><tr><th>Блогер</th><th>Заработано</th></tr>{bl_rows or "<tr><td colspan='2'>Нет данных</td></tr>"}</table>
</body></html>""")

    # =============================================================================
    # === УПРАВЛЕНИЕ ТАРИФАМИ =====================================================
    # =============================================================================
    @app.get("/admin/tariffs", response_class=HTMLResponse)
    async def tariffs_page(request: Request):
        is_authenticated(request)
        from main import load_tariffs
        tariffs = load_tariffs()
        conn = get_db()
        try:
            users = conn.execute("SELECT user_id, username FROM users WHERE role='saas' ORDER BY username").fetchall()
        finally:
            conn.close()
        rows = "".join(
            f"""<tr><td>{t['id']}</td><td>{t['name']}</td><td>{t['days']} дн.</td><td>{t['price_rub']:.0f} ₽</td><td>{t['price_stars']} ⭐</td>
            <td><form action="/admin/tariffs/edit/{t['id']}" method="post" style="display:inline"><input type="hidden" name="name" value="{t['name']}"><input type="hidden" name="days" value="{t['days']}"><input type="hidden" name="price_rub" value="{t['price_rub']}"><input type="hidden" name="price_stars" value="{t['price_stars']}"><button style="background:#f39c12;color:#fff;border:none;border-radius:4px;padding:4px 8px;cursor:pointer;">✏️</button></form>
            <form action="/admin/tariffs/delete/{t['id']}" method="post" style="display:inline" onsubmit="return confirm('Удалить?')"><button style="background:#e74c3c;color:#fff;border:none;border-radius:4px;padding:4px 8px;cursor:pointer;">🗑</button></form></td></tr>"""
            for t in tariffs
        )
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Тарифы</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1,h2{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin:15px 0;}}th,td{{padding:8px;border:1px solid #333;text-align:left;}}
th{{background:#1a1d27;}}form{{margin:5px 0;}}input,select{{background:#1e2130;border:1px solid #444;color:#fff;padding:6px;border-radius:4px;}}
button{{padding:6px 12px;background:#3498db;border:none;color:#fff;border-radius:4px;cursor:pointer;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>💎 Тарифы</h1>
<h2>Добавить новый тариф</h2><form action="/admin/tariffs/add" method="post"><input type="text" name="name" placeholder="Название" required><input type="number" name="days" placeholder="Дней" required><input type="number" name="price_rub" placeholder="Цена в рублях" required step="0.01"><input type="number" name="price_stars" placeholder="Цена в звёздах" required><button>Создать</button></form>
<h2>Существующие тарифы</h2><table><tr><th>ID</th><th>Название</th><th>Дней</th><th>Рубли</th><th>Звёзды</th><th></th></tr>{rows}</table>
<h2>Назначить подписку пользователю</h2><form action="/admin/tariffs/assign" method="post"><select name="user_id"><option value="">-- Выберите пользователя --</option>{"".join(f"<option value='{u['user_id']}'>@{u['username'] or u['user_id']}</option>" for u in users)}</select><select name="tariff_id"><option value="">-- Выберите тариф --</option>{"".join(f"<option value='{t['id']}'> {t['name']} ({t['days']}дн.)</option>" for t in tariffs)}</select><button>Продлить / Назначить</button></form>
</body></html>""")

    @app.post("/admin/tariffs/add")
    async def add_tariff(request: Request, name: str = Form(...), days: int = Form(...), price_rub: float = Form(...), price_stars: int = Form(...)):
        is_authenticated(request)
        conn = get_db()
        try:
            conn.execute("INSERT INTO tariffs (name, days, price_rub, price_stars) VALUES (?, ?, ?, ?)", (name, days, price_rub, price_stars))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/tariffs", status_code=302)

    @app.post("/admin/tariffs/edit/{tariff_id}")
    async def edit_tariff(request: Request, tariff_id: int, name: str = Form(...), days: int = Form(...), price_rub: float = Form(...), price_stars: int = Form(...)):
        is_authenticated(request)
        conn = get_db()
        try:
            conn.execute("UPDATE tariffs SET name=?, days=?, price_rub=?, price_stars=? WHERE id=?", (name, days, price_rub, price_stars, tariff_id))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/tariffs", status_code=302)

    @app.post("/admin/tariffs/delete/{tariff_id}")
    async def delete_tariff(request: Request, tariff_id: int):
        is_authenticated(request)
        conn = get_db()
        try:
            conn.execute("DELETE FROM tariffs WHERE id=?", (tariff_id,))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/tariffs", status_code=302)

    @app.post("/admin/tariffs/assign")
    async def assign_tariff(request: Request, user_id: int = Form(...), tariff_id: int = Form(...)):
        is_authenticated(request)
        conn = get_db()
        try:
            tariff = conn.execute("SELECT days FROM tariffs WHERE id=?", (tariff_id,)).fetchone()
            if tariff:
                new_date = (datetime.now(timezone.utc) + timedelta(days=tariff["days"])).isoformat()
                conn.execute("UPDATE users SET subscription_until=?, is_active=1 WHERE user_id=?", (new_date, user_id))
                conn.execute("UPDATE users SET tariff_id = ? WHERE user_id = ?", (tariff_id, user_id))
                conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/tariffs", status_code=302)

    # =============================================================================
    # === АУДИТ ===================================================================
    # =============================================================================
    @app.get("/admin/audit", response_class=HTMLResponse)
    async def audit_page(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            logs = conn.execute("SELECT * FROM admin_audit ORDER BY id DESC LIMIT 200").fetchall()
        finally:
            conn.close()
        rows = "".join(f"<tr><td>{l['id']}</td><td>{l['admin_id']}</td><td>{l['action']}</td><td>{l['details']}</td><td>{str(l['created_at'])[:16]}</td></tr>" for l in logs)
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Аудит</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin-top:15px;}}th,td{{padding:8px;border:1px solid #333;text-align:left;}}th{{background:#1a1d27;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>📜 Аудит действий</h1>
<table><tr><th>ID</th><th>Админ</th><th>Действие</th><th>Детали</th><th>Дата</th></tr>
{rows if rows else "<tr><td colspan='5'>Нет записей</td></tr>"}</table></body></html>""")

    # =============================================================================
    # === ШПИОНСКИЙ РЕЖИМ: УПРАВЛЕНИЕ КАНАЛАМИ ====================================
    # =============================================================================
    from channel_manager import get_full_channel_report, channel_quick_action, safe_publish_to_channel

    @app.get("/admin/channel/{channel_id}", response_class=HTMLResponse)
    async def channel_card(request: Request, channel_id: str):
        is_authenticated(request)
        report = await get_full_channel_report(bot, channel_id)
        info = report["info"]
        rights = report["rights"]
        posts = report["recent_posts"]
        admins = report["administrators"]

        if rights["error"]:
            status_color, status_text = "#e74c3c", f"❌ Ошибка: {rights['error']}"
        elif rights["status"] == "creator":
            status_color, status_text = "#2ecc71", "👑 Создатель"
        elif rights["is_admin"]:
            status_color, status_text = "#2ecc71", "✅ Администратор"
        else:
            status_color, status_text = "#f39c12", f"⚠️ Не админ (статус: {rights['status']})"

        admin_rows = "".join(f"<tr><td>{'👑' if a['status']=='creator' else '👤'}</td><td>@{a['username'] or a['user_id']}</td><td>{a['status']}</td><td>{'✅' if a['can_post'] else '❌'}</td></tr>" for a in admins)
        post_rows = "".join(f"<tr><td>{p['message_id']}</td><td>{p['date']}</td><td>{(p['text'] or '')[:100]}</td></tr>" for p in posts)

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Канал {channel_id}</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}h1,h2{{color:#fff;}}
table{{width:100%;border-collapse:collapse;margin:15px 0;}}th,td{{padding:10px;border:1px solid #333;text-align:left;}}
th{{background:#1a1d27;}}.row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #2a2d3a;}}
.lbl{{color:#888;}}button{{padding:6px 12px;background:#3498db;border:none;color:#fff;border-radius:4px;cursor:pointer;}}
input,textarea{{background:#1e2130;border:1px solid #444;color:#fff;padding:6px;border-radius:4px;width:100%;}}</style></head>
<body><a href="/admin/dashboard">← Дашборд</a><h1>📢 Канал: {info.get('title', channel_id)}</h1>
<p style="color:{status_color}"><b>Статус бота:</b> {status_text}</p>
<div class="row"><span class="lbl">ID:</span> <code>{info.get('id', '—')}</code></div>
<div class="row"><span class="lbl">Username:</span> <span>@{info.get('username', '—')}</span></div>
<div class="row"><span class="lbl">Подписчиков:</span> <span>{info.get('member_count', '—')}</span></div>
<div class="row"><span class="lbl">Описание:</span> <span>{info.get('description', '—')}</span></div>
{"<h2>👥 Администраторы</h2><table><tr><th></th><th>Пользователь</th><th>Роль</th><th>Публикация</th></tr>" + admin_rows + "</table>" if admins else ""}
{"<h2>📝 Последние посты</h2><table><tr><th>ID</th><th>Дата</th><th>Текст</th></tr>" + post_rows + "</table>" if posts else ""}
{"<h2>🚀 Тестовая публикация</h2><form action='/admin/channel/" + channel_id + "/publish' method='post'><textarea name='text' placeholder='Текст поста' rows=3></textarea><br><br><input type='text' name='photo_url' placeholder='URL фото (необязательно)'><br><br><button>Опубликовать</button></form>" if rights["can_post"] else ""}
{"<h2>⚙️ Изменить описание</h2><form action='/admin/channel/" + channel_id + "/description' method='post'><input type='text' name='description' placeholder='Новое описание' value='" + (info.get('description') or '') + "'><button>Сохранить</button></form>" if rights["can_post"] else ""}
{"<h2>🖼 Сменить аватар</h2><form action='/admin/channel/" + channel_id + "/photo' method='post'><input type='text' name='photo_url' placeholder='Прямая ссылка на фото'><button>Установить</button></form>" if rights["can_post"] else ""}
</body></html>"""
        return HTMLResponse(html)

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

    # =====================================================================
    # === ПОПОЛНЕНИЕ КАТАЛОГА GDESLON (АДМИН) ============================
    # =====================================================================
    @app.get("/admin/refill-catalog/{user_id}", response_class=HTMLResponse)
    async def refill_catalog_page(request: Request, user_id: int):
        is_authenticated(request)
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Пополнение каталога</title>
<style>body{{font-family:Arial;background:#0f1117;color:#e0e0e8;padding:20px;}}
button{{padding:10px 20px;background:#3498db;border:none;color:#fff;border-radius:4px;cursor:pointer;}}</style></head>
<body><h2>Пополнить каталог для пользователя {user_id}</h2>
<form action="/admin/refill-catalog/{user_id}/run" method="post">
<button>Запустить пополнение</button></form></body></html>""")

    @app.post("/admin/refill-catalog/{user_id}/run")
    async def refill_catalog_run(request: Request, user_id: int):
        is_authenticated(request)
        from main import refill_all_catalogs

        conn = get_db()
        try:
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not user:
                return HTMLResponse("Пользователь не найден", status_code=404)
            before = conn.execute("SELECT COUNT(*) as cnt FROM gdeslon_catalog WHERE user_id = ? AND used = 0", (user_id,)).fetchone()["cnt"]
        finally:
            conn.close()

        try:
            await refill_all_catalogs(bot)
        except Exception as e:
            return HTMLResponse(f"<h3>Ошибка при пополнении</h3><pre>{html.escape(str(e))}</pre>", status_code=500)

        conn = get_db()
        after = conn.execute("SELECT COUNT(*) as cnt FROM gdeslon_catalog WHERE user_id = ? AND used = 0", (user_id,)).fetchone()["cnt"]
        conn.close()

        added = after - before
        if added > 0:
            title = "✅ Каталог успешно пополнен!"
            desc = f"В базу добавлено <b>{added}</b> новых товаров."
            color = "#2ecc71"
        else:
            title = "ℹ️ Новых товаров нет"
            desc = "Каталог не был пополнен. Фиды пусты или все товары уже загружены."
            color = "#f39c12"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta http-equiv="refresh" content="3;url=/admin/user/{user_id}"><title>Пополнение</title>
<style>body{{font-family:Arial;background:#0f1117;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;}}
.box{{background:#1a1d27;padding:40px;border-radius:10px;text-align:center;border-top:5px solid {color};}}
a{{color:#3498db;text-decoration:none;}}</style></head>
<body><div class="box"><h2 style="color:{color};">{title}</h2><p style="font-size:18px;">{desc}</p>
<p style="color:#888;font-size:14px;margin-top:20px;">Возвращаем обратно в карточку...</p>
<a href="/admin/user/{user_id}">Вернуться немедленно</a></div></body></html>"""
        return HTMLResponse(html)

    return app
