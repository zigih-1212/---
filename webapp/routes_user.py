# webapp/routes_user.py — полная актуальная версия

import os
import uuid
import csv
import io
import logging
import xlsxwriter
from io import BytesIO
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

# ------------------------------------------------------------------------------
# Шаблон главной страницы статистики
# ------------------------------------------------------------------------------
USER_STATS_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Моя статистика</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; }
    h1 { color: #ff4444; }
    .nav { margin-bottom: 20px; display: flex; gap: 15px; }
    .nav a { color: #ff4444; text-decoration: none; padding: 8px 16px; border-radius: 8px; background: #333; }
    .nav a.active { background: #ff4444; color: #fff; }
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
    <div class="nav">
        <a href="/my-stats?token={{ token }}" class="active">📊 Статистика</a>
        <a href="/my-stats/templates?token={{ token }}">📝 Шаблоны</a>
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

    <div class="card">
        <h2>📄 Отчёт для ОРД</h2>
        <p style="margin-bottom:10px;">Скачайте CSV-файл со всеми публикациями и количеством просмотров для подачи в ЕРИР.</p>
        <a id="ord-report-link" href="#" class="btn">📥 Скачать отчёт (CSV)</a>
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
        <table id="channels-table">
            <tr><th>Канал</th><th>Постов</th><th>Кликов</th><th>Продаж</th><th>Доход</th><th>Конверсия</th></tr>
        </table>
    </div>
    <div class="card">
        <h2>🏆 Топ-5 товаров по публикациям</h2>
        <ol id="top-products"></ol>
    </div>

    <!-- Бета-функция: предпросмотр поста (скрыта по умолчанию) -->
    <div id="preview-block" style="display: none;">
        <div class="card">
            <h2>👀 Предпросмотр поста (бета)</h2>
            <div style="display:flex; gap:10px; margin-bottom:15px; flex-wrap:wrap;">
                <button onclick="loadPreview()" class="btn">🎲 Случайный товар</button>
                <button onclick="publishPost()" class="btn" style="background: #4caf50;">🚀 Опубликовать в канал</button>
                <button onclick="document.getElementById('preview-content').innerHTML = ''; window._currentProductId = null;" class="btn" style="background: #555;">🧹 Очистить</button>
            </div>
            <div id="preview-container" style="background: #1e1e1e; border-radius: 12px; padding: 20px; border: 1px solid #333;">
                <div id="preview-content" style="color: #ccc; text-align: center; padding: 40px 20px;">
                    Нажмите «Случайный товар» для предпросмотра
                </div>
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
(function() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (!token) { document.body.innerHTML = 'Токен не указан'; return; }

    let currentPeriod = '30d';
    let postsChart, revenueChart, clicksChart, storeChart;

    document.getElementById('ord-report-link').href = `/my-stats/ord-report?token=${token}`;

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

        // ===== НОВЫЙ БЛОК: Таблица последних постов для ОРД =====
        const postsTableBody = document.querySelector('#recent-posts-table tbody');
        if (!postsTableBody) {
            const card = document.querySelector('.card:last-child')?.parentElement;
            if (card) {
                const newCard = document.createElement('div');
                newCard.className = 'card';
                newCard.innerHTML = `
                    <h2>📋 Последние посты для ОРД</h2>
                    <div style="overflow-x: auto;">
                        <table id="recent-posts-table">
                            <thead>
                                <tr><th>ERID</th><th>Ссылка</th><th>Показы</th><th>Дата</th></tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                    </div>
                `;
                card.appendChild(newCard);
            }
        }

        const postsTable = document.querySelector('#recent-posts-table tbody');
        if (postsTable) {
            postsTable.innerHTML = '';
            if (data.recent_posts && data.recent_posts.length > 0) {
                data.recent_posts.forEach(p => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td><code style="font-size:12px;">${p.erid || '—'}</code></td>
                        <td><a href="${p.link || '#'}" target="_blank" style="color: #4d6bfe;">Перейти</a></td>
                        <td>${p.views || 0}</td>
                        <td>${p.date ? new Date(p.date).toLocaleDateString('ru-RU') : '—'}</td>
                    `;
                    postsTable.appendChild(tr);
                });
            } else {
                postsTable.innerHTML = '<tr><td colspan="4" style="text-align:center; color:#888;">Нет постов с ERID</td></tr>';
            }
        }
        // ===== КОНЕЦ НОВОГО БЛОКА =====
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

    // ===== БЕТА-ФУНКЦИЯ: ПРЕДПРОСМОТР ПОСТА =====
    const isBeta = {{ is_beta }};
    if (isBeta) {
        const previewBlock = document.getElementById('preview-block');
        if (previewBlock) {
            previewBlock.style.display = 'block';
        }
    }

    window.loadPreview = async function(productId = null) {
        const container = document.getElementById('preview-content');
        if (!container) return;
        container.innerHTML = '<div style="text-align:center; padding:20px;">⏳ Загрузка...</div>';
        
        try {
            let url = `/my-stats/preview-post?token=${token}`;
            if (productId) url += `&product_id=${productId}`;
            
            const resp = await fetch(url);
            const data = await resp.json();
            
            if (!data.ok) {
                container.innerHTML = `<div style="text-align:center; padding:20px; color:#ff4444;">❌ ${data.error}</div>`;
                return;
            }
            
            const adultBadge = data.source === 'Розовый кролик' 
                ? '<div style="background:#ff4444; color:#fff; padding:4px 12px; border-radius:12px; font-size:12px; display:inline-block; margin-bottom:8px;">🔞 18+</div>' 
                : '';
            
            const imageHtml = data.image_url 
                ? `<div style="margin-bottom:12px;"><img src="${data.image_url}" style="max-width:100%; max-height:300px; border-radius:8px; object-fit:contain; background:#111;" onerror="this.style.display='none'"></div>` 
                : '';
            
            container.innerHTML = `
                <div style="background: #0f0f0f; border-radius:12px; padding:16px; max-width:500px; margin:0 auto; text-align:left; border:1px solid #2a2a2a;">
                    ${adultBadge}
                    ${imageHtml}
                    <div style="font-size:14px; line-height:1.6; word-wrap:break-word; white-space:pre-wrap;">
                        ${data.caption.replace(/\n/g, '<br>')}
                    </div>
                    <div style="margin-top:12px; padding-top:12px; border-top:1px solid #2a2a2a; font-size:12px; color:#888;">
                        <span style="color:#4d6bfe;">💡 Нажмите «Опубликовать в канал», чтобы отправить этот пост</span>
                    </div>
                </div>
            `;
            
            window._currentProductId = data.product_id;
            window._currentPartnerUrl = data.partner_url;
            
        } catch (e) {
            container.innerHTML = `<div style="text-align:center; padding:20px; color:#ff4444;">❌ Ошибка загрузки: ${e.message}</div>`;
        }
    };

window.publishPost = async function() {
    if (!window._currentProductId) {
        alert('Сначала загрузите предпросмотр!');
        return;
    }

    if (!confirm('Опубликовать этот пост в ваш канал?')) return;

    const container = document.getElementById('preview-content');
    if (!container) return;
    container.innerHTML = '<div style="text-align:center; padding:20px;">⏳ Публикация...</div>';

    try {
        const formData = new FormData();
        formData.append('token', token);
        formData.append('product_id', window._currentProductId);

        const resp = await fetch('/my-stats/publish-post', { method: 'POST', body: formData });
        const result = await resp.json();

        if (result.ok) {
            container.innerHTML = `
                <div style="text-align:center; padding:20px; color:#4caf50;">
                    ✅ Пост опубликован в канал!
                </div>
                <div style="text-align:center; padding:10px; font-size:12px; color:#888;">
                    Кнопки предпросмотра временно скрыты. Загрузите новый товар.
                </div>
            `;
            window._currentProductId = null;
        } else {
            container.innerHTML = `<div style="text-align:center; padding:20px; color:#ff4444;">❌ Ошибка: ${result.error}</div>`;
        }
    } catch (e) {
        container.innerHTML = `<div style="text-align:center; padding:20px; color:#ff4444;">❌ Ошибка публикации: ${e.message}</div>`;
    }
};
    // ===== КОНЕЦ БЕТА-ФУНКЦИИ =====

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

# ------------------------------------------------------------------------------
# Шаблон редактора шаблонов (с учётом роли)
# ------------------------------------------------------------------------------
TEMPLATES_PAGE_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Шаблоны постов</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; }
    h1 { color: #ff4444; }
    .nav { margin-bottom: 20px; display: flex; gap: 15px; }
    .nav a { color: #ff4444; text-decoration: none; padding: 8px 16px; border-radius: 8px; background: #333; }
    .nav a.active { background: #ff4444; color: #fff; }
    .tabs { display: flex; gap: 10px; margin-bottom: 20px; }
    .tabs button { background: #333; color: #ccc; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; }
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
</style>
</head>
<body>
<div class="container">
    <div class="nav">
        <a href="/my-stats?token={{ token }}">📊 Статистика</a>
        <a href="/my-stats/templates?token={{ token }}" class="active">📝 Шаблоны</a>
    </div>
    <h1>📝 Шаблоны постов</h1>
    <div class="tabs">
        <button id="tab-product" class="active" onclick="switchTab('product')">Товарный</button>
        <button id="tab-video" onclick="switchTab('video')">Видео</button>
    </div>

    <div id="tab-product-content" class="editor-panel">
        <div class="editor">
            <textarea id="product-template" placeholder="Введите шаблон..."></textarea>
            <div class="actions">
                <button onclick="saveTemplate('product')">Сохранить</button>
                <button onclick="resetTemplate('product')">Сбросить</button>
                <button onclick="previewRealProduct()">Предпросмотр с товаром</button>
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
    <div class="preview-box">
        <h3>Предпросмотр</h3>
        <div id="preview-content"></div>
    </div>
</div>

<script>
const token = "{{ token }}";
const role = "{{ role }}";   // "saas" или "blogger"
const isSaaS = (role === "saas");
let currentTab = 'product';

const placeholders = {
    product: ['{title}', '{price}', '{currency}', '{link}', '{advertiser}', '{erid}', '{old_price}', '{discount_percent}', '{delivery_line}', '{promocode_line}', '{price_label}', '{cta_phrase}'],
    video: ['{title}', '{link}', '{description}']
};
const defaultProduct = `🔥 <b>{title}</b>\n\n💰 {price_label}: {price} {currency}{discount_line}\n👉 {link}\n{promocode_line}{delivery_line}\n{cta_phrase}\n\nРеклама. {advertiser}. Erid: {erid}`;
const defaultVideo = `🎬 <b>{title}</b>\n\n{description}\n\n🔗 <a href='{link}'>Смотреть</a>`;

if (isSaaS) {
    // Скрываем вкладку видео
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
        renderPlaceholders('product');
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
    const template = document.getElementById(`${currentTab}-template`).value;
    const preview = document.getElementById('preview-content');
    if (currentTab === 'product') {
        const testData = {
            title: 'Пример товара',
            price: '1990',
            currency: '₽',
            link: '<a href="#">Посмотреть</a>',
            advertiser: 'Магазин',
            erid: 'erid:XXX',
            old_price: '2990',
            discount_percent: '33',
            discount_line: '\n🔥 Скидка 33%',
            delivery_line: '\n🚚 Бесплатная доставка',
            promocode_line: '\n🎟 Промокод: SALE',
            price_label: 'Цена',
            cta_phrase: '🔥 Количество товара по акции ограничено!'
        };
        preview.innerHTML = template.replace(/\{(\w+)\}/g, (match, key) => testData[key] || match);
    } else {
        const testData = {
            title: 'Моё видео',
            link: 'https://youtube.com/...',
            description: 'Описание ролика'
        };
        preview.innerHTML = template.replace(/\{(\w+)\}/g, (match, key) => testData[key] || match);
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
    const def = type === 'product' ? defaultProduct : defaultVideo;
    document.getElementById(`${type}-template`).value = def;
    updatePreview();
}

async function previewRealProduct() {
    const container = document.getElementById('preview-content');
    if (!container) return;
    container.innerHTML = '<div style="text-align:center; padding:20px;">⏳ Загрузка...</div>';
    try {
        const formData = new FormData();
        formData.append('token', token);
        formData.append('template', document.getElementById('product-template').value);

        const resp = await fetch('/my-stats/preview-post', { method: 'POST', body: formData });
        const data = await resp.json();

        if (!data.ok) {
            container.innerHTML = `<div style="text-align:center; padding:20px; color:#ff4444;">❌ ${data.error}</div>`;
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
    } catch (e) {
        container.innerHTML = `<div style="text-align:center; padding:20px; color:#ff4444;">❌ Ошибка загрузки: ${e.message}</div>`;
    }
}

function switchTab(tab) {
    currentTab = tab;
    document.getElementById('tab-product').classList.toggle('active', tab === 'product');
    document.getElementById('tab-video').classList.toggle('active', tab === 'video');
    document.getElementById('tab-product-content').style.display = tab === 'product' ? 'flex' : 'none';
    document.getElementById('tab-video-content').style.display = tab === 'video' ? 'flex' : 'none';
    updatePreview();
}

document.getElementById('product-template').addEventListener('input', updatePreview);
document.getElementById('video-template').addEventListener('input', updatePreview);

loadTemplates();
</script>
</body>
</html>'''

# ------------------------------------------------------------------------------
# Эндпоинты
# ------------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def user_stats_page(token: str = Query(...)):
    user_id = get_user_id_from_token(token)
    preview_available = is_feature_enabled(user_id, "preview_post")

    html = USER_STATS_TEMPLATE.replace('{{ token }}', token)
    html = html.replace('{{ is_beta }}', 'true' if preview_available else 'false')
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
        recent_posts = conn.execute("""SELECT erid, direct_link, views_count, published_at FROM posts WHERE user_id = ? AND status = 'published' AND erid IS NOT NULL AND erid != ''ORDER BY published_at DESC LIMIT 20""", (user_id,)).fetchall()
        return JSONResponse({
            "posts_labels": [r["day"] for r in post_rows],
            "posts_counts": [r["count"] for r in post_rows],
            "revenue_labels": [r["day"] for r in revenue_rows],
            "revenue_values": [r["total"] for r in revenue_rows],
            "clicks_labels": all_days,
            "clicks_counts": clicks_counts,
            "conversion_labels": all_days,
            "recent_posts": [{"erid": p["erid"],"link": p["direct_link"],"views": p["views_count"] or 0,"date": p["published_at"]} for p in recent_posts],
            "conversion_values": conversion_values,
            "store_labels": [r["source"] or "Без названия" for r in store_rows],
            "store_values": [r["cnt"] for r in store_rows],
            "balance_available": balance["balance_available"] if balance else 0,
            "balance_pending": balance["balance_pending"] if balance else 0,
            "total_posts": total_posts,
            "total_revenue": total_revenue,
            "channels": [{"title": r["channel_title"] or r["channel_id"], "posts": r["posts_cnt"], "clicks": r["clicks"], "leads": r["leads"], "earnings": r["earnings"], "conversion": round(r["leads"] / r["clicks"] * 100, 1) if r["clicks"] > 0 else 0} for r in channel_rows],
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
    full_path = os.path.join(UPLOAD_DIR, path)
    if not os.path.exists(full_path):
        return HTMLResponse("Файл не найден", status_code=404)
    return FileResponse(full_path)

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
        user = conn.execute("SELECT product_template, video_template FROM users WHERE user_id=?", (user_id,)).fetchone()
        return JSONResponse({"product_template": user["product_template"] if user else "", "video_template": user["video_template"] if user else ""})
    finally:
        conn.close()

@router.post("/save-template")
async def save_template(token: str = Form(...), type: str = Form(...), template: str = Form(...)):
    user_id = get_user_id_from_token(token)
    if type not in ("product", "video"):
        return JSONResponse({"ok": False})
    column = "product_template" if type == "product" else "video_template"
    conn = get_db()
    try:
        conn.execute(f"UPDATE users SET {column}=? WHERE user_id=?", (template, user_id))
        conn.commit()
        return JSONResponse({"ok": True})
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
        else:
            return JSONResponse({"html": "Предпросмотр видео пока недоступен"})
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
                    conn.execute(
                        """INSERT INTO posts 
                        (user_id, donor_post_id, channel_id, target_channel_id, subid1, subid2, direct_link, erid, status, published_at, caption)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?)""",
                        (user_id, donor_post_id, ch['channel_id'], ch['channel_id'], ch['sub_id'], subid2, direct_link,
                         product["erid"], datetime.now(timezone.utc).isoformat(), caption)
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
    user_id = get_user_id_from_token(token)
    
    # Логирование для отладки
    logger.info(f"Запрос отчёта ОРД для user_id={user_id}")
    
    # Сбор просмотров из Telegram
    bot = request.app.state.bot
    await collect_views_for_user(user_id, bot)
    
    conn = get_db()
    try:
        posts = conn.execute("""
            SELECT p.published_at, p.erid, p.views_count, p.direct_link 
            FROM posts p 
            WHERE p.user_id = ? AND p.status = 'published' AND p.erid IS NOT NULL AND p.erid != ''
            ORDER BY p.published_at DESC
        """, (user_id,)).fetchall()
        
        logger.info(f"Найдено {len(posts)} постов для отчёта")
    finally:
        conn.close()

    if not posts:
        # Возвращаем Excel только с заголовками, но с уведомлением
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("ORD")
        headers = ["erid", "Площадка", "Тип площадки", "Количество показов", "Количество переходов", "Сумма потраченная", "Дата начала", "Дата окончания"]
        for col, header in enumerate(headers):
            worksheet.write(0, col, header)
        worksheet.set_column(0, 0, 30)
        workbook.close()
        output.seek(0)
        filename = f"VK_ORD_Report_{user_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    # Создаём Excel-файл с данными
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet("ORD")

    headers = ["erid", "Площадка", "Тип площадки", "Количество показов", "Количество переходов", "Сумма потраченная", "Дата начала", "Дата окончания"]
    for col, header in enumerate(headers):
        worksheet.write(0, col, header)

    row = 1
    for p in posts:
        erid = p["erid"]
        link = p["direct_link"] or ""
        views = p["views_count"] or 0
        
        try:
            pub_date = datetime.fromisoformat(p["published_at"].replace("Z", "+00:00"))
            date_str = pub_date.strftime("%d.%m.%Y")
        except Exception:
            date_str = ""

        worksheet.write(row, 0, erid)
        worksheet.write(row, 1, link)
        worksheet.write(row, 2, "Сайт/Приложение")
        worksheet.write(row, 3, views)
        worksheet.write(row, 4, 0)
        worksheet.write(row, 5, 0)
        worksheet.write(row, 6, date_str)
        worksheet.write(row, 7, "")
        row += 1

    worksheet.set_column(0, 0, 30)
    worksheet.set_column(1, 1, 50)
    workbook.close()
    output.seek(0)

    filename = f"VK_ORD_Report_{user_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
