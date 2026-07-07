# webapp/routes_user.py
import os
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from services.db import get_db
from webapp.auth import get_user_id_from_token
from datetime import datetime, timedelta, timezone
from jinja2 import Environment, FileSystemLoader

router = APIRouter()
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates')
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

@router.get("/", response_class=HTMLResponse)
async def user_stats_page(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    return HTMLResponse(env.get_template("user_stats.html").render(token=token))

@router.get("/data")
async def user_stats_data(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        # Пример: количество постов по дням за последние 30 дней
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        rows = conn.execute("""
            SELECT DATE(published_at) as day, COUNT(*) as count
            FROM posts
            WHERE user_id=? AND status='published' AND published_at >= ?
            GROUP BY day
            ORDER BY day
        """, (user_id, since)).fetchall()
        labels = [r["day"] for r in rows]
        counts = [r["count"] for r in rows]

        # Баланс
        balance = conn.execute("SELECT balance_available, balance_pending FROM users WHERE user_id=?",
                               (user_id,)).fetchone()
        return JSONResponse({
            "labels": labels,
            "counts": counts,
            "balance_available": balance["balance_available"] if balance else 0,
            "balance_pending": balance["balance_pending"] if balance else 0,
        })
    finally:
        conn.close()
