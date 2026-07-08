# webapp/routes_user.py
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from services.db import get_db
from webapp.auth import get_user_id_from_token
from datetime import datetime, timedelta, timezone

router = APIRouter()

USER_STATS_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Моя статистика</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; }
    h1 { color: #ff4444; }
    .container { max-width: 800px; margin: auto; }
    canvas { background: #222; border-radius: 12px; padding: 10px; }
    .balance { margin-top: 20px; font-size: 1.2em; }
</style>
</head>
<body>
<div class="container">
    <h1>📊 Статистика</h1>
    <canvas id="postsChart" width="400" height="200"></canvas>
    <div class="balance" id="balance-info">Загрузка...</div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
(async function() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (!token) { document.body.innerHTML = 'Токен не указан'; return; }

    try {
        const resp = await fetch(`/my-stats/data?token=${token}`);
        const data = await resp.json();

        const ctx = document.getElementById('postsChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: [{
                    label: 'Постов за день',
                    data: data.counts,
                    borderColor: '#ff4444',
                    backgroundColor: 'rgba(255,68,68,0.1)',
                    fill: true,
                }]
            },
            options: {
                scales: {
                    y: { beginAtZero: true, ticks: { stepSize: 1 } }
                }
            }
        });

        document.getElementById('balance-info').innerHTML = `
            <p>💰 Доступно к выводу: <b>${data.balance_available.toFixed(2)} ₽</b></p>
            <p>⏳ В ожидании: <b>${data.balance_pending.toFixed(2)} ₽</b></p>
        `;
    } catch (e) {
        document.body.innerHTML = 'Ошибка загрузки данных. Попробуйте обновить страницу или запросить новую ссылку.';
    }
})();
</script>
</body>
</html>'''

@router.get("/", response_class=HTMLResponse)
async def user_stats_page(token: str = Query(...)):
    get_user_id_from_token(token)  # проверим токен
    return HTMLResponse(content=USER_STATS_TEMPLATE)

@router.get("/data")
async def user_stats_data(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
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
