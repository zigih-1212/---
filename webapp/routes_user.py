# webapp/routes_user.py (полная замена содержимого)

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
    .container { max-width: 1000px; margin: auto; }
    .period-selector { margin-bottom: 20px; }
    .period-selector button { background: #333; color: #ccc; border: 1px solid #555; padding: 8px 16px; cursor: pointer; }
    .period-selector button.active { background: #ff4444; color: #fff; border-color: #ff4444; }
    canvas { background: #222; border-radius: 12px; padding: 10px; margin-bottom: 30px; }
    .balance { font-size: 1.2em; margin-bottom: 20px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="container">
    <h1>📊 Статистика</h1>
    <div class="period-selector">
        <button id="btn7d">7 дней</button>
        <button id="btn30d" class="active">30 дней</button>
        <button id="btnAll">Всё время</button>
    </div>
    <div class="balance" id="balance-info">Загрузка...</div>
    <div class="grid">
        <div><canvas id="postsChart"></canvas></div>
        <div><canvas id="revenueChart"></canvas></div>
    </div>
    <div style="max-width:400px; margin:auto;"><canvas id="storeChart"></canvas></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
(async function() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (!token) { document.body.innerHTML = 'Токен не указан'; return; }

    let currentPeriod = '30d';
    let postsChart, revenueChart, storeChart;

    async function loadData(period) {
        const resp = await fetch(`/my-stats/data?token=${token}&period=${period}`);
        const data = await resp.json();

        document.getElementById('balance-info').innerHTML = `
            <p>💰 Доступно к выводу: <b>${data.balance_available.toFixed(2)} ₽</b></p>
            <p>⏳ В ожидании: <b>${data.balance_pending.toFixed(2)} ₽</b></p>
            <p>📬 Постов за период: <b>${data.total_posts}</b> | 💵 Доход: <b>${data.total_revenue.toFixed(2)} ₽</b></p>
        `;

        if (postsChart) postsChart.destroy();
        postsChart = new Chart(document.getElementById('postsChart'), {
            type: 'line',
            data: {
                labels: data.posts_labels,
                datasets: [{
                    label: 'Постов за день',
                    data: data.posts_counts,
                    borderColor: '#ff4444',
                    backgroundColor: 'rgba(255,68,68,0.1)',
                    fill: true,
                }]
            },
            options: { scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } } }
        });

        if (revenueChart) revenueChart.destroy();
        if (data.revenue_values && data.revenue_values.length > 0) {
            revenueChart = new Chart(document.getElementById('revenueChart'), {
                type: 'line',
                data: {
                    labels: data.revenue_labels,
                    datasets: [{
                        label: 'Доход (₽)',
                        data: data.revenue_values,
                        borderColor: '#4caf50',
                        backgroundColor: 'rgba(76,175,80,0.1)',
                        fill: true,
                    }]
                },
                options: { scales: { y: { beginAtZero: true } } }
            });
        } else {
            document.getElementById('revenueChart').getContext('2d').clearRect(0,0,400,200);
            revenueChart = null;
        }

        if (storeChart) storeChart.destroy();
        if (data.store_labels && data.store_labels.length > 0) {
            storeChart = new Chart(document.getElementById('storeChart'), {
                type: 'doughnut',
                data: {
                    labels: data.store_labels,
                    datasets: [{
                        label: 'Постов',
                        data: data.store_values,
                        backgroundColor: ['#ff4444','#4caf50','#ff9800','#2196f3','#9c27b0','#00bcd4','#ffeb3b','#e91e63','#8bc34a','#607d8b'],
                    }]
                }
            });
        }
    }

    document.getElementById('btn7d').addEventListener('click', () => {
        document.querySelectorAll('.period-selector button').forEach(b => b.classList.remove('active'));
        document.getElementById('btn7d').classList.add('active');
        loadData('7d');
    });
    document.getElementById('btn30d').addEventListener('click', () => {
        document.querySelectorAll('.period-selector button').forEach(b => b.classList.remove('active'));
        document.getElementById('btn30d').classList.add('active');
        loadData('30d');
    });
    document.getElementById('btnAll').addEventListener('click', () => {
        document.querySelectorAll('.period-selector button').forEach(b => b.classList.remove('active'));
        document.getElementById('btnAll').classList.add('active');
        loadData('all');
    });

    loadData('30d');
})();
</script>
</body>
</html>'''

@router.get("/", response_class=HTMLResponse)
async def user_stats_page(token: str = Query(...)):
    get_user_id_from_token(token)
    return HTMLResponse(content=USER_STATS_TEMPLATE)

@router.get("/data")
async def user_stats_data(token: str = Query(...), period: str = Query("30d")):
    user_id = get_user_id_from_token(token)

    # Определяем смещение даты
    if period == "7d":
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    elif period == "30d":
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    else:  # all – используем начало 2020 года как достаточно давнюю дату
        since = "2020-01-01T00:00:00"

    conn = get_db()
    try:
        # Посты по дням
        post_rows = conn.execute("""
            SELECT DATE(published_at) as day, COUNT(*) as count
            FROM posts
            WHERE user_id=? AND status='published' AND published_at >= ?
            GROUP BY day ORDER BY day
        """, (user_id, since)).fetchall()

        # Доход по дням (сумма approved)
        revenue_rows = conn.execute("""
            SELECT DATE(time, 'unixepoch') as day, SUM(payment_sum) as total
            FROM admitad_transactions
            WHERE user_id=? AND time >= strftime('%s', ?) AND payment_status = 'approved'
            GROUP BY day ORDER BY day
        """, (user_id, since)).fetchall()

        # Магазины (по постам)
        store_rows = conn.execute("""
            SELECT g.source, COUNT(*) as cnt
            FROM posts p
            JOIN gdeslon_catalog g ON p.donor_post_id LIKE 'admitad_' || g.id || '_%'
            WHERE p.user_id=? AND p.status='published' AND p.published_at >= ?
            GROUP BY g.source ORDER BY cnt DESC
        """, (user_id, since)).fetchall()

        # Баланс
        balance = conn.execute("SELECT balance_available, balance_pending FROM users WHERE user_id=?",
                               (user_id,)).fetchone()

        total_posts = sum(r["count"] for r in post_rows) if post_rows else 0
        total_revenue = sum(r["total"] for r in revenue_rows) if revenue_rows else 0.0

        return JSONResponse({
            "posts_labels": [r["day"] for r in post_rows],
            "posts_counts": [r["count"] for r in post_rows],
            "revenue_labels": [r["day"] for r in revenue_rows],
            "revenue_values": [r["total"] for r in revenue_rows],
            "store_labels": [r["source"] or "Без названия" for r in store_rows],
            "store_values": [r["cnt"] for r in store_rows],
            "balance_available": balance["balance_available"] if balance else 0,
            "balance_pending": balance["balance_pending"] if balance else 0,
            "total_posts": total_posts,
            "total_revenue": total_revenue,
        })
    finally:
        conn.close()
