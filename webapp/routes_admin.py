# webapp/routes_admin.py
import os
import io, csv
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Form, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse
from jinja2 import Environment, BaseLoader, TemplateNotFound
from services.db import get_db
from webapp.auth import (
    admin_required, create_admin_session, delete_admin_session,
    verify_admin_session, verify_admin_token
)
from webapp.dependencies import get_bot
from webapp.templates import (
    BASE_TEMPLATE, LOGIN_TEMPLATE, DASHBOARD_TEMPLATE, USERS_TEMPLATE,
    USER_EDIT_TEMPLATE, POSTS_TEMPLATE, QUARANTINE_TEMPLATE, TARIFFS_TEMPLATE,
    TARIFF_EDIT_TEMPLATE, BROADCAST_TEMPLATE, PROMOCODES_TEMPLATE,
    STORE_DELIVERY_TEMPLATE, TEST_PROMOCODES_TEMPLATE, BULK_ACTIONS_TEMPLATE,
    SETTINGS_TEMPLATE, AUDIT_TEMPLATE, REPORTS_TEMPLATE,
    ADMIN_PAYOUTS_TEMPLATE
)
from fastapi.responses import StreamingResponse
from config import BOT_USERNAME

router = APIRouter()

# ---------- Загрузчик шаблонов ----------
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
    "admin_users.html": USERS_TEMPLATE,
    "admin_user_edit.html": USER_EDIT_TEMPLATE,
    "admin_posts.html": POSTS_TEMPLATE,
    "admin_quarantine.html": QUARANTINE_TEMPLATE,
    "admin_tariffs.html": TARIFFS_TEMPLATE,
    "admin_tariff_edit.html": TARIFF_EDIT_TEMPLATE,
    "admin_broadcast.html": BROADCAST_TEMPLATE,
    "admin_promocodes.html": PROMOCODES_TEMPLATE,
    "admin_store_delivery.html": STORE_DELIVERY_TEMPLATE,
    "admin_test_promocodes.html": TEST_PROMOCODES_TEMPLATE,
    "admin_bulk_actions.html": BULK_ACTIONS_TEMPLATE,
    "admin_settings.html": SETTINGS_TEMPLATE,
    "admin_audit.html": AUDIT_TEMPLATE,
    "admin_reports.html": REPORTS_TEMPLATE,
    "admin_payouts.html": ADMIN_PAYOUTS_TEMPLATE,
}

env = Environment(loader=DictLoader(TEMPLATES))

def render(template_name: str, **kwargs):
    template = env.get_template(template_name)
    return HTMLResponse(template.render(**kwargs))

def generate_csv(rows, headers):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row[h] for h in headers])
    output.seek(0)
    return output.getvalue()
# ---------- Вход / Выход ----------
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
            return render("login.html", error="Неверный или просроченный токен.")
    return render("login.html")

@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("admin_session")
    if token:
        delete_admin_session(token)
    resp = RedirectResponse(url="/admin/login", status_code=303)
    resp.delete_cookie("admin_session")
    return resp

# ---------- Дашборд ----------
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        active_saas = conn.execute("SELECT COUNT(*) FROM users WHERE role='saas' AND is_active=1").fetchone()[0]
        active_bloggers = conn.execute("SELECT COUNT(*) FROM users WHERE role='blogger' AND is_active=1").fetchone()[0]
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        posts_today = conn.execute("SELECT COUNT(*) FROM posts WHERE status='published' AND DATE(published_at)=?", (today,)).fetchone()[0]
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        posts_week = conn.execute("SELECT COUNT(*) FROM posts WHERE status='published' AND published_at >= ?", (week_ago,)).fetchone()[0]
        errors_today = conn.execute("SELECT COUNT(*) FROM posts WHERE status='error' AND DATE(created_at)=?", (today,)).fetchone()[0]
        pending_payouts = conn.execute("SELECT COUNT(*) FROM payouts WHERE status='pending'").fetchone()[0]
        last_users = conn.execute("SELECT user_id, role, created_at FROM users ORDER BY created_at DESC LIMIT 5").fetchall()
        last_posts = conn.execute("SELECT id, channel_id, status, published_at, created_at FROM posts ORDER BY id DESC LIMIT 5").fetchall()
    finally:
        conn.close()
    return render("admin_dashboard.html",
                  active_saas=active_saas, active_bloggers=active_bloggers,
                  posts_today=posts_today, posts_week=posts_week,
                  errors_today=errors_today, pending_payouts=pending_payouts,
                  last_users=last_users, last_posts=last_posts, active_page='dashboard')
# ---------- Пользователи ----------
@router.get("/users", response_class=HTMLResponse)
async def users_list(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        users = conn.execute("""
            SELECT u.user_id, u.role, u.subscription_until, u.tariff_id, t.name as tariff_name,
                   u.balance_available, u.balance_pending, u.commission_rate
            FROM users u LEFT JOIN tariffs t ON u.tariff_id = t.id
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
                         role: str = Form(...), subscription_until: str = Form(""),
                         tariff_id: int = Form(0), balance_available: float = Form(0.0),
                         balance_pending: float = Form(0.0),
                         commission_rate: float = Form(0.95),
                         _: int = Depends(admin_required)):
    conn = get_db()
    try:
        sub_until = subscription_until if subscription_until else None
        conn.execute("""
            UPDATE users SET role=?, subscription_until=?, tariff_id=?,
            balance_available=?, balance_pending=?, commission_rate=?
            WHERE user_id=?
        """, (role, sub_until, tariff_id, balance_available, balance_pending, commission_rate, user_id))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(url="/admin/users", status_code=303)

@router.get("/payouts", response_class=HTMLResponse)
async def payouts_list(request: Request, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        users = conn.execute("""
            SELECT user_id, role, username, balance_available, sub_id
            FROM users
            WHERE balance_available > 0
            ORDER BY balance_available DESC
        """).fetchall()
        requests = conn.execute("""
            SELECT pr.id, pr.user_id, pr.amount, pr.message, pr.status, pr.receipt_photo, pr.created_at
            FROM payout_requests pr
            ORDER BY 
                CASE pr.status 
                    WHEN 'processing' THEN 1 
                    WHEN 'awaiting_receipt' THEN 2 
                    WHEN 'receipt_uploaded' THEN 3 
                    ELSE 4 
                END,
                pr.created_at DESC
            LIMIT 50
        """).fetchall()
    finally:
        conn.close()
    return render("admin_payouts.html", users=users, requests=requests, active_page='payouts', bot_username=BOT_USERNAME)

@router.post("/payouts/request/{request_id}/send-money")
async def send_money(request_id: int, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT * FROM payout_requests WHERE id=? AND status='processing'", (request_id,)).fetchone()
        if not req:
            return RedirectResponse(url="/admin/payouts", status_code=303)
        user_id = req["user_id"]
        # Меняем статус
        conn.execute("UPDATE payout_requests SET status='awaiting_receipt' WHERE id=?", (request_id,))
        conn.commit()
        # Уведомление блогеру (через бота)
        bot = request.app.state.bot
        try:
            await bot.send_message(
                user_id,
                f"💰 Вам отправлен перевод на сумму <b>{req['amount']} ₽</b>.\n"
                "В соответствии с законом, вы обязаны в течение 24 часов сформировать чек в приложении «Мой налог» "
                "и отправить его сюда, нажав кнопку «📤 Отправить чек» в разделе Финансы.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        log_admin_action(admin_id, "send_money", f"request #{request_id}")
    finally:
        conn.close()
    return RedirectResponse(url="/admin/payouts", status_code=303)

@router.post("/payouts/request/{request_id}/decline")
async def decline_payout_request(request_id: int, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT * FROM payout_requests WHERE id=? AND status!='completed'", (request_id,)).fetchone()
        if not req:
            return RedirectResponse(url="/admin/payouts", status_code=303)
        user_id = req["user_id"]
        amount = req["amount"]
        # Если статус был processing или awaiting_receipt, возвращаем баланс
        if req["status"] in ("processing", "awaiting_receipt", "receipt_uploaded"):
            conn.execute("UPDATE users SET balance_available = balance_available + ? WHERE user_id=?", (amount, user_id))
        conn.execute("UPDATE payout_requests SET status='declined' WHERE id=?", (request_id,))
        conn.commit()
        log_admin_action(admin_id, "decline_payout", f"request #{request_id}")
    finally:
        conn.close()
    return RedirectResponse(url="/admin/payouts", status_code=303)

@router.post("/payouts/request/{request_id}/confirm-receipt")
async def confirm_receipt(request_id: int, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT * FROM payout_requests WHERE id=? AND status='receipt_uploaded'", (request_id,)).fetchone()
        if not req:
            return RedirectResponse(url="/admin/payouts", status_code=303)
        conn.execute("UPDATE payout_requests SET status='completed' WHERE id=?", (request_id,))
        conn.commit()
        log_admin_action(admin_id, "confirm_receipt", f"request #{request_id}")
        # Можно уведомить блогера
    finally:
        conn.close()
    return RedirectResponse(url="/admin/payouts", status_code=303)

@router.post("/payouts/pay")
async def payouts_execute(request: Request, user_id: int = Form(...), amount: float = Form(...),
                          admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        user = conn.execute("SELECT balance_available FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user:
            return RedirectResponse(url="/admin/payouts", status_code=303)
        if amount > user["balance_available"]:
            amount = user["balance_available"]
        conn.execute("INSERT INTO payouts (user_id, amount_requested, amount_to_withdraw, amount_blogger, card, status) VALUES (?, ?, ?, ?, ?, 'completed')",
                     (user_id, amount, amount, 0, 'manual'))
        conn.execute("UPDATE users SET balance_available = balance_available - ? WHERE user_id=?", (amount, user_id))
        conn.execute("UPDATE users SET payout_notified=0 WHERE user_id=?", (user_id,))
        conn.commit()
        log_admin_action(admin_id, "manual_payout", f"user {user_id} payout {amount}")
    finally:
        conn.close()
    return RedirectResponse(url="/admin/payouts", status_code=303)

@router.post("/payouts/request/{request_id}/complete")
async def complete_payout_request(request_id: int, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT * FROM payout_requests WHERE id=?", (request_id,)).fetchone()
        if not req or req["status"] != "pending":
            return RedirectResponse(url="/admin/payouts", status_code=303)
        user_id = req["user_id"]
        amount = req["amount"]
        # Списать баланс, если хватает (обычно amount = весь доступный баланс на момент запроса)
        conn.execute("UPDATE users SET balance_available = balance_available - ? WHERE user_id=?", (amount, user_id))
        # Обновить статус запроса
        conn.execute("UPDATE payout_requests SET status='completed' WHERE id=?", (request_id,))
        # Запись в payouts для истории
        conn.execute("INSERT INTO payouts (user_id, amount_requested, amount_to_withdraw, amount_blogger, card, status) VALUES (?, ?, ?, ?, ?, 'completed')",
                     (user_id, amount, amount, 0, 'request'))
        conn.execute("UPDATE users SET payout_notified=0 WHERE user_id=?", (user_id,))        
        conn.commit()
        log_admin_action(admin_id, "complete_payout_request", f"request #{request_id} user {user_id} amount {amount}")
    finally:
        conn.close()
    return RedirectResponse(url="/admin/payouts", status_code=303)

@router.post("/payouts/request/{request_id}/decline")
async def decline_payout_request(request_id: int, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        conn.execute("UPDATE payout_requests SET status='declined' WHERE id=?", (request_id,))
        conn.commit()
        log_admin_action(admin_id, "decline_payout_request", f"request #{request_id}")
    finally:
        conn.close()
    return RedirectResponse(url="/admin/payouts", status_code=303)
# ---------- Посты ----------
@router.get("/posts", response_class=HTMLResponse)
async def posts_list(request: Request, status: str = "", user_id: str = "", _: int = Depends(admin_required)):
    conn = get_db()
        query = """
            SELECT p.id, p.user_id, p.channel_id, p.status, p.published_at, p.created_at,
                   g.image_url as photo_url,
                   p.caption as caption_text,
                   (SELECT channel_title FROM channels WHERE channel_id = p.channel_id AND user_id = p.user_id LIMIT 1) as channel_title
            FROM posts p
            LEFT JOIN gdeslon_catalog g ON p.donor_post_id LIKE 'admitad_' || g.id || '_%'
            WHERE 1=1
        """
    params = []
    if status:
        query += " AND p.status = ?"
        params.append(status)
    if user_id:
        query += " AND p.user_id = ?"
        params.append(user_id)
    query += " ORDER BY p.id DESC LIMIT 100"
    try:
        posts = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    response = render("admin_posts.html", posts=posts, request=request, active_page='posts')
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ---------- Карантин ----------
@router.get("/quarantine", response_class=HTMLResponse)
async def quarantine_list(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        posts = conn.execute("SELECT * FROM posts WHERE status='quarantine' ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    return render("admin_quarantine.html", posts=posts, active_page='quarantine')

@router.post("/quarantine/approve/{post_id}", response_class=HTMLResponse)
async def quarantine_approve(post_id: int, erid: str = Form(...), advertiser: str = Form(""), _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("UPDATE posts SET status='published', erid=?, advertiser=?, quarantine_reason=NULL WHERE id=?", (erid, advertiser, post_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/quarantine", status_code=303)

@router.get("/quarantine/delete/{post_id}")
async def quarantine_delete(post_id: int, _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/quarantine", status_code=303)

# ---------- Тарифы ----------
@router.get("/tariffs", response_class=HTMLResponse)
async def tariffs_list(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        tariffs = conn.execute("SELECT * FROM tariffs ORDER BY id").fetchall()
    finally:
        conn.close()
    return render("admin_tariffs.html", tariffs=tariffs, active_page='tariffs')

@router.post("/tariffs/add", response_class=HTMLResponse)
async def tariff_add(name: str = Form(...), days: int = Form(...), price_rub: float = Form(...),
                     price_stars: int = Form(...), max_channels: int = Form(5),
                     max_stores: int = Form(3), max_posts_per_day: int = Form(25),
                     _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("INSERT INTO tariffs (name, days, price_rub, price_stars, max_channels, max_stores, max_posts_per_day, is_active) VALUES (?,?,?,?,?,?,?,1)",
                 (name, days, price_rub, price_stars, max_channels, max_stores, max_posts_per_day))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/tariffs", status_code=303)

@router.get("/tariffs/edit/{tariff_id}", response_class=HTMLResponse)
async def tariff_edit_form(tariff_id: int, request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        tariff = conn.execute("SELECT * FROM tariffs WHERE id=?", (tariff_id,)).fetchone()
        if not tariff:
            return HTMLResponse("Тариф не найден", status_code=404)
    finally:
        conn.close()
    return render("admin_tariff_edit.html", tariff=tariff, active_page='tariffs')

@router.post("/tariffs/edit/{tariff_id}", response_class=HTMLResponse)
async def tariff_edit_save(tariff_id: int, name: str = Form(...), days: int = Form(...),
                           price_rub: float = Form(...), price_stars: int = Form(...),
                           max_channels: int = Form(5), max_stores: int = Form(3),
                           max_posts_per_day: int = Form(25), _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("UPDATE tariffs SET name=?, days=?, price_rub=?, price_stars=?, max_channels=?, max_stores=?, max_posts_per_day=? WHERE id=?",
                 (name, days, price_rub, price_stars, max_channels, max_stores, max_posts_per_day, tariff_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/tariffs", status_code=303)

@router.get("/tariffs/delete/{tariff_id}")
async def tariff_delete(tariff_id: int, _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("DELETE FROM tariffs WHERE id=?", (tariff_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/tariffs", status_code=303)

# ---------- Рассылка ----------
@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_form(request: Request, _: int = Depends(admin_required)):
    return render("admin_broadcast.html", active_page='broadcast')

@router.post("/broadcast", response_class=HTMLResponse)
async def broadcast_send(request: Request, text: str = Form(...), role: str = Form("all"), _: int = Depends(admin_required)):
    bot = request.app.state.bot
    conn = get_db()
    try:
        users = conn.execute("SELECT user_id FROM users" if role == "all" else f"SELECT user_id FROM users WHERE role='{role}'").fetchall()
        success = 0
        for u in users:
            try:
                await bot.send_message(chat_id=u["user_id"], text=text)
                success += 1
            except: pass
        return render("admin_broadcast.html", message=f"Отправлено {success} из {len(users)}", active_page='broadcast')
    finally:
        conn.close()

# ---------- Купоны магазинов ----------
@router.get("/promocodes", response_class=HTMLResponse)
async def promocodes_list(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        promos = conn.execute("SELECT * FROM store_promocodes ORDER BY store, promocode").fetchall()
    finally:
        conn.close()
    return render("admin_promocodes.html", promos=promos, active_page='promocodes')

@router.post("/promocodes/add", response_class=HTMLResponse)
async def promocode_add(store: str = Form(...), promocode: str = Form(...), description: str = Form(""), _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("INSERT INTO store_promocodes (store, promocode, description) VALUES (?,?,?)", (store, promocode, description))
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
async def store_delivery_update(store: str = Form(...), delivery_text: str = Form(...), _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO store_delivery (store, delivery_text) VALUES (?,?)", (store, delivery_text))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/admin/store_delivery", status_code=303)

# ---------- Тестовые промокоды ----------
@router.get("/test_promocodes", response_class=HTMLResponse)
async def test_promocodes_list(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    promos = conn.execute("SELECT id, code, days, (SELECT COUNT(*) FROM promocode_activations WHERE UPPER(code)=UPPER(p.code)) as used_count FROM promocodes p ORDER BY id").fetchall()
    formatted = [{"id": p["id"], "code": p["code"], "days": p["days"], "used": p["used_count"] > 0} for p in promos]
    conn.close()
    return render("admin_test_promocodes.html", promos=formatted, active_page='test_promo')

@router.post("/test_promocodes/add", response_class=HTMLResponse)
async def test_promocode_add(code: str = Form(...), days: int = Form(...), _: int = Depends(admin_required)):
    conn = get_db()
    conn.execute("INSERT INTO promocodes (code, days) VALUES (?,?)", (code.upper(), days))
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

# ---------- Массовые действия ----------
@router.get("/bulk-actions", response_class=HTMLResponse)
async def bulk_actions_form(request: Request, _: int = Depends(admin_required)):
    return render("admin_bulk_actions.html", active_page='bulk')

@router.post("/bulk-actions/execute", response_class=HTMLResponse)
async def bulk_actions_execute(request: Request, group: str = Form(...), action: str = Form(...),
                               days: int = Form(7), _: int = Depends(admin_required)):
    conn = get_db()
    cond = ""
    if group == "saas": cond = "WHERE role='saas'"
    elif group == "blogger": cond = "WHERE role='blogger'"
    elif group == "active": cond = "WHERE is_active=1"
    elif group == "banned": cond = "WHERE is_active=0"
    elif group == "expired": cond = "WHERE subscription_until < datetime('now')"
    if action == "extend":
        conn.execute(f"UPDATE users SET subscription_until = datetime(subscription_until, '+{days} days') {cond}")
    elif action == "ban":
        conn.execute(f"UPDATE users SET is_active=0 {cond}")
    elif action == "unban":
        conn.execute(f"UPDATE users SET is_active=1 {cond}")
    elif action == "delete":
        conn.execute(f"DELETE FROM users {cond}")
    conn.commit()
    count = conn.total_changes
    conn.close()
    return render("admin_bulk_actions.html", message=f"Выполнено. Затронуто строк: {count}", active_page='bulk')

# ---------- Глобальные настройки ----------
@router.get("/settings-edit", response_class=HTMLResponse)
async def settings_edit_form(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = {r['key']: r['value'] for r in rows}
    conn.close()
    return render("admin_settings.html", settings=settings, active_page='settings')

@router.post("/settings-edit/save", response_class=HTMLResponse)
async def settings_edit_save(
    night_start: str = Form("23:00"),
    night_end: str = Form("08:00"),
    run_interval: str = Form("900"),
    min_payout: str = Form("2000"),
    payout_bank_pct: str = Form("0.043"),
    admin_id: int = Depends(admin_required)
):
    conn = get_db()
    try:
        for key, val in [
            ("night_start", night_start),
            ("night_end", night_end),
            ("run_interval", run_interval),
            ("min_payout", min_payout),
            ("payout_bank_pct", payout_bank_pct)
        ]:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, val))
        conn.commit()
        log_admin_action(admin_id, "edit_settings", f"night={night_start}-{night_end}, interval={run_interval}, min_payout={min_payout}")
    finally:
        conn.close()
    return RedirectResponse(url="/admin/settings-edit", status_code=303)

@router.get("/payouts/csv")
async def download_payouts_csv(_: int = Depends(admin_required)):
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, user_id, amount, message, status, receipt_photo, created_at
            FROM payout_requests
            ORDER BY id DESC
        """).fetchall()
    finally:
        conn.close()
    csv_content = generate_csv(rows, ["id", "user_id", "amount", "message", "status", "receipt_photo", "created_at"])
    return StreamingResponse(io.StringIO(csv_content), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=payouts.csv"})

@router.get("/subid-stats/csv")
async def download_subid_stats_csv(_: int = Depends(admin_required)):
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT s.subid1, s.clicks_count, s.leads_count, s.earnings_pending, s.earnings_approved, 
                   c.channel_title, u.username
            FROM subid_stats s
            LEFT JOIN channels c ON c.sub_id = s.subid1
            LEFT JOIN users u ON c.user_id = u.user_id
            ORDER BY s.earnings_approved DESC
        """).fetchall()
    finally:
        conn.close()
    csv_content = generate_csv(rows, ["subid1", "clicks_count", "leads_count", "earnings_pending", "earnings_approved", "channel_title", "username"])
    return StreamingResponse(io.StringIO(csv_content), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=subid_stats.csv"})

@router.get("/referrals/csv")
async def download_referrals_csv(_: int = Depends(admin_required)):
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT r.referrer_id, ref.username as referrer_name, r.referral_id, ref2.username as referral_name, r.total_brought_profit
            FROM referrals r
            JOIN users ref ON r.referrer_id = ref.user_id
            JOIN users ref2 ON r.referral_id = ref2.user_id
            ORDER BY r.total_brought_profit DESC
        """).fetchall()
    finally:
        conn.close()
    csv_content = generate_csv(rows, ["referrer_id", "referrer_name", "referral_id", "referral_name", "total_brought_profit"])
    return StreamingResponse(io.StringIO(csv_content), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=referrals.csv"})
# ---------- Аудит ----------
@router.get("/audit", response_class=HTMLResponse)
async def audit_list(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    audits = conn.execute("SELECT * FROM admin_audit ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()
    return render("admin_audit.html", audits=audits, active_page='audit')

# ---------- Отчёты ----------
@router.get("/reports", response_class=HTMLResponse)
async def reports_list(request: Request, _: int = Depends(admin_required)):
    reports_dir = "/app/data/reports"
    files = sorted(os.listdir(reports_dir), reverse=True) if os.path.exists(reports_dir) else []
    return render("admin_reports.html", files=files, active_page='reports')

@router.get("/reports/download/{fname}")
async def reports_download(fname: str, _: int = Depends(admin_required)):
    path = os.path.join("/app/data/reports", fname)
    if os.path.isfile(path):
        return FileResponse(path, media_type='text/csv', filename=fname)
    return HTMLResponse("Файл не найден", status_code=404)

@router.get("/dashboard/data")
async def dashboard_data(_: int = Depends(admin_required)):
    conn = get_db()
    try:
        # Посты по дням за последние 30 дней
        posts_by_day = conn.execute("""
            SELECT DATE(published_at) as day, COUNT(*) as cnt
            FROM posts
            WHERE status='published' AND published_at >= datetime('now', '-30 days')
            GROUP BY day
            ORDER BY day
        """).fetchall()
        # Доход по дням (сумма payment_sum) за последние 30 дней
        revenue_by_day = conn.execute("""
            SELECT DATE(time, 'unixepoch') as day, SUM(payment_sum) as total
            FROM admitad_transactions
            WHERE time >= strftime('%s', 'now', '-30 days')
            GROUP BY day
            ORDER BY day
        """).fetchall()
        # Распределение по магазинам за последние 30 дней (по количеству постов)
        store_distribution = conn.execute("""
            SELECT g.source, COUNT(*) as cnt
            FROM posts p
            JOIN gdeslon_catalog g ON p.donor_post_id LIKE 'admitad_' || g.id || '_%'
            WHERE p.status='published' AND p.published_at >= datetime('now', '-30 days')
            GROUP BY g.source
            ORDER BY cnt DESC
        """).fetchall()
    finally:
        conn.close()

    return {
        "posts_labels": [r["day"] for r in posts_by_day],
        "posts_counts": [r["cnt"] for r in posts_by_day],
        "revenue_labels": [r["day"] for r in revenue_by_day],
        "revenue_values": [r["total"] for r in revenue_by_day],
        "store_labels": [r["source"] or "Неизвестно" for r in store_distribution],
        "store_values": [r["cnt"] for r in store_distribution],
    }
