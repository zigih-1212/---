# webapp/routes_user.py — полная версия с чатом выплат

import os
import uuid
from fastapi import APIRouter, Request, Query, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from services.db import get_db
from webapp.auth import get_user_id_from_token
from datetime import datetime, timedelta, timezone, date
from config import BOT_USERNAME, MIN_PAYOUT, ADMIN_IDS, WEBAPP_ADMIN_URL
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

router = APIRouter()

UPLOAD_DIR = "/app/data/receipts"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------- Шаблон основной страницы статистики ----------
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
    button, .btn { background: #ff4444; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 1em; margin-top: 10px; text-decoration: none; display: inline-block; }
    button:hover { opacity: 0.9; }
    .payout-form textarea { width: 100%; padding: 12px; margin: 10px 0; background: #333; border: 1px solid #555; color: #ccc; border-radius: 8px; }
    #payout-msg { margin-top: 10px; }
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

    <div class="card">
        <h2>💰 Финансы</h2>
        <div class="balance" id="finance-balance">Загрузка...</div>
        <div id="payout-actions">
            <div id="payout-request-form" style="display:none;">
                <h3>💸 Запросить выплату</h3>
                <textarea id="payout-details" rows="3" placeholder="Введите реквизиты: номер карты, банк и т.д."></textarea>
                <button onclick="submitPayoutRequest()">📤 Отправить запрос</button>
                <div id="payout-msg"></div>
            </div>
            <div id="active-payout-link" style="display:none;">
                <a id="chat-link" href="#" class="btn">💬 Перейти в чат с администратором</a>
            </div>
        </div>
        <div id="finance-transactions" style="margin-top:20px;"></div>
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

    async function loadData(period) {
        const resp = await fetch(`/my-stats/data?token=${token}&period=${period}`);
        const data = await resp.json();

        document.getElementById('finance-balance').innerHTML = `
            <p>💳 Доступно к выводу: <b>${data.balance_available.toFixed(2)} ₽</b></p>
            <p>⏳ В ожидании: <b>${data.balance_pending.toFixed(2)} ₽</b></p>
            <p>📬 Постов за период: <b>${data.total_posts}</b> | 💵 Доход: <b>${data.total_revenue.toFixed(2)} ₽</b></p>
        `;

        // Проверяем активную заявку
        const statusResp = await fetch(`/my-stats/payout-status?token=${token}`);
        const statusData = await statusResp.json();
        const reqForm = document.getElementById('payout-request-form');
        const activeLink = document.getElementById('active-payout-link');
        const chatLink = document.getElementById('chat-link');

        if (statusData.has_active) {
            reqForm.style.display = 'none';
            activeLink.style.display = 'block';
            chatLink.href = `/my-stats/chat/${statusData.request_id}?token=${token}`;
        } else {
            activeLink.style.display = 'none';
            if (data.balance_available >= 3000) {
                reqForm.style.display = 'block';
            } else {
                reqForm.style.display = 'none';
            }
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

    window.submitPayoutRequest = async function() {
        const details = document.getElementById('payout-details').value.trim();
        if (details.length < 10) {
            document.getElementById('payout-msg').innerHTML = '❌ Слишком короткие реквизиты. Минимум 10 символов.';
            return;
        }
        document.getElementById('payout-msg').innerHTML = '⏳ Отправка...';
        const formData = new FormData();
        formData.append('token', token);
        formData.append('details', details);
        const resp = await fetch('/my-stats/request-payout', { method: 'POST', body: formData });
        const result = await resp.json();
        if (result.ok) {
            window.location.href = `/my-stats/chat/${result.request_id}?token=${token}`;
        } else {
            document.getElementById('payout-msg').innerHTML = '❌ ' + result.error;
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

# ---------- Шаблон чата выплат (для пользователя) ----------
CHAT_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Чат выплаты</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; }
    h1 { color: #ff4444; }
    .container { max-width: 700px; margin: auto; }
    .status-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-weight: bold; margin-left: 10px; }
    .status-processing { background: #ff9800; color: #000; }
    .status-awaiting_receipt { background: #2196f3; color: #fff; }
    .status-receipt_uploaded { background: #4caf50; color: #fff; }
    .status-completed { background: #888; color: #fff; }
    .status-declined { background: #f44336; color: #fff; }
    .chat-box { background: #111; border-radius: 10px; padding: 15px; height: 400px; overflow-y: auto; margin: 15px 0; }
    .chat-msg { margin-bottom: 12px; padding: 8px 12px; border-radius: 8px; }
    .chat-msg.admin { background: #2a1a1a; text-align: right; }
    .chat-msg.user { background: #1a2a1a; text-align: left; }
    .chat-msg .time { font-size: 0.75em; color: #888; display: block; margin-top: 4px; }
    .chat-input { display: flex; gap: 10px; margin-top: 10px; }
    .chat-input input { flex: 1; padding: 12px; background: #333; border: 1px solid #555; color: #ccc; border-radius: 8px; }
    .chat-input button, .file-upload button { background: #ff4444; color: white; border: none; padding: 12px 20px; border-radius: 8px; cursor: pointer; }
    .file-upload { margin-top: 15px; display: flex; align-items: center; gap: 10px; }
    .file-upload input[type="file"] { display: none; }
    .file-upload label { background: #333; border: 2px dashed #555; padding: 12px 20px; border-radius: 8px; cursor: pointer; }
    .file-upload label:hover { border-color: #ff4444; }
    .preview-img { max-width: 100px; max-height: 100px; margin-left: 10px; }
    .back-link { margin-bottom: 20px; display: inline-block; color: #ff4444; }
</style>
</head>
<body>
<div class="container">
    <a href="/my-stats?token={{ token }}" class="back-link">← Назад к статистике</a>
    <h1>💬 Чат по заявке #{{ request_id }} <span class="status-badge" id="status-badge">{{ status }}</span></h1>
    <div class="chat-box" id="chat-messages">Загрузка...</div>
    <div class="chat-input">
        <input type="text" id="message-text" placeholder="Введите сообщение...">
        <button onclick="sendMessage()">📨</button>
    </div>
    <div id="receipt-upload-section" class="file-upload" style="display: {{ 'block' if status == 'awaiting_receipt' else 'none' }};">
        <input type="file" id="receipt-file" accept="image/*" onchange="previewFile()">
        <label for="receipt-file">📎 Выберите чек</label>
        <button onclick="uploadReceipt()">📤 Отправить</button>
        <img id="preview" class="preview-img" style="display:none;">
    </div>
</div>

<script>
const requestId = {{ request_id }};
const token = "{{ token }}";

async function loadMessages() {
    const resp = await fetch(`/my-stats/payout-chat/${requestId}?token=${token}`);
    const messages = await resp.json();
    const chatDiv = document.getElementById('chat-messages');
    chatDiv.innerHTML = messages.map(msg => {
        const side = msg.sender_role === 'admin' ? 'admin' : 'user';
        let text = '';
        if (msg.file_path) {
            text = `<a href="/my-stats/receipt-file?path=${encodeURIComponent(msg.file_path)}&token=${token}" target="_blank"><img src="/my-stats/receipt-file?path=${encodeURIComponent(msg.file_path)}&token=${token}" style="max-width:150px; border-radius:8px;"></a>`;
        }
        if (msg.message) text += msg.message;
        return `<div class="chat-msg ${side}">${text}<span class="time">${msg.created_at}</span></div>`;
    }).join('');
    chatDiv.scrollTop = chatDiv.scrollHeight;
}

async function sendMessage() {
    const text = document.getElementById('message-text').value.trim();
    if (!text) return;
    const formData = new FormData();
    formData.append('token', token);
    formData.append('request_id', requestId);
    formData.append('message', text);
    await fetch('/my-stats/send-message', { method: 'POST', body: formData });
    document.getElementById('message-text').value = '';
    loadMessages();
}

function previewFile() {
    const file = document.getElementById('receipt-file').files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            document.getElementById('preview').src = e.target.result;
            document.getElementById('preview').style.display = 'block';
        };
        reader.readAsDataURL(file);
    }
}

async function uploadReceipt() {
    const fileInput = document.getElementById('receipt-file');
    if (!fileInput.files.length) return;
    const formData = new FormData();
    formData.append('token', token);
    formData.append('request_id', requestId);
    formData.append('file', fileInput.files[0]);
    const resp = await fetch('/my-stats/upload-receipt', { method: 'POST', body: formData });
    const result = await resp.json();
    if (result.ok) {
        loadMessages();
        document.getElementById('receipt-file').value = '';
        document.getElementById('preview').style.display = 'none';
        document.getElementById('status-badge').textContent = 'receipt_uploaded';
        document.getElementById('status-badge').className = 'status-badge status-receipt_uploaded';
        document.getElementById('receipt-upload-section').style.display = 'none';
    } else {
        alert(result.error || 'Ошибка загрузки');
    }
}

setInterval(loadMessages, 10000);
loadMessages();
</script>
</body>
</html>'''

# ---------- Эндпоинты ----------
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
        post_rows = conn.execute("""
            SELECT DATE(published_at) as day, COUNT(*) as count
            FROM posts
            WHERE user_id=? AND status='published' AND published_at >= ?
            GROUP BY day ORDER BY day
        """, (user_id, since)).fetchall()

        revenue_rows = conn.execute("""
            SELECT DATE(time, 'unixepoch') as day, SUM(payment_sum) as total
            FROM admitad_transactions
            WHERE user_id=? AND time >= strftime('%s', ?) AND payment_status = 'approved'
            GROUP BY day ORDER BY day
        """, (user_id, since)).fetchall()

        clicks_rows = conn.execute("""
            SELECT DATE(time, 'unixepoch') as day, COUNT(*) as clicks
            FROM admitad_transactions
            WHERE user_id=? AND time >= strftime('%s', ?) AND action='click'
            GROUP BY day ORDER BY day
        """, (user_id, since)).fetchall()

        leads_rows = conn.execute("""
            SELECT DATE(time, 'unixepoch') as day, COUNT(*) as leads
            FROM admitad_transactions
            WHERE user_id=? AND time >= strftime('%s', ?) AND action='lead'
            GROUP BY day ORDER BY day
        """, (user_id, since)).fetchall()

        store_rows = conn.execute("""
            SELECT g.source, COUNT(*) as cnt
            FROM posts p
            JOIN gdeslon_catalog g ON p.donor_post_id LIKE 'admitad_' || g.id || '_%'
            WHERE p.user_id=? AND p.status='published' AND p.published_at >= ?
            GROUP BY g.source ORDER BY cnt DESC
        """, (user_id, since)).fetchall()

        balance = conn.execute("SELECT balance_available, balance_pending FROM users WHERE user_id=?",
                               (user_id,)).fetchone()

        total_posts = sum(r["count"] for r in post_rows) if post_rows else 0
        total_revenue = sum(r["total"] for r in revenue_rows) if revenue_rows else 0.0

        clicks_dict = {r["day"]: r["clicks"] for r in clicks_rows}
        leads_dict = {r["day"]: r["leads"] for r in leads_rows}

        start_date = date.today() - timedelta(days={"7d":7, "30d":30}.get(period, 1000))
        end_date = date.today()
        all_days = [(start_date + timedelta(days=i)).isoformat() for i in range((end_date - start_date).days + 1)]

        clicks_counts = [clicks_dict.get(day, 0) for day in all_days]
        leads_counts = [leads_dict.get(day, 0) for day in all_days]

        conversion_values = []
        for c, l in zip(clicks_counts, leads_counts):
            conversion_values.append(round(l / c * 100, 1) if c > 0 else 0.0)

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

        top_products = conn.execute("""
            SELECT g.title, COUNT(*) as cnt
            FROM posts p
            JOIN gdeslon_catalog g ON p.donor_post_id LIKE 'admitad_' || g.id || '_%'
            WHERE p.user_id = ? AND p.status='published' AND p.published_at >= ?
            GROUP BY g.title
            ORDER BY cnt DESC
            LIMIT 5
        """, (user_id, since)).fetchall()

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


@router.get("/chat/{request_id}", response_class=HTMLResponse)
async def user_chat_page(request_id: int, token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        req = conn.execute("SELECT id, status FROM payout_requests WHERE id=? AND user_id=?", 
                           (request_id, user_id)).fetchone()
        if not req:
            return HTMLResponse("Заявка не найдена", status_code=404)
        # Рендерим шаблон чата
        return HTMLResponse(content=CHAT_TEMPLATE.replace("{{ request_id }}", str(request_id))
                                              .replace("{{ status }}", req["status"])
                                              .replace("{{ token }}", token))
    finally:
        conn.close()


@router.post("/request-payout")
async def request_payout(request: Request, token: str = Form(...), details: str = Form(...)):
    user_id = get_user_id_from_token(token)
    if len(details.strip()) < 10:
        return JSONResponse({"ok": False, "error": "Слишком короткие реквизиты"})
    
    conn = get_db()
    try:
        user = conn.execute("SELECT role, balance_available, tax_status, oferta_accepted FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user or user["oferta_accepted"] != 1:
            return JSONResponse({"ok": False, "error": "Оферта не принята"})
        if user["tax_status"] != "business":
            return JSONResponse({"ok": False, "error": "Требуется статус самозанятого/ИП"})
        
        available = user["balance_available"] or 0.0
        if available < MIN_PAYOUT:
            return JSONResponse({"ok": False, "error": f"Минимальная сумма вывода: {MIN_PAYOUT} ₽"})
        
        active = conn.execute("SELECT id FROM payout_requests WHERE user_id=? AND status IN ('processing','awaiting_receipt','receipt_uploaded')", (user_id,)).fetchone()
        if active:
            return JSONResponse({"ok": False, "error": "У вас уже есть активная заявка"})
        
        conn.execute("UPDATE users SET balance_available = balance_available - ? WHERE user_id=?", (available, user_id))
        cursor = conn.execute(
            "INSERT INTO payout_requests (user_id, amount, message, status) VALUES (?, ?, ?, 'processing')",
            (user_id, available, details.strip())
        )
        request_id = cursor.lastrowid
        conn.execute("INSERT INTO payout_chat (request_id, sender_role, message) VALUES (?, 'user', ?)",
                     (request_id, f"Реквизиты: {details.strip()}"))
        conn.commit()
        
        # Уведомление админам
        bot = request.app.state.bot
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id,
                    f"🔔 Новый запрос на выплату #{request_id}\nПользователь: {user_id}\nСумма: {available:.2f} ₽",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🌐 Админка", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))]
                    ])
                )
            except: pass
        return JSONResponse({"ok": True, "request_id": request_id})
    finally:
        conn.close()


@router.get("/payout-status")
async def payout_status(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        active = conn.execute(
            "SELECT id, status FROM payout_requests WHERE user_id=? AND status IN ('processing','awaiting_receipt','receipt_uploaded') ORDER BY id DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        if active:
            return JSONResponse({"has_active": True, "request_id": active["id"], "status": active["status"]})
        return JSONResponse({"has_active": False})
    finally:
        conn.close()


@router.get("/payout-chat/{request_id}")
async def get_payout_chat(request_id: int, token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        req = conn.execute("SELECT user_id FROM payout_requests WHERE id=?", (request_id,)).fetchone()
        if not req or req["user_id"] != user_id:
            return JSONResponse([])
        messages = conn.execute("""
            SELECT sender_role, message, file_path, created_at
            FROM payout_chat
            WHERE request_id = ?
            ORDER BY created_at ASC
        """, (request_id,)).fetchall()
        return JSONResponse([{
            "sender_role": m["sender_role"],
            "message": m["message"],
            "file_path": m["file_path"],
            "created_at": m["created_at"]
        } for m in messages])
    finally:
        conn.close()


@router.post("/send-message")
async def send_chat_message(token: str = Form(...), request_id: int = Form(...), message: str = Form(...)):
    user_id = get_user_id_from_token(token)
    if not message.strip():
        return JSONResponse({"ok": False})
    conn = get_db()
    try:
        req = conn.execute("SELECT user_id, status FROM payout_requests WHERE id=?", (request_id,)).fetchone()
        if not req or req["user_id"] != user_id or req["status"] in ('completed', 'declined'):
            return JSONResponse({"ok": False})
        conn.execute("INSERT INTO payout_chat (request_id, sender_role, message) VALUES (?, 'user', ?)",
                     (request_id, message.strip()))
        conn.commit()
        return JSONResponse({"ok": True})
    finally:
        conn.close()


@router.post("/upload-receipt")
async def upload_receipt(token: str = Form(...), request_id: int = Form(...), file: UploadFile = File(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        req = conn.execute("SELECT user_id, status FROM payout_requests WHERE id=?", (request_id,)).fetchone()
        if not req or req["user_id"] != user_id or req["status"] != "awaiting_receipt":
            return JSONResponse({"ok": False, "error": "Нельзя загрузить чек"})
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
            return JSONResponse({"ok": False, "error": "Формат не поддерживается"})
        filename = f"{uuid.uuid4()}{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(await file.read())
        conn.execute("INSERT INTO payout_chat (request_id, sender_role, file_path) VALUES (?, 'user', ?)",
                     (request_id, filename))
        conn.execute("UPDATE payout_requests SET status='receipt_uploaded', receipt_photo=? WHERE id=?", 
                     (filename, request_id))
        conn.commit()
        return JSONResponse({"ok": True})
    finally:
        conn.close()


@router.get("/receipt-file")
async def get_receipt_file(path: str = Query(...), token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    full_path = os.path.join(UPLOAD_DIR, path)
    if not os.path.exists(full_path):
        return HTMLResponse("Файл не найден", status_code=404)
    return FileResponse(full_path)
