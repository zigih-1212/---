# webapp/routes_admin.py
import os
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from services.db import get_db
from webapp.auth import admin_required, create_admin_session, delete_admin_session, verify_admin_session
from webapp.dependencies import get_bot

router = APIRouter()
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates')
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

def render(template_name: str, **kwargs):
    template = env.get_template(template_name)
    return HTMLResponse(template.render(**kwargs))

# ---------- Логин (без меню) ----------
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # Если уже залогинен – перекинуть на дашборд
    token = request.cookies.get("admin_session")
    if token and verify_admin_session(token):
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    return render("login.html")

@router.post("/login")
async def login(response_class=HTMLResponse, request: Request = None, username: str = Form(...), password: str = Form(...)):
    from config import ADMIN_PASSWORD
    if username == "admin" and password == ADMIN_PASSWORD:
        token = create_admin_session()
        resp = RedirectResponse(url="/admin/dashboard", status_code=303)
        resp.set_cookie(key="admin_session", value=token, httponly=True, max_age=86400)
        return resp
    return render("login.html", error="Invalid credentials")

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
        saas_count = conn.execute("SELECT COUNT(*) FROM users WHERE role='saas'").fetchone()[0]
        blogger_count = conn.execute("SELECT COUNT(*) FROM users WHERE role='blogger'").fetchone()[0]
        total_posts = conn.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()[0]
        total_tx = conn.execute("SELECT COUNT(*) FROM admitad_transactions").fetchone()[0]
        total_balance = conn.execute("SELECT SUM(balance_available) FROM users").fetchone()[0] or 0
    finally:
        conn.close()
    return render("admin_dashboard.html", saas=saas_count, bloggers=blogger_count,
                  posts=total_posts, tx=total_tx, balance=total_balance)

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
