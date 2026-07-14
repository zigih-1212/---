# webapp/templates.py

# ---------- CSS (общий) ----------
CSS_CONTENT = '''
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #1a1a1a; color: #e0e0e0; display: flex; min-height: 100vh; }
.sidebar { width: 260px; background: #111; padding: 30px 20px; display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
.sidebar a { color: #bbb; text-decoration: none; padding: 12px 16px; border-radius: 8px; font-weight: 500; transition: all 0.2s; }
.sidebar a:hover, .sidebar a.active { background: #ff4444; color: #fff; }
.main-content { flex: 1; padding: 40px; overflow-y: auto; }
.card { background: #222; border-radius: 16px; padding: 30px; margin-bottom: 30px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
h1 { color: #ff4444; margin-bottom: 20px; font-size: 2em; }
h2 { color: #ddd; margin: 20px 0 10px; font-size: 1.5em; }
button, .btn { background: #ff4444; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-size: 1em; cursor: pointer; transition: background 0.2s; text-decoration: none; display: inline-block; }
button:hover, .btn:hover { background: #e03333; }
input, textarea, select { background: #333; border: 1px solid #555; color: #ddd; padding: 12px; border-radius: 8px; width: 100%; margin-bottom: 15px; font-size: 1em; }
table { width: 100%; border-collapse: collapse; margin-top: 20px; }
th, td { padding: 12px; border-bottom: 1px solid #333; text-align: left; }
th { background: #2a2a2a; color: #ff4444; }
tr:hover { background: #2a2a2a; }
.error { color: #ff4444; margin-bottom: 15px; }
.success { color: #4caf50; margin-bottom: 15px; }
.top-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
.logout { background: transparent; border: 1px solid #ff4444; color: #ff4444; padding: 8px 20px; }
.logout:hover { background: #ff4444; color: #fff; }
.badge { background: #ff4444; color: #fff; border-radius: 12px; padding: 2px 10px; font-size: 0.9em; }
'''

# ---------- BASE ----------
BASE_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{% block title %}AutoPost Bot{% endblock %}</title>
<style>''' + CSS_CONTENT + '''</style></head>
<body>
<div class="sidebar">
    <h2 style="color:#ff4444; margin-bottom:20px;">⚡ AutoPost</h2>
    <a href="/admin/dashboard" class="{{ 'active' if active_page == 'dashboard' }}">📊 Дашборд</a>
    <a href="/admin/users" class="{{ 'active' if active_page == 'users' }}">👥 Пользователи</a>
    <a href="/admin/posts" class="{{ 'active' if active_page == 'posts' }}">📬 Посты</a>
    <a href="/admin/quarantine" class="{{ 'active' if active_page == 'quarantine' }}">🚨 Карантин</a>
    <a href="/admin/tariffs" class="{{ 'active' if active_page == 'tariffs' }}">💎 Тарифы</a>
    <a href="/admin/promocodes" class="{{ 'active' if active_page == 'promocodes' }}">🎟 Купоны</a>
    <a href="/admin/store_delivery" class="{{ 'active' if active_page == 'delivery' }}">🚚 Доставка</a>
    <a href="/admin/test_promocodes" class="{{ 'active' if active_page == 'test_promo' }}">🎁 Промокоды (тест)</a>
    <a href="/admin/broadcast" class="{{ 'active' if active_page == 'broadcast' }}">📣 Рассылка</a>
    <a href="/admin/payouts" class="{{ 'active' if active_page == 'payouts' }}">💰 Выплаты</a>
    <a href="/admin/bulk-actions" class="{{ 'active' if active_page == 'bulk' }}">👥 Массовые действия</a>
    <a href="/admin/settings-edit" class="{{ 'active' if active_page == 'settings' }}">⚙️ Настройки</a>
    <a href="/admin/audit" class="{{ 'active' if active_page == 'audit' }}">📜 Аудит</a>
    <a href="/admin/reports" class="{{ 'active' if active_page == 'reports' }}">📁 Отчёты</a>
    <a href="/admin/logout" class="logout">Выйти</a>
</div>
<div class="main-content">
    {% block content %}{% endblock %}
</div>
</body>
</html>'''

ADMIN_PAYOUTS_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Выплаты{% endblock %}
{% block content %}
<h1>💰 Выплаты</h1>
<div style="display: flex; gap: 20px;">
    <div style="flex: 1; overflow-x: auto;">
        <h2>Запросы</h2>
        <table>
            <tr><th>ID</th><th>Польз.</th><th>Сумма</th><th>Статус</th><th></th></tr>
            {% for r in requests %}
            <tr>
                <td>{{ r['id'] }}</td>
                <td>{{ r['user_id'] }}</td>
                <td>{{ r['amount'] }} ₽</td>
                <td>{{ r['status'] }}</td>
                <td><button onclick="loadChat({{ r['id'] }})">Чат</button></td>
            </tr>
            {% endfor %}
        </table>
        <h2>Быстрые выплаты</h2>
        <table>
            <tr><th>ID</th><th>Роль</th><th>Доступно</th><th></th></tr>
            {% for u in users %}
            <tr>
                <td>{{ u['user_id'] }}</td>
                <td>{{ u['role'] }}</td>
                <td>{{ u['balance_available'] }} ₽</td>
                <td>
                    <form method="post" action="/admin/payouts/pay" style="display:inline;">
                        <input type="hidden" name="user_id" value="{{ u['user_id'] }}">
                        <input type="number" name="amount" value="{{ u['balance_available'] }}" step="0.01" style="width:100px;">
                        <button type="submit">Выплатить</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>
    <div id="chat-container" style="flex: 1; display: none; background: #1e1e1e; border-radius: 10px; padding: 15px;">
        <h3>Чат по заявке #<span id="chat-request-id"></span></h3>
        <div id="chat-messages" style="max-height: 400px; overflow-y: auto; margin: 10px 0;"></div>
        <div style="display: flex; gap: 5px;">
            <input type="text" id="admin-chat-input" placeholder="Сообщение..." style="flex:1;">
            <button onclick="sendAdminMessage()">Отправить</button>
        </div>
        <div style="margin-top: 10px;">
            <button onclick="sendMoney()" id="send-money-btn" style="display:none;">💸 Деньги отправлены</button>
            <button onclick="declineRequest()" id="decline-btn" style="display:none;">❌ Отклонить</button>
            <button onclick="confirmReceipt()" id="confirm-btn" style="display:none;">✅ Подтвердить чек</button>
        </div>
    </div>
</div>

<script>
let currentRequestId = null;
let currentStatus = '';

async function loadChat(requestId) {
    currentRequestId = requestId;
    document.getElementById('chat-container').style.display = 'block';
    document.getElementById('chat-request-id').textContent = requestId;
    const resp = await fetch(`/admin/payouts/${requestId}/chat`);
    const messages = await resp.json();
    const chatDiv = document.getElementById('chat-messages');
    chatDiv.innerHTML = messages.map(m => {
        const side = m.sender_role === 'admin' ? 'admin' : 'user';
        const text = m.message || (m.file_path ? `<a href="/admin/receipt-file?path=${encodeURIComponent(m.file_path)}" target="_blank">📎 Чек</a>` : '');
        return `<div style="text-align:${side==='admin'?'right':'left'}; color:${side==='admin'?'#ff9800':'#4caf50'}">${text}<br><small>${m.created_at}</small></div>`;
    }).join('');
    chatDiv.scrollTop = chatDiv.scrollHeight;

    // Узнаем статус заявки и покажем нужные кнопки
    const statusResp = await fetch(`/admin/payouts/${requestId}/status`);
    const statusData = await statusResp.json();
    currentStatus = statusData.status;
    document.getElementById('send-money-btn').style.display = (currentStatus === 'processing') ? 'inline-block' : 'none';
    document.getElementById('decline-btn').style.display = (currentStatus !== 'completed') ? 'inline-block' : 'none';
    document.getElementById('confirm-btn').style.display = (currentStatus === 'receipt_uploaded') ? 'inline-block' : 'none';
}

async function sendAdminMessage() {
    if (!currentRequestId) return;
    const text = document.getElementById('admin-chat-input').value;
    if (!text) return;
    const formData = new FormData();
    formData.append('message', text);
    await fetch(`/admin/payouts/${currentRequestId}/send-message`, {method: 'POST', body: formData});
    document.getElementById('admin-chat-input').value = '';
    loadChat(currentRequestId);
}

async function sendMoney() {
    await fetch(`/admin/payouts/request/${currentRequestId}/send-money`, {method: 'POST'});
    loadChat(currentRequestId);
}
async function declineRequest() {
    await fetch(`/admin/payouts/request/${currentRequestId}/decline`, {method: 'POST'});
    loadChat(currentRequestId);
}
async function confirmReceipt() {
    await fetch(`/admin/payouts/request/${currentRequestId}/confirm-receipt`, {method: 'POST'});
    loadChat(currentRequestId);
}
</script>
{% endblock %}'''
# ---------- LOGIN ----------
LOGIN_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>Вход в админку</title>
<style>''' + CSS_CONTENT + '''</style></head>
<body style="justify-content:center; align-items:center; background:#1a1a1a;">
<div class="card" style="width:400px; text-align:center;">
    <h1>⚡ AutoPost</h1>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <p style="margin-bottom:20px;">Войдите по одноразовой ссылке из бота (<code>/admin</code>)</p>
</div>
</body>
</html>'''

# ---------- DASHBOARD ----------
DASHBOARD_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Дашборд{% endblock %}
{% block content %}
<div class="top-bar"><h1>📊 Дашборд</h1></div>

<!-- Текстовые метрики (прежние) -->
<div class="card">
    <h2>Ключевые метрики</h2>
    <table>
        <tr><td>SaaS активных</td><td><strong>{{ active_saas }}</strong></td></tr>
        <tr><td>Постов сегодня</td><td><strong>{{ posts_today }}</strong></td></tr>
        <tr><td>Постов за неделю</td><td><strong>{{ posts_week }}</strong></td></tr>
        <tr><td>Ошибок сегодня</td><td><strong>{{ errors_today }}</strong></td></tr>
        <tr><td>Ожидающих выплат</td><td><strong>{{ pending_payouts }}</strong></td></tr>
    </table>
</div>

<!-- Графики -->
<div class="card">
    <h2>Посты за 30 дней</h2>
    <canvas id="postsChart" width="400" height="200"></canvas>
</div>
<div class="card">
    <h2>Доход за 30 дней</h2>
    <canvas id="revenueChart" width="400" height="200"></canvas>
</div>
<div class="card">
    <h2>Магазины (30 дней)</h2>
    <canvas id="storeChart" width="400" height="200"></canvas>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
(async function() {
    const resp = await fetch('/admin/dashboard/data');
    const data = await resp.json();

    // Посты
    new Chart(document.getElementById('postsChart'), {
        type: 'line',
        data: {
            labels: data.posts_labels,
            datasets: [{
                label: 'Посты',
                data: data.posts_counts,
                borderColor: '#ff4444',
                backgroundColor: 'rgba(255,68,68,0.1)',
                fill: true,
            }]
        },
        options: {
            scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } }
        }
    });

    // Доход
    new Chart(document.getElementById('revenueChart'), {
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
            scales: { y: { beginAtZero: true } }
        }
    });

    // Магазины (круговая)
    new Chart(document.getElementById('storeChart'), {
        type: 'doughnut',
        data: {
            labels: data.store_labels,
            datasets: [{
                label: 'Постов',
                data: data.store_values,
                backgroundColor: [
                    '#ff4444', '#4caf50', '#ff9800', '#2196f3', '#9c27b0',
                    '#00bcd4', '#ffeb3b', '#e91e63', '#8bc34a', '#607d8b'
                ],
            }]
        }
    });
})();
</script>
{% endblock %}'''

# ---------- USERS LIST ----------
USERS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Пользователи{% endblock %}
{% block content %}
<h1>👥 Пользователи</h1>
<div class="card">
    <table>
        <tr><th>ID</th><th>Роль</th><th>Подписка до</th><th>Тариф</th><th>Баланс</th><th>Действия</th></tr>
        {% for u in users %}
        <tr>
            <td>{{ u['user_id'] }}</td>
            <td>{{ u['role'] }}</td>
            <td>{{ u['subscription_until'] or '—' }}</td>
            <td>{{ u['tariff_name'] or '—' }}</td>
            <td>{{ u['balance_available'] or 0 }} ₽</td>
            <td><a href="/admin/users/edit/{{ u['user_id'] }}" class="btn">Изменить</a></td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- USER EDIT ----------
USER_EDIT_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Редактирование пользователя{% endblock %}
{% block content %}
<h1>✏️ Пользователь #{{ user['user_id'] }}</h1>
<div class="card">
    <form method="post" action="/admin/users/edit/{{ user['user_id'] }}">
        <label>Роль:</label>
        <select name="role">
            <option value="saas" {{ 'selected' if user['role'] == 'saas' }}>SaaS</option>
            <option value="blogger" {{ 'selected' if user['role'] == 'blogger' }}>Блогер</option>
        </select>
        <label>Подписка до (UTC, ГГГГ-ММ-ДД ЧЧ:ММ):</label>
        <input name="subscription_until" value="{{ user['subscription_until'] or '' }}" placeholder="2026-12-31 23:59">
        <label>Тариф:</label>
        <select name="tariff_id">
            <option value="0" {{ 'selected' if not user['tariff_id'] }}>Без тарифа</option>
            {% for t in tariffs %}
            <option value="{{ t['id'] }}" {{ 'selected' if user['tariff_id'] == t['id'] }}>{{ t['name'] }}</option>
            {% endfor %}
        </select>
        <label>Баланс доступный:</label>
        <input name="balance_available" value="{{ user['balance_available'] or 0 }}" type="number" step="0.01">
        <label>Баланс ожидающий:</label>
        <input name="balance_pending" value="{{ user['balance_pending'] or 0 }}" type="number" step="0.01">
        <button type="submit">Сохранить</button>
    </form>
</div>
{% endblock %}'''

# ---------- POSTS LIST ----------
POSTS_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Посты{% endblock %}
{% block content %}
<h1>📬 Посты (последние 100)</h1>
<form method="get" action="/admin/posts" style="margin-bottom:20px;">
    <label>Статус:</label>
    <select name="status">
        <option value="">Все</option>
        <option value="published" {{ 'selected' if request.query_params.get('status') == 'published' }}>Опубликован</option>
        <option value="pending" {{ 'selected' if request.query_params.get('status') == 'pending' }}>Ожидает</option>
        <option value="quarantine" {{ 'selected' if request.query_params.get('status') == 'quarantine' }}>Карантин</option>
    </select>
    <label>Пользователь (ID):</label>
    <input name="user_id" value="{{ request.query_params.get('user_id', '') }}" placeholder="ID пользователя">
    <button type="submit">Фильтр</button>
</form>
<div class="card">
    <table id="posts-table">
        <tr><th>ID</th><th>Пользователь</th><th>Канал</th><th>Статус</th><th>Дата</th></tr>
        {% for p in posts %}
        <tr data-photo="{{ p['photo_url'] or '' }}" 
            data-caption="{{ p['caption_text'] or '' | e }}" 
            data-channel="{{ p['channel_title'] or p['channel_id'] or '—' }}" 
            style="cursor:pointer;">
            <td>{{ p['id'] }}</td>
            <td>{{ p['user_id'] }}</td>
            <td>{{ p['channel_id'] or '—' }}</td>
            <td>{{ p['status'] }}</td>
            <td>{{ p['published_at'] or p['created_at'] }}</td>
        </tr>
        {% endfor %}
    </table>
</div>

<!-- Модальное окно для превью поста -->
<div id="post-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); z-index:1000; justify-content:center; align-items:center;">
    <div style="background:#0f0f0f; border-radius:12px; max-width:400px; width:90%; overflow:hidden; color:#fff; font-family: 'Segoe UI', sans-serif; position:relative;">
        <span id="close-modal" style="position:absolute; top:8px; right:12px; color:#aaa; font-size:20px; cursor:pointer; z-index:10;">✕</span>
        <div style="background:#1a1a1a; padding:10px 15px; display:flex; align-items:center;">
            <div style="background:#ff4444; border-radius:50%; width:32px; height:32px; display:flex; align-items:center; justify-content:center; margin-right:10px; font-weight:bold; font-size:14px;">#</div>
            <div id="modal-channel-title" style="font-weight:600; font-size:15px;">Канал</div>
        </div>
        <img id="modal-photo" src="" style="width:100%; display:none;" onerror="this.style.display='none'">
        <div id="modal-caption" style="padding:10px 15px 15px; font-size:14px; line-height:1.4; word-wrap:break-word;"></div>
    </div>
</div>

<script>
    const modal = document.getElementById('post-modal');
    const modalPhoto = document.getElementById('modal-photo');
    const modalCaption = document.getElementById('modal-caption');
    const modalChannel = document.getElementById('modal-channel-title');
    const closeBtn = document.getElementById('close-modal');

    document.querySelectorAll('#posts-table tr[data-photo]').forEach(row => {
        row.addEventListener('click', () => {
            const photo = row.getAttribute('data-photo');
            const caption = row.getAttribute('data-caption');
            const channel = row.getAttribute('data-channel') || 'Канал';
            if (photo) {
                modalPhoto.src = photo;
                modalPhoto.style.display = 'block';
            } else {
                modalPhoto.style.display = 'none';
            }
            modalCaption.innerHTML = caption || '<i style="color:#888;">Текст поста отсутствует</i>';
            modalChannel.textContent = channel;
            modal.style.display = 'flex';
        });
    });

    closeBtn.addEventListener('click', () => {
        modal.style.display = 'none';
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.style.display = 'none';
        }
    });

    // Автообновление каждые 30 секунд
    setInterval(function() {
        location.reload();
    }, 30000);
</script>
{% endblock %}'''

# ---------- QUARANTINE ----------
QUARANTINE_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Карантин{% endblock %}
{% block content %}
<h1>🚨 Карантин</h1>
<div class="card">
    <table>
        <tr><th>ID</th><th>Пользователь</th><th>Канал</th><th>ERID</th><th>Причина</th><th></th></tr>
        {% for p in posts %}
        <tr>
            <td>{{ p['id'] }}</td>
            <td>{{ p['user_id'] }}</td>
            <td>{{ p['channel_id'] or '—' }}</td>
            <td>{{ p['erid'] or '—' }}</td>
            <td>{{ p['quarantine_reason'] }}</td>
            <td>
                <form method="post" action="/admin/quarantine/approve/{{ p['id'] }}" style="display:inline;">
                    <input name="erid" placeholder="ERID" required>
                    <input name="advertiser" placeholder="Рекламодатель">
                    <button type="submit">Одобрить</button>
                </form>
                <a href="/admin/quarantine/delete/{{ p['id'] }}" class="btn">Удалить</a>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- TARIFFS ----------
TARIFFS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Тарифы{% endblock %}
{% block content %}
<h1>💎 Тарифы</h1>
<div class="card">
    <h2>Добавить</h2>
    <form method="post" action="/admin/tariffs/add">
        <input name="name" placeholder="Название" required>
        <input name="days" placeholder="Дней" type="number" required>
        <input name="price_rub" placeholder="Цена RUB" type="number" step="0.01" required>
        <input name="price_stars" placeholder="Цена Stars" type="number" required>
        <input name="max_channels" placeholder="Макс. каналов" type="number" value="5">
        <input name="max_stores" placeholder="Макс. магазинов" type="number" value="3">
        <input name="max_posts_per_day" placeholder="Постов в день" type="number" value="25">
        <button type="submit">Создать</button>
    </form>
</div>
<div class="card">
    <h2>Список</h2>
    <table>
        <tr><th>Название</th><th>Дней</th><th>Цена RUB</th><th>Stars</th><th></th></tr>
        {% for t in tariffs %}
        <tr>
            <td>{{ t['name'] }}</td>
            <td>{{ t['days'] }}</td>
            <td>{{ t['price_rub'] }}</td>
            <td>{{ t['price_stars'] }}</td>
            <td>
                <a href="/admin/tariffs/edit/{{ t['id'] }}" class="btn">Ред.</a>
                <a href="/admin/tariffs/delete/{{ t['id'] }}" class="btn">Удалить</a>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- TARIFF EDIT ----------
TARIFF_EDIT_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Редактирование тарифа{% endblock %}
{% block content %}
<h1>✏️ Тариф "{{ tariff['name'] }}"</h1>
<div class="card">
    <form method="post" action="/admin/tariffs/edit/{{ tariff['id'] }}">
        <input name="name" value="{{ tariff['name'] }}" required>
        <input name="days" value="{{ tariff['days'] }}" type="number" required>
        <input name="price_rub" value="{{ tariff['price_rub'] }}" type="number" step="0.01" required>
        <input name="price_stars" value="{{ tariff['price_stars'] }}" type="number" required>
        <input name="max_channels" value="{{ tariff['max_channels'] }}" type="number">
        <input name="max_stores" value="{{ tariff['max_stores'] }}" type="number">
        <input name="max_posts_per_day" value="{{ tariff['max_posts_per_day'] }}" type="number">
        <button type="submit">Сохранить</button>
    </form>
</div>
{% endblock %}'''

# ---------- BROADCAST ----------
BROADCAST_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Рассылка{% endblock %}
{% block content %}
<h1>📣 Массовая рассылка</h1>
<div class="card">
    {% if message %}<p class="success">{{ message }}</p>{% endif %}
    <form method="post" action="/admin/broadcast">
        <textarea name="text" rows="5" placeholder="Текст сообщения..." required></textarea>
        <select name="role">
            <option value="all">Всем</option>
            <option value="saas">SaaS</option>
            <option value="blogger">Блогерам</option>
        </select>
        <button type="submit">Отправить</button>
    </form>
</div>
{% endblock %}'''

# ---------- PROMOCODES (STORE) ----------
PROMOCODES_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Купоны магазинов{% endblock %}
{% block content %}
<h1>🎟 Купоны магазинов</h1>
<div class="card">
    <h2>Добавить</h2>
    <form method="post" action="/admin/promocodes/add">
        <input name="store" placeholder="Магазин" required>
        <input name="promocode" placeholder="Промокод" required>
        <input name="description" placeholder="Описание">
        <button type="submit">Добавить</button>
    </form>
</div>
<div class="card">
    <h2>Список</h2>
    <table>
        <tr><th>Магазин</th><th>Код</th><th>Описание</th><th></th></tr>
        {% for p in promos %}
        <tr><td>{{ p['store'] }}</td><td><code>{{ p['promocode'] }}</code></td><td>{{ p['description'] }}</td><td><a href="/admin/promocodes/delete/{{ p['id'] }}">Удалить</a></td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- STORE DELIVERY ----------
STORE_DELIVERY_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Доставка{% endblock %}
{% block content %}
<h1>🚚 Доставка</h1>
<div class="card">
    <h2>Обновить</h2>
    <form method="post" action="/admin/store_delivery/update">
        <input name="store" placeholder="Магазин" required>
        <input name="delivery_text" placeholder="Условия" required>
        <button type="submit">Сохранить</button>
    </form>
</div>
<div class="card">
    <h2>Текущие данные</h2>
    <table>
        <tr><th>Магазин</th><th>Условия</th></tr>
        {% for d in deliveries %}
        <tr><td>{{ d['store'] }}</td><td>{{ d['delivery_text'] }}</td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- TEST PROMOCODES ----------
TEST_PROMOCODES_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Промокоды (тест){% endblock %}
{% block content %}
<h1>🎁 Промокоды (тестовый период)</h1>
<div class="card">
    <h2>Добавить</h2>
    <form method="post" action="/admin/test_promocodes/add">
        <input name="code" placeholder="Код" required>
        <input name="days" placeholder="Дней" type="number" required>
        <button type="submit">Создать</button>
    </form>
</div>
<div class="card">
    <h2>Список</h2>
    <table>
        <tr><th>Код</th><th>Дней</th><th>Использован?</th><th></th></tr>
        {% for p in promos %}
        <tr><td><code>{{ p['code'] }}</code></td><td>{{ p['days'] }}</td><td>{{ 'Да' if p['used'] else 'Нет' }}</td><td><a href="/admin/test_promocodes/delete/{{ p['id'] }}">Удалить</a></td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- BULK ACTIONS ----------
BULK_ACTIONS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Массовые действия{% endblock %}
{% block content %}
<h1>👥 Массовые действия</h1>
<div class="card">
    <form method="post" action="/admin/bulk-actions/execute">
        <label>Группа пользователей:</label>
        <select name="group">
            <option value="all">Все</option>
            <option value="saas">SaaS</option>
            <option value="blogger">Блогеры</option>
            <option value="active">Активные</option>
            <option value="banned">Забаненные</option>
            <option value="expired">Истекшая подписка</option>
        </select>
        <label>Действие:</label>
        <select name="action">
            <option value="extend">Продлить на N дней</option>
            <option value="ban">Забанить</option>
            <option value="unban">Разбанить</option>
            <option value="delete">Удалить</option>
        </select>
        <label>Дней (для продления):</label>
        <input name="days" value="7" type="number">
        <button type="submit">Выполнить</button>
    </form>
    {% if message %}<p class="success">{{ message }}</p>{% endif %}
</div>
{% endblock %}'''

# ---------- SETTINGS ----------
SETTINGS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Глобальные настройки{% endblock %}
{% block content %}
<h1>⚙️ Глобальные настройки</h1>
<div class="card">
    <form method="post" action="/admin/settings-edit/save">
        <label>Ночной режим, начало (HH:MM):</label>
        <input name="night_start" value="{{ settings.get('night_start', '23:00') }}">
        <label>Ночной режим, конец (HH:MM):</label>
        <input name="night_end" value="{{ settings.get('night_end', '08:00') }}">
        <label>Интервал сканирования (сек):</label>
        <input name="run_interval" value="{{ settings.get('run_interval', '900') }}" type="number">
        <label>Минимальная выплата (RUB):</label>
        <input name="min_payout" value="{{ settings.get('min_payout', '2000') }}" type="number">
        <label>Комиссия банка (%):</label>
        <input name="payout_bank_pct" value="{{ settings.get('payout_bank_pct', '0.043') }}" step="0.001">
        <button type="submit">Сохранить</button>
    </form>
</div>
{% endblock %}'''

# ---------- AUDIT ----------
AUDIT_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Аудит{% endblock %}
{% block content %}
<h1>📜 Аудит (последние 200)</h1>
<div class="card">
    <table>
        <tr><th>Админ</th><th>Действие</th><th>Детали</th><th>Дата</th></tr>
        {% for a in audits %}
        <tr><td>{{ a['admin_id'] }}</td><td>{{ a['action'] }}</td><td>{{ a['details'] }}</td><td>{{ a['created_at'] }}</td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- REPORTS ----------
REPORTS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}Ежедневные отчёты{% endblock %}
{% block content %}
<h1>📁 Отчёты</h1>

<div class="card">
    <h2>Ежедневные файлы (CSV)</h2>
    <table>
        <tr><th>Имя файла</th><th></th></tr>
        {% for f in files %}
        <tr><td>{{ f }}</td><td><a href="/admin/reports/download/{{ f }}" class="btn">Скачать</a></td></tr>
        {% endfor %}
    </table>
</div>

<div class="card" style="margin-top:30px;">
    <h2>Финансовые и аналитические отчёты</h2>
    <p><a href="/admin/payouts/csv" class="btn">Скачать историю выплат (CSV)</a></p>
    <p><a href="/admin/subid-stats/csv" class="btn">Скачать статистику SubID (CSV)</a></p>
    <p><a href="/admin/referrals/csv" class="btn">Скачать реферальные связи (CSV)</a></p>
</div>
{% endblock %}'''
