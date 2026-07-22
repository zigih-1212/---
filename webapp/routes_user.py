# webapp/routes_user.py — полная актуальная версия

import os
import uuid
import csv
import io
import logging
import xlsxwriter
from io import BytesIO
from pathlib import Path
from fastapi import APIRouter, Request, Query, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from services.db import get_db
from webapp.auth import get_user_id_from_token
from datetime import datetime, timedelta, timezone, date
from config import BOT_USERNAME, MIN_PAYOUT, ADMIN_IDS, WEBAPP_ADMIN_URL
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from services.text_rewriter import generate_post_text
from services.admitad import get_delivery_for_store, get_random_promocode
from utils.feature_flags import is_feature_available_async, is_feature_enabled
from helpers import collect_views_for_user

router = APIRouter()
logger = logging.getLogger("autopost_bot.user")

UPLOAD_DIR = "/app/data/receipts"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _safe_path(base_dir: str, user_path: str) -> str | None:
    base = Path(base_dir).resolve()
    full = (base / user_path).resolve()
    if not str(full).startswith(str(base)):
        return None
    return str(full)


# ------------------------------------------------------------------------------
# Шаблон главной страницы статистики
# ------------------------------------------------------------------------------
USER_STATS_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Моя статистика</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; }
    h1 { color: #ff4444; }
    .nav { margin-bottom: 20px; display: flex; gap: 10px; overflow-x: auto; -webkit-overflow-scrolling: touch; padding-bottom: 5px; }
    .nav a { color: #ff4444; text-decoration: none; padding: 8px 16px; border-radius: 8px; background: #333; white-space: nowrap; flex-shrink: 0; }
    .nav a.active { background: #ff4444; color: #fff; }
    .container { max-width: 1100px; margin: auto; }
    .period-selector { margin-bottom: 20px; display: flex; gap: 8px; flex-wrap: wrap; }
    .period-selector button { background: #333; color: #ccc; border: 1px solid #555; padding: 8px 16px; cursor: pointer; border-radius: 6px; }
    .period-selector button.active { background: #ff4444; color: #fff; border-color: #ff4444; }
    canvas { background: #222; border-radius: 12px; padding: 10px; margin-bottom: 30px; max-width: 100%; }
    .balance { font-size: 1.2em; margin-bottom: 20px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .card { background: #1e1e1e; border-radius: 12px; padding: 20px; margin-bottom: 30px; }
    table { width: 100%; border-collapse: collapse; margin-top: 15px; overflow-x: auto; display: block; }
    th, td { padding: 8px 12px; border-bottom: 1px solid #333; text-align: left; }
    th { background: #2a2a2a; color: #ff4444; }
    tr:hover { background: #2a2a2a; }
    button, .btn { background: #ff4444; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 1em; margin-top: 10px; text-decoration: none; display: inline-block; }
    button:hover { opacity: 0.9; }
    .payout-form textarea { width: 100%; padding: 12px; margin: 10px 0; background: #333; border: 1px solid #555; color: #ccc; border-radius: 8px; }
    #payout-msg { margin-top: 10px; }

    /* Hamburger sidebar */
    .hamburger { display: none; position: fixed; top: 15px; left: 15px; z-index: 1000; background: #ff4444; color: white; border: none; font-size: 24px; padding: 8px 12px; border-radius: 8px; cursor: pointer; }
    .sidebar { position: fixed; top: 0; left: -280px; width: 260px; height: 100%; background: #222; transition: left 0.3s; z-index: 999; padding: 60px 20px 20px; overflow-y: auto; }
    .sidebar.open { left: 0; }
    .sidebar a { display: block; color: #ccc; padding: 12px 16px; text-decoration: none; border-radius: 8px; margin-bottom: 5px; font-size: 1em; }
    .sidebar a:hover, .sidebar a.active { background: #ff4444; color: #fff; }
    .overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 998; }
    .overlay.open { display: block; }
    @media (max-width: 768px) {
        .hamburger { display: block; }
        .nav { display: none !important; }
        body { padding: 15px; }
        .container { max-width: 100%; }
        .grid { grid-template-columns: 1fr; }
    }
</style>
</head>
<body>
<div class="container">
    <button class="hamburger" onclick="toggleSidebar()">☰</button>
    <div class="overlay" onclick="toggleSidebar()"></div>
    <div class="sidebar">
        <a href="/my-stats?token={{ token }}" class="active">📊 Статистика</a>
        <a href="/my-stats/templates?token={{ token }}">📝 Шаблоны</a>
        <a href="/my-stats/cpc-campaigns?token={{ token }}">👆 CPC кампании</a>
        <a href="/my-stats/settings?token={{ token }}">⚙️ Настройки</a>
        <a href="/my-stats/guide?token={{ token }}">📖 Инструкция</a>
    </div>
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

    <div class="card" id="ord-section">
        <h2>📄 Отчёт для ОРД</h2>
        <p style="margin-bottom:10px;">Скачайте Excel-файл со всеми публикациями и количеством просмотров для подачи в ЕРИР.</p>
        <a id="ord-report-link" href="#" class="btn">📥 Скачать отчёт для ОРД (XLSX)</a>
    </div>

    <div class="grid">
        <div><canvas id="postsChart"></canvas></div>
        <div id="revenue-chart-container"><canvas id="revenueChart"></canvas></div>
    </div>
    <div class="grid">
        <div><canvas id="clicksChart"></canvas></div>
        <div style="max-width:400px; margin:auto;"><canvas id="storeChart"></canvas></div>
    </div>

    <div class="card">
        <h2>📢 Сравнение каналов</h2>
        <div style="display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin-bottom:15px;">
            <label for="channel-select" style="font-weight:bold;">Канал:</label>
            <select id="channel-select">
                <option value="all">Все каналы</option>
            </select>
        </div>
        <table id="channels-table">
            <tr><th>Канал</th><th>Постов</th><th>Кликов</th><th>Продаж</th><th>Доход</th><th>Конверсия</th></tr>
        </table>
    </div>
    <div class="card" id="channel-summary-card" style="display:none;">
        <h2>📈 Метрики выбранного канала</h2>
        <p id="channel-summary">Выберите канал выше, чтобы увидеть подробную статистику.</p>
    </div>

    <div class="card">
        <h2>🏆 Топ-5 товаров по публикациям</h2>
        <ol id="top-products"></ol>
    </div>

</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
    document.querySelector('.overlay').classList.toggle('open');
}
(function() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (!token) { document.body.innerHTML = 'Токен не указан'; return; }

    let currentPeriod = '30d';
    let postsChart, revenueChart, clicksChart, storeChart;

    const channelSelect = document.getElementById('channel-select');

    document.getElementById('ord-report-link').href = `/my-stats/ord-report?token=${token}`;

    function populateChannelOptions(channels) {
        if (!channelSelect || !channels) return;
        if (channelSelect.options.length > 1) return;
        channels.forEach(ch => {
            const opt = document.createElement('option');
            opt.value = ch.channel_id;
            opt.textContent = ch.title;
            channelSelect.appendChild(opt);
        });
    }

    function updateChannelDisplay(channels) {
        const table = document.getElementById('channels-table');
        const summaryCard = document.getElementById('channel-summary-card');
        const summaryText = document.getElementById('channel-summary');
        if (!table) return;
        table.innerHTML = '<tr><th>Канал</th><th>Постов</th><th>Кликов</th><th>Продаж</th><th>Доход</th><th>Конверсия</th></tr>';
        const selected = channelSelect ? channelSelect.value : 'all';
        const filtered = (channels || []).filter(ch => selected === 'all' || ch.channel_id === selected);
        if (filtered.length > 0) {
            filtered.forEach(ch => {
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
        if (selected !== 'all' && filtered.length === 1) {
            if (summaryCard) summaryCard.style.display = 'block';
            if (summaryText) summaryText.innerHTML = `Канал: <b>${filtered[0].title}</b><br>Постов: <b>${filtered[0].posts}</b>, Клики: <b>${filtered[0].clicks}</b>, Продаж: <b>${filtered[0].leads}</b>, Доход: <b>${filtered[0].earnings.toFixed(2)} ₽</b>, Конверсия: <b>${filtered[0].conversion}%</b>`;
        } else if (summaryCard) {
            summaryCard.style.display = 'none';
            if (summaryText) summaryText.innerHTML = 'Выберите канал выше, чтобы увидеть подробную статистику.';
        }
    }

    if (channelSelect) {
        channelSelect.addEventListener('change', () => updateChannelDisplay(window._channelMetrics || []));
    }

    async function loadData(period) {
        const resp = await fetch(`/my-stats/data?token=${token}&period=${period}`);
        const data = await resp.json();

        document.getElementById('finance-balance').innerHTML = `
            <p>💳 Доступно к выводу: <b>${data.balance_available.toFixed(2)} ₽</b></p>
            <p>⏳ В ожидании: <b>${data.balance_pending.toFixed(2)} ₽</b></p>
            <p>📬 Постов за период: <b>${data.total_posts}</b> | 💵 Доход: <b>${data.total_revenue.toFixed(2)} ₽</b></p>
        `;

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

        const txDiv = document.getElementById('finance-transactions');
        if (data.recent_transactions && data.recent_transactions.length > 0) {
            let html = '<h3>Последние транзакции</h3><table><tr><th>Сумма</th><th>Статус</th><th>Заказ</th><th>Дата</th></tr>';
            data.recent_transactions.forEach(t => {
                const statusEmoji = {pending: '⏳', approved: '✅', declined: '❌', new: '🆕', waiting: '⏳', paid: '💳'}[t.status] || '❓';
                let reasonHtml = '';
                if (t.status === 'declined' && t.decline_reason) {
                    reasonHtml = `<br><small style="color:#ff4444;">Причина: ${t.decline_reason}</small>`;
                }
                html += `<tr><td>${t.amount} ${t.currency}</td><td>${statusEmoji} ${t.status}${reasonHtml}</td><td>${t.order_id || '—'}</td><td>${t.date}</td></tr>`;
            });
            html += '</table>';
            txDiv.innerHTML = html;
        } else {
            txDiv.innerHTML = '<p>Нет транзакций</p>';
        }

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

        const revenueContainer = document.getElementById('revenue-chart-container');
        if (revenueChart) revenueChart.destroy();
        if (data.revenue_values && data.revenue_values.length > 0) {
            revenueContainer.style.display = 'block';
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
            revenueContainer.style.display = 'none';
            revenueChart = null;
        }

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

        window._channelMetrics = data.channels || [];
        populateChannelOptions(window._channelMetrics);
        updateChannelDisplay(window._channelMetrics);

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

    // Кнопки переключения периода
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

    // Функция запроса выплаты
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

    // Первая загрузка
    loadData('30d');
})();
</script>
</body>
</html>'''

# ------------------------------------------------------------------------------
# Шаблон чата выплат (пользователь)
# ------------------------------------------------------------------------------
CHAT_TEMPLATE = r'''<!DOCTYPE html>
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

# ------------------------------------------------------------------------------
# Шаблон редактора шаблонов (с учётом роли)
# ------------------------------------------------------------------------------
TEMPLATES_PAGE_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Шаблоны постов</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; }
    h1 { color: #ff4444; }
    .nav { margin-bottom: 20px; display: flex; gap: 15px; }
    .nav a { color: #ff4444; text-decoration: none; padding: 8px 16px; border-radius: 8px; background: #333; }
    .nav a.active { background: #ff4444; color: #fff; }
    .tabs { display: flex; gap: 10px; margin-bottom: 20px; overflow-x: auto; white-space: nowrap; -webkit-overflow-scrolling: touch; }
    .tabs button { background: #333; color: #ccc; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; flex-shrink: 0; }
    .tabs button.active { background: #ff4444; color: #fff; }
    .editor-panel { display: flex; gap: 20px; flex-wrap: wrap; }
    .editor { flex: 2; min-width: 300px; }
    .editor textarea { width: 100%; height: 200px; background: #333; color: #ccc; border: 1px solid #555; border-radius: 8px; padding: 12px; font-size: 1em; }
    .placeholders { flex: 1; min-width: 200px; background: #1e1e1e; border-radius: 12px; padding: 15px; }
    .placeholders h3 { margin-top: 0; color: #ff4444; }
    .placeholder-btn { background: #444; color: #fff; border: none; padding: 6px 12px; border-radius: 6px; margin: 4px 2px; cursor: pointer; }
    .preview-box { background: #111; border-radius: 12px; padding: 15px; margin-top: 20px; }
    .preview-box h3 { color: #ff4444; }
    #preview-content { background: #1a1a1a; padding: 15px; border-radius: 8px; }
    .actions { margin-top: 15px; display: flex; gap: 10px; }
    /* Hamburger sidebar */
    .hamburger { display: none; position: fixed; top: 15px; left: 15px; z-index: 1000; background: #ff4444; color: white; border: none; font-size: 24px; padding: 8px 12px; border-radius: 8px; cursor: pointer; }
    .sidebar { position: fixed; top: 0; left: -280px; width: 260px; height: 100%; background: #222; transition: left 0.3s; z-index: 999; padding: 60px 20px 20px; overflow-y: auto; }
    .sidebar.open { left: 0; }
    .sidebar a { display: block; color: #ccc; padding: 12px 16px; text-decoration: none; border-radius: 8px; margin-bottom: 5px; font-size: 1em; }
    .sidebar a:hover, .sidebar a.active { background: #ff4444; color: #fff; }
    .overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 998; }
    .overlay.open { display: block; }
    @media (max-width: 768px) {
        .hamburger { display: block; }
        .nav { display: none !important; }
        body { padding: 15px; }
        .container { max-width: 100%; }
    }
</style>
</head>
<body>
<div class="container">
    <button class="hamburger" onclick="toggleSidebar()">☰</button>
    <div class="overlay" onclick="toggleSidebar()"></div>
    <div class="sidebar">
        <a href="/my-stats?token={{ token }}">📊 Статистика</a>
        <a href="/my-stats/templates?token={{ token }}" class="active">📝 Шаблоны</a>
        <a href="/my-stats/cpc-campaigns?token={{ token }}">👆 CPC кампании</a>
        <a href="/my-stats/settings?token={{ token }}">⚙️ Настройки</a>
        <a href="/my-stats/guide?token={{ token }}">📖 Инструкция</a>
    </div>
    <h1>📝 Шаблоны постов</h1>
    <div class="tabs">
        <button id="tab-product" class="active" onclick="switchTab('product')">🛒 Товарный (CPA)</button>
        <button id="tab-video" onclick="switchTab('video')">🎬 Видео</button>
        <button id="tab-cpc" onclick="switchTab('cpc')">👆 Клики (CPC)</button>
    </div>

    <div id="tab-product-content" class="editor-panel">
        <div class="editor">
            <textarea id="product-template" placeholder="Введите шаблон..."></textarea>
            <div class="actions">
                <button onclick="saveTemplate('product')">Сохранить</button>
                <button onclick="resetTemplate('product')">Сбросить</button>
                <button onclick="renderProductPreview()">Обновить предпросмотр</button>
            </div>
        </div>
        <div class="placeholders">
            <h3>Вставить</h3>
            <div id="product-placeholders"></div>
        </div>
    </div>
    <div id="tab-video-content" class="editor-panel" style="display:none;">
        <div class="editor">
            <textarea id="video-template" placeholder="Введите шаблон..."></textarea>
            <div class="actions">
                <button onclick="saveTemplate('video')">Сохранить</button>
                <button onclick="resetTemplate('video')">Сбросить</button>
            </div>
        </div>
        <div class="placeholders">
            <h3>Вставить</h3>
            <div id="video-placeholders"></div>
        </div>
    </div>
    <div id="tab-cpc-content" class="editor-panel" style="display:none;">
        <div class="editor">
            <textarea id="cpc-template" placeholder="Введите шаблон CPC-постов..."></textarea>
            <div class="actions">
                <button onclick="saveTemplate('cpc')">Сохранить</button>
                <button onclick="resetTemplate('cpc')">Сбросить</button>
                <button onclick="renderCpcPreview()">Обновить предпросмотр</button>
            </div>
        </div>
        <div class="placeholders">
            <h3>Вставить</h3>
            <div id="cpc-placeholders"></div>
        </div>
    </div>
    <div class="preview-box">
        <h3>Предпросмотр</h3>
        <div id="preview-content"></div>
    </div>
</div>

<script>
function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
    document.querySelector('.overlay').classList.toggle('open');
}
const token = "{{ token }}";
const role = "{{ role }}";   // "saas" или "blogger"
const isSaaS = (role === "saas");
let currentTab = 'product';

const placeholders = {
    product: ['{title}', '{price}', '{currency}', '{link}', '{advertiser}', '{erid}', '{old_price}', '{discount_percent}', '{delivery_line}', '{promocode_line}', '{price_label}', '{cta_phrase}'],
    video: ['{title}', '{link}', '{description}'],
    cpc: ['{name}', '{link}', '{description}']
};
const defaultProduct = `🔥 <b>{title}</b>\n\n💰 {price_label}: {price} {currency}{discount_line}\n👉 {link}\n{promocode_line}{delivery_line}\n{cta_phrase}\n\nРеклама. {advertiser}. Erid: {erid}`;
const defaultVideo = `🎬 <b>{title}</b>\n\n{description}\n\n🔗 <a href='{link}'>Смотреть</a>`;
const defaultCpc = `👆 <b>{name}</b>\n\n{description}\n\n{link}`;
let previewDebounceTimer = null;

if (isSaaS) {
    // Скрываем вкладку видео для SaaS
    document.getElementById('tab-video').style.display = 'none';
    document.getElementById('tab-video-content').style.display = 'none';
}

async function loadTemplates() {
    try {
        const resp = await fetch(`/my-stats/get-templates?token=${token}`);
        const data = await resp.json();
        document.getElementById('product-template').value = data.product_template || defaultProduct;
        if (!isSaaS) {
            document.getElementById('video-template').value = data.video_template || defaultVideo;
            renderPlaceholders('video');
        }
        document.getElementById('cpc-template').value = data.cpc_template || defaultCpc;
        renderPlaceholders('product');
        renderPlaceholders('cpc');
        updatePreview();
    } catch(e) {
        console.error(e);
    }
}

function renderPlaceholders(type) {
    const container = document.getElementById(`${type}-placeholders`);
    if (!container) return;
    container.innerHTML = placeholders[type].map(p => `<button class="placeholder-btn" onclick="insertPlaceholder('${type}', '${p}')">${p}</button>`).join('');
}

function insertPlaceholder(type, placeholder) {
    const textarea = document.getElementById(`${type}-template`);
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value;
    textarea.value = text.substring(0, start) + placeholder + text.substring(end);
    textarea.focus();
    textarea.setSelectionRange(start + placeholder.length, start + placeholder.length);
    updatePreview();
}

function updatePreview() {
    if (currentTab === 'product') {
        scheduleProductPreview();
    } else if (currentTab === 'cpc') {
        renderCpcPreview();
    } else {
        renderVideoSample();
    }
}

function renderVideoSample() {
    const template = document.getElementById('video-template').value;
    const preview = document.getElementById('preview-content');
    const testData = {
        title: 'Моё видео',
        link: 'https://youtube.com/...',
        description: 'Описание ролика'
    };
    preview.innerHTML = template.replace(/\{(\w+)\}/g, (match, key) => testData[key] || match);
}

function scheduleProductPreview() {
    if (previewDebounceTimer) {
        clearTimeout(previewDebounceTimer);
    }
    previewDebounceTimer = setTimeout(() => {
        renderProductPreview();
    }, 400);
}

async function renderProductPreview() {
    const template = document.getElementById('product-template').value;
    const container = document.getElementById('preview-content');
    if (!container) return;
    if (!template.trim()) {
        container.innerHTML = '<div style="text-align:center; padding:20px; color:#888;">Введите шаблон, чтобы увидеть предпросмотр.</div>';
        return;
    }
    container.innerHTML = '<div style="text-align:center; padding:20px;">⏳ Обновление предпросмотра...</div>';

    try {
        const formData = new FormData();
        formData.append('token', token);
        formData.append('template', template);

        const resp = await fetch('/my-stats/preview-post', { method: 'POST', body: formData });
        const data = await resp.json();

        if (!data.ok) {
            container.innerHTML = `<div style="text-align:center; padding:20px; color:#ff4444;">❌ ${data.error}</div>`;
            window._currentProductId = null;
            return;
        }

        const imageHtml = data.image_url
            ? `<div style="margin-bottom:12px;"><img src="${data.image_url}" style="max-width:100%; max-height:300px; border-radius:8px; object-fit:contain; background:#111;" onerror="this.style.display='none'"></div>`
            : '';
        const captionHtml = `<div style="font-size:14px; line-height:1.6; word-wrap:break-word; white-space:pre-wrap;">${data.caption.replace(/\n/g, '<br>')}</div>`;

        container.innerHTML = `
            <div style="background: #0f0f0f; border-radius:12px; padding:16px; max-width:700px; margin:0 auto; text-align:left; border:1px solid #2a2a2a;">
                ${imageHtml}
                ${captionHtml}
                <div style="margin-top:12px; padding-top:12px; border-top:1px solid #2a2a2a; font-size:12px; color:#888;">
                    <span style="color:#4d6bfe;">💡 Предпросмотр на случайном товаре с текущим шаблоном</span>
                </div>
            </div>
        `;

        window._currentProductId = data.product_id;
        window._currentPartnerUrl = data.partner_url;
    } catch (e) {
        container.innerHTML = `<div style="text-align:center; padding:20px; color:#ff4444;">❌ Ошибка загрузки: ${e.message}</div>`;
        window._currentProductId = null;
    }
}

async function saveTemplate(type) {
    const template = document.getElementById(`${type}-template`).value;
    const formData = new FormData();
    formData.append('token', token);
    formData.append('type', type);
    formData.append('template', template);
    await fetch('/my-stats/save-template', { method: 'POST', body: formData });
    alert('Сохранено');
}

async function resetTemplate(type) {
    const defaults = { product: defaultProduct, video: defaultVideo, cpc: defaultCpc };
    document.getElementById(`${type}-template`).value = defaults[type] || '';
    updatePreview();
}

function switchTab(tab) {
    currentTab = tab;
    document.getElementById('tab-product').classList.toggle('active', tab === 'product');
    document.getElementById('tab-video').classList.toggle('active', tab === 'video');
    document.getElementById('tab-cpc').classList.toggle('active', tab === 'cpc');
    document.getElementById('tab-product-content').style.display = tab === 'product' ? 'flex' : 'none';
    document.getElementById('tab-video-content').style.display = tab === 'video' ? 'flex' : 'none';
    document.getElementById('tab-cpc-content').style.display = tab === 'cpc' ? 'flex' : 'none';
    updatePreview();
}

function renderCpcPreview() {
    const template = document.getElementById('cpc-template').value || defaultCpc;
    const container = document.getElementById('preview-content');
    if (!container) return;
    container.innerHTML = '<div style="text-align:center; padding:20px;">⏳ Загрузка предпросмотра...</div>';
    (async () => {
        const resp = await fetch(`/my-stats/preview-template?token=${token}&type=cpc`);
        const data = await resp.json();
        const imageHtml = data.image_url
            ? `<div style="margin-bottom:12px;"><img src="${data.image_url}" style="max-width:100%; max-height:300px; border-radius:8px; object-fit:contain; background:#111;" onerror="this.style.display='none'"></div>`
            : '';
        const textHtml = `<div style="font-size:14px; line-height:1.6; word-wrap:break-word; white-space:pre-wrap;">${data.html.replace(/\n/g, '<br>')}</div>`;
        container.innerHTML = `<div style="background:#0f0f0f; border-radius:12px; padding:16px; max-width:700px; margin:0 auto; text-align:left; border:1px solid #2a2a2a;">${imageHtml}${textHtml}</div>`;
    })();
}

document.getElementById('product-template').addEventListener('input', updatePreview);
document.getElementById('video-template').addEventListener('input', updatePreview);
document.getElementById('cpc-template').addEventListener('input', updatePreview);

loadTemplates();
</script>
</body>
</html>'''

# ------------------------------------------------------------------------------
# Шаблон страницы настроек
# ------------------------------------------------------------------------------
SETTINGS_PAGE_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Настройки</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; max-width: 800px; margin: 0 auto; }
    h1 { color: #ff4444; font-size: 1.5em; margin-bottom: 20px; }
    .nav { margin-bottom: 20px; display: flex; gap: 10px; overflow-x: auto; -webkit-overflow-scrolling: touch; padding-bottom: 5px; }
    .nav a { color: #ff4444; text-decoration: none; padding: 8px 16px; border-radius: 8px; background: #333; white-space: nowrap; flex-shrink: 0; }
    .nav a.active { background: #ff4444; color: #fff; }
    .section { background: #222; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
    .section h2 { color: #ddd; font-size: 1.2em; margin: 0 0 15px 0; }
    label { display: block; margin-bottom: 5px; color: #aaa; font-size: 0.9em; }
    input, select { background: #333; border: 1px solid #555; color: #ddd; padding: 12px; border-radius: 8px; width: 100%; margin-bottom: 15px; font-size: 1em; box-sizing: border-box; }
    input[type="checkbox"] { width: auto; margin-right: 8px; }
    .checkbox-label { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; cursor: pointer; }
    .checkbox-label input { margin: 0; }
    .btn { background: #ff4444; color: white; border: none; padding: 12px 24px; border-radius: 8px; font-size: 1em; cursor: pointer; width: 100%; }
    .btn:hover { background: #e03333; }
    .btn-small { background: #444; color: #ccc; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85em; }
    .btn-small:hover { background: #555; }
    .btn-danger { background: #c62828; }
    .btn-danger:hover { background: #b71c1c; }
    .success { color: #4caf50; margin-bottom: 10px; }
    .error { color: #ff4444; margin-bottom: 10px; }
    .store-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; padding: 10px; background: #2a2a2a; border-radius: 8px; }
    .store-row label { margin: 0; flex: 1; }
    .store-row select { width: auto; margin: 0; min-width: 120px; }
    .channel-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; padding: 10px; background: #2a2a2a; border-radius: 8px; }
    .channel-row span { flex: 1; }
    .info-text { background: #1e1e1e; border-radius: 8px; padding: 15px; margin-bottom: 15px; color: #aaa; line-height: 1.6; }
    .info-text code { background: #333; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }
    .tabs { display: flex; gap: 8px; margin-bottom: 20px; overflow-x: auto; white-space: nowrap; -webkit-overflow-scrolling: touch; }
    .tab-btn { background: #333; border: 1px solid #555; color: #ddd; padding: 10px 20px; border-radius: 8px; cursor: pointer; flex-shrink: 0; min-width: 100px; text-align: center; }
    .tab-btn.active { background: #ff4444; color: #fff; border-color: #ff4444; }
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    /* Hamburger sidebar */
    .hamburger { display: none; position: fixed; top: 15px; left: 15px; z-index: 1000; background: #ff4444; color: white; border: none; font-size: 24px; padding: 8px 12px; border-radius: 8px; cursor: pointer; }
    .sidebar { position: fixed; top: 0; left: -280px; width: 260px; height: 100%; background: #222; transition: left 0.3s; z-index: 999; padding: 60px 20px 20px; overflow-y: auto; }
    .sidebar.open { left: 0; }
    .sidebar a { display: block; color: #ccc; padding: 12px 16px; text-decoration: none; border-radius: 8px; margin-bottom: 5px; font-size: 1em; }
    .sidebar a:hover, .sidebar a.active { background: #ff4444; color: #fff; }
    .overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 998; }
    .overlay.open { display: block; }
    @media (max-width: 768px) {
        .hamburger { display: block; }
        .nav { display: none !important; }
        body { padding: 15px; }
    }
</style>
</head>
<body>
    <button class="hamburger" onclick="toggleSidebar()">☰</button>
    <div class="overlay" onclick="toggleSidebar()"></div>
    <div class="sidebar">
        <a href="/my-stats?token={{ token }}">📊 Статистика</a>
        <a href="/my-stats/templates?token={{ token }}">📝 Шаблоны</a>
        <a href="/my-stats/settings?token={{ token }}" class="active">⚙️ Настройки</a>
        <a href="/my-stats/guide?token={{ token }}">📖 Инструкция</a>
    </div>
    <h1>⚙️ Настройки</h1>

    <div class="tabs">
        <button class="tab-btn active" data-tab="general">Основные</button>
        <button class="tab-btn" data-tab="cyclic">Расписание</button>
        <button class="tab-btn" data-tab="video">Видео-каналы</button>
        <button class="tab-btn" data-tab="referral">Рефералка</button>
    </div>

    <div id="tab-general" class="tab-content active">
        <div class="section">
            <h2>Периодичность</h2>
            <label>Интервал между постами (минуты)</label>
            <input type="number" id="post-interval" min="5" value="60">
        </div>
        <div class="section">
            <h2>Посты</h2>
            <div class="checkbox-label"><input type="checkbox" id="auto-pin"> 📌 Авто-закреп постов на 24 часа</div>
            <div class="checkbox-label"><input type="checkbox" id="notify-posts"> 🔔 Уведомлять о каждом опубликованном посте</div>
            <div class="checkbox-label"><input type="checkbox" id="skip-preview"> 🚀 Публиковать без предпросмотра</div>
            <label>Автоудаление постов</label>
            <select id="auto-delete">
                <option value="0">❌ Выключено</option>
                <option value="1">1 час</option>
                <option value="6">6 часов</option>
                <option value="12">12 часов</option>
                <option value="24">1 день</option>
                <option value="48">2 дня</option>
                <option value="72">3 дня</option>
                <option value="168" selected>7 дней (по умолчанию)</option>
                <option value="336">14 дней</option>
                <option value="720">30 дней</option>
            </select>
        </div>
        <div class="section">
            <h2>Фильтр товаров</h2>
            <label>Минимальная скидка для CPA-товаров (%) — <b>0</b> = все товары</label>
            <input type="number" id="min-discount" min="0" max="100" value="0">
        </div>
        <div class="section">
            <h2>Налоговый статус (для выплат)</h2>
            <label>Выберите ваш статус в РФ</label>
            <select id="tax-status">
                <option value="">Не указан</option>
                <option value="business">🧾 Самозанятый / ИП</option>
                <option value="individual">👤 Физическое лицо</option>
            </select>
        </div>
        <button class="btn" onclick="saveGeneralSettings()">💾 Сохранить настройки</button>
        <div id="save-msg" style="margin-top:10px;"></div>
    </div>

    <div id="tab-cyclic" class="tab-content">
        <div class="section">
            <h2>⏰ Циклический постинг</h2>
            <p style="color:#aaa; margin-bottom:15px;">Задайте периодичность для каждого магазина. Если расписание не настроено — магазины чередуются автоматически.</p>
            <div id="cyclic-list"></div>
            <button class="btn" onclick="saveCyclicSchedules()">💾 Сохранить расписание</button>
            <div id="cyclic-msg" style="margin-top:10px;"></div>
        </div>
    </div>

    <div id="tab-video" class="tab-content">
        <div class="section" id="video-section">
            <h2>🎥 Подключённые видео-каналы</h2>
            <div id="video-list"></div>
            <hr style="border-color:#333; margin:15px 0;">
            <h3>Добавить канал</h3>
            <label>Платформа</label>
            <select id="video-platform">
                <option value="youtube">YouTube</option>
                <option value="rutube">Rutube</option>
                <option value="vk_video">VK Видео</option>
                <option value="dzen">Дзен</option>
            </select>
            <label>ID канала / Username</label>
            <input type="text" id="video-channel-id" placeholder="UC... или @username">
            <button class="btn" onclick="addVideoChannel()">➕ Добавить</button>
            <div id="video-msg" style="margin-top:10px;"></div>
        </div>
    </div>

    <div id="tab-referral" class="tab-content">
        <div class="section">
            <h2>🔗 Реферальная программа</h2>
            <div class="info-text">
                Приглашайте других пользователей и получайте <b>10%</b> от их чистого заработка!
                Деньги удерживаются из доли приглашённого и перечисляются вам.
            </div>
            <div id="referral-info"></div>
            <label>Ваша реферальная ссылка:</label>
            <input type="text" id="referral-link" readonly onclick="this.select()" style="cursor:pointer;">
        </div>
    </div>
</div>

<script>
function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
    document.querySelector('.overlay').classList.toggle('open');
}
const token = "{{ token }}";
const role = "{{ role }}";

const intervalOptions = [
    [0, "Выключено"], [1, "1 час"], [6, "6 часов"], [12, "12 часов"],
    [24, "1 день"], [48, "2 дня"], [72, "3 дня"], [168, "7 дней"],
    [336, "14 дней"], [720, "30 дней"]
];

// Tabs
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    });
});

// Load settings
async function loadSettings() {
    try {
        const resp = await fetch(`/my-stats/settings-data?token=${token}`);
        const data = await resp.json();
        document.getElementById('post-interval').value = data.post_interval_minutes || 60;
        document.getElementById('auto-delete').value = data.default_auto_delete_hours || 168;
        document.getElementById('auto-pin').checked = data.auto_pin;
        document.getElementById('notify-posts').checked = data.notify_posts;
        document.getElementById('skip-preview').checked = data.force_preview_confirmed;
        document.getElementById('min-discount').value = data.min_discount || 0;
        if (data.tax_status) document.getElementById('tax-status').value = data.tax_status;
        loadCyclic(data.stores);
        loadVideoChannels(data.video_channels);
        loadReferral(data.sub_id);
    } catch(e) { console.error(e); }
}

function loadCyclic(stores) {
    const container = document.getElementById('cyclic-list');
    if (!stores || stores.length === 0) {
        container.innerHTML = '<p style="color:#888;">Сначала выберите магазины в боте (🏪 Магазины).</p>';
        return;
    }
    container.innerHTML = stores.map(s => `
        <div class="store-row">
            <label>${s.name}</label>
            <select data-store="${s.id}" ${!s.available ? 'disabled' : ''}>
                ${intervalOptions.map(([val, label]) =>
                    `<option value="${val}" ${s.interval == val && val > 0 ? 'selected' : ''}>${label}</option>`
                ).join('')}
                <option value="-1" ${s.interval > 0 && !intervalOptions.some(o => o[0] == s.interval) ? 'selected' : ''} disabled>—</option>
            </select>
        </div>
    `).join('');
}

function loadVideoChannels(channels) {
    const container = document.getElementById('video-list');
    if (!channels || channels.length === 0) {
        container.innerHTML = '<p style="color:#888;">Нет подключённых видео-каналов.</p>';
        return;
    }
    container.innerHTML = channels.map(ch => `
        <div class="channel-row">
            <span>${ch.platform}: <b>${ch.channel_id}</b> ${ch.is_active ? '🟢' : '🔴'}</span>
            <button class="btn-small btn-danger" onclick="removeVideoChannel(${ch.id})">Удалить</button>
        </div>
    `).join('');
}

function loadReferral(subId) {
    const container = document.getElementById('referral-info');
    if (!subId) {
        container.innerHTML = '<p style="color:#888;">Сначала добавьте канал, чтобы получить реферальную ссылку.</p>';
        document.getElementById('referral-link').value = '';
        return;
    }
    document.getElementById('referral-link').value = `https://t.me/{{ bot_username }}?start=${subId}`;
}

async function saveGeneralSettings() {
    const btn = document.querySelector('#tab-general .btn');
    btn.disabled = true;
    btn.textContent = '⏳ Сохранение...';
    const formData = new FormData();
    formData.append('token', token);
    formData.append('post_interval_minutes', document.getElementById('post-interval').value);
    formData.append('default_auto_delete_hours', document.getElementById('auto-delete').value);
    formData.append('auto_pin', document.getElementById('auto-pin').checked ? '1' : '0');
    formData.append('notify_posts', document.getElementById('notify-posts').checked ? '1' : '0');
    formData.append('force_preview_confirmed', document.getElementById('skip-preview').checked ? '1' : '0');
    formData.append('min_discount', document.getElementById('min-discount').value);
    formData.append('tax_status', document.getElementById('tax-status').value);
    try {
        const resp = await fetch('/my-stats/save-settings', { method: 'POST', body: formData });
        const data = await resp.json();
        const msg = document.getElementById('save-msg');
        msg.innerHTML = data.ok ? '<p class="success">✅ Настройки сохранены</p>' : '<p class="error">❌ Ошибка сохранения</p>';
        setTimeout(() => msg.innerHTML = '', 3000);
    } catch(e) { console.error(e); }
    btn.disabled = false;
    btn.textContent = '💾 Сохранить настройки';
}

async function saveCyclicSchedules() {
    const rows = document.querySelectorAll('#cyclic-list .store-row select');
    const schedules = [];
    rows.forEach(sel => {
        const val = parseInt(sel.value);
        if (val > 0) schedules.push({ store_id: parseInt(sel.dataset.store), interval_days: val });
    });
    const formData = new FormData();
    formData.append('token', token);
    formData.append('schedules', JSON.stringify(schedules));
    try {
        const resp = await fetch('/my-stats/save-cyclic', { method: 'POST', body: formData });
        const data = await resp.json();
        const msg = document.getElementById('cyclic-msg');
        msg.innerHTML = data.ok ? '<p class="success">✅ Расписание сохранено</p>' : '<p class="error">❌ Ошибка</p>';
        setTimeout(() => msg.innerHTML = '', 3000);
    } catch(e) { console.error(e); }
}

async function addVideoChannel() {
    const platform = document.getElementById('video-platform').value;
    const channelId = document.getElementById('video-channel-id').value.trim();
    if (!channelId) return;
    const formData = new FormData();
    formData.append('token', token);
    formData.append('platform', platform);
    formData.append('channel_id', channelId);
    try {
        const resp = await fetch('/my-stats/add-video-channel', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.ok) {
            document.getElementById('video-channel-id').value = '';
            loadVideoChannels(data.channels);
        }
        const msg = document.getElementById('video-msg');
        msg.innerHTML = data.ok ? '<p class="success">✅ Канал добавлен</p>' : '<p class="error">❌ ' + (data.error || 'Ошибка') + '</p>';
        setTimeout(() => msg.innerHTML = '', 3000);
    } catch(e) { console.error(e); }
}

async function removeVideoChannel(id) {
    if (!confirm('Удалить видео-канал?')) return;
    const formData = new FormData();
    formData.append('token', token);
    formData.append('channel_id', id);
    try {
        const resp = await fetch('/my-stats/remove-video-channel', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.ok) loadVideoChannels(data.channels);
    } catch(e) { console.error(e); }
}

loadSettings();
</script>
</body>
</html>'''

# ------------------------------------------------------------------------------
# Эндпоинты
# ------------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def user_stats_page(token: str = Query(...)):
    user_id = get_user_id_from_token(token)

    html = USER_STATS_TEMPLATE.replace('{{ token }}', token)
    return HTMLResponse(content=html)

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
        post_rows = conn.execute("""SELECT DATE(published_at) as day, COUNT(*) as count FROM posts WHERE user_id=? AND status='published' AND published_at >= ? GROUP BY day ORDER BY day""", (user_id, since)).fetchall()
        revenue_rows = conn.execute("""SELECT DATE(time, 'unixepoch') as day, SUM(payment_sum) as total FROM admitad_transactions WHERE user_id=? AND time >= strftime('%s', ?) AND payment_status = 'approved' GROUP BY day ORDER BY day""", (user_id, since)).fetchall()
        clicks_rows = conn.execute("""SELECT DATE(time, 'unixepoch') as day, COUNT(*) as clicks FROM admitad_transactions WHERE user_id=? AND time >= strftime('%s', ?) AND action='click' GROUP BY day ORDER BY day""", (user_id, since)).fetchall()
        leads_rows = conn.execute("""SELECT DATE(time, 'unixepoch') as day, COUNT(*) as leads FROM admitad_transactions WHERE user_id=? AND time >= strftime('%s', ?) AND action='lead' GROUP BY day ORDER BY day""", (user_id, since)).fetchall()
        store_rows = conn.execute("""SELECT g.source, COUNT(*) as cnt FROM posts p JOIN gdeslon_catalog g ON p.donor_post_id LIKE 'admitad_' || g.id || '_%' WHERE p.user_id=? AND p.status='published' AND p.published_at >= ? GROUP BY g.source ORDER BY cnt DESC""", (user_id, since)).fetchall()
        balance = conn.execute("SELECT balance_available, balance_pending FROM users WHERE user_id=?", (user_id,)).fetchone()
        total_posts = sum(r["count"] for r in post_rows) if post_rows else 0
        total_revenue = sum(r["total"] for r in revenue_rows) if revenue_rows else 0.0
        clicks_dict = {r["day"]: r["clicks"] for r in clicks_rows}
        leads_dict = {r["day"]: r["leads"] for r in leads_rows}
        start_date = date.today() - timedelta(days={"7d":7, "30d":30}.get(period, 1000))
        end_date = date.today()
        all_days = [(start_date + timedelta(days=i)).isoformat() for i in range((end_date - start_date).days + 1)]
        clicks_counts = [clicks_dict.get(day, 0) for day in all_days]
        leads_counts = [leads_dict.get(day, 0) for day in all_days]
        conversion_values = [round(l / c * 100, 1) if c > 0 else 0.0 for c, l in zip(clicks_counts, leads_counts)]
        channel_rows = conn.execute("""SELECT c.channel_title, c.channel_id, COUNT(p.id) as posts_cnt, COALESCE(s.clicks_count, 0) as clicks, COALESCE(s.leads_count, 0) as leads, COALESCE(s.earnings_approved, 0) as earnings FROM channels c LEFT JOIN posts p ON p.channel_id = c.channel_id AND p.user_id = c.user_id AND p.status='published' AND p.published_at >= ? LEFT JOIN subid_stats s ON s.subid1 = c.sub_id WHERE c.user_id = ? AND c.is_active = 1 GROUP BY c.channel_id ORDER BY earnings DESC""", (since, user_id)).fetchall()
        top_products = conn.execute("""SELECT g.title, COUNT(*) as cnt FROM posts p JOIN gdeslon_catalog g ON p.donor_post_id LIKE 'admitad_' || g.id || '_%' WHERE p.user_id = ? AND p.status='published' AND p.published_at >= ? GROUP BY g.title ORDER BY cnt DESC LIMIT 5""", (user_id, since)).fetchall()
        transactions = conn.execute("""SELECT payment_sum, currency, payment_status, order_id, action, time, decline_reason FROM admitad_transactions WHERE user_id = ? ORDER BY time DESC LIMIT 10""", (user_id,)).fetchall()
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
            "channels": [{"title": r["channel_title"] or r["channel_id"], "channel_id": r["channel_id"], "posts": r["posts_cnt"], "clicks": r["clicks"], "leads": r["leads"], "earnings": r["earnings"], "conversion": round(r["leads"] / r["clicks"] * 100, 1) if r["clicks"] > 0 else 0} for r in channel_rows],
            "top_products": [{"title": r["title"], "count": r["cnt"]} for r in top_products],
            "recent_transactions": [{"amount": t["payment_sum"], "currency": t["currency"], "status": t["payment_status"], "order_id": t["order_id"], "action": t["action"], "date": datetime.fromtimestamp(int(t["time"]), tz=timezone.utc).strftime("%d.%m.%Y %H:%M") if t["time"] else "", "decline_reason": t["decline_reason"] or ""} for t in transactions] if transactions else [],
            "bot_username": BOT_USERNAME
        })
    finally:
        conn.close()

@router.get("/chat/{request_id}", response_class=HTMLResponse)
async def user_chat_page(request_id: int, token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        req = conn.execute("SELECT id, status FROM payout_requests WHERE id=? AND user_id=?", (request_id, user_id)).fetchone()
        if not req:
            return HTMLResponse("Заявка не найдена", status_code=404)
        html = CHAT_TEMPLATE.replace("{{ request_id }}", str(request_id)).replace("{{ status }}", req["status"]).replace("{{ token }}", token)
        return HTMLResponse(content=html)
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
        cursor = conn.execute("INSERT INTO payout_requests (user_id, amount, message, status) VALUES (?, ?, ?, 'processing')", (user_id, available, details.strip()))
        request_id = cursor.lastrowid
        conn.execute("INSERT INTO payout_chat (request_id, sender_role, message) VALUES (?, 'user', ?)", (request_id, f"Реквизиты: {details.strip()}"))
        conn.commit()
        bot = request.app.state.bot
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, f"🔔 Новый запрос на выплату #{request_id}\nПользователь: {user_id}\nСумма: {available:.2f} ₽", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌐 Админка", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))]]))
            except: pass
        return JSONResponse({"ok": True, "request_id": request_id})
    finally:
        conn.close()

@router.get("/payout-status")
async def payout_status(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        active = conn.execute("SELECT id, status FROM payout_requests WHERE user_id=? AND status IN ('processing','awaiting_receipt','receipt_uploaded') ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
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
        messages = conn.execute("SELECT sender_role, message, file_path, created_at FROM payout_chat WHERE request_id = ? ORDER BY created_at ASC", (request_id,)).fetchall()
        return JSONResponse([{"sender_role": m["sender_role"], "message": m["message"], "file_path": m["file_path"], "created_at": m["created_at"]} for m in messages])
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
        conn.execute("INSERT INTO payout_chat (request_id, sender_role, message) VALUES (?, 'user', ?)", (request_id, message.strip()))
        conn.commit()
        return JSONResponse({"ok": True})
    finally:
        conn.close()

from fastapi import Form
from fastapi.responses import RedirectResponse, HTMLResponse
from services.db import get_db

@router.post("/upload-receipt")
async def upload_receipt(
    request: Request,
    request_id: int = Form(...),
    receipt_link: str = Form(...)  # Теперь принимаем ссылку текстом
):
    # Проверка, что ссылка ведет на сайт ФНС
    if "lknpd.nalog.ru" not in receipt_link:
        # Если ссылка чужая - выдаем ошибку
        return HTMLResponse(
            "❌ Ошибка: Вы должны предоставить официальную ссылку на чек из сервиса «Мой Налог» (она начинается с lknpd.nalog.ru). <br><a href='javascript:history.back()'>Вернуться назад</a>", 
            status_code=400
        )

    conn = get_db()
    try:
        # Поле receipt_photo в БД имеет тип TEXT, поэтому оно идеально подходит для хранения URL-ссылки
        conn.execute(
            "UPDATE payout_requests SET status = 'receipt_uploaded', receipt_photo = ? WHERE id = ?",
            (receipt_link, request_id)
        )
        # Добавляем системное сообщение в чат выплат
        conn.execute(
            "INSERT INTO payout_chat (request_id, sender_role, message) VALUES (?, 'user', ?)",
            (request_id, f"Пользователь предоставил чек (ссылка):\n{receipt_link}")
        )
        conn.commit()
    finally:
        conn.close()

    # Редирект пользователя обратно в чат
    token = request.query_params.get("token") or ""
    return RedirectResponse(url=f"/my-stats/chat/{request_id}?token={token}", status_code=303)

@router.get("/receipt-file")
async def get_receipt_file(path: str = Query(...), token: str = Query(...)):
    get_user_id_from_token(token)
    safe = _safe_path(UPLOAD_DIR, path)
    if not safe or not os.path.exists(safe):
        return HTMLResponse("Файл не найден", status_code=404)
    return FileResponse(safe)

# ---------- Шаблоны ----------
@router.get("/templates", response_class=HTMLResponse)
async def templates_page(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        user = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
        role = user["role"] if user else "blogger"
    finally:
        conn.close()
    html = TEMPLATES_PAGE_TEMPLATE.replace('{{ token }}', token).replace('{{ role }}', role)
    return HTMLResponse(content=html)

@router.get("/get-templates")
async def get_templates(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        user = conn.execute("SELECT product_template, video_template, cpc_template FROM users WHERE user_id=?", (user_id,)).fetchone()
        return JSONResponse({
            "product_template": user["product_template"] if user else "",
            "video_template": user["video_template"] if user else "",
            "cpc_template": user["cpc_template"] if user else ""
        })
    finally:
        conn.close()

@router.post("/save-template")
async def save_template(token: str = Form(...), type: str = Form(...), template: str = Form(...)):
    user_id = get_user_id_from_token(token)
    if type not in ("product", "video", "cpc"):
        return JSONResponse({"ok": False})
    column = {"product": "product_template", "video": "video_template", "cpc": "cpc_template"}[type]
    conn = get_db()
    try:
        conn.execute(f"UPDATE users SET {column}=? WHERE user_id=?", (template, user_id))
        conn.commit()
        return JSONResponse({"ok": True})
    finally:
        conn.close()

# ---------- Настройки ----------
@router.get("/settings", response_class=HTMLResponse)
async def settings_page(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        user = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
        role = user["role"] if user else "blogger"
    finally:
        conn.close()
    html = SETTINGS_PAGE_TEMPLATE.replace('{{ token }}', token).replace('{{ role }}', role)
    return HTMLResponse(content=html)

@router.get("/settings-data")
async def get_settings_data(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        user = conn.execute("""SELECT post_interval_minutes, default_auto_delete_hours,
            auto_pin, notify_posts, force_preview_confirmed, min_discount, tax_status, sub_id
            FROM users WHERE user_id=?""", (user_id,)).fetchone()
        user_stores = conn.execute(
            "SELECT category_id FROM user_category_preferences WHERE user_id=?", (user_id,)
        ).fetchall()
        schedules = conn.execute(
            "SELECT store_id, interval_days FROM cyclic_schedules WHERE user_id=?", (user_id,)
        ).fetchall()
        video_channels = conn.execute(
            "SELECT id, platform, channel_id, is_active FROM social_channels WHERE user_id=?", (user_id,)
        ).fetchall()
        from services.admitad import STORE_ID_MAP
        stores = []
        for s in user_stores:
            sid = s["category_id"]
            name = STORE_ID_MAP.get(sid, f"ID {sid}")
            interval = 0
            for sch in schedules:
                if sch["store_id"] == sid:
                    interval = sch["interval_days"]
                    break
            stores.append({"id": sid, "name": name, "interval": interval, "available": True})
        return JSONResponse({
            "post_interval_minutes": user["post_interval_minutes"] if user else 60,
            "default_auto_delete_hours": user["default_auto_delete_hours"] if user else 168,
            "auto_pin": bool(user["auto_pin"]) if user else True,
            "notify_posts": bool(user["notify_posts"]) if user else True,
            "force_preview_confirmed": bool(user["force_preview_confirmed"]) if user else False,
            "min_discount": user["min_discount"] if user else 0,
            "tax_status": user["tax_status"] if user else "",
            "stores": stores,
            "video_channels": [{"id": v["id"], "platform": v["platform"], "channel_id": v["channel_id"], "is_active": v["is_active"]} for v in video_channels],
            "sub_id": user["sub_id"] if user else "",
        })
    finally:
        conn.close()

@router.post("/save-settings")
async def save_settings(
    token: str = Form(...),
    post_interval_minutes: int = Form(60),
    default_auto_delete_hours: int = Form(168),
    auto_pin: int = Form(1),
    notify_posts: int = Form(1),
    force_preview_confirmed: int = Form(0),
    min_discount: int = Form(0),
    tax_status: str = Form(""),
):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        conn.execute("""UPDATE users SET
            post_interval_minutes=?, default_auto_delete_hours=?, auto_pin=?,
            notify_posts=?, force_preview_confirmed=?, min_discount=?, tax_status=?
            WHERE user_id=?""",
            (post_interval_minutes, default_auto_delete_hours, auto_pin,
             notify_posts, force_preview_confirmed, min_discount, tax_status, user_id))
        conn.commit()
        return JSONResponse({"ok": True})
    except Exception as e:
        logger.error(f"Save settings error: {e}")
        return JSONResponse({"ok": False, "error": str(e)})
    finally:
        conn.close()

@router.post("/save-cyclic")
async def save_cyclic_schedules(token: str = Form(...), schedules: str = Form("[]")):
    user_id = get_user_id_from_token(token)
    import json
    try:
        conn = get_db()
        try:
            conn.execute("DELETE FROM cyclic_schedules WHERE user_id=?", (user_id,))
            sched_list = json.loads(schedules)
            for s in sched_list:
                conn.execute("""
                    INSERT INTO cyclic_schedules (user_id, store_id, interval_days, is_active)
                    VALUES (?, ?, ?, 1)
                """, (user_id, s["store_id"], s["interval_days"]))
            conn.commit()
            return JSONResponse({"ok": True})
        finally:
            conn.close()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})

@router.post("/add-video-channel")
async def add_video_channel(token: str = Form(...), platform: str = Form(...), channel_id: str = Form(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO social_channels (user_id, platform, channel_id, is_active) VALUES (?, ?, ?, 1)",
            (user_id, platform, channel_id)
        )
        conn.commit()
        channels = conn.execute(
            "SELECT id, platform, channel_id, is_active FROM social_channels WHERE user_id=?", (user_id,)
        ).fetchall()
        return JSONResponse({
            "ok": True,
            "channels": [{"id": v["id"], "platform": v["platform"], "channel_id": v["channel_id"], "is_active": v["is_active"]} for v in channels]
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
    finally:
        conn.close()

@router.post("/remove-video-channel")
async def remove_video_channel(token: str = Form(...), channel_id: int = Form(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM social_channels WHERE id=? AND user_id=?", (channel_id, user_id)
        )
        conn.commit()
        channels = conn.execute(
            "SELECT id, platform, channel_id, is_active FROM social_channels WHERE user_id=?", (user_id,)
        ).fetchall()
        return JSONResponse({
            "ok": True,
            "channels": [{"id": v["id"], "platform": v["platform"], "channel_id": v["channel_id"], "is_active": v["is_active"]} for v in channels]
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
    finally:
        conn.close()

@router.get("/preview-template")
async def preview_template(token: str = Query(...), type: str = Query("product")):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        if type == "product":
            product = conn.execute("SELECT * FROM gdeslon_catalog WHERE user_id=? AND erid IS NOT NULL AND erid != '' ORDER BY RANDOM() LIMIT 1", (user_id,)).fetchone()
            if not product:
                return JSONResponse({"html": "Нет товаров для предпросмотра"})
            delivery_info = get_delivery_for_store(product["source"] or "")
            promocode = get_random_promocode(product["source"] or "")
            user_tmpl = conn.execute("SELECT product_template FROM users WHERE user_id=?", (user_id,)).fetchone()
            custom_template = user_tmpl["product_template"] if user_tmpl and user_tmpl["product_template"] else None
            caption = generate_post_text(
                title=product["title"], price=product["price"], currency=product["currency"] or "₽",
                advertiser=product["advertiser"] or "Рекламодатель", erid=product["erid"],
                partner_url=product["partner_url"] or "https://example.com",
                old_price=product["old_price"], discount_percent=product["discount_percent"],
                delivery_info=delivery_info, promocode=promocode,
                custom_template=custom_template
            )
            return JSONResponse({"html": caption})
        elif type == "cpc":
            user_tmpl = conn.execute("SELECT cpc_template FROM users WHERE user_id=?", (user_id,)).fetchone()
            tmpl = user_tmpl["cpc_template"] if user_tmpl and user_tmpl["cpc_template"] else "👆 <b>{name}</b>\n\n{link}"
            campaign = conn.execute(
                "SELECT name, image_url, description FROM cpc_campaigns WHERE user_id=? ORDER BY RANDOM() LIMIT 1",
                (user_id,)
            ).fetchone()
            if campaign:
                html = tmpl.replace("{name}", campaign["name"]).replace("{link}", "https://example.com/cpc/ref").replace("{description}", campaign["description"] or "")
                return JSONResponse({"html": html, "image_url": campaign["image_url"] or ""})
            html = tmpl.replace("{name}", "Тестовый рекламодатель").replace("{link}", "https://example.com/cpc/ref").replace("{description}", "Описание магазина")
            return JSONResponse({"html": html, "image_url": ""})
        else:
            return JSONResponse({"html": "Предпросмотр пока недоступен"})
    finally:
        conn.close()

# =============================================================================
# === БЕТА-ФУНКЦИЯ: ПРЕДПРОСМОТР ПОСТА =======================================
# =============================================================================

@router.api_route("/preview-post", methods=["GET", "POST"])
async def preview_post(
    request: Request,
    token: str = Form(None),
    product_id: int = Query(None),
    template: str = Form(None)
):
    try:
        token = token or request.query_params.get("token")
        user_id = get_user_id_from_token(token)
        
        # Проверка доступа к бета-функции
        if not await is_feature_available_async(user_id, "preview_post"):
            return JSONResponse({"ok": False, "error": "Функция в режиме тестирования"})
        
        conn = get_db()
        try:
            if product_id:
                product = conn.execute(
                    "SELECT * FROM gdeslon_catalog WHERE id = ? AND user_id = ?",
                    (product_id, user_id)
                ).fetchone()
            else:
                product = conn.execute(
                    """SELECT * FROM gdeslon_catalog 
                       WHERE user_id = ? AND erid IS NOT NULL AND erid != ''
                       ORDER BY RANDOM() LIMIT 1""",
                    (user_id,)
                ).fetchone()
            
            if not product:
                return JSONResponse({"ok": False, "error": "Нет доступных товаров"})
            
            # Генерация текста по шаблону
            from services.text_rewriter import generate_post_text
            from services.admitad import get_delivery_for_store, get_random_promocode
            
            source = product["source"] or ""
            delivery_info = get_delivery_for_store(source)
            promocode = get_random_promocode(source)
            
            if template and template.strip():
                custom_template = template
            else:
                user_tmpl = conn.execute(
                    "SELECT product_template FROM users WHERE user_id = ?",
                    (user_id,)
                ).fetchone()
                custom_template = user_tmpl["product_template"] if user_tmpl else None
            
            caption = generate_post_text(
                title=product["title"],
                price=product["price"],
                currency=product["currency"] or "₽",
                advertiser=product["advertiser"] or "Рекламодатель",
                erid=product["erid"],
                partner_url=product["partner_url"] or "#",
                adult=source in ["Розовый кролик"],
                old_price=product["old_price"],
                discount_percent=product["discount_percent"],
                delivery_info=delivery_info,
                promocode=promocode,
                custom_template=custom_template
            )
            
            return JSONResponse({
                "ok": True,
                "title": product["title"],
                "image_url": product["image_url"],
                "caption": caption,
                "price": product["price"],
                "currency": product["currency"] or "₽",
                "advertiser": product["advertiser"] or "Рекламодатель",
                "erid": product["erid"],
                "source": source,
                "product_id": product["id"],
                "partner_url": product["partner_url"]
            })
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Ошибка в preview_post: {e}")
        return JSONResponse({"ok": False, "error": f"Внутренняя ошибка: {str(e)}"})

@router.post("/publish-post")
async def publish_post(request: Request, token: str = Form(...), product_id: int = Form(...)):
    try:
        user_id = get_user_id_from_token(token)
        
        # Проверка доступа к бета-функции
        if not await is_feature_available_async(user_id, "preview_post"):
            return JSONResponse({"ok": False, "error": "Функция в режиме тестирования"})
        
        bot = request.app.state.bot
        
        conn = get_db()
        try:
            product = conn.execute(
                "SELECT * FROM gdeslon_catalog WHERE id = ? AND user_id = ?",
                (product_id, user_id)
            ).fetchone()
            if not product:
                return JSONResponse({"ok": False, "error": "Товар не найден"})
            
            # Помечаем как использованный
            conn.execute("UPDATE gdeslon_catalog SET used = 1 WHERE id = ?", (product_id,))
            
            channels = conn.execute(
                "SELECT channel_id, sub_id FROM channels WHERE user_id = ? AND is_active = 1",
                (user_id,)
            ).fetchall()
            if not channels:
                return JSONResponse({"ok": False, "error": "Нет активных каналов"})
            
            from services.saas_core import publish_post_with_fallback
            from services.text_rewriter import generate_post_text
            from services.admitad import get_delivery_for_store, get_random_promocode
            from handlers.saas import generate_subid2
            
            source = product["source"] or ""
            delivery_info = get_delivery_for_store(source)
            promocode = get_random_promocode(source)
            user_tmpl = conn.execute(
                "SELECT product_template FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            custom_template = user_tmpl["product_template"] if user_tmpl else None
            
            for ch in channels:
                final_url = product["partner_url"]
                if ch["sub_id"]:
                    if '?' in final_url:
                        final_url += '&subid=' + ch["sub_id"]
                    else:
                        final_url += '?subid=' + ch["sub_id"]
                
                subid2 = generate_subid2(user_id, ch["channel_id"])
                if '?' in final_url:
                    final_url += '&subid2=' + subid2
                else:
                    final_url += '?subid2=' + subid2
                
                caption = generate_post_text(
                    title=product["title"],
                    price=product["price"],
                    currency=product["currency"] or "₽",
                    advertiser=product["advertiser"] or "Рекламодатель",
                    erid=product["erid"],
                    partner_url=final_url,
                    old_price=product["old_price"],
                    discount_percent=product["discount_percent"],
                    delivery_info=delivery_info,
                    promocode=promocode,
                    custom_template=custom_template
                )
                
                msg = await publish_post_with_fallback(
                    bot=bot,
                    channel_id=ch["channel_id"],
                    caption=caption,
                    photo_url=product["image_url"],
                    has_spoiler=source in ["Розовый кролик"]
                )
                
                if msg:
                    direct_link = f"https://t.me/{ch['channel_id'].lstrip('@')}/{msg.message_id}"
                    donor_post_id = f"admitad_{product['id']}_{user_id}_{int(datetime.now(timezone.utc).timestamp())}"
                    user_row = conn.execute("SELECT default_auto_delete_hours FROM users WHERE user_id=?", (user_id,)).fetchone()
                    ad_hours = user_row["default_auto_delete_hours"] if user_row and user_row["default_auto_delete_hours"] is not None else 168
                    conn.execute(
                        """INSERT INTO posts 
                        (user_id, donor_post_id, channel_id, target_channel_id, subid1, subid2, direct_link, erid, status, published_at, caption, auto_delete_hours)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?)""",
                        (user_id, donor_post_id, ch['channel_id'], ch['channel_id'], ch['sub_id'], subid2, direct_link,
                         product["erid"], datetime.now(timezone.utc).isoformat(), caption, ad_hours)
                    )
                    conn.commit()
            
            return JSONResponse({"ok": True})
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Ошибка в publish_post: {e}")
        return JSONResponse({"ok": False, "error": f"Внутренняя ошибка: {str(e)}"})

@router.get("/ord-report")
async def download_ord_report(token: str = Query(...), request: Request = None):
    try:
        user_id = get_user_id_from_token(token)
        logger.info(f"Запрос отчёта ОРД для user_id={user_id}")

        # 1. Собираем просмотры (если бот доступен)
        bot = None
        if request and hasattr(request.app.state, 'bot'):
            bot = request.app.state.bot
        if bot:
            try:
                await collect_views_for_user(user_id, bot)
            except Exception as e:
                logger.error(f"Ошибка сбора просмотров для user_id={user_id}: {e}")

        # 2. Получаем посты с ERID
        conn = get_db()
        try:
            posts = conn.execute("""
                SELECT p.published_at, p.erid, p.views_count, p.direct_link, p.channel_id,
                       COALESCE(c.channel_title, '') AS channel_title
                FROM posts p
                LEFT JOIN channels c ON c.user_id = p.user_id AND c.channel_id = p.channel_id
                WHERE p.user_id = ? AND p.status = 'published' AND p.erid IS NOT NULL AND p.erid != ''
                ORDER BY p.published_at DESC
            """, (user_id,)).fetchall()
            logger.info(f"Найдено {len(posts)} постов для отчёта")
        finally:
            conn.close()

        # 3. Создаём Excel-файл
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True, 'remove_timezone': True})
        worksheet = workbook.add_worksheet("ORD")

        # Заголовки (расширенные)
        headers = [
            "ERID",
            "Площадка (Telegram)",
            "Тип площадки",
            "Количество показов",
            "Количество переходов",
            "Сумма потраченная",
            "Дата начала",
            "Дата окончания",
            "Ссылка на пост",
            "Название канала"
        ]
        for col, header in enumerate(headers):
            worksheet.write(0, col, header)

        date_format = workbook.add_format({'num_format': 'dd.mm.yyyy'})

        row_idx = 1
        for post in posts:
            erid = post["erid"] or ""
            views = post["views_count"] or 0
            direct_link = post["direct_link"] or ""
            channel_title = post["channel_title"] or "Telegram"
            published_at = post["published_at"]

            # Обработка даты (снимаем часовой пояс)
            try:
                pub_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                if pub_date.tzinfo is not None:
                    pub_date = pub_date.replace(tzinfo=None)
            except Exception:
                pub_date = datetime.now()

            worksheet.write(row_idx, 0, erid)
            worksheet.write(row_idx, 1, "Telegram")
            worksheet.write(row_idx, 2, channel_title)
            worksheet.write(row_idx, 3, views)
            worksheet.write(row_idx, 4, 0)  # переходы – нет точных данных
            worksheet.write(row_idx, 5, 0)  # сумма – не применимо
            worksheet.write_datetime(row_idx, 6, pub_date, date_format)
            worksheet.write_datetime(row_idx, 7, pub_date, date_format)
            worksheet.write(row_idx, 8, direct_link)
            worksheet.write(row_idx, 9, channel_title)
            row_idx += 1

        # Автоширина
        worksheet.set_column(0, 0, 30)
        worksheet.set_column(1, 2, 18)
        worksheet.set_column(3, 5, 20)
        worksheet.set_column(6, 7, 14)
        worksheet.set_column(8, 9, 40)

        workbook.close()
        output.seek(0)

        filename = f"AutoPost_ORD_Report_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        logger.error(f"Ошибка в ord-report: {e}")
        return HTMLResponse(
            f"<h2>❌ Ошибка формирования отчёта</h2>"
            f"<p>Попробуйте позже или обратитесь в поддержку.</p>"
            f"<br><a href='javascript:history.back()'>Вернуться</a>",
            status_code=500
        )
# ---------- Инструкция ----------
GUIDE_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Инструкция</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; }
    h1 { color: #ff4444; }
    .nav { margin-bottom: 20px; display: flex; gap: 15px; }
    .nav a { color: #ff4444; text-decoration: none; padding: 8px 16px; border-radius: 8px; background: #333; }
    .nav a.active { background: #ff4444; color: #fff; }
    .container { max-width: 900px; margin: auto; }
    .card { background: #1e1e1e; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
    .card h2 { color: #ff4444; margin-top: 0; }
    .card h3 { color: #ff9800; }
    .card ol, .card ul { padding-left: 20px; line-height: 1.8; }
    .card li { margin-bottom: 8px; }
    .card code { background: #333; padding: 2px 6px; border-radius: 4px; color: #4caf50; }
    .warning { background: #2a1a1a; border-left: 4px solid #ff4444; padding: 12px; border-radius: 8px; margin: 10px 0; }
    .success { background: #1a2a1a; border-left: 4px solid #4caf50; padding: 12px; border-radius: 8px; margin: 10px 0; }
    a { color: #4d6bfe; }
    /* Hamburger sidebar */
    .hamburger { display: none; position: fixed; top: 15px; left: 15px; z-index: 1000; background: #ff4444; color: white; border: none; font-size: 24px; padding: 8px 12px; border-radius: 8px; cursor: pointer; }
    .sidebar { position: fixed; top: 0; left: -280px; width: 260px; height: 100%; background: #222; transition: left 0.3s; z-index: 999; padding: 60px 20px 20px; overflow-y: auto; }
    .sidebar.open { left: 0; }
    .sidebar a { display: block; color: #ccc; padding: 12px 16px; text-decoration: none; border-radius: 8px; margin-bottom: 5px; font-size: 1em; }
    .sidebar a:hover, .sidebar a.active { background: #ff4444; color: #fff; }
    .overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 998; }
    .overlay.open { display: block; }
    @media (max-width: 768px) {
        .hamburger { display: block; }
        .nav { display: none !important; }
        body { padding: 15px; }
    }
</style>
</head>
<body>
<div class="container">
    <button class="hamburger" onclick="toggleSidebar()">☰</button>
    <div class="overlay" onclick="toggleSidebar()"></div>
    <div class="sidebar">
        <a href="/my-stats?token={{ token }}">📊 Статистика</a>
        <a href="/my-stats/templates?token={{ token }}">📝 Шаблоны</a>
        <a href="/my-stats/cpc-campaigns?token={{ token }}">👆 CPC кампании</a>
        <a href="/my-stats/settings?token={{ token }}">⚙️ Настройки</a>
        <a href="/my-stats/guide?token={{ token }}" class="active">📖 Инструкция</a>
    </div>
    <h1>📖 Инструкция</h1>

    <div class="card">
        <h2>🚀 Быстрый старт</h2>
        <ol>
            <li><b>Добавьте канал</b> — отправьте боту @username вашего Telegram-канала</li>
            <li><b>Назначьте бота администратором</b> канала с правом публикации</li>
            <li><b>Выберите магазины</b> в разделе «🏪 Магазины» в боте</li>
            <li><b>Настройте интервал</b> публикаций в разделе «веб-настройках (⚙️ Настройки)»</li>
            <li><b>Готово!</b> Бот начнёт публиковать товары с партнёрскими ссылками</li>
        </ol>
    </div>

    <div class="card">
        <h2>💰 Как устроен доход</h2>
        <p>Когда подписчик переходит по ссылке и покупает товар:</p>
        <ul>
            <li><b>«В ожидании»</b> — магазин проверяет заказ (30–90 дней)</li>
            <li><b>«Доступно к выводу»</b> — деньги подтверждены</li>
        </ul>
        <p>Вы получаете <b>70%</b> от комиссии за каждую покупку.</p>
    </div>

    <div class="card">
        <h2>💳 Вывод средств</h2>
        <ol>
            <li>Накопите <b>3000 ₽</b> в разделе «Доступно к выводу»</li>
            <li>Оформите статус <b>Самозанятого</b> (бесплатно в приложении «Мой Налог») или <b>ИП</b></li>
            <li>Нажмите «💸 Запросить выплату» на этой странице</li>
            <li>Укажите реквизиты карты</li>
            <li>После получения денег — <b>загрузите чек</b> из «Мой Налог» в течение 24 часов</li>
        </ol>
        <div class="warning">⚠️ Если не загрузить чек за 24 часа — аккаунт будет заблокирован</div>
    </div>

    <div class="card">
        <h2>📊 Отчёт для ОРД (ЕРИР)</h2>
        <p>Раз в месяц вам нужно подавать статистику по рекламным постам в ОРД:</p>
        <ol>
            <li>На странице статистики нажмите <b>«📥 Скачать отчёт»</b></li>
            <li>Загрузите полученный Excel-файл в личный кабинет ОРД (например, VK ОРД)</li>
            <li>Проверьте, что все ERID и показы совпадают</li>
        </ol>
        <div class="success">✅ Бот автоматически собирает просмотры и формирует отчёт</div>
    </div>

    <div class="card">
        <h2>🔗 Реферальная программа</h2>
        <p>Приглашайте других пользователей по реферальной ссылке и получайте <b>10%</b> от их дохода.</p>
        <p>Ссылку можно найти в боте: «🔗 Реферальная ссылка» в личном кабинете.</p>
    </div>

    <div class="card">
        <h2>🛡️ Юридическая информация</h2>
        <ul>
            <li>Все посты содержат обязательную маркировку <b>ERID</b> (ФЗ №38 «О рекламе»)</li>
            <li>Товары без ERID не загружаются в каталог</li>
            <li>Вы самостоятельно несёте ответственность за подачу статистики в ОРД</li>
            <li><a href="https://teletype.in/@miliron/yYN0SEGfm5l" target="_blank">📄 Политика конфиденциальности</a></li>
        </ul>
    </div>

    <div class="card">
        <h2>📞 Поддержка</h2>
        <p>По всем вопросам пишите: <a href="https://t.me/Zigih90" target="_blank">@Zigih90</a></p>
    </div>
</div>
<script>
function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
    document.querySelector('.overlay').classList.toggle('open');
}
</script>
</body>
</html>'''

@router.get("/guide", response_class=HTMLResponse)
async def user_guide(token: str = Query(...)):
    html = GUIDE_TEMPLATE.replace('{{ token }}', token)
    return HTMLResponse(content=html)

# ---------------------------------------------------------------------------
# CPC кампании (веб-редактор)
# ---------------------------------------------------------------------------
CPC_CAMPAIGNS_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CPC кампании</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; max-width: 800px; margin: 0 auto; }
    h1 { color: #ff4444; font-size: 1.5em; margin-bottom: 10px; }
    .nav { margin-bottom: 20px; display: flex; gap: 10px; overflow-x: auto; -webkit-overflow-scrolling: touch; padding-bottom: 5px; }
    .nav a { color: #ff4444; text-decoration: none; padding: 8px 16px; border-radius: 8px; background: #333; white-space: nowrap; flex-shrink: 0; }
    .hamburger { display: none; position: fixed; top: 15px; left: 15px; z-index: 1000; background: #ff4444; color: white; border: none; font-size: 24px; padding: 8px 12px; border-radius: 8px; cursor: pointer; }
    .sidebar { position: fixed; top: 0; left: -280px; width: 260px; height: 100%; background: #222; transition: left 0.3s; z-index: 999; padding: 60px 20px 20px; overflow-y: auto; }
    .sidebar.open { left: 0; }
    .sidebar a { display: block; color: #ccc; padding: 12px 16px; text-decoration: none; border-radius: 8px; margin-bottom: 5px; font-size: 1em; }
    .sidebar a:hover, .sidebar a.active { background: #ff4444; color: #fff; }
    .overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 998; }
    .overlay.open { display: block; }
    @media (max-width: 768px) { .hamburger { display: block; } body { padding: 15px; } }
    .campaign-card { background: #222; border-radius: 12px; padding: 16px; margin-bottom: 16px; display: flex; gap: 16px; align-items: flex-start; }
    .campaign-img { width: 80px; height: 80px; border-radius: 8px; object-fit: contain; background: #333; flex-shrink: 0; }
    .campaign-info { flex: 1; min-width: 0; }
    .campaign-name { font-size: 1.1em; font-weight: bold; color: #ddd; margin-bottom: 4px; }
    .campaign-status { font-size: 0.85em; margin-bottom: 10px; }
    .campaign-status.active { color: #4caf50; }
    .campaign-status.inactive { color: #888; }
    .campaign-textarea { width: 100%; background: #333; border: 1px solid #555; color: #ddd; padding: 10px; border-radius: 8px; font-size: 0.95em; min-height: 80px; margin-bottom: 10px; box-sizing: border-box; resize: vertical; font-family: sans-serif; }
    .campaign-actions { display: flex; gap: 8px; }
    .btn-save { background: #ff4444; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 0.9em; }
    .btn-save:hover { background: #e03333; }
    .btn-toggle { background: #444; color: #ccc; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 0.9em; }
    .btn-toggle:hover { background: #555; }
    .btn-toggle.on { background: #2e7d32; color: #fff; }
    .btn-toggle.off { background: #555; color: #aaa; }
    .success { color: #4caf50; font-size: 0.85em; margin-top: 4px; }
    .no-campaigns { color: #888; text-align: center; padding: 40px; font-size: 1.1em; }
    .campaign-desc { background: #1e1e1e; border-radius: 8px; padding: 12px; margin-bottom: 10px; font-size: 0.9em; color: #aaa; line-height: 1.5; max-height: 200px; overflow-y: auto; }
    .campaign-desc b { color: #ddd; }
    .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 2000; justify-content: center; align-items: center; }
    .modal-overlay.open { display: flex; }
    .modal-box { background: #222; border-radius: 12px; padding: 24px; max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto; color: #ccc; font-size: 0.95em; line-height: 1.6; }
    .modal-box h2 { color: #ff4444; margin-top: 0; font-size: 1.2em; }
    .modal-close { background: #ff4444; color: white; border: none; padding: 8px 20px; border-radius: 6px; cursor: pointer; margin-top: 16px; font-size: 0.9em; }
</style>
</head>
<body>
    <button class="hamburger" onclick="toggleSidebar()">☰</button>
    <div class="overlay" onclick="toggleSidebar()"></div>
    <div class="sidebar">
        <a href="/my-stats?token={{ token }}">📊 Статистика</a>
        <a href="/my-stats/templates?token={{ token }}">📝 Шаблоны</a>
        <a href="/my-stats/cpc-campaigns?token={{ token }}" class="active">👆 CPC кампании</a>
        <a href="/my-stats/settings?token={{ token }}">⚙️ Настройки</a>
        <a href="/my-stats/guide?token={{ token }}">📖 Инструкция</a>
    </div>
    <h1>👆 CPC кампании</h1>
    <p style="color:#aaa;margin-bottom:20px;">Напишите свой рекламный текст для каждой кампании. Пост будет опубликован с логотипом рекламодателя.</p>
    <div id="campaigns-list"></div>
    <div class="modal-overlay" id="rulesModal" onclick="if(event.target===this)closeRulesModal()">
        <div class="modal-box">
            <h2 id="rulesModalTitle">Правила магазина</h2>
            <div id="rulesModalContent" style="white-space:pre-wrap;"></div>
            <button class="modal-close" onclick="closeRulesModal()">Закрыть</button>
        </div>
    </div>
    <script>
    function toggleSidebar() {
        document.querySelector('.sidebar').classList.toggle('open');
        document.querySelector('.overlay').classList.toggle('open');
    }
    async function loadCampaigns() {
        const res = await fetch('/my-stats/cpc-campaigns-data?token={{ token }}');
        const data = await res.json();
        const container = document.getElementById('campaigns-list');
        if (!data.length) {
            container.innerHTML = '<div class="no-campaigns">Нет CPC-кампаний. Подключите рекламодателей в кабинете Admitad.</div>';
            return;
        }
        container.innerHTML = data.map(c => {
            const isActive = c.is_active === 1;
            const statusClass = isActive ? 'active' : 'inactive';
            const statusText = isActive ? '✅ Активна' : '❌ Неактивна';
            const toggleClass = isActive ? 'on' : 'off';
            const toggleText = isActive ? '🔴 Отключить' : '🟢 Включить';
            const imgHtml = c.image_url ? `<img class="campaign-img" src="${c.image_url}" alt="" onerror="this.style.display='none'">` : '<div class="campaign-img"></div>';
            const rulesBtnHtml = (c.more_rules || (c.traffics && c.traffics !== '[]' && c.traffics !== '{}')) ? `<button class="btn-save" style="background:#e67e22;" onclick='openRulesModal(${JSON.stringify(c.name).replace(/'/g,"\\'")}, ${JSON.stringify(c.more_rules||"").replace(/'/g,"\\'")}, ${JSON.stringify(c.traffics||"").replace(/'/g,"\\'")})'>⚠️ Правила</button>` : '';
            return `<div class="campaign-card">
                ${imgHtml}
                <div class="campaign-info">
                    <div class="campaign-name">${c.name}</div>
                    <div class="campaign-status ${statusClass}">${statusText}</div>
                    <div class="campaign-actions">
                        ${rulesBtnHtml}
                        <button class="btn-toggle ${toggleClass}" onclick="toggleCampaign(${c.id}, ${isActive ? 0 : 1})">${toggleText}</button>
                    </div>
                </div>
            </div>`;
        }).join('');
    }
    function openRulesModal(name, rules, traffics) {
        document.getElementById('rulesModalTitle').textContent = '⚠️ Правила: ' + name;
        let html = '';
        if (traffics) {
            try {
                const t = typeof traffics === 'string' ? JSON.parse(traffics) : traffics;
                if (Array.isArray(t) && t.length) {
                    const allowed = t.filter(x => x.enabled).map(x => '✅ ' + x.name);
                    const denied = t.filter(x => !x.enabled).map(x => '❌ ' + x.name);
                    if (denied.length) html += '<b>❌ Запрещено:</b><br>' + denied.join('<br>') + '<br><br>';
                    if (allowed.length) html += '<b>✅ Разрешено:</b><br>' + allowed.join('<br>');
                }
            } catch(e) {}
        }
        if (!html && rules) html = rules;
        if (!html) html = 'Правила не найдены.';
        document.getElementById('rulesModalContent').innerHTML = html;
        document.getElementById('rulesModal').classList.add('open');
    }
    function closeRulesModal() {
        document.getElementById('rulesModal').classList.remove('open');
    }
    async function toggleCampaign(id, newState) {
        const f = new FormData();
        f.append('token', '{{ token }}');
        f.append('campaign_id', id);
        const res = await fetch('/my-stats/toggle-cpc-campaign', { method: 'POST', body: f });
        const data = await res.json();
        if (data.ok) {
            if (data.warning) alert(data.warning);
            loadCampaigns();
        } else if (data.error) {
            alert(data.error);
        }
    }
    loadCampaigns();
    </script>
</body>
</html>'''

@router.get("/cpc-campaigns", response_class=HTMLResponse)
async def cpc_campaigns_page(token: str = Query(...)):
    html = CPC_CAMPAIGNS_TEMPLATE.replace('{{ token }}', token)
    return HTMLResponse(content=html)

@router.get("/cpc-campaigns-data")
async def get_cpc_campaigns_data(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, campaign_id, name, text, image_url, description, rules, more_rules, traffics, is_active, interval_hours, last_posted_at "
            "FROM cpc_campaigns WHERE user_id=? ORDER BY name",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

@router.post("/save-cpc-text")
async def save_cpc_text(token: str = Form(...), campaign_id: int = Form(...), text: str = Form("")):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        conn.execute(
            "UPDATE cpc_campaigns SET text=? WHERE id=? AND user_id=?",
            (text, campaign_id, user_id)
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}

@router.post("/save-cpc-image")
async def save_cpc_image(token: str = Form(...), campaign_id: int = Form(...), image_url: str = Form("")):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        conn.execute(
            "UPDATE cpc_campaigns SET image_url=? WHERE id=? AND user_id=?",
            (image_url, campaign_id, user_id)
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}

@router.post("/save-cpc-rules")
async def save_cpc_rules(token: str = Form(...), campaign_id: int = Form(...), rules: str = Form("")):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        conn.execute(
            "UPDATE cpc_campaigns SET rules=? WHERE id=? AND user_id=?",
            (rules, campaign_id, user_id)
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}

@router.post("/toggle-cpc-campaign")
async def toggle_cpc_campaign(token: str = Form(...), campaign_id: int = Form(...)):
    user_id = get_user_id_from_token(token)
    conn = get_db()
    try:
        user = conn.execute("SELECT cpc_banned, cpc_warned FROM users WHERE user_id=?", (user_id,)).fetchone()
        if user and user["cpc_banned"]:
            return {"ok": False, "error": "❌ CPC заблокирован для вашего аккаунта. Обратитесь к администратору."}

        row = conn.execute(
            "SELECT is_active FROM cpc_campaigns WHERE id=? AND user_id=?",
            (campaign_id, user_id)
        ).fetchone()
        if row:
            new_val = 0 if row["is_active"] else 1
            if new_val == 1 and user and not user["cpc_warned"]:
                conn.execute("UPDATE users SET cpc_warned=1 WHERE user_id=?", (user_id,))
                conn.execute(
                    "UPDATE cpc_campaigns SET is_active=? WHERE id=? AND user_id=?",
                    (new_val, campaign_id, user_id)
                )
                conn.commit()
                return {"ok": True, "warning": "⚠️ Вы несёте ответственность за маркировку рекламы (ФЗ-38). Штрафы: физлица до 80 000₽, юрлица до 500 000₽."}

            conn.execute(
                "UPDATE cpc_campaigns SET is_active=? WHERE id=? AND user_id=?",
                (new_val, campaign_id, user_id)
            )
            conn.commit()
    finally:
        conn.close()
    return {"ok": True}
