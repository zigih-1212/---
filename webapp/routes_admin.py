import os
import io, csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _safe_path(base_dir: str, user_path: str) -> str | None:
    """Resolve user_path inside base_dir; return None if traversal detected."""
    base = Path(base_dir).resolve()
    full = (base / user_path).resolve()
    if not str(full).startswith(str(base)):
        return None
    return str(full)
from fastapi import APIRouter, Request, Form, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse, StreamingResponse, JSONResponse
from jinja2 import Environment, BaseLoader, TemplateNotFound
from services.db import get_db
from webapp.auth import (
    admin_required, create_admin_session, delete_admin_session,
    verify_admin_session, verify_admin_token
)
from webapp.dependencies import get_bot
from webapp.templates import (
    BASE_TEMPLATE, LOGIN_TEMPLATE, DASHBOARD_TEMPLATE, USERS_TEMPLATE,
    USER_EDIT_TEMPLATE, POSTS_TEMPLATE, QUARANTINE_TEMPLATE,
    BROADCAST_TEMPLATE, PROMOCODES_TEMPLATE,
    STORE_DELIVERY_TEMPLATE, BULK_ACTIONS_TEMPLATE,
    SETTINGS_TEMPLATE, AUDIT_TEMPLATE, REPORTS_TEMPLATE,
    ADMIN_PAYOUTS_TEMPLATE,
    ADMIN_CHAT_TEMPLATE,
    ADMIN_CPC_TEMPLATE
)
from config import BOT_USERNAME
from aiogram.enums import ParseMode
from utils.feature_flags import (
    get_beta_testers, get_all_features, set_feature_status,
    add_beta_tester, remove_beta_tester
)
from helpers import log_admin_action

router = APIRouter()
logger = logging.getLogger("autopost_bot.admin")
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
    "admin_broadcast.html": BROADCAST_TEMPLATE,
    "admin_store_delivery.html": STORE_DELIVERY_TEMPLATE,
    "admin_bulk_actions.html": BULK_ACTIONS_TEMPLATE,
    "admin_settings.html": SETTINGS_TEMPLATE,
    "admin_audit.html": AUDIT_TEMPLATE,
    "admin_reports.html": REPORTS_TEMPLATE,
    "admin_payouts.html": ADMIN_PAYOUTS_TEMPLATE,
    "admin_chat.html": ADMIN_CHAT_TEMPLATE,
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

@router.get("/", response_class=HTMLResponse)
async def admin_root(request: Request):
    return RedirectResponse(url="/admin/dashboard", status_code=303)
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

@router.get("/payouts/{request_id}/chat", response_class=HTMLResponse)
async def admin_chat_page(request_id: int, request: Request, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT status FROM payout_requests WHERE id=?", (request_id,)).fetchone()
        if not req:
            return HTMLResponse("Заявка не найдена", status_code=404)
        return render("admin_chat.html", request_id=request_id, status=req["status"])
    finally:
        conn.close()

@router.get("/payouts/{request_id}/chat-data")
async def admin_chat_data(request_id: int, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT status FROM payout_requests WHERE id=?", (request_id,)).fetchone()
        if not req:
            return JSONResponse({"status": "unknown", "messages": []})
        messages = conn.execute("""
            SELECT sender_role, message, file_path, created_at
            FROM payout_chat
            WHERE request_id = ?
            ORDER BY created_at ASC
        """, (request_id,)).fetchall()
        return JSONResponse({
            "status": req["status"],
            "messages": [{
                "sender_role": m["sender_role"],
                "message": m["message"],
                "file_path": m["file_path"],
                "created_at": m["created_at"]
            } for m in messages]
        })
    finally:
        conn.close()

@router.post("/payouts/{request_id}/send-message")
async def admin_send_message(request_id: int, message: str = Form(...), admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT status FROM payout_requests WHERE id=?", (request_id,)).fetchone()
        if not req or req["status"] in ('completed', 'declined'):
            return JSONResponse({"ok": False})
        conn.execute("INSERT INTO payout_chat (request_id, sender_role, message) VALUES (?, 'admin', ?)",
                     (request_id, message))
        conn.commit()
        return JSONResponse({"ok": True})
    finally:
        conn.close()


@router.post("/payouts/request/{request_id}/send-money")
async def send_money(request_id: int, request: Request, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT * FROM payout_requests WHERE id=? AND status='processing'", (request_id,)).fetchone()
        if not req:
            return RedirectResponse(url="/admin/payouts", status_code=303)
        user_id = req["user_id"]
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE payout_requests SET status='awaiting_receipt', sent_at=?, receipt_reminded=0 WHERE id=?",
            (now_iso, request_id)
        )
        # Сообщение в чат
        conn.execute("INSERT INTO payout_chat (request_id, sender_role, message) VALUES (?, 'admin', ?)",
                     (request_id, "💰 Деньги отправлены. Пожалуйста, загрузите чек из приложения «Мой налог»."))
        conn.commit()

        # Уведомление блогеру
        bot = request.app.state.bot
        try:
            await bot.send_message(
                user_id,
                f"💰 Вам отправлен перевод на сумму <b>{req['amount']} ₽</b>.\nЗагрузите чек в веб-статистике.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        log_admin_action(admin_id, "send_money", f"request #{request_id}")
    finally:
        conn.close()
    return RedirectResponse(url="/admin/payouts", status_code=303)

@router.post("/payouts/request/{request_id}/decline")
async def decline_payout_request(request_id: int, request: Request, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT * FROM payout_requests WHERE id=? AND status!='completed'", (request_id,)).fetchone()
        if not req:
            return RedirectResponse(url="/admin/payouts", status_code=303)
        user_id = req["user_id"]
        amount = req["amount"]
        if req["status"] in ("processing", "awaiting_receipt", "receipt_uploaded"):
            conn.execute("UPDATE users SET balance_available = balance_available + ? WHERE user_id=?", (amount, user_id))
        conn.execute("UPDATE payout_requests SET status='declined' WHERE id=?", (request_id,))
        conn.execute("INSERT INTO payout_chat (request_id, sender_role, message) VALUES (?, 'admin', ?)",
                     (request_id, "❌ Заявка отклонена. Средства возвращены на баланс."))
        conn.commit()

        bot = request.app.state.bot
        try:
            await bot.send_message(user_id, "❌ Ваша заявка на выплату отклонена.")
        except: pass
        log_admin_action(admin_id, "decline_payout", f"request #{request_id}")
    finally:
        conn.close()
    return RedirectResponse(url="/admin/payouts", status_code=303)

@router.post("/payouts/request/{request_id}/confirm-receipt")
async def confirm_receipt(request_id: int, request: Request, admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT * FROM payout_requests WHERE id=? AND status='receipt_uploaded'", (request_id,)).fetchone()
        if not req:
            return RedirectResponse(url="/admin/payouts", status_code=303)
        conn.execute("UPDATE payout_requests SET status='completed' WHERE id=?", (request_id,))
        conn.execute("INSERT INTO payout_chat (request_id, sender_role, message) VALUES (?, 'admin', ?)",
                     (request_id, "✅ Чек принят. Выплата завершена."))
        conn.commit()

        bot = request.app.state.bot
        try:
            await bot.send_message(req["user_id"], "✅ Ваш чек принят! Выплата успешно завершена.")
        except: pass
        log_admin_action(admin_id, "confirm_receipt", f"request #{request_id}")
    finally:
        conn.close()
    return RedirectResponse(url="/admin/payouts", status_code=303)

@router.get("/payouts/{request_id}/status")
async def payout_request_status(request_id: int, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        req = conn.execute("SELECT status FROM payout_requests WHERE id=?", (request_id,)).fetchone()
        if req:
            return JSONResponse({"status": req["status"]})
        return JSONResponse({"status": "unknown"})
    finally:
        conn.close()

@router.get("/receipt-file")
async def get_receipt_file(path: str = Query(...), _: int = Depends(admin_required)):
    full_path = _safe_path("/app/data/receipts", path)
    if not full_path or not os.path.exists(full_path):
        return HTMLResponse("Файл не найден", status_code=404)
    return FileResponse(full_path)

@router.post("/settings/feature-status")
async def set_feature_status_endpoint(request: Request, feature_name: str = Form(...), status: str = Form(...), admin_id: int = Depends(admin_required)):
    """Установить статус фичи: dev | beta | released"""
    try:
        if set_feature_status(feature_name, status):
            log_admin_action(admin_id, "feature_status_changed", f"{feature_name}={status}")
        return RedirectResponse(url="/admin/settings-edit", status_code=303)
    except Exception as e:
        logger.error(f"Ошибка изменения статуса фичи: {e}")
        return HTMLResponse(f"<h1>Ошибка: {e}</h1>", status_code=500)


@router.post("/settings/beta-add")
async def beta_add(request: Request, user_id: int = Form(...), admin_id: int = Depends(admin_required)):
    try:
        if add_beta_tester(user_id):
            log_admin_action(admin_id, "beta_add", f"user_id={user_id}")
        return RedirectResponse(url="/admin/settings-edit", status_code=303)
    except Exception as e:
        logger.error(f"Ошибка добавления бета-тестера: {e}")
        return HTMLResponse(f"<h1>Ошибка: {e}</h1>", status_code=500)


@router.post("/settings/beta-remove")
async def beta_remove(request: Request, user_id: int = Form(...), admin_id: int = Depends(admin_required)):
    try:
        if remove_beta_tester(user_id):
            log_admin_action(admin_id, "beta_remove", f"user_id={user_id}")
        return RedirectResponse(url="/admin/settings-edit", status_code=303)
    except Exception as e:
        logger.error(f"Ошибка удаления бета-тестера: {e}")
        return HTMLResponse(f"<h1>Ошибка: {e}</h1>", status_code=500)
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
        pending_payouts = conn.execute("SELECT COUNT(*) FROM payout_requests WHERE status IN ('processing','awaiting_receipt','receipt_uploaded')").fetchone()[0]
        channels = conn.execute("SELECT DISTINCT channel_id, channel_title FROM channels ORDER BY channel_title").fetchall()
        
        # Аномалии CTR (пользователи, у которых средний CTR > 25% за 7 дней)
        raw_ctr = conn.execute("""
            SELECT s.subid1, s.clicks_count, s.leads_count,
                   ROUND(CAST(s.leads_count AS REAL) / NULLIF(s.clicks_count, 0) * 100, 1) as ctr,
                   c.user_id, u.username, c.channel_title
            FROM subid_stats s
            JOIN channels c ON c.sub_id = s.subid1
            JOIN users u ON u.user_id = c.user_id
            WHERE s.clicks_count > 10
              AND CAST(s.leads_count AS REAL) / s.clicks_count > 0.25
            ORDER BY ctr DESC
            LIMIT 10
        """).fetchall()
        ctr_alerts = [{
            "subid1": r["subid1"],
            "clicks": r["clicks_count"],
            "leads": r["leads_count"],
            "ctr": r["ctr"],
            "user_id": r["user_id"],
            "username": r["username"],
            "channel_title": r["channel_title"],
        } for r in raw_ctr]
    finally:
        conn.close()
    return render("admin_dashboard.html",
                  active_saas=active_saas, active_bloggers=active_bloggers,
                  posts_today=posts_today, posts_week=posts_week,
                  errors_today=errors_today, pending_payouts=pending_payouts,
                  channels=channels,
                  ctr_alerts=ctr_alerts,
                  current_period_label='30 дней',
                  period='30d',
                  active_page='dashboard')

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
                         cpc_banned: int = Form(0),
                         _: int = Depends(admin_required)):
    conn = get_db()
    try:
        sub_until = subscription_until if subscription_until else None
        conn.execute("""
            UPDATE users SET role=?, subscription_until=?, tariff_id=?,
            balance_available=?, balance_pending=?, commission_rate=?, cpc_banned=?
            WHERE user_id=?
        """, (role, sub_until, tariff_id, balance_available, balance_pending, commission_rate, cpc_banned, user_id))
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

# ---------- Посты ----------
@router.get("/posts", response_class=HTMLResponse)
async def posts_list(request: Request, user_id: str = "", _: int = Depends(admin_required)):
    conn = get_db()
    try:
        # Сначала получаем посты
        query = """
            SELECT p.id, p.user_id, p.channel_id, p.status, p.published_at, p.created_at,
                   p.erid as erid,
                   p.direct_link as direct_link,
                   p.donor_post_id,
                   p.caption as caption_text,
                   (SELECT channel_title FROM channels WHERE channel_id = p.channel_id AND user_id = p.user_id LIMIT 1) as channel_title
            FROM posts p
            WHERE p.status = 'published'
        """
        params = []
        if user_id:
            query += " AND p.user_id = ?"
            params.append(user_id)
        query += " ORDER BY p.id DESC LIMIT 100"
        posts = conn.execute(query, params).fetchall()
        
        # Получаем фото отдельным запросом для каждого поста
        for post in posts:
            donor_id = post["donor_post_id"]
            if donor_id and donor_id.startswith("admitad_"):
                try:
                    import re
                    match = re.match(r"admitad_(\d+)_", donor_id)
                    if match:
                        product_id = int(match.group(1))
                        product = conn.execute(
                            "SELECT image_url FROM gdeslon_catalog WHERE id = ? AND user_id = ?",
                            (product_id, post["user_id"])
                        ).fetchone()
                        if product:
                            post["photo_url"] = product["image_url"] or ""
                except Exception as e:
                    logger.warning(f"Не удалось получить фото для поста {post['id']}: {e}")
    except Exception as e:
        logger.error(f"Ошибка в posts_list: {e}")
        posts = []
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





# ---------- Рассылка ----------
@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_form(request: Request, _: int = Depends(admin_required)):
    return render("admin_broadcast.html", active_page='broadcast')

@router.post("/broadcast", response_class=HTMLResponse)
async def broadcast_send(request: Request, text: str = Form(...), role: str = Form("all"), _: int = Depends(admin_required)):
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



# ---------- Массовые действия ----------
@router.get("/bulk-actions", response_class=HTMLResponse)
async def bulk_actions_form(request: Request, _: int = Depends(admin_required)):
    return render("admin_bulk_actions.html", active_page='bulk')

@router.get("/bulk-actions/users")
async def bulk_actions_users(q: str = Query(""), _: int = Depends(admin_required)):
    conn = get_db()
    try:
        if q:
            users = conn.execute("""
                SELECT user_id, username, role, is_active, balance_available
                FROM users
                WHERE CAST(user_id AS TEXT) LIKE ? OR username LIKE ?
                ORDER BY user_id LIMIT 50
            """, (f"%{q}%", f"%{q}%")).fetchall()
        else:
            users = conn.execute("""
                SELECT user_id, username, role, is_active, balance_available
                FROM users ORDER BY user_id DESC LIMIT 50
            """).fetchall()
    finally:
        conn.close()
    return JSONResponse([{
        "user_id": u["user_id"],
        "username": u["username"] or "",
        "role": u["role"],
        "is_active": u["is_active"],
        "balance": u["balance_available"] or 0,
    } for u in users])

@router.post("/bulk-actions/execute", response_class=HTMLResponse)
async def bulk_actions_execute(request: Request, group: str = Form(...), action: str = Form(...),
                               value: float = Form(0), user_ids: str = Form(""),
                               _: int = Depends(admin_required)):
    conn = get_db()
    try:
        if user_ids:
            id_list = [int(x.strip()) for x in user_ids.split(",") if x.strip().isdigit()]
            if not id_list:
                return render("admin_bulk_actions.html", message="Некорректный список ID", active_page='bulk')
            placeholders = ",".join("?" * len(id_list))
            cond = f"WHERE user_id IN ({placeholders})"
            params = list(id_list)
        else:
            params = []
            cond = ""
            if group == "saas": cond = "WHERE role='saas'"
            elif group == "blogger": cond = "WHERE role='blogger'"
            elif group == "active": cond = "WHERE is_active=1"
            elif group == "banned": cond = "WHERE is_active=0"
            elif group == "with_balance": cond = "WHERE balance_available > 0"
            elif group == "no_posts": cond = f"WHERE user_id NOT IN (SELECT DISTINCT user_id FROM posts WHERE status='published')"
            elif group == "beta": cond = "WHERE beta_tester=1"

        if action == "activate":
            conn.execute(f"UPDATE users SET is_active=1 {cond}", params)
        elif action == "deactivate":
            conn.execute(f"UPDATE users SET is_active=0 {cond}", params)
        elif action == "reset_balance":
            conn.execute(f"UPDATE users SET balance_available=0, balance_pending=0 {cond}", params)
        elif action == "add_balance":
            if value > 0:
                conn.execute(f"UPDATE users SET balance_available = balance_available + ? {cond}", [value] + params)
        elif action == "set_commission":
            if 0 < value <= 1:
                conn.execute(f"UPDATE users SET commission_rate = ? {cond}", [value] + params)
        elif action == "add_beta":
            conn.execute(f"UPDATE users SET beta_tester=1 {cond}", params)
        elif action == "remove_beta":
            conn.execute(f"UPDATE users SET beta_tester=0 {cond}", params)
        elif action == "delete":
            conn.execute(f"DELETE FROM users {cond}", params)
        conn.commit()
        count = conn.total_changes
    finally:
        conn.close()
    return render("admin_bulk_actions.html", message=f"Выполнено. Затронуто строк: {count}", active_page='bulk')

@router.post("/bulk-actions/send-message", response_class=HTMLResponse)
async def bulk_send_message(request: Request, group: str = Form(...), text: str = Form(...),
                            user_ids: str = Form(""), _: int = Depends(admin_required)):
    bot = request.app.state.bot
    conn = get_db()
    try:
        if user_ids:
            id_list = [int(x.strip()) for x in user_ids.split(",") if x.strip().isdigit()]
            if not id_list:
                return render("admin_bulk_actions.html", message="Некорректный список ID", active_page='bulk')
            placeholders = ",".join("?" * len(id_list))
            users = conn.execute(f"SELECT user_id FROM users WHERE user_id IN ({placeholders})", id_list).fetchall()
        else:
            cond = ""
            if group == "saas": cond = "WHERE role='saas'"
            elif group == "blogger": cond = "WHERE role='blogger'"
            elif group == "active": cond = "WHERE is_active=1"
            elif group == "with_balance": cond = "WHERE balance_available > 0"
            elif group == "no_posts": cond = f"WHERE user_id NOT IN (SELECT DISTINCT user_id FROM posts WHERE status='published')"
            elif group == "beta": cond = "WHERE beta_tester=1"
            users = conn.execute(f"SELECT user_id FROM users {cond}").fetchall()

        sent = 0
        for u in users:
            try:
                await bot.send_message(chat_id=u["user_id"], text=text)
                sent += 1
            except Exception:
                pass
    finally:
        conn.close()
    return render("admin_bulk_actions.html", message=f"Сообщение отправлено {sent} из {len(users)} пользователям", active_page='bulk')

@router.get("/bulk-actions/export-csv")
async def bulk_export_csv(group: str = Query("all"), admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        cond = ""
        if group == "saas": cond = "WHERE role='saas'"
        elif group == "blogger": cond = "WHERE role='blogger'"
        elif group == "active": cond = "WHERE is_active=1"
        elif group == "banned": cond = "WHERE is_active=0"
        elif group == "with_balance": cond = "WHERE balance_available > 0"
        elif group == "no_posts": cond = f"WHERE user_id NOT IN (SELECT DISTINCT user_id FROM posts WHERE status='published')"
        elif group == "beta": cond = "WHERE beta_tester=1"

        users = conn.execute(f"""
            SELECT user_id, username, role, is_active, balance_available, balance_pending,
                   commission_rate, beta_tester, created_at
            FROM users {cond}
            ORDER BY user_id
        """).fetchall()
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "username", "role", "active", "balance_available", "balance_pending",
                      "commission_rate", "beta_tester", "created_at"])
    for u in users:
        writer.writerow([u["user_id"], u["username"] or "", u["role"], u["is_active"],
                         u["balance_available"], u["balance_pending"], u["commission_rate"],
                         u["beta_tester"], u["created_at"]])
    output.seek(0)
    log_admin_action(admin_id, "export_users_csv", f"group={group}, {len(users)} users")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=users_{group}_{datetime.now().strftime('%Y%m%d')}.csv"}
    )

# ---------- Глобальные настройки ----------
@router.get("/settings-edit", response_class=HTMLResponse)
async def settings_edit_form(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings_dict = {r['key']: r['value'] for r in rows}
    conn.close()
    
    # Получаем список всех фич и бета-тестеров
    features = get_all_features()
    beta_testers = get_beta_testers()
    feature_labels = {
        'preview_post': 'Предпросмотр постов',
        'ab_testing': 'A/B тестирование',
        'achievements': 'Достижения',
        'new_ui': 'Новый интерфейс',
        'alpha_feature': 'Альфа-функция'
    }
    for feature in features:
        feature['label'] = feature_labels.get(feature['name'], feature['name'])
    
    return render("admin_settings.html", 
                  settings=settings_dict, 
                  features=features,
                  beta_testers=beta_testers,
                  active_page='settings')

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
            ("NIGHT_START", night_start),
            ("NIGHT_END", night_end),
            ("RUN_INTERVAL_SECONDS", run_interval),
            ("PAYOUT_FIXED_FEE", min_payout),
            ("PAYOUT_BANK_PCT", payout_bank_pct)
        ]:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, val))
        conn.commit()
        log_admin_action(admin_id, "edit_settings", f"night={night_start}-{night_end}, interval={run_interval}, min_payout={min_payout}")
    except Exception as e:
        logger.error(f"Settings save error: {e}")
        return HTMLResponse(f"<h1>Ошибка сохранения: {e}</h1>", status_code=500)
    finally:
        conn.close()
    return RedirectResponse(url="/admin/settings-edit", status_code=303)

@router.get("/payouts/csv")
async def download_payouts_csv(admin_id: int = Depends(admin_required)):
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, user_id, amount, status, created_at
            FROM payout_requests
            ORDER BY id DESC
        """).fetchall()
    finally:
        conn.close()
    log_admin_action(admin_id, "export_payouts_csv", f"{len(rows)} rows")
    csv_content = generate_csv(rows, ["id", "user_id", "amount", "status", "created_at"])
    return StreamingResponse(io.StringIO(csv_content), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=payouts.csv"})

@router.get("/subid-stats/csv")
async def download_subid_stats_csv(admin_id: int = Depends(admin_required)):
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
    log_admin_action(admin_id, "export_subid_csv", f"{len(rows)} rows")
    csv_content = generate_csv(rows, ["subid1", "clicks_count", "leads_count", "earnings_pending", "earnings_approved", "channel_title", "username"])
    return StreamingResponse(io.StringIO(csv_content), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=subid_stats.csv"})

@router.get("/referrals/csv")
async def download_referrals_csv(admin_id: int = Depends(admin_required)):
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
    log_admin_action(admin_id, "export_referrals_csv", f"{len(rows)} rows")
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
    full_path = _safe_path("/app/data/reports", fname)
    if not full_path or not os.path.isfile(full_path):
        return HTMLResponse("Файл не найден", status_code=404)
    return FileResponse(full_path, media_type='text/csv', filename=fname)

@router.get("/dashboard/data")
async def dashboard_data(
    channel_id: str = Query(None),
    period: str = Query("30d"),
    _: int = Depends(admin_required)
):
    """Расширенный API дашборда с выбором периода и детальной статистикой."""
    conn = get_db()
    try:
        # Определяем период
        period_days = {"7d": 7, "30d": 30, "90d": 90, "all": None}
        period_labels = {"7d": "7 дней", "30d": "30 дней", "90d": "90 дней", "all": "Всё время"}
        days = period_days.get(period, 30)
        current_period_label = period_labels.get(period, "30 дней")
        date_filter = f"AND p.published_at >= datetime('now', '-{days} days')" if days else ""
        date_filter_at = f"AND at.time >= strftime('%s', 'now', '-{days} days')" if days else ""
        date_filter_subid = f"AND s.updated_at >= datetime('now', '-{days} days')" if days else ""

        channel_filter = ""
        params = []
        if channel_id and channel_id != 'all':
            channel_filter = "AND p.channel_id = ?"
            params.append(channel_id)

        # --- 1. Посты по дням ---
        posts_by_day = conn.execute(f"""
            SELECT DATE(published_at) as day, COUNT(*) as cnt
            FROM posts p
            WHERE p.status='published' {date_filter.replace('p.published_at', 'published_at')}
            {channel_filter}
            GROUP BY day
            ORDER BY day
        """, params).fetchall()

        # --- 2. Доход approved по дням ---
        if channel_id and channel_id != 'all':
            revenue_by_day = conn.execute(f"""
                SELECT DATE(at.time, 'unixepoch') as day, SUM(at.payment_sum) as total
                FROM admitad_transactions at
                LEFT JOIN channels c ON c.sub_id = at.subid1
                WHERE at.payment_status = 'approved'
                  {date_filter_at.replace('at.time', 'at.time')}
                  AND c.channel_id = ?
                GROUP BY day
                ORDER BY day
            """, (channel_id,)).fetchall()
        else:
            revenue_by_day = conn.execute(f"""
                SELECT DATE(time, 'unixepoch') as day, SUM(payment_sum) as total
                FROM admitad_transactions
                WHERE payment_status = 'approved'
                  {date_filter_at.replace('at.time', 'time')}
                GROUP BY day
                ORDER BY day
            """).fetchall()

        # --- 3. Доход pending по дням ---
        if channel_id and channel_id != 'all':
            pending_by_day = conn.execute(f"""
                SELECT DATE(at.time, 'unixepoch') as day, SUM(at.payment_sum) as total
                FROM admitad_transactions at
                LEFT JOIN channels c ON c.sub_id = at.subid1
                WHERE at.payment_status = 'pending'
                  {date_filter_at.replace('at.time', 'at.time')}
                  AND c.channel_id = ?
                GROUP BY day
                ORDER BY day
            """, (channel_id,)).fetchall()
        else:
            pending_by_day = conn.execute(f"""
                SELECT DATE(time, 'unixepoch') as day, SUM(payment_sum) as total
                FROM admitad_transactions
                WHERE payment_status = 'pending'
                  {date_filter_at.replace('at.time', 'time')}
                GROUP BY day
                ORDER BY day
            """).fetchall()

        # --- 4. Магазины по доходам (approved) ---
        if channel_id and channel_id != 'all':
            store_revenue = conn.execute(f"""
                SELECT COALESCE(g.source, 'Другой') as store,
                       COUNT(DISTINCT at.id) as transactions,
                       SUM(at.payment_sum) as revenue,
                       COUNT(DISTINCT p.id) as posts_count
                FROM admitad_transactions at
                LEFT JOIN posts p ON p.donor_post_id LIKE '%' || at.admitad_id || '%' AND p.status='published'
                LEFT JOIN gdeslon_catalog g ON g.id = CAST(substr(p.donor_post_id, 9, instr(substr(p.donor_post_id, 9), '_') - 1) AS INTEGER)
                WHERE at.payment_status = 'approved'
                  {date_filter_at.replace('at.time', 'at.time')}
                  AND p.channel_id = ?
                GROUP BY store
                ORDER BY revenue DESC
                LIMIT 15
            """, (channel_id,)).fetchall()
        else:
            store_revenue = conn.execute(f"""
                SELECT COALESCE(g.source, 'Другой') as store,
                       COUNT(DISTINCT at.id) as transactions,
                       SUM(at.payment_sum) as revenue,
                       COUNT(DISTINCT p.id) as posts_count
                FROM admitad_transactions at
                LEFT JOIN posts p ON p.donor_post_id LIKE '%' || at.admitad_id || '%' AND p.status='published'
                LEFT JOIN gdeslon_catalog g ON g.id = CAST(substr(p.donor_post_id, 9, instr(substr(p.donor_post_id, 9), '_') - 1) AS INTEGER)
                WHERE at.payment_status = 'approved'
                  {date_filter_at.replace('at.time', 'at.time')}
                GROUP BY store
                ORDER BY revenue DESC
                LIMIT 15
            """).fetchall()

        # --- 5. Топ-пользователей по доходу ---
        if channel_id and channel_id != 'all':
            top_users = conn.execute(f"""
                SELECT u.user_id, u.username, u.role,
                       COALESCE(SUM(at.payment_sum), 0) as total_revenue,
                       COUNT(DISTINCT at.id) as transactions,
                       COUNT(DISTINCT p.id) as posts_count
                FROM users u
                LEFT JOIN posts p ON p.user_id = u.user_id AND p.status='published' AND p.channel_id = ?
                  {date_filter.replace('p.published_at', 'p.published_at')}
                LEFT JOIN channels c ON c.user_id = u.user_id AND c.channel_id = ?
                LEFT JOIN subid_stats s ON s.subid1 = c.sub_id
                LEFT JOIN admitad_transactions at ON at.subid1 = c.sub_id AND at.payment_status = 'approved'
                  {date_filter_at.replace('at.time', 'at.time')}
                GROUP BY u.user_id
                HAVING total_revenue > 0 OR posts_count > 0
                ORDER BY total_revenue DESC
                LIMIT 20
            """, (channel_id, channel_id)).fetchall()
        else:
            top_users = conn.execute(f"""
                SELECT u.user_id, u.username, u.role,
                       COALESCE(SUM(at.payment_sum), 0) as total_revenue,
                       COUNT(DISTINCT at.id) as transactions,
                       COUNT(DISTINCT p.id) as posts_count
                FROM users u
                LEFT JOIN admitad_transactions at ON at.user_id = u.user_id AND at.payment_status = 'approved'
                  {date_filter_at.replace('at.time', '')}
                LEFT JOIN posts p ON p.user_id = u.user_id AND p.status='published'
                  {date_filter.replace('p.published_at', 'p.published_at')}
                GROUP BY u.user_id
                HAVING total_revenue > 0 OR posts_count > 0
                ORDER BY total_revenue DESC
                LIMIT 20
            """).fetchall()

        # --- 6. Общая статистика ---
        total_stats = conn.execute(f"""
            SELECT
                COALESCE(SUM(CASE WHEN at.payment_status='approved' THEN at.payment_sum ELSE 0 END), 0) as total_approved,
                COALESCE(SUM(CASE WHEN at.payment_status='pending' THEN at.payment_sum ELSE 0 END), 0) as total_pending,
                COUNT(DISTINCT CASE WHEN at.payment_status='approved' THEN at.id END) as approved_count,
                COUNT(DISTINCT CASE WHEN at.payment_status='pending' THEN at.id END) as pending_count
            FROM admitad_transactions at
            WHERE 1=1 {date_filter_at.replace('at.time', 'at.time')}
        """).fetchone()

        # --- 7. Магазины по постам (как было) ---
        store_dist_params = list(params)
        if channel_id and channel_id != 'all':
            store_dist_params.append(channel_id)
        store_distribution = conn.execute(f"""
            SELECT g.source, COUNT(*) as cnt
            FROM posts p
            JOIN gdeslon_catalog g ON p.donor_post_id LIKE 'admitad_' || g.id || '_%'
            WHERE p.status='published' {date_filter.replace('p.published_at', 'p.published_at')}
            {channel_filter}
            GROUP BY g.source
            ORDER BY cnt DESC
        """, store_dist_params).fetchall()

        # --- 8. Аномалии CTR ---
        ctr_alerts = conn.execute("""
            SELECT s.subid1, s.clicks_count, s.leads_count,
                   ROUND(CAST(s.leads_count AS REAL) / NULLIF(s.clicks_count, 0) * 100, 1) as ctr,
                   c.user_id, u.username, c.channel_title
            FROM subid_stats s
            JOIN channels c ON c.sub_id = s.subid1
            JOIN users u ON u.user_id = c.user_id
            WHERE s.clicks_count > 10
              AND CAST(s.leads_count AS REAL) / s.clicks_count > 0.25
            ORDER BY ctr DESC
            LIMIT 10
        """).fetchall()

        # --- 9. Статистика по каналам ---
        if channel_id and channel_id != 'all':
            channel_stats = conn.execute(f"""
                SELECT c.channel_id, c.channel_title, c.user_id, u.username,
                       COUNT(DISTINCT p.id) as posts_count,
                       COALESCE(SUM(s.clicks_count), 0) as clicks,
                       COALESCE(SUM(s.leads_count), 0) as leads,
                       COALESCE(SUM(s.earnings_approved), 0) as earnings
                FROM channels c
                LEFT JOIN users u ON u.user_id = c.user_id
                LEFT JOIN posts p ON p.channel_id = c.channel_id AND p.status='published'
                  {date_filter.replace('p.published_at', 'p.published_at')}
                LEFT JOIN subid_stats s ON s.subid1 = c.sub_id
                WHERE c.is_active = 1 AND c.channel_id = ?
                GROUP BY c.channel_id
            """, (channel_id,)).fetchall()
        else:
            channel_stats = conn.execute(f"""
                SELECT c.channel_id, c.channel_title, c.user_id, u.username,
                       COUNT(DISTINCT p.id) as posts_count,
                       COALESCE(SUM(s.clicks_count), 0) as clicks,
                       COALESCE(SUM(s.leads_count), 0) as leads,
                       COALESCE(SUM(s.earnings_approved), 0) as earnings
                FROM channels c
                LEFT JOIN users u ON u.user_id = c.user_id
                LEFT JOIN posts p ON p.channel_id = c.channel_id AND p.status='published'
                  {date_filter.replace('p.published_at', 'p.published_at')}
                LEFT JOIN subid_stats s ON s.subid1 = c.sub_id
                WHERE c.is_active = 1
                GROUP BY c.channel_id
                HAVING posts_count > 0 OR clicks > 0
                ORDER BY earnings DESC
                LIMIT 20
            """).fetchall()

        # --- 10. Сводка по выбранному каналу ---
        channel_summary = None
        selected_channel_title = None
        if channel_id and channel_id != 'all':
            channel_summary = conn.execute(f"""
                SELECT c.channel_title,
                       COUNT(DISTINCT p.id) as posts_count,
                       COALESCE(SUM(s.clicks_count), 0) as clicks,
                       COALESCE(SUM(s.leads_count), 0) as leads,
                       COALESCE(SUM(s.earnings_approved), 0) as earnings
                FROM channels c
                LEFT JOIN posts p ON p.channel_id = c.channel_id AND p.status = 'published'
                  {date_filter.replace('p.published_at', 'p.published_at')}
                LEFT JOIN subid_stats s ON s.subid1 = c.sub_id
                WHERE c.channel_id = ?
                GROUP BY c.channel_id
            """, (channel_id,)).fetchone()
            if channel_summary:
                selected_channel_title = channel_summary['channel_title'] or channel_id
            else:
                selected_channel_title = channel_id

        # --- 11. Статистика по SubID2 (отдельные посты) ---
        subid2_stats = conn.execute(f"""
            SELECT 
                p.subid2,
                c.channel_id,
                c.channel_title,
                COUNT(DISTINCT at.id) as transactions,
                COALESCE(SUM(CASE WHEN at.payment_status = 'approved' THEN at.payment_sum ELSE 0 END), 0) as earnings_approved,
                COALESCE(SUM(CASE WHEN at.payment_status = 'pending' THEN at.payment_sum ELSE 0 END), 0) as earnings_pending,
                COUNT(DISTINCT CASE WHEN at.payment_status IN ('approved', 'pending') THEN at.id END) as clicks,
                COUNT(DISTINCT CASE WHEN at.payment_status = 'approved' THEN at.id END) as leads
            FROM posts p
            LEFT JOIN channels c ON c.channel_id = p.channel_id
            LEFT JOIN admitad_transactions at ON at.subid2 = p.subid2
            WHERE p.status = 'published'
              {date_filter.replace('p.published_at', 'p.published_at')}
              {channel_filter}
            GROUP BY p.subid2, c.channel_id
            HAVING clicks > 0 OR leads > 0 OR earnings_approved > 0 OR earnings_pending > 0
            ORDER BY earnings_approved DESC
            LIMIT 50
        """, params).fetchall()

    finally:
        conn.close()

    conversion = 0.0
    if channel_summary and channel_summary['clicks'] > 0:
        conversion = round(channel_summary['leads'] / channel_summary['clicks'] * 100, 1)

    # Собираем все даты для графика доходов (approved + pending)
    all_revenue_dates = sorted(set(
        [r["day"] for r in revenue_by_day] +
        [r["day"] for r in pending_by_day]
    ))

    revenue_map = {r["day"]: r["total"] for r in revenue_by_day}
    pending_map = {r["day"]: r["total"] for r in pending_by_day}

    # Подготовка subid2_stats для шаблона
    subid2_list = []
    for s in subid2_stats:
        clicks = s["clicks"] or 0
        leads = s["leads"] or 0
        ctr = round(leads / clicks * 100, 1) if clicks > 0 else 0
        earnings = (s["earnings_approved"] or 0) + (s["earnings_pending"] or 0)
        status = "✅ Одобрено" if s["earnings_approved"] > 0 else ("⏳ В ожидании" if s["earnings_pending"] > 0 else "—")
        subid2_list.append({
            "subid2": s["subid2"] or "—",
            "channel_id": s["channel_id"],
            "channel_title": s["channel_title"],
            "clicks": clicks,
            "leads": leads,
            "ctr": ctr,
            "earnings": earnings,
            "status": status
        })

    return {
        "period": period,
        "current_period_label": current_period_label,
        "posts_labels": [r["day"] for r in posts_by_day],
        "posts_counts": [r["cnt"] for r in posts_by_day],
        "revenue_labels": all_revenue_dates,
        "revenue_approved": [revenue_map.get(d, 0) for d in all_revenue_dates],
        "revenue_pending": [pending_map.get(d, 0) for d in all_revenue_dates],
        "store_labels": [r["source"] or "Неизвестно" for r in store_distribution],
        "store_values": [r["cnt"] for r in store_distribution],
        "store_revenue_labels": [r["store"] for r in store_revenue],
        "store_revenue_values": [r["revenue"] for r in store_revenue],
        "store_revenue_posts": [r["posts_count"] for r in store_revenue],
        "store_revenue_transactions": [r["transactions"] for r in store_revenue],
        "top_users": [
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "role": r["role"],
                "total_revenue": r["total_revenue"],
                "transactions": r["transactions"],
                "posts_count": r["posts_count"]
            } for r in top_users
        ],
        "total_approved": total_stats["total_approved"],
        "total_pending": total_stats["total_pending"],
        "approved_count": total_stats["approved_count"],
        "pending_count": total_stats["pending_count"],
        "channel_stats": [
            {
                "channel_id": r["channel_id"],
                "channel_title": r["channel_title"],
                "user_id": r["user_id"],
                "username": r["username"],
                "posts_count": r["posts_count"],
                "clicks": r["clicks"],
                "leads": r["leads"],
                "earnings": r["earnings"],
                "conversion": round(r["leads"] / r["clicks"] * 100, 1) if r["clicks"] > 0 else 0,
                "ctr": round(r["leads"] / r["clicks"] * 100, 1) if r["clicks"] > 0 else 0
            } for r in channel_stats
        ],
        "ctr_alerts": [
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "channel_title": r["channel_title"],
                "subid1": r["subid1"],
                "clicks": r["clicks_count"],
                "leads": r["leads_count"],
                "ctr": r["ctr"]
            } for r in ctr_alerts
        ],
        "channel_summary": {
            "posts_count": channel_summary["posts_count"],
            "clicks": channel_summary["clicks"],
            "leads": channel_summary["leads"],
            "earnings": channel_summary["earnings"],
            "conversion": conversion
        } if channel_summary else None,
        "selected_channel_title": selected_channel_title,
        "subid2_stats": subid2_list,
    }


@router.get("/cpc")
async def admin_cpc_page(request: Request, _: int = Depends(admin_required)):
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT c.campaign_id, c.name, c.image_url,
                   COALESCE(a.description, '') as description,
                   COALESCE(a.rules, '') as rules,
                   COUNT(*) as user_count,
                   SUM(c.times_posted) as times_posted
            FROM cpc_campaigns c
            LEFT JOIN cpc_admin_settings a ON c.campaign_id = a.campaign_id
            GROUP BY c.campaign_id
            ORDER BY c.name
        """).fetchall()
    finally:
        conn.close()
    return render("admin_cpc.html", campaigns=[dict(r) for r in rows], active_page='cpc')


@router.post("/cpc-save")
async def admin_cpc_save(campaign_id: int = Form(...), description: str = Form(""), rules: str = Form(""), _: int = Depends(admin_required)):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO cpc_admin_settings (campaign_id, description, rules, updated_at) VALUES (?,?,?,datetime('now')) "
            "ON CONFLICT(campaign_id) DO UPDATE SET description=excluded.description, rules=excluded.rules, updated_at=datetime('now')",
            (campaign_id, description, rules)
        )
        conn.execute(
            "UPDATE cpc_campaigns SET description=?, more_rules=? WHERE campaign_id=?",
            (description, rules, campaign_id)
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@router.post("/cpc-sync-all")
async def admin_cpc_sync_all(_: int = Depends(admin_required)):
    conn = get_db()
    try:
        user_ids = [r["user_id"] for r in conn.execute(
            "SELECT DISTINCT user_id FROM cpc_campaigns"
        ).fetchall()]
    finally:
        conn.close()

    from handlers.saas import _sync_cpc_campaigns
    count = 0
    for uid in user_ids:
        try:
            await _sync_cpc_campaigns(uid)
            count += 1
        except Exception as e:
            logger.error(f"CPC sync error for user {uid}: {e}")
    return {"ok": True, "count": count}