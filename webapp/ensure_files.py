# webapp/ensure_files.py
import os

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')
STATIC_CSS_DIR = os.path.join(os.path.dirname(__file__), 'static', 'css')

FILES = {
    'templates/base.html': r'''<!DOCTYPE html>
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
</html>''',
    'templates/login.html': r'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Вход в админку</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body class="dark-theme">
    <div class="container">
        <h1>Вход</h1>
        {% if error %}<p class="error">{{ error }}</p>{% endif %}
        <form method="post" action="/admin/login">
            <input type="text" name="username" placeholder="Логин" required><br>
            <input type="password" name="password" placeholder="Пароль" required><br>
            <button type="submit">Войти</button>
        </form>
    </div>
</body>
</html>''',
    'templates/admin_dashboard.html': r'''{% extends "base.html" %}
{% block title %}Дашборд{% endblock %}
{% block content %}
<h1>Общая статистика</h1>
<ul>
    <li>SaaS клиентов: {{ saas }}</li>
    <li>Блогеров: {{ bloggers }}</li>
    <li>Постов опубликовано: {{ posts }}</li>
    <li>Транзакций: {{ tx }}</li>
    <li>Баланс пользователей: {{ balance }} ₽</li>
</ul>
{% endblock %}''',
    'templates/admin_broadcast.html': r'''{% extends "base.html" %}
{% block title %}Рассылка{% endblock %}
{% block content %}
<h1>📣 Массовая рассылка</h1>
{% if message %}<p style="color: lightgreen;">{{ message }}</p>{% endif %}
<form method="post" action="/admin/broadcast">
    <textarea name="text" rows="5" placeholder="Текст сообщения..." required></textarea><br>
    <select name="role">
        <option value="all">Всем пользователям</option>
        <option value="saas">Только SaaS</option>
        <option value="blogger">Только блогерам</option>
    </select><br>
    <button type="submit">Отправить</button>
</form>
{% endblock %}''',
    'templates/admin_promocodes.html': r'''{% extends "base.html" %}
{% block title %}Управление промокодами{% endblock %}
{% block content %}
<h1>🎟 Промокоды</h1>
<h2>Добавить</h2>
<form method="post" action="/admin/promocodes/add">
    <input name="store" placeholder="Магазин (название)" required>
    <input name="promocode" placeholder="Промокод" required>
    <input name="description" placeholder="Описание (необязательно)">
    <button type="submit">Добавить</button>
</form>
<h2>Список</h2>
<table>
    <tr><th>Магазин</th><th>Промокод</th><th>Описание</th><th></th></tr>
    {% for p in promos %}
    <tr>
        <td>{{ p['store'] }}</td>
        <td><code>{{ p['promocode'] }}</code></td>
        <td>{{ p['description'] or '' }}</td>
        <td><a href="/admin/promocodes/delete/{{ p['id'] }}" style="color:red;">Удалить</a></td>
    </tr>
    {% endfor %}
</table>
{% endblock %}''',
    'templates/admin_store_delivery.html': r'''{% extends "base.html" %}
{% block title %}Информация о доставке{% endblock %}
{% block content %}
<h1>🚚 Доставка</h1>
<h2>Обновить данные</h2>
<form method="post" action="/admin/store_delivery/update">
    <input name="store" placeholder="Магазин" required>
    <input name="delivery_text" placeholder="Условия доставки" required>
    <button type="submit">Сохранить</button>
</form>
<h2>Текущие данные</h2>
<table>
    <tr><th>Магазин</th><th>Условия</th></tr>
    {% for d in deliveries %}
    <tr>
        <td>{{ d['store'] }}</td>
        <td>{{ d['delivery_text'] }}</td>
    </tr>
    {% endfor %}
</table>
{% endblock %}''',
    'templates/user_stats.html': r'''{% extends "base.html" %}
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
{% endblock %}''',
    'static/css/style.css': r'''body.dark-theme {
    background-color: #1a1a1a;
    color: #ccc;
    font-family: sans-serif;
    margin: 0;
    padding: 0;
}
nav {
    background: #111;
    padding: 10px;
}
nav a {
    color: #ff4444;
    margin-right: 15px;
    text-decoration: none;
}
nav a:hover {
    text-decoration: underline;
}
.container {
    max-width: 1200px;
    margin: auto;
    padding: 20px;
}
button {
    background: #ff4444;
    color: #fff;
    border: none;
    padding: 8px 16px;
    cursor: pointer;
    border-radius: 4px;
}
input, textarea, select {
    background: #333;
    color: #ccc;
    border: 1px solid #555;
    padding: 5px;
    margin: 5px 0;
    border-radius: 3px;
}
.error {
    color: #ff4444;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10px;
}
th, td {
    padding: 5px;
    border-bottom: 1px solid #333;
    text-align: left;
}
th {
    background: #222;
}
'''
}

def ensure_files():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    os.makedirs(STATIC_CSS_DIR, exist_ok=True)
    for rel_path, content in FILES.items():
        full_path = os.path.join(os.path.dirname(__file__), rel_path)
        if not os.path.exists(full_path):
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content.strip())
