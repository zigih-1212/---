# webapp/routes_user.py (исправленный)

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from services.db import get_db
from webapp.auth import get_user_id_from_token
from datetime import datetime, timedelta, timezone, date
from config import BOT_USERNAME

router = APIRouter()

USER_STATS_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Моя статистика</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; }
    h1 { color: #ff4444; }
    .container { max-width: 1100px; margin: auto; }
    .period-selector { margin-bottom: 20px; }
    .period-selector button { background: #333; color: #ccc; border: 1px solid #555; padding: 8px 16px; cursor: pointer; }
    .period-selector button.active { background: #ff4444; color: #fff; border-color: #ff4444; }
    canvas { background: #222; border-radius: 12px; padding: 10px; margin-bottom: 30px; }
    .balance { font-size: 1.2em; margin-bottom: 20px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .card { background: #1e1e1e; border-radius: 12px; padding: 20px; margin-bottom: 30px; }
    table { width: 100%; border-collapse: collapse; margin-top: 15px; }
    th, td { padding: 8px 12px; border-bottom: 1px solid #333; text-align: left; }
    th { background: #2a2a2a; color: #ff4444; }
    tr:hover { background: #2a2a2a; }
    #payout-btn { background: #4caf50; color: white; border: none; padding: 12px 24px; border-radius: 8px; font-size: 1.1em; cursor: pointer; margin-top: 15px; transition: background 0.2s; }
    #payout-btn:hover { background: #388e3c; }
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

    <!-- 💰 Финансы -->
    <div class="card" id="finance-card">
        <h2>💰 Финансы</h2>
        <div class="balance" id="finance-balance">Загрузка...</div>
        <button id="payout-btn" style="display:none;" onclick="requestPayout()">💸 Запросить выплату</button>
        <div id="finance-transactions" style="margin-top:15px;"></div>
    </div>

    <div class="grid">
        <div><canvas id="postsChart"></canvas></div>
        <div><canvas id="revenueChart"></canvas></div>
    </div>
    <div class="grid">
        <div><canvas id="clicksChart"></canvas></div>
        <div style="max-width:400px; margin:auto;"><canvas id="storeChart"></canvas></div>
    </div>

    <div class="card">
        <h2>📢 Сравнение каналов</h2>
        <table id="channels-table">
            <tr><th>Канал</th><th>Постов</th><th>Кликов</th><th>Продаж</th><th>Доход</th><th>Конверсия</th></tr>
        </table>
    </div>
    <div class="card">
        <h2>🏆 Топ-5 товаров</h2>
        <ol id="top-products"></ol>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
(async function() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (!token) { document.body.innerHTML = 'Токен не указан'; return; }

    let currentPeriod = '30d';
    let postsChart, revenueChart, clicksChart, storeChart;
    let botUsername = '';

    async function loadData(period) {
        const resp = await fetch(`/my-stats/data?token=${token}&period=${period}`);
        const data = await resp.json();

        // Сохраняем bot_username для кнопки выплаты
        botUsername = data.bot_username || '';

        // Финансы
        document.getElementById('finance-balance').innerHTML = `
            <p>💳 Доступно к выводу: <b>${data.balance_available.toFixed(2)} ₽</b></p>
            <p>⏳ В ожидании: <b>${data.balance_pending.toFixed(2)} ₽</b></p>
            <p>📬 Постов за период: <b>${data.total_posts}</b> | 💵 Доход: <b>${data.total_revenue.toFixed(2)} ₽</b></p>
        `;

        // Кнопка выплаты
        const payoutBtn = document.getElementById('payout-btn');
        if (data.balance_available >= 3000) {
            payoutBtn.style.display = 'inline-block';
        } else {
            payoutBtn.style.display = 'none';
        }

        // Таблица транзакций
        const txDiv = document.getElementById('finance-transactions');
        if (data.recent_transactions && data.recent_transactions.length > 0) {
            let html = '<h3>Последние транзакции</h3><table><tr><th>Сумма</th><th>Статус</th><th>Заказ</th><th>Дата</th></tr>';
            data.recent_transactions.forEach(t => {
                const statusEmoji = {pending: '⏳', approved: '✅', declined: '❌', new: '🆕', waiting: '⏳', paid: '💳'}[t.status] || '❓';
                html += `<tr><td>${t.amount} ${t.currency}</td><td>${statusEmoji} ${t.status}</td><td>${t.order_id || '—'}</td><td>${t.date}</td></tr>`;
            });
            html += '</table>';
            txDiv.innerHTML = html;
        } else {
            txDiv.innerHTML = '<p>Нет транзакций</p>';
        }

        // Посты
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
            options: {
                plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.raw} пост(ов)` } } },
                scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } }
            }
        });

        // Доход
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
                options: {
                    plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.raw} ₽` } } },
                    scales: { y: { beginAtZero: true } }
                }
            });
        } else {
            document.getElementById('revenueChart').getContext('2d').clearRect(0,0,400,200);
            revenueChart = null;
        }

        // Клики + Конверсия
        if (clicksChart) clicksChart.destroy();
        if (data.clicks_labels && data.clicks_labels.length > 0) {
            clicksChart = new Chart(document.getElementById('clicksChart'), {
                type: 'bar',
                data: {
                    labels: data.clicks_labels,
                    datasets: [
                        {
                            label: 'Клики',
                            data: data.clicks_counts,
                            backgroundColor: 'rgba(33,150,243,0.6)',
                            yAxisID: 'y-clicks'
                        },
                        {
                            label: 'Конверсия, %',
                            data: data.conversion_values,
                            type: 'line',
                            borderColor: '#ff9800',
                            backgroundColor: 'rgba(255,152,0,0.1)',
                            yAxisID: 'y-conv',
                            fill: false,
                        }
                    ]
                },
                options: {
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: function(ctx) {
                                    if (ctx.dataset.label === 'Клики') return `${ctx.raw} кликов`;
                                    return `${ctx.raw} %`;
                                }
                            }
                        }
                    },
                    scales: {
                        'y-clicks': {
                            type: 'linear',
                            position: 'left',
                            beginAtZero: true,
                            title: { display: true, text: 'Клики' }
                        },
                        'y-conv': {
                            type: 'linear',
                            position: 'right',
                            beginAtZero: true,
                            max: 100,
                            title: { display: true, text: 'Конверсия, %' },
                            grid: { drawOnChartArea: false }
                        }
                    }
                }
            });
        }

        // Магазины
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
                },
                options: {
                    plugins: { tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${ctx.raw} пост(ов)` } } }
                }
            });
        }

        // Таблица каналов
        const table = document.getElementById('channels-table');
        table.innerHTML = '<tr><th>Канал</th><th>Постов</th><th>Кликов</th><th>Продаж</th><th>Доход</th><th>Конверсия</th></tr>';
        if (data.channels && data.channels.length > 0) {
            data.channels.forEach(ch => {
                const row = table.insertRow();
                row.innerHTML = `
                    <td>${ch.title}</td>
                    <td>${ch.posts}</td>
                    <td>${ch.clicks}</td>
                    <td>${ch.leads}</td>
                    <td>${ch.earnings.toFixed(2)} ₽</td>
                    <td>${ch.conversion}%</td>
                `;
            });
        } else {
            table.insertRow().innerHTML = '<td colspan="6">Нет данных</td>';
        }

        // Топ товаров
        const topList = document.getElementById('top-products');
        topList.innerHTML = '';
        if (data.top_products && data.top_products.length > 0) {
            data.top_products.forEach(p => {
                const li = document.createElement('li');
                li.textContent = `${p.title} (${p.count} раз)`;
                topList.appendChild(li);
            });
        } else {
            topList.innerHTML = '<li>Нет данных</li>';
        }
    }

    // Функция запроса выплаты (открывает чат с ботом)
    window.requestPayout = function() {
        if (botUsername) {
            // Прямая ссылка на бота с командой /start payout
            window.location.href = `https://t.me/${botUsername}?start=payout`;
        } else {
            alert('Имя бота не загружено. Обновите страницу.');
        }
    };

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

    if period == "7d":
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    elif period == "30d":
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    else:
        since = "2020-01-01T00:00:00"

    conn = get_db()
    try:
        # Посты
        post_rows = conn.execute("""
            SELECT DATE(published_at) as day, COUNT(*) as count
            FROM posts
            WHERE user_id=? AND status='published' AND published_at >= ?
            GROUP BY day ORDER BY day
        """, (user_id, since)).fetchall()

        # Доход (approved)
        revenue_rows = conn.execute("""
            SELECT DATE(time, 'unixepoch') as day, SUM(payment_sum) as total
            FROM admitad_transactions
            WHERE user_id=? AND time >= strftime('%s', ?) AND payment_status = 'approved'
            GROUP BY day ORDER BY day
        """, (user_id, since)).fetchall()

        # Клики (по дням, из транзакций с action='click')
        clicks_rows = conn.execute("""
            SELECT DATE(time, 'unixepoch') as day, COUNT(*) as clicks
            FROM admitad_transactions
            WHERE user_id=? AND time >= strftime('%s', ?) AND action='click'
            GROUP BY day ORDER BY day
        """, (user_id, since)).fetchall()

        # Лиды (pending/approved) по дням
        leads_rows = conn.execute("""
            SELECT DATE(time, 'unixepoch') as day, COUNT(*) as leads
            FROM admitad_transactions
            WHERE user_id=? AND time >= strftime('%s', ?) AND action='lead'
            GROUP BY day ORDER BY day
        """, (user_id, since)).fetchall()

        # Магазины (из постов)
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

        # Собираем словари по дням для кликов и лидов
        clicks_dict = {r["day"]: r["clicks"] for r in clicks_rows}
        leads_dict = {r["day"]: r["leads"] for r in leads_rows}

        # Определяем все дни в периоде для корректных нулей
        start_date = date.today() - timedelta(days={"7d":7, "30d":30}.get(period, 1000))
        end_date = date.today()
        all_days = [(start_date + timedelta(days=i)).isoformat() for i in range((end_date - start_date).days + 1)]

        clicks_counts = [clicks_dict.get(day, 0) for day in all_days]
        leads_counts = [leads_dict.get(day, 0) for day in all_days]

        # Конверсия (leads/clicks * 100) по дням, если кликов 0, то 0
        conversion_values = []
        for c, l in zip(clicks_counts, leads_counts):
            conversion_values.append(round(l / c * 100, 1) if c > 0 else 0.0)

        # Сравнение каналов
        channel_rows = conn.execute("""
            SELECT c.channel_title, c.channel_id,
                   COUNT(p.id) as posts_cnt,
                   COALESCE(s.clicks_count, 0) as clicks,
                   COALESCE(s.leads_count, 0) as leads,
                   COALESCE(s.earnings_approved, 0) as earnings
            FROM channels c
            LEFT JOIN posts p ON p.channel_id = c.channel_id AND p.user_id = c.user_id AND p.status='published' AND p.published_at >= ?
            LEFT JOIN subid_stats s ON s.subid1 = c.sub_id
            WHERE c.user_id = ? AND c.is_active = 1
            GROUP BY c.channel_id
            ORDER BY earnings DESC
        """, (since, user_id)).fetchall()

        # Топ-5 товаров
        top_products = conn.execute("""
            SELECT g.title, COUNT(*) as cnt
            FROM posts p
            JOIN gdeslon_catalog g ON p.donor_post_id LIKE 'admitad_' || g.id || '_%'
            WHERE p.user_id = ? AND p.status='published' AND p.published_at >= ?
            GROUP BY g.title
            ORDER BY cnt DESC
            LIMIT 5
        """, (user_id, since)).fetchall()

        # Последние 10 транзакций
        transactions = conn.execute("""
            SELECT payment_sum, currency, payment_status, order_id, action, time
            FROM admitad_transactions
            WHERE user_id = ?
            ORDER BY time DESC
            LIMIT 10
        """, (user_id,)).fetchall()

        return JSONResponse({
            "posts_labels": [r["day"] for r in post_rows],
            "posts_counts": [r["count"] for r in post_rows],
            "revenue_labels": [r["day"] for r in revenue_rows],
            "revenue_values": [r["total"] for r in revenue_rows],
            "clicks_labels": all_days,
            "clicks_counts": clicks_counts,
            "conversion_labels": all_days,
            "conversion_values": conversion_values,
            "store_labels": [r["source"] or "Без названия" for r in store_rows],
            "store_values": [r["cnt"] for r in store_rows],
            "balance_available": balance["balance_available"] if balance else 0,
            "balance_pending": balance["balance_pending"] if balance else 0,
            "total_posts": total_posts,
            "total_revenue": total_revenue,
            "channels": [{
                "title": r["channel_title"] or r["channel_id"],
                "posts": r["posts_cnt"],
                "clicks": r["clicks"],
                "leads": r["leads"],
                "earnings": r["earnings"],
                "conversion": round(r["leads"] / r["clicks"] * 100, 1) if r["clicks"] > 0 else 0
            } for r in channel_rows],
            "top_products": [{"title": r["title"], "count": r["cnt"]} for r in top_products],
            "recent_transactions": [
                {
                    "amount": t["payment_sum"],
                    "currency": t["currency"],
                    "status": t["payment_status"],
                    "order_id": t["order_id"],
                    "action": t["action"],
                    "date": datetime.fromtimestamp(int(t["time"]), tz=timezone.utc).strftime("%d.%m.%Y %H:%M") if t["time"] else ""
                } for t in transactions
            ] if transactions else [],
            "bot_username": BOT_USERNAME
        })
    finally:
        conn.close()
