# -*- coding: utf-8 -*-
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
.tabs { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
.tab-btn { background: #333; border: 1px solid #555; color: #ddd; padding: 10px 20px; border-radius: 8px; cursor: pointer; transition: all 0.2s; }
.tab-btn:hover { background: #444; }
.tab-btn.active { background: #ff4444; color: #fff; border-color: #ff4444; }
.tab-content { display: none; }
.tab-content.active { display: block; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-top: 20px; }
.stat-card { background: #2a2a2a; border-radius: 12px; padding: 20px; }
.stat-card h3 { color: #aaa; font-size: 0.9em; margin-bottom: 8px; font-weight: 500; }
.stat-card .value { font-size: 2em; font-weight: bold; color: #fff; }
.stat-card .value.positive { color: #4caf50; }
.stat-card .value.negative { color: #f44336; }
.stat-card .value.warning { color: #ff9800; }
'''

# ---------- BASE ----------
BASE_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{% block title %}AutoPost Bot{% endblock %}</title>
<style>''' + CSS_CONTENT + '''</style></head>
<body>
<div class="sidebar">
    <h2 style="color:#ff4444; margin-bottom:20px;">\u26a1 AutoPost</h2>
    <a href="/admin/dashboard" class="{{ 'active' if active_page == 'dashboard' }}">\U0001F4CA \u0414\u0430\u0448\u0431\u043e\u0440\u0434</a>
    <a href="/admin/users" class="{{ 'active' if active_page == 'users' }}">\U0001F465 \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438</a>
    <a href="/admin/posts" class="{{ 'active' if active_page == 'posts' }}">\U0001F4EC \u041f\u043e\u0441\u0442\u044b</a>
    <a href="/admin/store_delivery" class="{{ 'active' if active_page == 'delivery' }}">\U0001F69A \u0414\u043e\u0441\u0442\u0430\u0432\u043a\u0430</a>
    <a href="/admin/broadcast" class="{{ 'active' if active_page == 'broadcast' }}">\U0001F4E3 \u0420\u0430\u0441\u0441\u044b\u043b\u043a\u0430</a>
    <a href="/admin/payouts" class="{{ 'active' if active_page == 'payouts' }}">\U0001F4B0 \u0412\u044b\u043f\u043b\u0430\u0442\u044b</a>
    <a href="/admin/bulk-actions" class="{{ 'active' if active_page == 'bulk' }}">\U0001F465 \u041c\u0430\u0441\u0441\u043e\u0432\u044b\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f</a>
    <a href="/admin/settings-edit" class="{{ 'active' if active_page == 'settings' }}">\u2699\ufe0f \u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438</a>
    <a href="/admin/audit" class="{{ 'active' if active_page == 'audit' }}">\U0001F4DC \u0410\u0443\u0434\u0438\u0442</a>
    <a href="/admin/reports" class="{{ 'active' if active_page == 'reports' }}">\U0001F4C1 \u041e\u0442\u0447\u0451\u0442\u044b</a>
    <a href="/admin/logout" class="logout">\u0412\u044b\u0439\u0442\u0438</a>
</div>
<div class="main-content">
    {% block content %}{% endblock %}
</div>
</body>
</html>'''

# ---------- LOGIN ----------
LOGIN_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>\u0412\u0445\u043e\u0434 \u0432 \u0430\u0434\u043c\u0438\u043d\u043a\u0443</title>
<style>''' + CSS_CONTENT + '''</style></head>
<body style="justify-content:center; align-items:center; background:#1a1a1a;">
<div class="card" style="width:400px; text-align:center;">
    <h1>\u26a1 AutoPost</h1>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <p style="margin-bottom:20px;">\u0412\u043e\u0439\u0434\u0438\u0442\u0435 \u043f\u043e \u043e\u0434\u043d\u043e\u0440\u0430\u0437\u043e\u0432\u043e\u0439 \u0441\u0441\u044b\u043b\u043a\u0435 \u0438\u0437 \u0431\u043e\u0442\u0430 (<code>/admin</code>)</p>
</div>
</body>
</html>'''

# ---------- DASHBOARD (с аномалиями CTR) ----------
DASHBOARD_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}Дашборд{% endblock %}
{% block content %}
<div class="top-bar"><h1>\U0001F4CA \u0414\u0430\u0448\u0431\u043e\u0440\u0434</h1></div>

<div class="card">
    <h2>\u041a\u043b\u044e\u0447\u0435\u0432\u044b\u0435 \u043c\u0435\u0442\u0440\u0438\u043a\u0438</h2>
    <table>
        <tr><td>SaaS \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445</td><td><strong>{{ active_saas }}</strong></td></tr>
        <tr><td>\u0411\u043b\u043e\u0433\u0435\u0440\u043e\u0432 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445</td><td><strong>{{ active_bloggers }}</strong></td></tr>
        <tr><td>\u041f\u043e\u0441\u0442\u043e\u0432 \u0441\u0435\u0433\u043e\u0434\u043d\u044f</td><td><strong>{{ posts_today }}</strong></td></tr>
        <tr><td>\u041f\u043e\u0441\u0442\u043e\u0432 \u0437\u0430 \u043d\u0435\u0434\u0435\u043b\u044e</td><td><strong>{{ posts_week }}</strong></td></tr>
        <tr><td>\u041e\u0448\u0438\u0431\u043e\u043a \u0441\u0435\u0433\u043e\u0434\u043d\u044f</td><td><strong>{{ errors_today }}</strong></td></tr>
        <tr><td>\u041e\u0436\u0438\u0434\u0430\u044e\u0449\u0438\u0445 \u0432\u044b\u043f\u043b\u0430\u0442</td><td><strong>{{ pending_payouts }}</strong></td></tr>
    </table>
</div>

{% if ctr_alerts %}
<div class="card" style="border: 2px solid #ff9800;">
    <h2>\u26a0\ufe0f \u0410\u043d\u043e\u043c\u0430\u043b\u044c\u043d\u044b\u0439 CTR (\u0432\u044b\u0448\u0435 25%)</h2>
    <table>
        <tr><th>\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c</th><th>\u041a\u0430\u043d\u0430\u043b</th><th>SubID</th><th>\u041a\u043b\u0438\u043a\u0438</th><th>\u041b\u0438\u0434\u044b</th><th>CTR</th></tr>
        {% for a in ctr_alerts %}
        <tr>
            <td>{{ a['username'] or a['user_id'] }}</td>
            <td>{{ a['channel_title'] }}</td>
            <td><code>{{ a['subid1'] }}</code></td>
            <td>{{ a['clicks'] }}</td>
            <td>{{ a['leads'] }}</td>
            <td style="color:#ff9800; font-weight:bold;">{{ a['ctr'] }}%</td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endif %}

<!-- Period Selector -->
<div class="card">
    <h2>\U0001F4C5 \u041f\u0435\u0440\u0438\u043e\u0434</h2>
    <div class="tabs">
        <button class="tab-btn active" data-period="7d">7 \u0434\u043d\u0435\u0439</button>
        <button class="tab-btn" data-period="30d">30 \u0434\u043d\u0435\u0439</button>
        <button class="tab-btn" data-period="90d">90 \u0434\u043d\u0435\u0439</button>
        <button class="tab-btn" data-period="all">\u0412\u0441\u0451 \u0432\u0440\u0435\u043c\u044f</button>
    </div>
</div>

<!-- Channel Filter -->
<div class="card">
    <h2>\U0001F50D \u0424\u0438\u043b\u044c\u0442\u0440 \u043f\u043e \u043a\u0430\u043d\u0430\u043b\u0443</h2>
    <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:center;">
        <label style="font-weight:bold; margin-right:8px;">\u041a\u0430\u043d\u0430\u043b:</label>
        <select id="channel-select" style="min-width:220px; padding:10px; background:#333; border:1px solid #555; color:#ddd; border-radius:8px;">
            <option value="all">\u0412\u0441\u0435 \u043a\u0430\u043d\u0430\u043b\u044b</option>
            {% for ch in channels %}
            <option value="{{ ch['channel_id'] }}">{{ ch['channel_title'] or ch['channel_id'] }}</option>
            {% endfor %}
        </select>
        <div style="margin-left:auto; color:#bbb;">\u0412\u044b\u0431\u0440\u0430\u043d \u043a\u0430\u043d\u0430\u043b: <span id="selected-channel-name">\u0412\u0441\u0435 \u043a\u0430\u043d\u0430\u043b\u044b</span></div>
    </div>
</div>

<div class="card" id="channel-summary-card" style="display:none;">
    <h2>\U0001F4C8 \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 \u043f\u043e \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u043e\u043c\u0443 \u043a\u0430\u043d\u0430\u043b\u0443</h2>
    <div id="channel-summary" style="font-size:0.95em; color:#ddd;"></div>
</div>

<!-- Channel Performance Table -->
<div class="card">
    <h2>\U0001F4CA \u041f\u0440\u043e\u0438\u0437\u0432\u043e\u0434\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c \u043a\u0430\u043d\u0430\u043b\u043e\u0432 ({{ current_period_label }})</h2>
    <div style="overflow-x:auto;">
        <table id="channel-table">
            <thead>
                <tr>
                    <th>\u041a\u0430\u043d\u0430\u043b</th>
                    <th>\u0412\u043b\u0430\u0434\u0435\u043b\u0435\u0446</th>
                    <th>\u041f\u043e\u0441\u0442\u043e\u0432</th>
                    <th>\u041a\u043b\u0438\u043a\u0438</th>
                    <th>\u041b\u0438\u0434\u044b</th>
                    <th>CTR</th>
                    <th>\u0414\u043e\u0445\u043e\u0434 (\u20bd)</th>
                    <th>\u041a\u043e\u043d\u0432\u0435\u0440\u0441\u0438\u044f</th>
                    <th>SubID</th>
                </tr>
            </thead>
            <tbody id="channel-table-body">
                {% for ch in channel_stats %}
                <tr>
                    <td>{{ ch.channel_title or ch.channel_id }}</td>
                    <td>{{ ch.username or ch.user_id }}</td>
                    <td>{{ ch.posts_count }}</td>
                    <td>{{ ch.clicks }}</td>
                    <td>{{ ch.leads }}</td>
                    <td>{{ "%.1f"|format(ch.ctr) if ch.clicks > 0 else "0" }}%</td>
                    <td class="{% if ch.earnings > 0 %}positive{% elif ch.earnings < 0 %}negative{% endif %}">{{ "%.2f"|format(ch.earnings) }}</td>
                    <td>{{ "%.1f"|format(ch.conversion) if ch.clicks > 0 else "0" }}%</td>
                    <td><code>{{ ch.channel_id }}</code></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<!-- Traffic Sources (SubID2) -->
<div class="card">
    <h2>\U0001F3AF \u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0438 \u0442\u0440\u0430\u0444\u0438\u043a\u0430 (SubID2) \u2014 {{ current_period_label }}</h2>
    <p style="color:#aaa; margin-bottom:15px; font-size:0.9em;">SubID2 \u043e\u0442\u0441\u043b\u0435\u0436\u0438\u0432\u0430\u0435\u0442 \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u044b\u0435 \u043f\u043e\u0441\u0442\u044b. \u041f\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0435\u0442, \u043a\u0430\u043a\u0438\u0435 \u043a\u043e\u043d\u043a\u0440\u0435\u0442\u043d\u044b\u0435 \u043f\u0443\u0431\u043b\u0438\u043a\u0430\u0446\u0438\u0438 \u043f\u0440\u0438\u043d\u043e\u0441\u044f\u0442 \u043a\u043b\u0438\u043a\u0438 \u0438 \u043b\u0438\u0434\u044b.</p>
    <div style="overflow-x:auto;">
        <table id="subid2-table">
            <thead>
                <tr>
                    <th>SubID2 (\u041f\u043e\u0441\u0442)</th>
                    <th>\u041a\u0430\u043d\u0430\u043b</th>
                    <th>\u041a\u043b\u0438\u043a\u0438</th>
                    <th>\u041b\u0438\u0434\u044b</th>
                    <th>CTR</th>
                    <th>\u0414\u043e\u0445\u043e\u0434 (\u20bd)</th>
                    <th>\u0421\u0442\u0430\u0442\u0443\u0441</th>
                </tr>
            </thead>
            <tbody id="subid2-table-body">
                {% for s in subid2_stats %}
                <tr>
                    <td><code>{{ s.subid2 }}</code></td>
                    <td>{{ s.channel_title or s.channel_id }}</td>
                    <td>{{ s.clicks }}</td>
                    <td>{{ s.leads }}</td>
                    <td>{{ "%.1f"|format(s.ctr) if s.clicks > 0 else "0" }}%</td>
                    <td>{{ "%.2f"|format(s.earnings) }}</td>
                    <td>{{ s.status }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<!-- Charts Row -->
<div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">
    <div class="card">
        <h2>\U0001F4DD \u041f\u043e\u0441\u0442\u044b \u0437\u0430 {{ current_period_label }}</h2>
        <p id="chart-scope" style="margin-top:8px; color:#aaa;">\u041f\u043e\u043a\u0430\u0437\u0430\u043d\u044b \u0434\u0430\u043d\u043d\u044b\u0435 \u0434\u043b\u044f \u0432\u0441\u0435\u0445 \u043a\u0430\u043d\u0430\u043b\u043e\u0432.</p>
        <canvas id="postsChart" width="400" height="200"></canvas>
    </div>
    <div class="card">
        <h2>\U0001F4B0 \u0414\u043e\u0445\u043e\u0434 \u0437\u0430 {{ current_period_label }}</h2>
        <canvas id="revenueChart" width="400" height="200"></canvas>
    </div>
</div>

<div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">
    <div class="card">
        <h2>\U0001F3EA \u041c\u0430\u0433\u0430\u0437\u0438\u043d\u044b \u043f\u043e \u043f\u043e\u0441\u0442\u0430\u043c ({{ current_period_label }})</h2>
        <canvas id="storeChart" width="400" height="200"></canvas>
    </div>
    <div class="card">
        <h2>\U0001F3EA \u041c\u0430\u0433\u0430\u0437\u0438\u043d\u044b \u043f\u043e \u0434\u043e\u0445\u043e\u0434\u0430\u043c ({{ current_period_label }})</h2>
        <canvas id="storeRevenueChart" width="400" height="200"></canvas>
    </div>
</div>

<!-- Top Users -->
<div class="card">
    <h2>\U0001F451 \u0422\u043e\u043f \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439 \u043f\u043e \u0434\u043e\u0445\u043e\u0434\u0443 ({{ current_period_label }})</h2>
    <div style="overflow-x:auto;">
        <table>
            <thead>
                <tr><th>\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c</th><th>\u0420\u043e\u043b\u044c</th><th>\u0414\u043e\u0445\u043e\u0434 (\u20bd)</th><th>\u0422\u0440\u0430\u043d\u0437\u0430\u043a\u0446\u0438\u0439</th><th>\u041f\u043e\u0441\u0442\u043e\u0432</th></tr>
            </thead>
            <tbody>
                {% for u in top_users %}
                <tr>
                    <td>{{ u.username or u.user_id }}</td>
                    <td>{{ u.role }}</td>
                    <td class="positive">{{ "%.2f"|format(u.total_revenue) }}</td>
                    <td>{{ u.transactions }}</td>
                    <td>{{ u.posts_count }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
(function() {
    const channelSelect = document.getElementById('channel-select');
    const channelSummary = document.getElementById('channel-summary');
    const channelSummaryCard = document.getElementById('channel-summary-card');
    const selectedChannelName = document.getElementById('selected-channel-name');
    const chartScope = document.getElementById('chart-scope');
    const tabBtns = document.querySelectorAll('.tab-btn');

    let postsChart, revenueChart, storeChart, storeRevenueChart;
    let currentPeriod = '30d';
    let currentChannelId = 'all';

    function formatNumber(value) {
        return value != null ? value.toLocaleString('ru-RU') : '0';
    }

    function formatMoney(value) {
        return value != null ? value.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '0.00';
    }

    function renderChannelSummary(data) {
        if (data.channel_summary) {
            channelSummaryCard.style.display = 'block';
            const summary = data.channel_summary;
            channelSummary.innerHTML = `
                <p><b>\u041f\u043e\u0441\u0442\u043e\u0432 \u0437\u0430 \u043f\u0435\u0440\u0438\u043e\u0434:</b> ${formatNumber(summary.posts_count)}</p>
                <p><b>\u041a\u043b\u0438\u043a\u0438:</b> ${formatNumber(summary.clicks)}</p>
                <p><b>\u041b\u0438\u0434\u044b:</b> ${formatNumber(summary.leads)}</p>
                <p><b>\u0414\u043e\u0445\u043e\u0434:</b> ${formatMoney(summary.earnings)} \u20bd</p>
                <p><b>\u041a\u043e\u043d\u0432\u0435\u0440\u0441\u0438\u044f:</b> ${summary.conversion.toFixed(1)}%</p>
            `;
        } else {
            channelSummaryCard.style.display = 'none';
            channelSummary.innerHTML = '';
        }
    }

    function updatePeriodTabs(period) {
        tabBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.period === period);
        });
    }

    async function loadData() {
        const url = currentChannelId === 'all' 
            ? `/admin/dashboard/data?period=${currentPeriod}`
            : `/admin/dashboard/data?channel_id=${encodeURIComponent(currentChannelId)}&period=${currentPeriod}`;
        
        const resp = await fetch(url);
        const data = await resp.json();

        const title = data.selected_channel_title || '\u0412\u0441\u0435 \u043a\u0430\u043d\u0430\u043b\u044b';
        selectedChannelName.textContent = title;
        chartScope.textContent = currentChannelId === 'all' || !currentChannelId
            ? `\u041f\u043e\u043a\u0430\u0437\u0430\u043d\u044b \u0434\u0430\u043d\u043d\u044b\u0435 \u0434\u043b\u044f \u0432\u0441\u0435\u0445 \u043a\u0430\u043d\u0430\u043b\u043e\u0432 (${data.period_label}).`
            : `\u041f\u043e\u043a\u0430\u0437\u0430\u043d\u044b \u0434\u0430\u043d\u043d\u044b\u0435 \u0434\u043b\u044f \u043a\u0430\u043d\u0430\u043b\u0430: ${title} (${data.period_label}).`;

        renderChannelSummary(data);

        // Posts Chart
        if (postsChart) postsChart.destroy();
        postsChart = new Chart(document.getElementById('postsChart'), {
            type: 'line',
            data: {
                labels: data.posts_labels,
                datasets: [{
                    label: '\u041f\u043e\u0441\u0442\u044b',
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

        // Revenue Chart
        if (revenueChart) revenueChart.destroy();
        revenueChart = new Chart(document.getElementById('revenueChart'), {
            type: 'line',
            data: {
                labels: data.revenue_labels,
                datasets: [
                    {
                        label: '\u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e (\u20bd)',
                        data: data.revenue_approved,
                        borderColor: '#4caf50',
                        backgroundColor: 'rgba(76,175,80,0.1)',
                        fill: true,
                    },
                    {
                        label: '\u0412 \u043e\u0436\u0438\u0434\u0430\u043d\u0438\u0438 (\u20bd)',
                        data: data.revenue_pending,
                        borderColor: '#ff9800',
                        backgroundColor: 'rgba(255,152,0,0.1)',
                        fill: true,
                    }
                ]
            },
            options: {
                scales: { y: { beginAtZero: true } }
            }
        });

        // Store Chart (by posts)
        if (storeChart) storeChart.destroy();
        storeChart = new Chart(document.getElementById('storeChart'), {
            type: 'doughnut',
            data: {
                labels: data.store_labels,
                datasets: [{
                    label: '\u041f\u043e\u0441\u0442\u043e\u0432',
                    data: data.store_values,
                    backgroundColor: [
                        '#ff4444', '#4caf50', '#ff9800', '#2196f3', '#9c27b0',
                        '#00bcd4', '#ffeb3b', '#e91e63', '#8bc34a', '#607d8b'
                    ],
                }]
            }
        });

        // Store Revenue Chart
        if (storeRevenueChart) storeRevenueChart.destroy();
        storeRevenueChart = new Chart(document.getElementById('storeRevenueChart'), {
            type: 'bar',
            data: {
                labels: data.store_revenue_labels,
                datasets: [{
                    label: '\u0414\u043e\u0445\u043e\u0434 (\u20bd)',
                    data: data.store_revenue_values,
                    backgroundColor: '#4caf50',
                }, {
                    label: '\u0422\u0440\u0430\u043d\u0437\u0430\u043a\u0446\u0438\u0439',
                    data: data.store_revenue_transactions,
                    backgroundColor: '#2196f3',
                    yAxisID: 'y1',
                }]
            },
            options: {
                scales: {
                    y: { beginAtZero: true, position: 'left' },
                    y1: { beginAtZero: true, position: 'right', grid: { drawOnChartArea: false } }
                }
            }
        });
    }

    channelSelect.addEventListener('change', () => {
        currentChannelId = channelSelect.value;
        loadData();
    });

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            currentPeriod = btn.dataset.period;
            updatePeriodTabs(currentPeriod);
            loadData();
        });
    });

    loadData();
})();
</script>
{% endblock %}'''

# ---------- USERS LIST ----------
USERS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438{% endblock %}
{% block content %}
<h1>\U0001F465 \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438</h1>
<div class="card">
    <table>
        <tr><th>ID</th><th>\u0420\u043e\u043b\u044c</th><th>\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u0434\u043e</th><th>\u0422\u0430\u0440\u0438\u0444</th><th>\u0411\u0430\u043b\u0430\u043d\u0441</th><th>\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u044f</th></tr>
        {% for u in users %}
        <tr>
            <td>{{ u['user_id'] }}</td>
            <td>{{ u['role'] }}</td>
            <td>{{ u['subscription_until'] or '\u2014' }}</td>
            <td>{{ u['tariff_name'] or '\u2014' }}</td>
            <td>{{ u['balance_available'] or 0 }} \u20bd</td>
            <td><a href="/admin/users/edit/{{ u['user_id'] }}" class="btn">\u0418\u0437\u043c\u0435\u043d\u0438\u0442\u044c</a></td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- USER EDIT ----------
USER_EDIT_TEMPLATE = '''{% extends "base.html" %}
{% block title %}\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f{% endblock %}
{% block content %}
<h1>\u270f\ufe0f \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c #{{ user['user_id'] }}</h1>
<div class="card">
    <form method="post" action="/admin/users/edit/{{ user['user_id'] }}">
        <label>\u0420\u043e\u043b\u044c:</label>
        <select name="role">
            <option value="saas" {{ 'selected' if user['role'] == 'saas' }}>SaaS</option>
            <option value="blogger" {{ 'selected' if user['role'] == 'blogger' }}>\u0411\u043b\u043e\u0433\u0435\u0440</option>
        </select>
        <label>\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 \u0434\u043e (UTC, \u0413\u0413\u0413\u0413-\u041c\u041c-\u0414\u0414 \u0427\u0427:\u041c\u041c):</label>
        <input name="subscription_until" value="{{ user['subscription_until'] or '' }}" placeholder="2026-12-31 23:59">
        <label>\u0422\u0430\u0440\u0438\u0444:</label>
        <select name="tariff_id">
            <option value="0" {{ 'selected' if not user['tariff_id'] }}>\u0411\u0435\u0437 \u0442\u0430\u0440\u0438\u0444\u0430</option>
            {% for t in tariffs %}
            <option value="{{ t['id'] }}" {{ 'selected' if user['tariff_id'] == t['id'] }}>{{ t['name'] }}</option>
            {% endfor %}
        </select>
        <label>\u0411\u0430\u043b\u0430\u043d\u0441 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0439:</label>
        <input name="balance_available" value="{{ user['balance_available'] or 0 }}" type="number" step="0.01">
        <label>\u0411\u0430\u043b\u0430\u043d\u0441 \u043e\u0436\u0438\u0434\u0430\u044e\u0449\u0438\u0439:</label>
        <input name="balance_pending" value="{{ user['balance_pending'] or 0 }}" type="number" step="0.01">
        <button type="submit">\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c</button>
    </form>
</div>
{% endblock %}'''

# ---------- POSTS LIST ----------
POSTS_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}\u041f\u043e\u0441\u0442\u044b{% endblock %}
{% block content %}
<h1>\U0001F4EC \u041f\u043e\u0441\u0442\u044b (\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 100 \u043e\u043f\u0443\u0431\u043b\u0438\u043a\u043e\u0432\u0430\u043d\u043d\u044b\u0445)</h1>
<form method="get" action="/admin/posts" style="margin-bottom:20px;">
    <label>\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c (ID):</label>
    <input name="user_id" value="{{ request.query_params.get('user_id', '') }}" placeholder="ID \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f">
    <button type="submit">\u0424\u0438\u043b\u044c\u0442\u0440</button>
</form>
<div class="card">
    <table id="posts-table">
        <tr><th>ID</th><th>\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c</th><th>\u041a\u0430\u043d\u0430\u043b</th><th>ERID</th><th>\u0421\u0441\u044b\u043b\u043a\u0430</th><th>\u0421\u0442\u0430\u0442\u0443\u0441</th><th>\u0414\u0430\u0442\u0430</th></tr>
        {% for p in posts %}
        <tr data-photo="{{ p['photo_url'] or '' }}" 
            data-caption="{{ p['caption_text'] or '' | e }}" 
            data-channel="{{ p['channel_title'] or p['channel_id'] or '\u2014' }}" 
            style="cursor:pointer;">
            <td>{{ p['id'] }}</td>
            <td>{{ p['user_id'] }}</td>
            <td>{{ p['channel_id'] or '\u2014' }}</td>
            <td>{{ p['erid'] or '\u2014' }}</td>
            <td>{% if p['direct_link'] %}<a href="{{ p['direct_link'] }}" target="_blank" style="color:#4d6bfe;">\u041e\u0442\u043a\u0440\u044b\u0442\u044c</a>{% else %}\u2014{% endif %}</td>
            <td>{{ p['status'] }}</td>
            <td>{{ p['published_at'] or p['created_at'] }}</td>
        </tr>
        {% endfor %}
    </table>
</div>

<div id="post-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); z-index:1000; justify-content:center; align-items:center;">
    <div style="background:#0f0f0f; border-radius:12px; max-width:400px; width:90%; overflow:hidden; color:#fff; font-family: 'Segoe UI', sans-serif; position:relative;">
        <span id="close-modal" style="position:absolute; top:8px; right:12px; color:#aaa; font-size:20px; cursor:pointer; z-index:10;">\u2715</span>
        <div style="background:#1a1a1a; padding:10px 15px; display:flex; align-items:center;">
            <div style="background:#ff4444; border-radius:50%; width:32px; height:32px; display:flex; align-items:center; justify-content:center; margin-right:10px; font-weight:bold; font-size:14px;">#</div>
            <div id="modal-channel-title" style="font-weight:600; font-size:15px;">\u041a\u0430\u043d\u0430\u043b</div>
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
            const channel = row.getAttribute('data-channel') || '\u041a\u0430\u043d\u0430\u043b';
            if (photo) {
                modalPhoto.src = photo;
                modalPhoto.style.display = 'block';
            } else {
                modalPhoto.style.display = 'none';
            }
            modalCaption.innerHTML = caption || '<i style="color:#888;">\u0422\u0435\u043a\u0441\u0442 \u043f\u043e\u0441\u0442\u0430 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442</i>';
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

    setInterval(function() {
        location.reload();
    }, 30000);
</script>
{% endblock %}'''

# ---------- QUARANTINE ----------
QUARANTINE_TEMPLATE = '''{% extends "base.html" %}
{% block title %}\u041a\u0430\u0440\u0430\u043d\u0442\u0438\u043d{% endblock %}
{% block content %}
<h1>\U0001F6A8 \u041a\u0430\u0440\u0430\u043d\u0442\u0438\u043d</h1>
<div class="card">
    <table>
        <tr><th>ID</th><th>\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c</th><th>\u041a\u0430\u043d\u0430\u043b</th><th>ERID</th><th>\u041f\u0440\u0438\u0447\u0438\u043d\u0430</th><th></th></tr>
        {% for p in posts %}
        <tr>
            <td>{{ p['id'] }}</td>
            <td>{{ p['user_id'] }}</td>
            <td>{{ p['channel_id'] or '\u2014' }}</td>
            <td>{{ p['erid'] or '\u2014' }}</td>
            <td>{{ p['quarantine_reason'] }}</td>
            <td>
                <form method="post" action="/admin/quarantine/approve/{{ p['id'] }}" style="display:inline;">
                    <input name="erid" placeholder="ERID" required>
                    <input name="advertiser" placeholder="\u0420\u0435\u043a\u043b\u0430\u043c\u043e\u0434\u0430\u0442\u0435\u043b\u044c">
                    <button type="submit">\u041e\u0434\u043e\u0431\u0440\u0438\u0442\u044c</button>
                </form>
                <a href="/admin/quarantine/delete/{{ p['id'] }}" class="btn">\u0423\u0434\u0430\u043b\u0438\u0442\u044c</a>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- BROADCAST ----------
BROADCAST_TEMPLATE = '''{% extends "base.html" %}
{% block title %}\u0420\u0430\u0441\u0441\u044b\u043b\u043a\u0430{% endblock %}
{% block content %}
<h1>\U0001F4E3 \u041c\u0430\u0441\u0441\u043e\u0432\u0430\u044f \u0440\u0430\u0441\u0441\u044b\u043b\u043a\u0430</h1>
<div class="card">
    {% if message %}<p class="success">{{ message }}</p>{% endif %}
    <form method="post" action="/admin/broadcast">
        <textarea name="text" rows="5" placeholder="\u0422\u0435\u043a\u0441\u0442 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f..." required></textarea>
        <select name="role">
            <option value="all">\u0412\u0441\u0435\u043c</option>
            <option value="saas">SaaS</option>
            <option value="blogger">\u0411\u043b\u043e\u0433\u0435\u0440\u0430\u043c</option>
        </select>
        <button type="submit">\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c</button>
    </form>
</div>
{% endblock %}'''

# ---------- PROMOCODES (STORE) ----------
PROMOCODES_TEMPLATE = '''{% extends "base.html" %}
{% block title %}\u041a\u0443\u043f\u043e\u043d\u044b \u043c\u0430\u0433\u0430\u0437\u0438\u043d\u043e\u0432{% endblock %}
{% block content %}
<h1>\U0001F39F\ufe0f \u041a\u0443\u043f\u043e\u043d\u044b \u043c\u0430\u0433\u0430\u0437\u0438\u043d\u043e\u0432</h1>
<div class="card">
    <h2>\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c</h2>
    <form method="post" action="/admin/promocodes/add">
        <input name="store" placeholder="\u041c\u0430\u0433\u0430\u0437\u0438\u043d" required>
        <input name="promocode" placeholder="\u041f\u0440\u043e\u043c\u043e\u043a\u043e\u0434" required>
        <input name="description" placeholder="\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435">
        <button type="submit">\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c</button>
    </form>
</div>
<div class="card">
    <h2>\u0421\u043f\u0438\u0441\u043e\u043a</h2>
    <table>
        <tr><th>\u041c\u0430\u0433\u0430\u0437\u0438\u043d</th><th>\u041a\u043e\u0434</th><th>\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435</th><th></th></tr>
        {% for p in promos %}
        <tr><td>{{ p['store'] }}</td><td><code>{{ p['promocode'] }}</code></td><td>{{ p['description'] }}</td><td><a href="/admin/promocodes/delete/{{ p['id'] }}">\u0423\u0434\u0430\u043b\u0438\u0442\u044c</a></td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- STORE DELIVERY ----------
STORE_DELIVERY_TEMPLATE = '''{% extends "base.html" %}
{% block title %}\u0414\u043e\u0441\u0442\u0430\u0432\u043a\u0430{% endblock %}
{% block content %}
<h1>\U0001F69A \u0414\u043e\u0441\u0442\u0430\u0432\u043a\u0430</h1>
<div class="card">
    <h2>\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c</h2>
    <form method="post" action="/admin/store_delivery/update">
        <input name="store" placeholder="\u041c\u0430\u0433\u0430\u0437\u0438\u043d" required>
        <input name="delivery_text" placeholder="\u0423\u0441\u043b\u043e\u0432\u0438\u044f" required>
        <button type="submit">\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c</button>
    </form>
</div>
<div class="card">
    <h2>\u0422\u0435\u043a\u0443\u0449\u0438\u0435 \u0434\u0430\u043d\u043d\u044b\u0435</h2>
    <table>
        <tr><th>\u041c\u0430\u0433\u0430\u0437\u0438\u043d</th><th>\u0423\u0441\u043b\u043e\u0432\u0438\u044f</th></tr>
        {% for d in deliveries %}
        <tr><td>{{ d['store'] }}</td><td>{{ d['delivery_text'] }}</td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- BULK ACTIONS ----------
BULK_ACTIONS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}\u041c\u0430\u0441\u0441\u043e\u0432\u044b\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f{% endblock %}
{% block content %}
<h1>\U0001F465 \u041c\u0430\u0441\u0441\u043e\u0432\u044b\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f</h1>
<div class="card">
    <form method="post" action="/admin/bulk-actions/execute">
        <label>\u0413\u0440\u0443\u043f\u043f\u0430 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439:</label>
        <select name="group">
            <option value="all">\u0412\u0441\u0435</option>
            <option value="saas">SaaS</option>
            <option value="blogger">\u0411\u043b\u043e\u0433\u0435\u0440\u044b</option>
            <option value="active">\u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0435</option>
            <option value="banned">\u0417\u0430\u0431\u0430\u043d\u0435\u043d\u043d\u044b\u0435</option>
            <option value="expired">\u041f\u0440\u043e\u0441\u0440\u043e\u0447\u0435\u043d\u043d\u044b\u0435</option>
        </select>
        <input type="hidden" name="action" id="bulk-action-input" value="activate">
        <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:10px; margin-top:10px;">
            <button type="button" onclick="setBulkAction('activate')">\u0410\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u0442\u044c</button>
            <button type="button" onclick="setBulkAction('deactivate')">\u0414\u0435\u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u0442\u044c</button>
            <button type="button" onclick="setBulkAction('reset_balance')">\u041e\u0431\u043d\u0443\u043b\u0438\u0442\u044c \u0431\u0430\u043b\u0430\u043d\u0441</button>
            <button type="button" onclick="setBulkAction('add_beta')">\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0432 \u0431\u0435\u0442\u0430</button>
            <button type="button" onclick="setBulkAction('remove_beta')">\u0423\u0431\u0440\u0430\u0442\u044c \u0438\u0437 \u0431\u0435\u0442\u0430</button>
            <button type="button" onclick="setBulkAction('delete')" style="background:#c62828;">\u0423\u0434\u0430\u043b\u0438\u0442\u044c</button>
        </div>
        <p style="color:#aaa; font-size:0.95em;">\u0422\u0435\u043a\u0443\u0449\u0430\u044f \u043e\u043f\u0435\u0440\u0430\u0446\u0438\u044f: <span id="current-bulk-action">\u0410\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u0442\u044c</span></p>
        <label>\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435 (\u0434\u043b\u044f reset_balance):</label>
        <input name="value" value="0" type="number">
        <button type="submit" style="margin-top:10px;">\u0412\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u044c</button>
        <script>
            function setBulkAction(action) {
                const actionInput = document.getElementById('bulk-action-input');
                const current = document.getElementById('current-bulk-action');
                actionInput.value = action;
                const labels = {
                    activate: '\u0410\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u0442\u044c',
                    deactivate: '\u0414\u0435\u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u0442\u044c',
                    reset_balance: '\u041e\u0431\u043d\u0443\u043b\u0438\u0442\u044c \u0431\u0430\u043b\u0430\u043d\u0441',
                    add_beta: '\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0432 \u0431\u0435\u0442\u0430',
                    remove_beta: '\u0423\u0431\u0440\u0430\u0442\u044c \u0438\u0437 \u0431\u0435\u0442\u0430',
                    delete: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c'
                };
                current.textContent = labels[action] || action;
            }
            setBulkAction('activate');
        </script>
    </form>
    {% if message %}<p class="success">{{ message }}</p>{% endif %}
</div>
{% endblock %}'''

# ---------- SETTINGS ----------
SETTINGS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}\u0413\u043b\u043e\u0431\u0430\u043b\u044c\u043d\u044b\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438{% endblock %}
{% block content %}
<h1>\u2699\ufe0f \u0413\u043b\u043e\u0431\u0430\u043b\u044c\u043d\u044b\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438</h1>
<div class="card">
    <form method="post" action="/admin/settings-edit/save">
        <label>\u041d\u043e\u0447\u043d\u043e\u0439 \u0440\u0435\u0436\u0438\u043c, \u043d\u0430\u0447\u0430\u043b\u043e (HH:MM):</label>
        <input name="night_start" value="{{ settings.get('night_start', '23:00') }}">
        <label>\u041d\u043e\u0447\u043d\u043e\u0439 \u0440\u0435\u0436\u0438\u043c, \u043a\u043e\u043d\u0435\u0446 (HH:MM):</label>
        <input name="night_end" value="{{ settings.get('night_end', '08:00') }}">
        <label>\u0418\u043d\u0442\u0435\u0440\u0432\u0430\u043b \u0441\u043a\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f (\u0441\u0435\u043a):</label>
        <input name="run_interval" value="{{ settings.get('run_interval', '900') }}" type="number">
        <label>\u041c\u0438\u043d\u0438\u043c\u0430\u043b\u044c\u043d\u0430\u044f \u0432\u044b\u043f\u043b\u0430\u0442\u0430 (RUB):</label>
        <input name="min_payout" value="{{ settings.get('min_payout', '2000') }}" type="number">
        <label>\u041a\u043e\u043c\u0438\u0441\u0441\u0438\u044f \u0431\u0430\u043d\u043a\u0430 (%):</label>
        <input name="payout_bank_pct" value="{{ settings.get('payout_bank_pct', '0.043') }}" step="0.001">
        <button type="submit">\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c</button>
    </form>
</div>

<!-- ===== \u041d\u041e\u0412\u042b\u0419 \u0411\u041b\u041e\u041a: \u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0444\u0438\u0447\u0430\u043c\u0438 ===== -->
<div class="card">
    <h2>\U0001F3AF \u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0444\u0438\u0447\u0430\u043c\u0438</h2>
    <table>
        <tr><th>\u0424\u0438\u0447\u0430</th><th>\u0421\u0442\u0430\u0442\u0443\u0441</th><th>\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u044f</th></tr>
        {% for feature in features %}
        <tr>
            <td><b>{{ feature['name'] }}</b></td>
            <td>
                <span style="padding:4px 12px; border-radius:4px; font-weight:bold; 
                    {% if feature['status'] == 'released' %}background:#4caf50; color:white;{% endif %}
                    {% if feature['status'] == 'beta' %}background:#ff9800; color:white;{% endif %}
                    {% if feature['status'] == 'dev' %}background:#999; color:white;{% endif %}
                ">
                    {% if feature['status'] == 'released' %}\u0412\u044b\u043f\u0443\u0449\u0435\u043d\u043e{% elif feature['status'] == 'beta' %}\u0411\u0435\u0442\u0430{% else %}\u0412 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0435{% endif %}
                </span>
            </td>
            <td>
                <form method="post" action="/admin/settings/feature-status" style="display:flex; gap:5px;">
                    <input type="hidden" name="feature_name" value="{{ feature['name'] }}">
                    {% if feature['status'] != 'dev' %}
                    <button type="submit" name="status" value="dev" style="background:#999; padding:5px 10px; font-size:0.9em;">\u2192 \u0412 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0435</button>
                    {% endif %}
                    {% if feature['status'] != 'beta' %}
                    <button type="submit" name="status" value="beta" style="background:#ff9800; padding:5px 10px; font-size:0.9em;">\u2192 \u0411\u0435\u0442\u0430</button>
                    {% endif %}
                    {% if feature['status'] != 'released' %}
                    <button type="submit" name="status" value="released" style="background:#4caf50; padding:5px 10px; font-size:0.9em;">\u2192 \u0412\u044b\u043f\u0443\u0449\u0435\u043d\u043e</button>
                    {% endif %}
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
    <p style="font-size: 0.85em; color: #888; margin-top: 10px;">
        <b>\u0412 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0435</b> \u2014 \u0441\u043a\u0440\u044b\u0442\u043e \u043e\u0442 \u0432\u0441\u0435\u0445<br>
        <b>\u0411\u0435\u0442\u0430</b> \u2014 \u0432\u0438\u0434\u044f\u0442 \u0442\u043e\u043b\u044c\u043a\u043e \u0431\u0435\u0442\u0430-\u0442\u0435\u0441\u0442\u0435\u0440\u044b<br>
        <b>\u0412\u044b\u043f\u0443\u0449\u0435\u043d\u043e</b> \u2014 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0432\u0441\u0435\u043c \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f\u043c
    </p>
</div>

<!-- ===== \u0411\u041b\u041e\u041a: \u0411\u0435\u0442\u0430-\u0442\u0435\u0441\u0442\u0435\u0440\u044b ===== -->
<div class="card">
    <h2>\U0001F52C \u0411\u0435\u0442\u0430-\u0442\u0435\u0441\u0442\u0435\u0440\u044b</h2>
    <p>\u0422\u0435\u043a\u0443\u0449\u0438\u0435 \u0431\u0435\u0442\u0430-\u0442\u0435\u0441\u0442\u0435\u0440\u044b ({{ beta_testers|length }}):</p>
    <table>
        <tr><th>ID</th><th>Username</th><th></th></tr>
        {% for tester in beta_testers %}
        <tr>
            <td>{{ tester['user_id'] }}</td>
            <td>{{ tester['username'] or '\u2014' }}</td>
            <td>
                <form method="post" action="/admin/settings/beta-remove" style="display:inline;">
                    <input type="hidden" name="user_id" value="{{ tester['user_id'] }}">
                    <button type="submit" style="background:#f44336; padding:5px 15px; font-size:0.9em;">\u0423\u0434\u0430\u043b\u0438\u0442\u044c</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
    
    <p style="margin-top: 20px;"><b>\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u043d\u043e\u0432\u043e\u0433\u043e \u0442\u0435\u0441\u0442\u0435\u0440\u0430:</b></p>
    <form method="post" action="/admin/settings/beta-add" style="display:flex; gap:10px;">
        <input type="number" name="user_id" placeholder="ID \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f" required style="width:150px;">
        <button type="submit">\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c</button>
    </form>
</div>
{% endblock %}'''

# ---------- AUDIT ----------
AUDIT_TEMPLATE = '''{% extends "base.html" %}
{% block title %}\u0410\u0443\u0434\u0438\u0442{% endblock %}
{% block content %}
<h1>\U0001F4DC \u0410\u0443\u0434\u0438\u0442 (\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 200)</h1>
<div class="card">
    <table>
        <tr><th>\u0410\u0434\u043c\u0438\u043d</th><th>\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0435</th><th>\u0414\u0435\u0442\u0430\u043b\u0438</th><th>\u0414\u0430\u0442\u0430</th></tr>
        {% for a in audits %}
        <tr><td>{{ a['admin_id'] }}</td><td>{{ a['action'] }}</td><td>{{ a['details'] }}</td><td>{{ a['created_at'] }}</td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- REPORTS ----------
REPORTS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}\u0415\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u044b\u0435 \u043e\u0442\u0447\u0451\u0442\u044b{% endblock %}
{% block content %}
<h1>\U0001F4C1 \u041e\u0442\u0447\u0451\u0442\u044b</h1>

<div class="card">
    <h2>\u0415\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u044b\u0435 \u0444\u0430\u0439\u043b\u044b (CSV)</h2>
    <table>
        <tr><th>\u0418\u043c\u044f \u0444\u0430\u0439\u043b\u0430</th><th></th></tr>
        {% for f in files %}
        <tr><td>{{ f }}</td><td><a href="/admin/reports/download/{{ f }}" class="btn">\u0421\u043a\u0430\u0447\u0430\u0442\u044c</a></td></tr>
        {% endfor %}
    </table>
</div>

<div class="card" style="margin-top:30px;">
    <h2>\u0424\u0438\u043d\u0430\u043d\u0441\u043e\u0432\u044b\u0435 \u0438 \u0430\u043d\u0430\u043b\u0438\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u043e\u0442\u0447\u0451\u0442\u044b</h2>
    <p><a href="/admin/payouts/csv" class="btn">\u0421\u043a\u0430\u0447\u0430\u0442\u044c \u0438\u0441\u0442\u043e\u0440\u0438\u044e \u0432\u044b\u043f\u043b\u0430\u0442 (CSV)</a></p>
    <p><a href="/admin/subid-stats/csv" class="btn">\u0421\u043a\u0430\u0447\u0430\u0442\u044c \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0443 SubID (CSV)</a></p>
    <p><a href="/admin/referrals/csv" class="btn">\u0421\u043a\u0430\u0447\u0430\u0442\u044c \u0440\u0435\u0444\u0435\u0440\u0430\u043b\u044c\u043d\u044b\u0435 \u0441\u0432\u044f\u0437\u0438 (CSV)</a></p>
</div>
{% endblock %}'''

# ---------- ADMIN PAYOUTS ----------
ADMIN_PAYOUTS_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}\u0412\u044b\u043f\u043b\u0430\u0442\u044b{% endblock %}
{% block content %}
<h1>\U0001F4B0 \u0412\u044b\u043f\u043b\u0430\u0442\u044b</h1>

<div class="card">
    <h2>\u0417\u0430\u043f\u0440\u043e\u0441\u044b \u043d\u0430 \u0432\u044b\u043f\u043b\u0430\u0442\u0443</h2>
    <table>
        <tr><th>ID</th><th>\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c</th><th>\u0421\u0443\u043c\u043c\u0430</th><th>\u0421\u0442\u0430\u0442\u0443\u0441</th><th></th></tr>
        {% for r in requests %}
        <tr>
            <td>{{ r['id'] }}</td>
            <td>{{ r['user_id'] }}</td>
            <td>{{ r['amount'] }} \u20bd</td>
            <td>{{ r['status'] }}</td>
            <td><a href="/admin/payouts/{{ r['id'] }}/chat" class="btn">\U0001F4AC \u0427\u0430\u0442</a></td>
        </tr>
        {% endfor %}
    </table>
</div>

<div class="card">
    <h2>\u0414\u043e\u0441\u0442\u0443\u043f\u043d\u043e \u043a \u0432\u044b\u043f\u043b\u0430\u0442\u0435</h2>
    <table>
        <tr><th>ID</th><th>\u0420\u043e\u043b\u044c</th><th>Username</th><th>\u0414\u043e\u0441\u0442\u0443\u043f\u043d\u043e</th><th></th></tr>
        {% for u in users %}
        <tr>
            <td>{{ u['user_id'] }}</td>
            <td>{{ u['role'] }}</td>
            <td>{{ u['username'] or '\u2014' }}</td>
            <td>{{ u['balance_available'] }} \u20bd</td>
            <td>
                <form method="post" action="/admin/payouts/pay" style="display:inline;">
                    <input type="hidden" name="user_id" value="{{ u['user_id'] }}">
                    <input type="number" name="amount" value="{{ u['balance_available'] }}" step="0.01" style="width:100px;">
                    <button type="submit">\u0412\u044b\u043f\u043b\u0430\u0442\u0438\u0442\u044c</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- ADMIN CHAT (полная страница) ----------
ADMIN_CHAT_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>\u0427\u0430\u0442 \u0432\u044b\u043f\u043b\u0430\u0442\u044b #{{ request_id }}</title>
<style>
    body { background: #1a1a1a; color: #ccc; font-family: sans-serif; padding: 20px; margin: 0; }
    h1 { color: #ff4444; }
    .back-link { color: #ff4444; text-decoration: none; display: inline-block; margin-bottom: 20px; }
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
    .chat-input button { background: #ff4444; color: white; border: none; padding: 12px 20px; border-radius: 8px; cursor: pointer; }
    .action-buttons { margin-top: 15px; display: flex; gap: 10px; }
    .action-buttons button { padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; color: white; }
    .send-money { background: #ff9800; }
    .decline { background: #f44336; }
    .confirm { background: #4caf50; }
</style>
</head>
<body>
<a href="/admin/payouts" class="back-link">\u2190 \u041d\u0430\u0437\u0430\u0434 \u043a \u0441\u043f\u0438\u0441\u043a\u0443 \u0432\u044b\u043f\u043b\u0430\u0442</a>
<h1>\U0001F4AC \u0427\u0430\u0442 \u043f\u043e \u0437\u0430\u044f\u0432\u043a\u0435 #{{ request_id }} <span class="status-badge" id="status-badge">{{ status }}</span></h1>
<div class="chat-box" id="chat-messages">\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430...</div>
<div class="chat-input">
    <input type="text" id="message-text" placeholder="\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435...">
    <button onclick="sendMessage()">\U0001F4E8</button>
</div>
<div class="action-buttons">
    <button id="send-money-btn" class="send-money" style="display:none;" onclick="sendMoney()">\U0001F4B8 \u0414\u0435\u043d\u044c\u0433\u0438 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u044b</button>
    <button id="decline-btn" class="decline" style="display:none;" onclick="declineRequest()">\u274c \u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c</button>
    <button id="confirm-btn" class="confirm" style="display:none;" onclick="confirmReceipt()">\u2705 \u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044c \u0447\u0435\u043a</button>
</div>

    <div id="receipt-warning" style="display:none; margin-top:15px; padding:12px; background:#2a1a1a; border:1px solid #ff9800; border-radius:8px;">
        \u26a0\ufe0f <b>\u0412\u043d\u0438\u043c\u0430\u043d\u0438\u0435:</b> \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0447\u0435\u043a \u0432\u0440\u0443\u0447\u043d\u0443\u044e \u2014 \u0441\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u0443\u043c\u043c\u0443, \u0434\u0430\u0442\u0443 \u0438 \u0418\u041d\u041d \u043f\u043e\u043b\u0443\u0447\u0430\u0442\u0435\u043b\u044f.
    </div>

<script>
const requestId = {{ request_id }};

async function loadChat() {
    try {
        const resp = await fetch(`/admin/payouts/${requestId}/chat-data`);
        if (!resp.ok) throw new Error('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438');
        const data = await resp.json();

        document.getElementById('status-badge').textContent = data.status;
        document.getElementById('status-badge').className = 'status-badge status-' + data.status;

        const chatDiv = document.getElementById('chat-messages');
        if (!data.messages || data.messages.length === 0) {
            chatDiv.innerHTML = '<p style="color:#888;">\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0439 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442</p>';
        } else {
            chatDiv.innerHTML = data.messages.map(msg => {
                const side = msg.sender_role === 'admin' ? 'admin' : 'user';
                let text = '';
                if (msg.file_path) {
                    text = `<a href="/admin/receipt-file?path=${encodeURIComponent(msg.file_path)}" target="_blank"><img src="/admin/receipt-file?path=${encodeURIComponent(msg.file_path)}" style="max-width:150px; border-radius:8px;"></a>`;
                }
                if (msg.message) text += msg.message.replace(/\n/g, '<br>');
                return `<div class="chat-msg ${side}">${text}<span class="time">${msg.created_at || ''}</span></div>`;
            }).join('');
        }
        chatDiv.scrollTop = chatDiv.scrollHeight;

        document.getElementById('send-money-btn').style.display = (data.status === 'processing') ? 'inline-block' : 'none';
        document.getElementById('decline-btn').style.display = (data.status !== 'completed' && data.status !== 'declined') ? 'inline-block' : 'none';
        document.getElementById('confirm-btn').style.display = (data.status === 'receipt_uploaded') ? 'inline-block' : 'none';
        document.getElementById('receipt-warning').style.display = (data.status === 'receipt_uploaded') ? 'block' : 'none';        
    } catch(e) {
        document.getElementById('chat-messages').innerHTML = '<p style="color:#ff4444;">\u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u0447\u0430\u0442\u0430</p>';
    }
}

async function sendMessage() {
    const text = document.getElementById('message-text').value.trim();
    if (!text) return;
    const formData = new FormData();
    formData.append('message', text);
    await fetch(`/admin/payouts/${requestId}/send-message`, { method: 'POST', body: formData });
    document.getElementById('message-text').value = '';
    loadChat();
}

async function sendMoney() {
    await fetch(`/admin/payouts/request/${requestId}/send-money`, { method: 'POST' });
    loadChat();
}
async function declineRequest() {
    await fetch(`/admin/payouts/request/${requestId}/decline`, { method: 'POST' });
    loadChat();
}
async function confirmReceipt() {
    await fetch(`/admin/payouts/request/${requestId}/confirm-receipt`, { method: 'POST' });
    loadChat();
}

setInterval(loadChat, 10000);
loadChat();
</script>
</body>
</html>'''

# Export all templates
TEMPLATES = {
    "base.html": BASE_TEMPLATE,
    "login.html": LOGIN_TEMPLATE,
    "admin_dashboard.html": DASHBOARD_TEMPLATE,
    "admin_users.html": USERS_TEMPLATE,
    "admin_user_edit.html": USER_EDIT_TEMPLATE,
    "admin_posts.html": POSTS_TEMPLATE,
    "admin_quarantine.html": QUARANTINE_TEMPLATE,
    "admin_broadcast.html": BROADCAST_TEMPLATE,
    "admin_promocodes.html": PROMOCODES_TEMPLATE,
    "admin_store_delivery.html": STORE_DELIVERY_TEMPLATE,
    "admin_bulk_actions.html": BULK_ACTIONS_TEMPLATE,
    "admin_settings.html": SETTINGS_TEMPLATE,
    "admin_audit.html": AUDIT_TEMPLATE,
    "admin_reports.html": REPORTS_TEMPLATE,
    "admin_payouts.html": ADMIN_PAYOUTS_TEMPLATE,
    "admin_chat.html": ADMIN_CHAT_TEMPLATE,
}