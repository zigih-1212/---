# webapp/routes_user.py
import os
from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, BaseLoader, TemplateNotFound
from services.db import get_db
from webapp.auth import get_user_id_from_token
from datetime import datetime, timedelta, timezone

router = APIRouter()

CSS_CONTENT = '''body.dark-theme { background-color: #1a1a1a; color: #ccc; font-family: sans-serif; margin: 0; padding: 0; }
.container { max-width: 1200px; margin: auto; padding: 20px; }
h1 { color: #ff4444; }

USER_STATS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Моя статистика{% endblock %}
{% block content %}
<h1>📊 Статистика</h1>
<div>
    <canvas id="postsChart" width="400" height="200"></canvas>
</div>
<div id="balance-info">Загрузка...</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
(async function() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    if (!token) { document.body.innerHTML = 'Токен не указан'; return; }

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
})();
</script>
{% endblock %}'''

# Чтобы работал extends "base.html", дадим ему определение из админского словаря
BASE_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}AutoPost Bot{% endblock %}</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body class="dark-theme">
    <nav>
        <a href="/admin/dashboard">Админ-панель</a> |
        <a href="/admin/broadcast">Рассылка</a> |
        <a href="/admin/promocodes">Промокоды</a> |
        <a href="/admin/store_delivery">Доставка</a> |
        <a href="/admin/logout" style="color: #ff4444;">Выйти</a>
    </nav>
    <div class="container">
        {% block content %}{% endblock %}
    </div>
</body>
</html>'''

class DictLoader(BaseLoader):
    def __init__(self, mapping):
        self.mapping = mapping
    def get_source(self, environment, template):
        if template not in self.mapping:
            raise TemplateNotFound(template)
        return self.mapping[template], None, lambda: True

env = Environment(loader=DictLoader({"base.html": BASE_TEMPLATE, "user_stats.html": USER_STATS_TEMPLATE}))

@router.get("/", response_class=HTMLResponse)
async def user_stats_page(token: str = Query(...)):
    get_user_id_from_token(token)  # проверим токен
    return HTMLResponse(env.get_template("user_stats.html").render(token=token))

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
