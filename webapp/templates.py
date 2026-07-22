# -*- coding: utf-8 -*-
# webapp/templates.py

# ---------- CSS (&#x43E;&#x431;&#x449;&#x438;&#x439;) ----------
CSS_CONTENT = '''
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #1a1a1a; color: #e0e0e0; display: flex; min-height: 100vh; }
.sidebar { width: 260px; background: #111; padding: 30px 20px; display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
.sidebar a { color: #bbb; text-decoration: none; padding: 12px 16px; border-radius: 8px; font-weight: 500; transition: all 0.2s; }
.sidebar a:hover, .sidebar a.active { background: #ff4444; color: #fff; }
.main-content { flex: 1; padding: 40px; overflow-y: auto; }
.hamburger { display: none; position: fixed; top: 12px; left: 12px; z-index: 1001; background: #ff4444; color: #fff; border: none; font-size: 24px; width: 44px; height: 44px; border-radius: 8px; cursor: pointer; align-items: center; justify-content: center; }
.sidebar-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 999; }
@media (max-width: 768px) {
    body { flex-direction: column; }
    .hamburger { display: flex; }
    .sidebar { position: fixed; top: 0; left: -280px; width: 280px; height: 100%; z-index: 1000; transition: left 0.3s; padding-top: 60px; }
    .sidebar.open { left: 0; }
    .sidebar-overlay.open { display: block; }
    .main-content { padding: 60px 12px 20px; margin-left: 0; }
}
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
<button class="hamburger" onclick="toggleSidebar()">☰</button>
<div class="sidebar-overlay" onclick="toggleSidebar()"></div>
<div class="sidebar" id="adminSidebar">
    <h2 style="color:#ff4444; margin-bottom:20px;">&#x26A1; AutoPost</h2>
    <a href="/admin/dashboard" class="{{ 'active' if active_page == 'dashboard' }}">&#x1F4CA; &#x414;&#x430;&#x448;&#x431;&#x43E;&#x440;&#x434;</a>
    <a href="/admin/users" class="{{ 'active' if active_page == 'users' }}">&#x1F465; &#x41F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x438;</a>
    <a href="/admin/posts" class="{{ 'active' if active_page == 'posts' }}">&#x1F4EC; &#x41F;&#x43E;&#x441;&#x442;&#x44B;</a>
    <a href="/admin/store_delivery" class="{{ 'active' if active_page == 'delivery' }}">&#x1F69A; &#x414;&#x43E;&#x441;&#x442;&#x430;&#x432;&#x43A;&#x430;</a>
    <a href="/admin/broadcast" class="{{ 'active' if active_page == 'broadcast' }}">&#x1F4E3; &#x420;&#x430;&#x441;&#x441;&#x44B;&#x43B;&#x43A;&#x430;</a>
    <a href="/admin/payouts" class="{{ 'active' if active_page == 'payouts' }}">&#x1F4B0; &#x412;&#x44B;&#x43F;&#x43B;&#x430;&#x442;&#x44B;</a>
    <a href="/admin/bulk-actions" class="{{ 'active' if active_page == 'bulk' }}">&#x1F465; &#x41C;&#x430;&#x441;&#x441;&#x43E;&#x432;&#x44B;&#x435; &#x434;&#x435;&#x439;&#x441;&#x442;&#x432;&#x438;&#x44F;</a>
    <a href="/admin/settings-edit" class="{{ 'active' if active_page == 'settings' }}">&#x2699;&#xFE0F; &#x41D;&#x430;&#x441;&#x442;&#x440;&#x43E;&#x439;&#x43A;&#x438;</a>
    <a href="/admin/audit" class="{{ 'active' if active_page == 'audit' }}">&#x1F4DC; &#x410;&#x443;&#x434;&#x438;&#x442;</a>
    <a href="/admin/reports" class="{{ 'active' if active_page == 'reports' }}">&#x1F4C1; &#x41E;&#x442;&#x447;&#x451;&#x442;&#x44B;</a>
    <a href="/admin/cpc" class="{{ 'active' if active_page == 'cpc' }}">&#x1F446; CPC</a>
    <a href="/admin/logout" class="logout">&#x412;&#x44B;&#x439;&#x442;&#x438;</a>
</div>
<div class="main-content">
    {% block content %}{% endblock %}
</div>
<script>
function toggleSidebar() {
    document.getElementById('adminSidebar').classList.toggle('open');
    document.querySelector('.sidebar-overlay').classList.toggle('open');
}
</script>
</body>
</html>'''

# ---------- LOGIN ----------
LOGIN_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>&#x412;&#x445;&#x43E;&#x434; &#x432; &#x430;&#x434;&#x43C;&#x438;&#x43D;&#x43A;&#x443;</title>
<style>''' + CSS_CONTENT + '''</style></head>
<body style="justify-content:center; align-items:center; background:#1a1a1a;">
<div class="card" style="width:400px; text-align:center;">
    <h1>&#x26A1; AutoPost</h1>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <p style="margin-bottom:20px;">&#x412;&#x43E;&#x439;&#x434;&#x438;&#x442;&#x435; &#x43F;&#x43E; &#x43E;&#x434;&#x43D;&#x43E;&#x440;&#x430;&#x437;&#x43E;&#x432;&#x43E;&#x439; &#x441;&#x441;&#x44B;&#x43B;&#x43A;&#x435; &#x438;&#x437; &#x431;&#x43E;&#x442;&#x430; (<code>/admin</code>)</p>
</div>
</body>
</html>'''

# ---------- DASHBOARD (&#x441; &#x430;&#x43D;&#x43E;&#x43C;&#x430;&#x43B;&#x438;&#x44F;&#x43C;&#x438; CTR) ----------
DASHBOARD_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}&#x414;&#x430;&#x448;&#x431;&#x43E;&#x440;&#x434;{% endblock %}
{% block content %}
<div class="top-bar"><h1>&#x1F4CA; &#x414;&#x430;&#x448;&#x431;&#x43E;&#x440;&#x434;</h1></div>

<div class="card">
    <h2>&#x41A;&#x43B;&#x44E;&#x447;&#x435;&#x432;&#x44B;&#x435; &#x43C;&#x435;&#x442;&#x440;&#x438;&#x43A;&#x438;</h2>
    <table>
        <tr><td>SaaS &#x430;&#x43A;&#x442;&#x438;&#x432;&#x43D;&#x44B;&#x445;</td><td><strong>{{ active_saas }}</strong></td></tr>
        <tr><td>&#x411;&#x43B;&#x43E;&#x433;&#x435;&#x440;&#x43E;&#x432; &#x430;&#x43A;&#x442;&#x438;&#x432;&#x43D;&#x44B;&#x445;</td><td><strong>{{ active_bloggers }}</strong></td></tr>
        <tr><td>&#x41F;&#x43E;&#x441;&#x442;&#x43E;&#x432; &#x441;&#x435;&#x433;&#x43E;&#x434;&#x43D;&#x44F;</td><td><strong>{{ posts_today }}</strong></td></tr>
        <tr><td>&#x41F;&#x43E;&#x441;&#x442;&#x43E;&#x432; &#x437;&#x430; &#x43D;&#x435;&#x434;&#x435;&#x43B;&#x44E;</td><td><strong>{{ posts_week }}</strong></td></tr>
        <tr><td>&#x41E;&#x448;&#x438;&#x431;&#x43E;&#x43A; &#x441;&#x435;&#x433;&#x43E;&#x434;&#x43D;&#x44F;</td><td><strong>{{ errors_today }}</strong></td></tr>
        <tr><td>&#x41E;&#x436;&#x438;&#x434;&#x430;&#x44E;&#x449;&#x438;&#x445; &#x432;&#x44B;&#x43F;&#x43B;&#x430;&#x442;</td><td><strong>{{ pending_payouts }}</strong></td></tr>
    </table>
</div>

{% if ctr_alerts %}
<div class="card" style="border: 2px solid #ff9800;">
    <h2>&#x26A0;&#xFE0F; &#x410;&#x43D;&#x43E;&#x43C;&#x430;&#x43B;&#x44C;&#x43D;&#x44B;&#x439; CTR (&#x432;&#x44B;&#x448;&#x435; 25%)</h2>
    <table>
        <tr><th>&#x41F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44C;</th><th>&#x41A;&#x430;&#x43D;&#x430;&#x43B;</th><th>SubID</th><th>&#x41A;&#x43B;&#x438;&#x43A;&#x438;</th><th>&#x41B;&#x438;&#x434;&#x44B;</th><th>CTR</th></tr>
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
    <h2>&#x1F4C5; &#x41F;&#x435;&#x440;&#x438;&#x43E;&#x434;</h2>
    <div class="tabs">
        <button class="tab-btn" data-period="7d">7 &#x434;&#x43D;&#x435;&#x439;</button>
        <button class="tab-btn active" data-period="30d">30 &#x434;&#x43D;&#x435;&#x439;</button>
        <button class="tab-btn" data-period="90d">90 &#x434;&#x43D;&#x435;&#x439;</button>
        <button class="tab-btn" data-period="all">&#x412;&#x441;&#x451; &#x432;&#x440;&#x435;&#x43C;&#x44F;</button>
    </div>
</div>

<!-- Channel Filter -->
<div class="card">
    <h2>&#x1F50D; &#x424;&#x438;&#x43B;&#x44C;&#x442;&#x440; &#x43F;&#x43E; &#x43A;&#x430;&#x43D;&#x430;&#x43B;&#x443;</h2>
    <div style="display:flex; flex-wrap:wrap; gap:10px; align-items:center;">
        <label style="font-weight:bold; margin-right:8px;">&#x41A;&#x430;&#x43D;&#x430;&#x43B;:</label>
        <select id="channel-select" style="min-width:220px; padding:10px; background:#333; border:1px solid #555; color:#ddd; border-radius:8px;">
            <option value="all">&#x412;&#x441;&#x435; &#x43A;&#x430;&#x43D;&#x430;&#x43B;&#x44B;</option>
            {% for ch in channels %}
            <option value="{{ ch['channel_id'] }}">{{ ch['channel_title'] or ch['channel_id'] }}</option>
            {% endfor %}
        </select>
        <div style="margin-left:auto; color:#bbb;">&#x412;&#x44B;&#x431;&#x440;&#x430;&#x43D; &#x43A;&#x430;&#x43D;&#x430;&#x43B;: <span id="selected-channel-name">&#x412;&#x441;&#x435; &#x43A;&#x430;&#x43D;&#x430;&#x43B;&#x44B;</span></div>
    </div>
</div>

<div class="card" id="channel-summary-card" style="display:none;">
    <h2>&#x1F4C8; &#x421;&#x442;&#x430;&#x442;&#x438;&#x441;&#x442;&#x438;&#x43A;&#x430; &#x43F;&#x43E; &#x432;&#x44B;&#x431;&#x440;&#x430;&#x43D;&#x43D;&#x43E;&#x43C;&#x443; &#x43A;&#x430;&#x43D;&#x430;&#x43B;&#x443;</h2>
    <div id="channel-summary" style="font-size:0.95em; color:#ddd;"></div>
</div>

<!-- Channel Performance Table (заполняется через JS) -->
<div class="card">
    <h2>&#x1F4CA; &#x41F;&#x440;&#x43E;&#x438;&#x437;&#x432;&#x43E;&#x434;&#x438;&#x442;&#x435;&#x43B;&#x44C;&#x43D;&#x43E;&#x441;&#x442;&#x44C; &#x43A;&#x430;&#x43D;&#x430;&#x43B;&#x43E;&#x432; (<span id="channel-period-label">30 &#x434;&#x43D;&#x435;&#x439;</span>)</h2>
    <div style="overflow-x:auto;">
        <table id="channel-table">
            <thead>
                <tr>
                    <th>&#x41A;&#x430;&#x43D;&#x430;&#x43B;</th>
                    <th>&#x412;&#x43B;&#x430;&#x434;&#x435;&#x43B;&#x435;&#x446;</th>
                    <th>&#x41F;&#x43E;&#x441;&#x442;&#x43E;&#x432;</th>
                    <th>&#x41A;&#x43B;&#x438;&#x43A;&#x438;</th>
                    <th>&#x41B;&#x438;&#x434;&#x44B;</th>
                    <th>CTR</th>
                    <th>&#x414;&#x43E;&#x445;&#x43E;&#x434; (&#x20BD;)</th>
                    <th>&#x41A;&#x43E;&#x43D;&#x432;&#x435;&#x440;&#x441;&#x438;&#x44F;</th>
                    <th>SubID</th>
                </tr>
            </thead>
            <tbody id="channel-table-body">
            </tbody>
        </table>
    </div>
</div>

<!-- Traffic Sources (SubID2) (заполняется через JS) -->
<div class="card">
    <h2>&#x1F3AF; &#x418;&#x441;&#x442;&#x43E;&#x447;&#x43D;&#x438;&#x43A;&#x438; &#x442;&#x440;&#x430;&#x444;&#x438;&#x43A;&#x430; (SubID2) &#x2014; <span id="subid2-period-label">30 &#x434;&#x43D;&#x435;&#x439;</span></h2>
    <p style="color:#aaa; margin-bottom:15px; font-size:0.9em;">SubID2 &#x43E;&#x442;&#x441;&#x43B;&#x435;&#x436;&#x438;&#x432;&#x430;&#x435;&#x442; &#x43E;&#x442;&#x434;&#x435;&#x43B;&#x44C;&#x43D;&#x44B;&#x435; &#x43F;&#x443;&#x431;&#x43B;&#x438;&#x43A;&#x430;&#x446;&#x438;&#x438;. &#x41F;&#x43E;&#x43A;&#x430;&#x437;&#x44B;&#x432;&#x430;&#x435;&#x442;, &#x43A;&#x430;&#x43A;&#x438;&#x435; &#x43A;&#x43E;&#x43D;&#x43A;&#x440;&#x435;&#x442;&#x43D;&#x44B;&#x435; &#x43F;&#x443;&#x431;&#x43B;&#x438;&#x43A;&#x430;&#x446;&#x438;&#x438; &#x43F;&#x440;&#x438;&#x43D;&#x43E;&#x441;&#x44F;&#x442; &#x43A;&#x43B;&#x438;&#x43A;&#x438; &#x438; &#x43B;&#x438;&#x434;&#x44B;.</p>
    <div style="overflow-x:auto;">
        <table id="subid2-table">
            <thead>
                <tr>
                    <th>SubID2 (&#x41F;&#x43E;&#x441;&#x442;)</th>
                    <th>&#x41A;&#x430;&#x43D;&#x430;&#x43B;</th>
                    <th>&#x41A;&#x43B;&#x438;&#x43A;&#x438;</th>
                    <th>&#x41B;&#x438;&#x434;&#x44B;</th>
                    <th>CTR</th>
                    <th>&#x414;&#x43E;&#x445;&#x43E;&#x434; (&#x20BD;)</th>
                    <th>&#x421;&#x442;&#x430;&#x442;&#x443;&#x441;</th>
                </tr>
            </thead>
            <tbody id="subid2-table-body">
            </tbody>
        </table>
    </div>
</div>

<!-- Charts Row -->
<div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">
    <div class="card">
        <h2>&#x1F4DD; &#x41F;&#x43E;&#x441;&#x442;&#x44B; &#x437;&#x430; {{ current_period_label }}</h2>
        <p id="chart-scope" style="margin-top:8px; color:#aaa;">&#x41F;&#x43E;&#x43A;&#x430;&#x437;&#x430;&#x43D;&#x44B; &#x434;&#x430;&#x43D;&#x43D;&#x44B;&#x435; &#x434;&#x43B;&#x44F; &#x432;&#x441;&#x435;&#x445; &#x43A;&#x430;&#x43D;&#x430;&#x43B;&#x43E;&#x432;.</p>
        <canvas id="postsChart" width="400" height="200"></canvas>
    </div>
    <div class="card">
        <h2>&#x1F4B0; &#x414;&#x43E;&#x445;&#x43E;&#x434; &#x437;&#x430; {{ current_period_label }}</h2>
        <canvas id="revenueChart" width="400" height="200"></canvas>
    </div>
</div>

<div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">
    <div class="card">
        <h2>&#x1F3EA; &#x41C;&#x430;&#x433;&#x430;&#x437;&#x438;&#x43D;&#x44B; &#x43F;&#x43E; &#x43F;&#x43E;&#x441;&#x442;&#x430;&#x43C; ({{ current_period_label }})</h2>
        <canvas id="storeChart" width="400" height="200"></canvas>
    </div>
    <div class="card">
        <h2>&#x1F3EA; &#x41C;&#x430;&#x433;&#x430;&#x437;&#x438;&#x43D;&#x44B; &#x43F;&#x43E; &#x434;&#x43E;&#x445;&#x43E;&#x434;&#x430;&#x43C; ({{ current_period_label }})</h2>
        <canvas id="storeRevenueChart" width="400" height="200"></canvas>
    </div>
</div>

<!-- Top Users (заполняется через JS) -->
<div class="card">
    <h2>&#x1F451; &#x422;&#x43E;&#x43F; &#x43F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x435;&#x439; &#x43F;&#x43E; &#x434;&#x43E;&#x445;&#x43E;&#x434;&#x443; (<span id="topusers-period-label">30 &#x434;&#x43D;&#x435;&#x439;</span>)</h2>
    <div style="overflow-x:auto;">
        <table id="top-users-table">
            <thead>
                <tr><th>&#x41F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44C;</th><th>&#x420;&#x43E;&#x43B;&#x44C;</th><th>&#x414;&#x43E;&#x445;&#x43E;&#x434; (&#x20BD;)</th><th>&#x422;&#x440;&#x430;&#x43D;&#x437;&#x430;&#x43A;&#x446;&#x438;&#x439;</th><th>&#x41F;&#x43E;&#x441;&#x442;&#x43E;&#x432;</th></tr>
            </thead>
            <tbody id="top-users-body">
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
                <p><b>&#x41F;&#x43E;&#x441;&#x442;&#x43E;&#x432; &#x437;&#x430; &#x43F;&#x435;&#x440;&#x438;&#x43E;&#x434;:</b> ${formatNumber(summary.posts_count)}</p>
                <p><b>&#x41A;&#x43B;&#x438;&#x43A;&#x438;:</b> ${formatNumber(summary.clicks)}</p>
                <p><b>&#x41B;&#x438;&#x434;&#x44B;:</b> ${formatNumber(summary.leads)}</p>
                <p><b>&#x414;&#x43E;&#x445;&#x43E;&#x434;:</b> ${formatMoney(summary.earnings)} &#x20BD;</p>
                <p><b>&#x41A;&#x43E;&#x43D;&#x432;&#x435;&#x440;&#x441;&#x438;&#x44F;:</b> ${summary.conversion.toFixed(1)}%</p>
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

        const title = data.selected_channel_title || '&#x412;&#x441;&#x435; &#x43A;&#x430;&#x43D;&#x430;&#x43B;&#x44B;';
        selectedChannelName.textContent = title;
        const label = data.current_period_label || data.period_label || '30 &#x434;&#x43D;&#x435;&#x439;';
        chartScope.textContent = currentChannelId === 'all' || !currentChannelId
            ? `&#x41F;&#x43E;&#x43A;&#x430;&#x437;&#x430;&#x43D;&#x44B; &#x434;&#x430;&#x43D;&#x43D;&#x44B;&#x435; &#x434;&#x43B;&#x44F; &#x432;&#x441;&#x435;&#x445; &#x43A;&#x430;&#x43D;&#x430;&#x43B;&#x43E;&#x432; (${label}).`
            : `&#x41F;&#x43E;&#x43A;&#x430;&#x437;&#x430;&#x43D;&#x44B; &#x434;&#x430;&#x43D;&#x43D;&#x44B;&#x435; &#x434;&#x43B;&#x44F; &#x43A;&#x430;&#x43D;&#x430;&#x43B;&#x430;: ${title} (${label}).`;

        // &#x41E;&#x431;&#x43D;&#x43E;&#x432;&#x43B;&#x44F;&#x435;&#x43C; &#x43F;&#x43E;&#x434;&#x43F;&#x438;&#x441;&#x438; &#x43F;&#x435;&#x440;&#x438;&#x43E;&#x434;&#x43E;&#x432; &#x432; &#x442;&#x430;&#x431;&#x43B;&#x438;&#x446;&#x430;&#x445;
        document.getElementById('channel-period-label').textContent = label;
        document.getElementById('subid2-period-label').textContent = label;
        document.getElementById('topusers-period-label').textContent = label;

        // &#x41E;&#x431;&#x43D;&#x43E;&#x432;&#x43B;&#x44F;&#x435;&#x43C; &#x442;&#x430;&#x431;&#x43B;&#x438;&#x446;&#x443; &#x43A;&#x430;&#x43D;&#x430;&#x43B;&#x43E;&#x432;
        const channelBody = document.getElementById('channel-table-body');
        if (channelBody && data.channel_stats) {
            channelBody.innerHTML = data.channel_stats.map(ch => {
                const ctr = ch.clicks > 0 ? ch.ctr.toFixed(1) : '0';
                const conv = ch.clicks > 0 ? ch.conversion.toFixed(1) : '0';
                const earningsClass = ch.earnings > 0 ? 'positive' : (ch.earnings < 0 ? 'negative' : '');
                return `<tr>
                    <td>${ch.channel_title || ch.channel_id}</td>
                    <td>${ch.username || ch.user_id}</td>
                    <td>${ch.posts_count}</td>
                    <td>${ch.clicks}</td>
                    <td>${ch.leads}</td>
                    <td>${ctr}%</td>
                    <td class="${earningsClass}">${ch.earnings.toFixed(2)}</td>
                    <td>${conv}%</td>
                    <td><code>${ch.channel_id}</code></td>
                </tr>`;
            }).join('');
        }

        // &#x41E;&#x431;&#x43D;&#x43E;&#x432;&#x43B;&#x44F;&#x435;&#x43C; &#x442;&#x430;&#x431;&#x43B;&#x438;&#x446;&#x443; SubID2
        const subid2Body = document.getElementById('subid2-table-body');
        if (subid2Body && data.subid2_stats) {
            subid2Body.innerHTML = data.subid2_stats.map(s => {
                const ctr = s.clicks > 0 ? s.ctr.toFixed(1) : '0';
                return `<tr>
                    <td><code>${s.subid2}</code></td>
                    <td>${s.channel_title || s.channel_id}</td>
                    <td>${s.clicks}</td>
                    <td>${s.leads}</td>
                    <td>${ctr}%</td>
                    <td>${s.earnings.toFixed(2)}</td>
                    <td>${s.status}</td>
                </tr>`;
            }).join('');
        }

        // &#x41E;&#x431;&#x43D;&#x43E;&#x432;&#x43B;&#x44F;&#x435;&#x43C; &#x442;&#x430;&#x431;&#x43B;&#x438;&#x446;&#x443; &#x442;&#x43E;&#x43F;-&#x43F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x435;&#x439;
        const topUsersBody = document.getElementById('top-users-body');
        if (topUsersBody && data.top_users) {
            topUsersBody.innerHTML = data.top_users.map(u => {
                return `<tr>
                    <td>${u.username || u.user_id}</td>
                    <td>${u.role}</td>
                    <td class="positive">${u.total_revenue.toFixed(2)}</td>
                    <td>${u.transactions}</td>
                    <td>${u.posts_count}</td>
                </tr>`;
            }).join('');
        }

        renderChannelSummary(data);

        // Posts Chart
        if (postsChart) postsChart.destroy();
        postsChart = new Chart(document.getElementById('postsChart'), {
            type: 'line',
            data: {
                labels: data.posts_labels,
                datasets: [{
                    label: '&#x41F;&#x43E;&#x441;&#x442;&#x44B;',
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
                        label: '&#x41E;&#x434;&#x43E;&#x431;&#x440;&#x435;&#x43D;&#x43E; (&#x20BD;)',
                        data: data.revenue_approved,
                        borderColor: '#4caf50',
                        backgroundColor: 'rgba(76,175,80,0.1)',
                        fill: true,
                    },
                    {
                        label: '&#x412; &#x43E;&#x436;&#x438;&#x434;&#x430;&#x43D;&#x438;&#x438; (&#x20BD;)',
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
                    label: '&#x41F;&#x43E;&#x441;&#x442;&#x43E;&#x432;',
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
                    label: '&#x414;&#x43E;&#x445;&#x43E;&#x434; (&#x20BD;)',
                    data: data.store_revenue_values,
                    backgroundColor: '#4caf50',
                }, {
                    label: '&#x422;&#x440;&#x430;&#x43D;&#x437;&#x430;&#x43A;&#x446;&#x438;&#x439;',
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
{% block title %}&#x41F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x438;{% endblock %}
{% block content %}
<h1>&#x1F465; &#x41F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x438;</h1>
<div class="card">
    <table>
        <tr><th>ID</th><th>&#x420;&#x43E;&#x43B;&#x44C;</th><th>&#x41F;&#x43E;&#x434;&#x43F;&#x438;&#x441;&#x43A;&#x430; &#x434;&#x43E;</th><th>&#x422;&#x430;&#x440;&#x438;&#x444;</th><th>&#x411;&#x430;&#x43B;&#x430;&#x43D;&#x441;</th><th>&#x414;&#x435;&#x439;&#x441;&#x442;&#x432;&#x438;&#x44F;</th></tr>
        {% for u in users %}
        <tr>
            <td>{{ u['user_id'] }}</td>
            <td>{{ u['role'] }}</td>
            <td>{{ u['subscription_until'] or '&#x2014;' }}</td>
            <td>{{ u['tariff_name'] or '&#x2014;' }}</td>
            <td>{{ u['balance_available'] or 0 }} &#x20BD;</td>
            <td><a href="/admin/users/edit/{{ u['user_id'] }}" class="btn">&#x418;&#x437;&#x43C;&#x435;&#x43D;&#x438;&#x442;&#x44C;</a></td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- USER EDIT ----------
USER_EDIT_TEMPLATE = '''{% extends "base.html" %}
{% block title %}&#x420;&#x435;&#x434;&#x430;&#x43A;&#x442;&#x438;&#x440;&#x43E;&#x432;&#x430;&#x43D;&#x438;&#x435; &#x43F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44F;{% endblock %}
{% block content %}
<h1>&#x270F;&#xFE0F; &#x41F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44C; #{{ user['user_id'] }}</h1>
<div class="card">
    <form method="post" action="/admin/users/edit/{{ user['user_id'] }}">
        <label>&#x420;&#x43E;&#x43B;&#x44C;:</label>
        <select name="role">
            <option value="saas" {{ 'selected' if user['role'] == 'saas' }}>SaaS</option>
            <option value="blogger" {{ 'selected' if user['role'] == 'blogger' }}>&#x411;&#x43B;&#x43E;&#x433;&#x435;&#x440;</option>
        </select>
        <label>&#x41F;&#x43E;&#x434;&#x43F;&#x438;&#x441;&#x43A;&#x430; &#x434;&#x43E; (UTC, &#x413;&#x413;&#x413;&#x413;-&#x41C;&#x41C;-&#x414;&#x414; &#x427;&#x427;:&#x41C;&#x41C;):</label>
        <input name="subscription_until" value="{{ user['subscription_until'] or '' }}" placeholder="2026-12-31 23:59">
        <label>&#x422;&#x430;&#x440;&#x438;&#x444;:</label>
        <select name="tariff_id">
            <option value="0" {{ 'selected' if not user['tariff_id'] }}>&#x411;&#x435;&#x437; &#x442;&#x430;&#x440;&#x438;&#x444;&#x430;</option>
            {% for t in tariffs %}
            <option value="{{ t['id'] }}" {{ 'selected' if user['tariff_id'] == t['id'] }}>{{ t['name'] }}</option>
            {% endfor %}
        </select>
        <label>&#x411;&#x430;&#x43B;&#x430;&#x43D;&#x441; &#x434;&#x43E;&#x441;&#x442;&#x443;&#x43F;&#x43D;&#x44B;&#x439;:</label>
        <input name="balance_available" value="{{ user['balance_available'] or 0 }}" type="number" step="0.01">
        <label>&#x411;&#x430;&#x43B;&#x430;&#x43D;&#x441; &#x43E;&#x436;&#x438;&#x434;&#x430;&#x44E;&#x449;&#x438;&#x439;:</label>
        <input name="balance_pending" value="{{ user['balance_pending'] or 0 }}" type="number" step="0.01">
        <button type="submit">&#x421;&#x43E;&#x445;&#x440;&#x430;&#x43D;&#x438;&#x442;&#x44C;</button>
    </form>
</div>
{% endblock %}'''

# ---------- POSTS LIST ----------
POSTS_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}&#x41F;&#x43E;&#x441;&#x442;&#x44B;{% endblock %}
{% block content %}
<h1>&#x1F4EC; &#x41F;&#x43E;&#x441;&#x442;&#x44B; (&#x43F;&#x43E;&#x441;&#x43B;&#x435;&#x434;&#x43D;&#x438;&#x435; 100 &#x43E;&#x43F;&#x443;&#x431;&#x43B;&#x438;&#x43A;&#x43E;&#x432;&#x430;&#x43D;&#x43D;&#x44B;&#x445;)</h1>
<form method="get" action="/admin/posts" style="margin-bottom:20px;">
    <label>&#x41F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44C; (ID):</label>
    <input name="user_id" value="{{ request.query_params.get('user_id', '') }}" placeholder="ID &#x43F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44F;">
    <button type="submit">&#x424;&#x438;&#x43B;&#x44C;&#x442;&#x440;</button>
</form>
<div class="card">
    <table id="posts-table">
        <tr><th>ID</th><th>&#x41F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44C;</th><th>&#x41A;&#x430;&#x43D;&#x430;&#x43B;</th><th>ERID</th><th>&#x421;&#x441;&#x44B;&#x43B;&#x43A;&#x430;</th><th>&#x421;&#x442;&#x430;&#x442;&#x443;&#x441;</th><th>&#x414;&#x430;&#x442;&#x430;</th></tr>
        {% for p in posts %}
        <tr data-photo="{{ p['photo_url'] or '' }}" 
            data-caption="{{ p['caption_text'] or '' | e }}" 
            data-channel="{{ p['channel_title'] or p['channel_id'] or '&#x2014;' }}" 
            data-link="{{ p['direct_link'] or '' }}" 
            style="cursor:pointer;">
            <td>{{ p['id'] }}</td>
            <td>{{ p['user_id'] }}</td>
            <td>{{ p['channel_id'] or '&#x2014;' }}</td>
            <td>{{ p['erid'] or '&#x2014;' }}</td>
            <td>{% if p['direct_link'] %}<a href="{{ p['direct_link'] }}" target="_blank" style="color:#4d6bfe;">&#x41E;&#x442;&#x43A;&#x440;&#x44B;&#x442;&#x44C;</a>{% else %}&#x2014;{% endif %}</td>
            <td>{{ p['status'] }}</td>
            <td>{{ p['published_at'] or p['created_at'] }}</td>
        </tr>
        {% endfor %}
    </table>
</div>

<div id="post-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); z-index:1000; justify-content:center; align-items:center;">
    <div style="background:#0f0f0f; border-radius:12px; max-width:400px; width:90%; overflow:hidden; color:#fff; font-family: 'Segoe UI', sans-serif; position:relative;">
        <span id="close-modal" style="position:absolute; top:8px; right:12px; color:#aaa; font-size:20px; cursor:pointer; z-index:10;">&#x2715;</span>
        <a id="modal-post-link" href="#" target="_blank" style="position:absolute; top:8px; right:40px; color:#4d6bfe; font-size:14px; cursor:pointer; z-index:10; text-decoration:none;">&#x1F517; Открыть</a>
        <div style="background:#1a1a1a; padding:10px 15px; display:flex; align-items:center;">
            <div style="background:#ff4444; border-radius:50%; width:32px; height:32px; display:flex; align-items:center; justify-content:center; margin-right:10px; font-weight:bold; font-size:14px;">#</div>
            <div id="modal-channel-title" style="font-weight:600; font-size:15px;">&#x41A;&#x430;&#x43D;&#x430;&#x43B;</div>
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

    const modalLink = document.getElementById('modal-post-link');

    document.querySelectorAll('#posts-table tr[data-photo]').forEach(row => {
        row.addEventListener('click', () => {
            const photo = row.getAttribute('data-photo');
            const caption = row.getAttribute('data-caption');
            const channel = row.getAttribute('data-channel') || '&#x41A;&#x430;&#x43D;&#x430;&#x43B;';
            const link = row.getAttribute('data-link') || '';
            modalLink.href = link || '#';
            modalLink.style.display = link ? 'block' : 'none';
            if (photo) {
                modalPhoto.src = photo;
                modalPhoto.style.display = 'block';
            } else {
                modalPhoto.style.display = 'none';
            }
            modalCaption.innerHTML = caption || '<i style="color:#888;">&#x422;&#x435;&#x43A;&#x441;&#x442; &#x43F;&#x43E;&#x441;&#x442;&#x430; &#x43E;&#x442;&#x441;&#x443;&#x442;&#x441;&#x442;&#x432;&#x443;&#x435;&#x442;</i>';
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
{% block title %}&#x41A;&#x430;&#x440;&#x430;&#x43D;&#x442;&#x438;&#x43D;{% endblock %}
{% block content %}
<h1>&#x1F6A8; &#x41A;&#x430;&#x440;&#x430;&#x43D;&#x442;&#x438;&#x43D;</h1>
<div class="card">
    <table>
        <tr><th>ID</th><th>&#x41F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44C;</th><th>&#x41A;&#x430;&#x43D;&#x430;&#x43B;</th><th>ERID</th><th>&#x41F;&#x440;&#x438;&#x447;&#x438;&#x43D;&#x430;</th><th></th></tr>
        {% for p in posts %}
        <tr>
            <td>{{ p['id'] }}</td>
            <td>{{ p['user_id'] }}</td>
            <td>{{ p['channel_id'] or '&#x2014;' }}</td>
            <td>{{ p['erid'] or '&#x2014;' }}</td>
            <td>{{ p['quarantine_reason'] }}</td>
            <td>
                <form method="post" action="/admin/quarantine/approve/{{ p['id'] }}" style="display:inline;">
                    <input name="erid" placeholder="ERID" required>
                    <input name="advertiser" placeholder="&#x420;&#x435;&#x43A;&#x43B;&#x430;&#x43C;&#x43E;&#x434;&#x430;&#x442;&#x435;&#x43B;&#x44C;">
                    <button type="submit">&#x41E;&#x434;&#x43E;&#x431;&#x440;&#x438;&#x442;&#x44C;</button>
                </form>
                <a href="/admin/quarantine/delete/{{ p['id'] }}" class="btn">&#x423;&#x434;&#x430;&#x43B;&#x438;&#x442;&#x44C;</a>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- BROADCAST ----------
BROADCAST_TEMPLATE = '''{% extends "base.html" %}
{% block title %}&#x420;&#x430;&#x441;&#x441;&#x44B;&#x43B;&#x43A;&#x430;{% endblock %}
{% block content %}
<h1>&#x1F4E3; &#x41C;&#x430;&#x441;&#x441;&#x43E;&#x432;&#x430;&#x44F; &#x440;&#x430;&#x441;&#x441;&#x44B;&#x43B;&#x43A;&#x430;</h1>
<div class="card">
    {% if message %}<p class="success">{{ message }}</p>{% endif %}
    <form method="post" action="/admin/broadcast">
        <textarea name="text" rows="5" placeholder="&#x422;&#x435;&#x43A;&#x441;&#x442; &#x441;&#x43E;&#x43E;&#x431;&#x449;&#x435;&#x43D;&#x438;&#x44F;..." required></textarea>
        <select name="role">
            <option value="all">&#x412;&#x441;&#x435;&#x43C;</option>
            <option value="saas">SaaS</option>
            <option value="blogger">&#x411;&#x43B;&#x43E;&#x433;&#x435;&#x440;&#x430;&#x43C;</option>
        </select>
        <button type="submit">&#x41E;&#x442;&#x43F;&#x440;&#x430;&#x432;&#x438;&#x442;&#x44C;</button>
    </form>
</div>
{% endblock %}'''

# ---------- PROMOCODES (STORE) ----------
PROMOCODES_TEMPLATE = '''{% extends "base.html" %}
{% block title %}&#x41A;&#x443;&#x43F;&#x43E;&#x43D;&#x44B; &#x43C;&#x430;&#x433;&#x430;&#x437;&#x438;&#x43D;&#x43E;&#x432;{% endblock %}
{% block content %}
<h1>&#x1F39F; &#x41A;&#x443;&#x43F;&#x43E;&#x43D;&#x44B; &#x43C;&#x430;&#x433;&#x430;&#x437;&#x438;&#x43D;&#x43E;&#x432;</h1>
<div class="card">
    <h2>&#x414;&#x43E;&#x431;&#x430;&#x432;&#x438;&#x442;&#x44C;</h2>
    <form method="post" action="/admin/promocodes/add">
        <input name="store" placeholder="&#x41C;&#x430;&#x433;&#x430;&#x437;&#x438;&#x43D;" required>
        <input name="promocode" placeholder="&#x41F;&#x440;&#x43E;&#x43C;&#x43E;&#x43A;&#x43E;&#x434;" required>
        <input name="description" placeholder="&#x41E;&#x43F;&#x438;&#x441;&#x430;&#x43D;&#x438;&#x435;">
        <button type="submit">&#x414;&#x43E;&#x431;&#x430;&#x432;&#x438;&#x442;&#x44C;</button>
    </form>
</div>
<div class="card">
    <h2>&#x421;&#x43F;&#x438;&#x441;&#x43E;&#x43A;</h2>
    <table>
        <tr><th>&#x41C;&#x430;&#x433;&#x430;&#x437;&#x438;&#x43D;</th><th>&#x41A;&#x43E;&#x434;</th><th>&#x41E;&#x43F;&#x438;&#x441;&#x430;&#x43D;&#x438;&#x435;</th><th></th></tr>
        {% for p in promos %}
        <tr><td>{{ p['store'] }}</td><td><code>{{ p['promocode'] }}</code></td><td>{{ p['description'] }}</td><td><a href="/admin/promocodes/delete/{{ p['id'] }}">&#x423;&#x434;&#x430;&#x43B;&#x438;&#x442;&#x44C;</a></td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- STORE DELIVERY ----------
STORE_DELIVERY_TEMPLATE = '''{% extends "base.html" %}
{% block title %}&#x414;&#x43E;&#x441;&#x442;&#x430;&#x432;&#x43A;&#x430;{% endblock %}
{% block content %}
<h1>&#x1F69A; &#x414;&#x43E;&#x441;&#x442;&#x430;&#x432;&#x43A;&#x430;</h1>
<div class="card">
    <h2>&#x41E;&#x431;&#x43D;&#x43E;&#x432;&#x438;&#x442;&#x44C;</h2>
    <form method="post" action="/admin/store_delivery/update">
        <input name="store" placeholder="&#x41C;&#x430;&#x433;&#x430;&#x437;&#x438;&#x43D;" required>
        <input name="delivery_text" placeholder="&#x423;&#x441;&#x43B;&#x43E;&#x432;&#x438;&#x44F;" required>
        <button type="submit">&#x421;&#x43E;&#x445;&#x440;&#x430;&#x43D;&#x438;&#x442;&#x44C;</button>
    </form>
</div>
<div class="card">
    <h2>&#x422;&#x435;&#x43A;&#x443;&#x449;&#x438;&#x435; &#x434;&#x430;&#x43D;&#x43D;&#x44B;&#x435;</h2>
    <table>
        <tr><th>&#x41C;&#x430;&#x433;&#x430;&#x437;&#x438;&#x43D;</th><th>&#x423;&#x441;&#x43B;&#x43E;&#x432;&#x438;&#x44F;</th></tr>
        {% for d in deliveries %}
        <tr><td>{{ d['store'] }}</td><td>{{ d['delivery_text'] }}</td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- BULK ACTIONS ----------
BULK_ACTIONS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}&#x41C;&#x430;&#x441;&#x441;&#x43E;&#x432;&#x44B;&#x435; &#x434;&#x435;&#x439;&#x441;&#x442;&#x432;&#x438;&#x44F;{% endblock %}
{% block content %}
<h1>&#x1F465; &#x41C;&#x430;&#x441;&#x441;&#x43E;&#x432;&#x44B;&#x435; &#x434;&#x435;&#x439;&#x441;&#x442;&#x432;&#x438;&#x44F;</h1>

<!-- Поиск пользователей -->
<div class="card">
    <h2>&#x1F50D; &#x412;&#x44B;&#x431;&#x43E;&#x440; &#x43F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x435;&#x439; (&#x43F;&#x43E; &#x43A;&#x43E;&#x43D;&#x43A;&#x440;&#x435;&#x442;&#x43D;&#x44B;&#x43C; ID / username)</h2>
    <div style="display:flex; gap:10px; margin-bottom:10px;">
        <input type="text" id="user-search" placeholder="ID: 123456 &#x438;&#x43B;&#x438; @username" style="flex:1; padding:8px; background:#1a1a2e; color:#fff; border:1px solid #333; border-radius:6px;">
        <button type="button" id="search-btn" style="background:#ff4444; color:white; border:none; padding:8px 16px; border-radius:6px; cursor:pointer;">&#x1F50D; &#x41D;&#x430;&#x439;&#x442;&#x438;</button>
    </div>
    <div id="user-results" style="max-height:250px; overflow-y:auto; display:none; border:1px solid #333; border-radius:6px; margin-bottom:10px;"></div>
    <div id="selected-users" style="display:flex; flex-wrap:wrap; gap:5px;"></div>
    <input type="hidden" id="selected-user-ids" value="">
    <p style="color:#888; font-size:0.85em; margin-top:8px;">&#x415;&#x441;&#x43B;&#x438; &#x43D;&#x438;&#x447;&#x435;&#x433;&#x43E; &#x43D;&#x435; &#x432;&#x44B;&#x431;&#x440;&#x430;&#x43D;&#x43E; &#x2014; &#x434;&#x435;&#x439;&#x441;&#x442;&#x432;&#x438;&#x435; &#x43F;&#x43E; &#x433;&#x440;&#x443;&#x43F;&#x43F;&#x435; &#x438;&#x437; &#x441;&#x43F;&#x438;&#x441;&#x43A;&#x430; &#x432;&#x44B;&#x448;&#x435;.</p>
</div>

<!-- Основные массовые действия -->
<div class="card">
    <h2>&#x2699;&#xFE0F; &#x414;&#x435;&#x439;&#x441;&#x442;&#x432;&#x438;&#x44F; &#x441; &#x43F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44F;&#x43C;&#x438;</h2>
    <form method="post" action="/admin/bulk-actions/execute" onsubmit="syncUserIds(this)">
        <input type="hidden" name="user_ids" value="">
        <label>&#x413;&#x440;&#x443;&#x43F;&#x43F;&#x430; &#x43F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x435;&#x439;:</label>
        <select name="group">
            <option value="all">&#x412;&#x441;&#x435;</option>
            <option value="saas">SaaS</option>
            <option value="blogger">&#x411;&#x43B;&#x43E;&#x433;&#x435;&#x440;&#x44B;</option>
            <option value="active">&#x410;&#x43A;&#x442;&#x438;&#x432;&#x43D;&#x44B;&#x435;</option>
            <option value="banned">&#x417;&#x430;&#x431;&#x430;&#x43D;&#x435;&#x43D;&#x43D;&#x44B;&#x435;</option>
            <option value="with_balance">&#x421; &#x431;&#x430;&#x43B;&#x430;&#x43D;&#x441;&#x43E;&#x43C;</option>
            <option value="no_posts">&#x411;&#x435;&#x437; &#x43F;&#x43E;&#x441;&#x442;&#x43E;&#x432;</option>
            <option value="beta">&#x411;&#x435;&#x442;&#x430;-&#x442;&#x435;&#x441;&#x442;&#x435;&#x440;&#x44B;</option>
        </select>
        <input type="hidden" name="action" id="bulk-action-input" value="activate">
        <div style="display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:10px; margin-top:10px;">
            <button type="button" onclick="setBulkAction('activate')">&#x410;&#x43A;&#x442;&#x438;&#x432;&#x438;&#x440;&#x43E;&#x432;&#x430;&#x442;&#x44C;</button>
            <button type="button" onclick="setBulkAction('deactivate')">&#x414;&#x435;&#x430;&#x43A;&#x442;&#x438;&#x432;&#x438;&#x440;&#x43E;&#x432;&#x430;&#x442;&#x44C;</button>
            <button type="button" onclick="setBulkAction('reset_balance')">&#x41E;&#x431;&#x43D;&#x443;&#x43B;&#x438;&#x442;&#x44C; &#x431;&#x430;&#x43B;&#x430;&#x43D;&#x441;</button>
            <button type="button" onclick="setBulkAction('add_balance')">&#x41D;&#x430;&#x447;&#x438;&#x441;&#x43B;&#x438;&#x442;&#x44C; &#x431;&#x430;&#x43B;&#x430;&#x43D;&#x441;</button>
            <button type="button" onclick="setBulkAction('set_commission')">&#x423;&#x441;&#x442;&#x430;&#x43D;&#x43E;&#x432;&#x438;&#x442;&#x44C; &#x43A;&#x43E;&#x43C;&#x438;&#x441;&#x441;&#x438;&#x44E;</button>
            <button type="button" onclick="setBulkAction('add_beta')">&#x414;&#x43E;&#x431;&#x430;&#x432;&#x438;&#x442;&#x44C; &#x432; &#x431;&#x435;&#x442;&#x430;</button>
            <button type="button" onclick="setBulkAction('remove_beta')">&#x423;&#x431;&#x440;&#x430;&#x442;&#x438;&#x442;&#x44C; &#x438;&#x437; &#x431;&#x435;&#x442;&#x430;</button>
            <button type="button" onclick="setBulkAction('delete')" style="background:#c62828;">&#x423;&#x434;&#x430;&#x43B;&#x438;&#x442;&#x44C;</button>
        </div>
        <p style="color:#aaa; font-size:0.95em;">&#x422;&#x435;&#x43A;&#x443;&#x449;&#x430;&#x44F; &#x43E;&#x43F;&#x435;&#x440;&#x430;&#x446;&#x438;&#x44F;: <span id="current-bulk-action">&#x410;&#x43A;&#x442;&#x438;&#x432;&#x438;&#x440;&#x43E;&#x432;&#x430;&#x442;&#x44C;</span></p>
        <div id="value-section">
            <label>&#x417;&#x43D;&#x430;&#x447;&#x435;&#x43D;&#x438;&#x435; (&#x441;&#x443;&#x43C;&#x43BC;&#x430; &#x434;&#x43B;&#x44F; &#x431;&#x430;&#x43B;&#x430;&#x43D;&#x441;&#x430;, 0&#x2013;1 &#x434;&#x43B;&#x44F; &#x43A;&#x43E;&#x43C;&#x438;&#x441;&#x441;&#x438;&#x438;):</label>
            <input name="value" id="bulk-value-input" value="0" type="number" step="0.01">
        </div>
        <button type="submit" style="margin-top:10px;">&#x412;&#x44B;&#x43F;&#x43E;&#x43B;&#x43D;&#x438;&#x442;&#x44C;</button>
    </form>
</div>

<!-- Отправка сообщения группе -->
<div class="card">
    <h2>&#x1F4AC; &#x41E;&#x442;&#x43F;&#x440;&#x430;&#x432;&#x438;&#x442;&#x44C; &#x441;&#x43E;&#x43E;&#x431;&#x449;&#x435;&#x43D;&#x438;&#x435; &#x433;&#x440;&#x443;&#x43F;&#x43F;&#x435;</h2>
    <form method="post" action="/admin/bulk-actions/send-message" onsubmit="syncUserIds(this)">
        <input type="hidden" name="user_ids" value="">
        <label>&#x413;&#x440;&#x443;&#x43F;&#x43F;&#x430;:</label>
        <select name="group">
            <option value="all">&#x412;&#x441;&#x435;</option>
            <option value="saas">SaaS</option>
            <option value="blogger">&#x411;&#x43B;&#x43E;&#x433;&#x435;&#x440;&#x44B;</option>
            <option value="active">&#x410;&#x43A;&#x442;&#x438;&#x432;&#x43D;&#x44B;&#x435;</option>
            <option value="with_balance">&#x421; &#x431;&#x430;&#x43B;&#x430;&#x43D;&#x441;&#x43E;&#x43C;</option>
            <option value="no_posts">&#x411;&#x435;&#x437; &#x43F;&#x43E;&#x441;&#x442;&#x43E;&#x432;</option>
            <option value="beta">&#x411;&#x435;&#x442;&#x430;-&#x442;&#x435;&#x441;&#x442;&#x435;&#x440;&#x44B;</option>
        </select>
        <label>&#x422;&#x435;&#x43A;&#x441;&#x442; &#x441;&#x43E;&#x43E;&#x431;&#x449;&#x435;&#x43D;&#x438;&#x44F;:</label>
        <textarea name="text" rows="3" style="width:100%; background:#1a1a2e; color:#fff; border:1px solid #333; border-radius:6px; padding:8px;" placeholder="Введите сообщение..."></textarea>
        <button type="submit" style="margin-top:10px;">&#x1F4E4; &#x41E;&#x442;&#x43F;&#x440;&#x430;&#x432;&#x438;&#x442;&#x44C;</button>
    </form>
</div>

<!-- Экспорт CSV -->
<div class="card">
    <h2>&#x1F4E5; &#x42D;&#x43A;&#x441;&#x43F;&#x43E;&#x440;&#x442; &#x43F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x435;&#x439; (CSV)</h2>
    <div style="display:flex; gap:8px; flex-wrap:wrap;">
        <a href="/admin/bulk-actions/export-csv?group=all" class="button">&#x412;&#x441;&#x435;</a>
        <a href="/admin/bulk-actions/export-csv?group=saas" class="button">SaaS</a>
        <a href="/admin/bulk-actions/export-csv?group=blogger" class="button">&#x411;&#x43B;&#x43E;&#x433;&#x435;&#x440;&#x44B;</a>
        <a href="/admin/bulk-actions/export-csv?group=active" class="button">&#x410;&#x43A;&#x442;&#x438;&#x432;&#x43D;&#x44B;&#x435;</a>
        <a href="/admin/bulk-actions/export-csv?group=with_balance" class="button">&#x421; &#x431;&#x430;&#x43B;&#x430;&#x43D;&#x441;&#x43E;&#x43C;</a>
        <a href="/admin/bulk-actions/export-csv?group=no_posts" class="button">&#x411;&#x435;&#x437; &#x43F;&#x43E;&#x441;&#x442;&#x43E;&#x432;</a>
        <a href="/admin/bulk-actions/export-csv?group=beta" class="button">&#x411;&#x435;&#x442;&#x430;</a>
    </div>
</div>

{% if message %}<div class="card" style="border:1px solid #4caf50;"><p style="color:#4caf50;">{{ message }}</p></div>{% endif %}

<script>
function setBulkAction(action) {
    const actionInput = document.getElementById('bulk-action-input');
    const current = document.getElementById('current-bulk-action');
    const valueSection = document.getElementById('value-section');
    actionInput.value = action;
    const labels = {
        activate: 'Активировать',
        deactivate: 'Деактивировать',
        reset_balance: 'Обнулить баланс',
        add_balance: 'Начислить баланс',
        set_commission: 'Установить комиссию',
        add_beta: 'Добавить в бета',
        remove_beta: 'Убрать из бета',
        delete: 'Удалить'
    };
    current.textContent = labels[action] || action;
    valueSection.style.display = (action === 'add_balance' || action === 'set_commission') ? 'block' : 'none';
}
setBulkAction('activate');

const selectedUsers = {};
function syncUserIds(form) {
    const ids = Object.keys(selectedUsers).join(',');
    const hidden = form.querySelector('input[name="user_ids"]');
    if (hidden) hidden.value = ids;
}

document.getElementById('search-btn').addEventListener('click', async () => {
    const q = document.getElementById('user-search').value.trim();
    if (!q) return;
    const box = document.getElementById('user-results');
    box.style.display = 'block';
    box.innerHTML = '<p style="color:#888; padding:8px;">&#x417;&#x430;&#x433;&#x440;&#x443;&#x437;&#x43A;&#x430;...</p>';
    try {
        const resp = await fetch(`/admin/bulk-actions/users?q=${encodeURIComponent(q)}`);
        const data = await resp.json();
        if (!data.users || data.users.length === 0) {
            box.innerHTML = '<p style="color:#888; padding:8px;">&#x41D;&#x438;&#x447;&#x435;&#x433;&#x43E; &#x43D;&#x435; &#x43D;&#x430;&#x439;&#x434;&#x435;&#x43D;&#x43E;</p>';
            return;
        }
        box.innerHTML = data.users.map(u => {
            const id = u.user_id;
            const checked = selectedUsers[id] ? 'checked' : '';
            const name = u.username ? `@${u.username}` : u.user_id;
            const role = u.role || '';
            return `<label style="display:flex; align-items:center; gap:8px; padding:8px; cursor:pointer; border-bottom:1px solid #222;">
                <input type="checkbox" ${checked} onchange="toggleUser(${id}, '${(u.username||'').replace(/'/g,"\\'")}', ${id}, '${role}')">
                <span><b>${name}</b> <span style="color:#888;">(${id})</span> <span style="color:#666;">${role}</span></span>
            </label>`;
        }).join('');
    } catch(e) {
        box.innerHTML = '<p style="color:#ff4444; padding:8px;">&#x41E;&#x448;&#x438;&#x431;&#x43A;&#x430;</p>';
    }
});

function toggleUser(id, username, userId, role) {
    if (selectedUsers[id]) {
        delete selectedUsers[id];
    } else {
        selectedUsers[id] = {username, userId, role};
    }
    renderSelected();
}

function removeUser(id) {
    delete selectedUsers[id];
    renderSelected();
}

function renderSelected() {
    const box = document.getElementById('selected-users');
    const ids = Object.keys(selectedUsers);
    document.getElementById('selected-user-ids').value = ids.join(',');
    if (ids.length === 0) {
        box.innerHTML = '';
        return;
    }
    box.innerHTML = ids.map(id => {
        const u = selectedUsers[id];
        const name = u.username ? `@${u.username}` : id;
        return `<span style="display:inline-flex;align-items:center;gap:4px;background:#333;border:1px solid #555;border-radius:16px;padding:4px 10px;margin:3px;font-size:0.9em;">${name} <button type="button" onclick="removeUser('${id}')" style="background:none;border:none;color:#ff4444;cursor:pointer;font-size:1.1em;">&times;</button></span>`;
    }).join('');
}
</script>
{% endblock %}'''

# ---------- SETTINGS ----------
SETTINGS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}&#x413;&#x43B;&#x43E;&#x431;&#x430;&#x43B;&#x44C;&#x43D;&#x44B;&#x435; &#x43D;&#x430;&#x441;&#x442;&#x440;&#x43E;&#x439;&#x43A;&#x438;{% endblock %}
{% block content %}
<h1>&#x2699;&#xFE0F; &#x413;&#x43B;&#x43E;&#x431;&#x430;&#x43B;&#x44C;&#x43D;&#x44B;&#x435; &#x43D;&#x430;&#x441;&#x442;&#x440;&#x43E;&#x439;&#x43A;&#x438;</h1>
<div class="card">
    <form method="post" action="/admin/settings-edit/save">
        <label>&#x41D;&#x43E;&#x447;&#x43D;&#x43E;&#x439; &#x440;&#x435;&#x436;&#x438;&#x43C;, &#x43D;&#x430;&#x447;&#x430;&#x43B;&#x43E; (HH:MM):</label>
        <input name="night_start" value="{{ settings.get('night_start', '23:00') }}">
        <label>&#x41D;&#x43E;&#x447;&#x43D;&#x43E;&#x439; &#x440;&#x435;&#x436;&#x438;&#x43C;, &#x43A;&#x43E;&#x43D;&#x435;&#x446; (HH:MM):</label>
        <input name="night_end" value="{{ settings.get('night_end', '08:00') }}">
        <label>&#x418;&#x43D;&#x442;&#x435;&#x440;&#x432;&#x430;&#x43B; &#x441;&#x43A;&#x430;&#x43D;&#x438;&#x440;&#x43E;&#x432;&#x430;&#x43D;&#x438;&#x44F; (&#x441;&#x435;&#x43A;):</label>
        <input name="run_interval" value="{{ settings.get('run_interval', '900') }}" type="number">
        <label>&#x41C;&#x438;&#x43D;&#x438;&#x43C;&#x430;&#x43B;&#x44C;&#x43D;&#x430;&#x44F; &#x432;&#x44B;&#x43F;&#x43B;&#x430;&#x442;&#x430; (RUB):</label>
        <input name="min_payout" value="{{ settings.get('min_payout', '2000') }}" type="number">
        <label>&#x41A;&#x43E;&#x43C;&#x438;&#x441;&#x441;&#x438;&#x44F; &#x431;&#x430;&#x43D;&#x43A;&#x430; (%):</label>
        <input name="payout_bank_pct" value="{{ settings.get('payout_bank_pct', '0.043') }}" step="0.001">
        <button type="submit">&#x421;&#x43E;&#x445;&#x440;&#x430;&#x43D;&#x438;&#x442;&#x44C;</button>
    </form>
</div>

<!-- ===== &#x41D;&#x41E;&#x412;&#x42B;&#x419; &#x411;&#x41B;&#x41E;&#x41A;: &#x423;&#x43F;&#x440;&#x430;&#x432;&#x43B;&#x435;&#x43D;&#x438;&#x435; &#x444;&#x438;&#x447;&#x430;&#x43C;&#x438; ===== -->
<div class="card">
    <h2>&#x1F3AF; &#x423;&#x43F;&#x440;&#x430;&#x432;&#x43B;&#x435;&#x43D;&#x438;&#x435; &#x444;&#x438;&#x447;&#x430;&#x43C;&#x438;</h2>
    <table>
        <tr><th>&#x424;&#x438;&#x447;&#x430;</th><th>&#x421;&#x442;&#x430;&#x442;&#x443;&#x441;</th><th>&#x414;&#x435;&#x439;&#x441;&#x442;&#x432;&#x438;&#x44F;</th></tr>
        {% for feature in features %}
        <tr>
            <td><b>{{ feature['name'] }}</b></td>
            <td>
                <span style="padding:4px 12px; border-radius:4px; font-weight:bold;
                    {% if feature['status'] == 'released' %}background:#4caf50; color:white;{% endif %}
                    {% if feature['status'] == 'beta' %}background:#ff9800; color:white;{% endif %}
                    {% if feature['status'] == 'dev' %}background:#999; color:white;{% endif %}">
                    {% if feature['status'] == 'released' %}&#x412;&#x44B;&#x43F;&#x443;&#x449;&#x435;&#x43D;&#x43E;{% elif feature['status'] == 'beta' %}&#x411;&#x435;&#x442;&#x430;{% else %}&#x412; &#x440;&#x430;&#x437;&#x440;&#x430;&#x431;&#x43E;&#x442;&#x43A;&#x435;{% endif %}
                </span>
            </td>
            <td>
                <form method="post" action="/admin/settings/feature-status" style="display:flex; gap:5px;">
                    <input type="hidden" name="feature_name" value="{{ feature['name'] }}">
                    {% if feature['status'] != 'dev' %}
                    <button type="submit" name="status" value="dev" style="background:#999; padding:5px 10px; font-size:0.9em;">&#x2192; &#x412; &#x440;&#x430;&#x437;&#x440;&#x430;&#x431;&#x43E;&#x442;&#x43A;&#x435;</button>
                    {% endif %}
                    {% if feature['status'] != 'beta' %}
                    <button type="submit" name="status" value="beta" style="background:#ff9800; padding:5px 10px; font-size:0.9em;">&#x2192; &#x411;&#x435;&#x442;&#x430;</button>
                    {% endif %}
                    {% if feature['status'] != 'released' %}
                    <button type="submit" name="status" value="released" style="background:#4caf50; padding:5px 10px; font-size:0.9em;">&#x2192; &#x412;&#x44B;&#x43F;&#x443;&#x449;&#x435;&#x43D;&#x43E;</button>
                    {% endif %}
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
    <p style="font-size: 0.85em; color: #888; margin-top: 10px;">
        <b>&#x412; &#x440;&#x430;&#x437;&#x440;&#x430;&#x431;&#x43E;&#x442;&#x43A;&#x435;</b> &#x2014; &#x441;&#x43A;&#x440;&#x44B;&#x442;&#x43E; &#x43E;&#x442; &#x432;&#x441;&#x435;&#x445;<br>
        <b>&#x411;&#x435;&#x442;&#x430;</b> &#x2014; &#x432;&#x438;&#x434;&#x44F;&#x442; &#x442;&#x43E;&#x43B;&#x44C;&#x43A;&#x43E; &#x431;&#x435;&#x442;&#x430;-&#x442;&#x435;&#x441;&#x442;&#x435;&#x440;&#x44B;<br>
        <b>&#x412;&#x44B;&#x43F;&#x443;&#x449;&#x435;&#x43D;&#x43E;</b> &#x2014; &#x434;&#x43E;&#x441;&#x442;&#x443;&#x43F;&#x43D;&#x430; &#x432;&#x441;&#x435;&#x43C; &#x43F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44F;&#x43C;
    </p>
</div>

<!-- ===== &#x411;&#x41B;&#x41E;&#x41A;: &#x411;&#x435;&#x442;&#x430;-&#x442;&#x435;&#x441;&#x442;&#x435;&#x440;&#x44B; ===== -->
<div class="card">
    <h2>&#x1F52C; &#x411;&#x435;&#x442;&#x430;-&#x442;&#x435;&#x441;&#x442;&#x435;&#x440;&#x44B;</h2>
    <p>&#x422;&#x435;&#x43A;&#x443;&#x449;&#x438;&#x435; &#x431;&#x435;&#x442;&#x430;-&#x442;&#x435;&#x441;&#x442;&#x435;&#x440;&#x44B; ({{ beta_testers|length }}):</p>
    <table>
        <tr><th>ID</th><th>Username</th><th></th></tr>
        {% for tester in beta_testers %}
        <tr>
            <td>{{ tester['user_id'] }}</td>
            <td>{{ tester['username'] or '&#x2014;' }}</td>
            <td>
                <form method="post" action="/admin/settings/beta-remove" style="display:inline;">
                    <input type="hidden" name="user_id" value="{{ tester['user_id'] }}">
                    <button type="submit" style="background:#f44336; padding:5px 15px; font-size:0.9em;">&#x423;&#x434;&#x430;&#x43B;&#x438;&#x442;&#x44C;</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
    
    <p style="margin-top: 20px;"><b>&#x414;&#x43E;&#x431;&#x430;&#x432;&#x438;&#x442;&#x44C; &#x43D;&#x43E;&#x432;&#x43E;&#x433;&#x43E; &#x442;&#x435;&#x441;&#x442;&#x435;&#x440;&#x430;:</b></p>
    <form method="post" action="/admin/settings/beta-add" style="display:flex; gap:10px;">
        <input type="number" name="user_id" placeholder="ID &#x43F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44F;" required style="width:150px;">
        <button type="submit">&#x414;&#x43E;&#x431;&#x430;&#x432;&#x438;&#x442;&#x44C;</button>
    </form>
</div>
{% endblock %}'''

# ---------- AUDIT ----------
AUDIT_TEMPLATE = '''{% extends "base.html" %}
{% block title %}&#x410;&#x443;&#x434;&#x438;&#x442;{% endblock %}
{% block content %}
<h1>&#x1F4DC; &#x410;&#x443;&#x434;&#x438;&#x442; (&#x43F;&#x43E;&#x441;&#x43B;&#x435;&#x434;&#x43D;&#x438;&#x435; 200)</h1>
<div class="card">
    <table>
        <tr><th>&#x410;&#x434;&#x43C;&#x438;&#x43D;</th><th>&#x414;&#x435;&#x439;&#x441;&#x442;&#x432;&#x438;&#x435;</th><th>&#x414;&#x435;&#x442;&#x430;&#x43B;&#x438;</th><th>&#x414;&#x430;&#x442;&#x430;</th></tr>
        {% for a in audits %}
        <tr><td>{{ a['admin_id'] }}</td><td>{{ a['action'] }}</td><td>{{ a['details'] }}</td><td>{{ a['created_at'] }}</td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- REPORTS ----------
REPORTS_TEMPLATE = '''{% extends "base.html" %}
{% block title %}&#x415;&#x436;&#x435;&#x434;&#x43D;&#x435;&#x432;&#x43D;&#x44B;&#x435; &#x43E;&#x442;&#x447;&#x451;&#x442;&#x44B;{% endblock %}
{% block content %}
<h1>&#x1F4C1; &#x41E;&#x442;&#x447;&#x451;&#x442;&#x44B;</h1>

<div class="card">
    <h2>&#x415;&#x436;&#x435;&#x434;&#x43D;&#x435;&#x432;&#x43D;&#x44B;&#x435; &#x444;&#x430;&#x439;&#x43B;&#x44B; (CSV)</h2>
    <table>
        <tr><th>&#x418;&#x43C;&#x44F; &#x444;&#x430;&#x439;&#x43B;&#x430;</th><th></th></tr>
        {% for f in files %}
        <tr><td>{{ f }}</td><td><a href="/admin/reports/download/{{ f }}" class="btn">&#x421;&#x43A;&#x430;&#x447;&#x430;&#x442;&#x44C;</a></td></tr>
        {% endfor %}
    </table>
</div>

<div class="card" style="margin-top:30px;">
    <h2>&#x424;&#x438;&#x43D;&#x430;&#x43D;&#x441;&#x43E;&#x432;&#x44B;&#x435; &#x438; &#x430;&#x43D;&#x430;&#x43B;&#x438;&#x442;&#x438;&#x447;&#x435;&#x441;&#x43A;&#x438;&#x435; &#x43E;&#x442;&#x447;&#x451;&#x442;&#x44B;</h2>
    <p><a href="/admin/payouts/csv" class="btn">&#x421;&#x43A;&#x430;&#x447;&#x430;&#x442;&#x44C; &#x438;&#x441;&#x442;&#x43E;&#x440;&#x438;&#x44E; &#x432;&#x44B;&#x43F;&#x43B;&#x430;&#x442; (CSV)</a></p>
    <p><a href="/admin/subid-stats/csv" class="btn">&#x421;&#x43A;&#x430;&#x447;&#x430;&#x442;&#x44C; &#x441;&#x442;&#x430;&#x442;&#x438;&#x441;&#x442;&#x438;&#x43A;&#x443; SubID (CSV)</a></p>
    <p><a href="/admin/referrals/csv" class="btn">&#x421;&#x43A;&#x430;&#x447;&#x430;&#x442;&#x44C; &#x440;&#x435;&#x444;&#x435;&#x440;&#x430;&#x43B;&#x44C;&#x43D;&#x44B;&#x435; &#x441;&#x432;&#x44F;&#x437;&#x438; (CSV)</a></p>
</div>
{% endblock %}'''

# ---------- ADMIN PAYOUTS ----------
ADMIN_PAYOUTS_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}&#x412;&#x44B;&#x43F;&#x43B;&#x430;&#x442;&#x44B;{% endblock %}
{% block content %}
<h1>&#x1F4B0; &#x412;&#x44B;&#x43F;&#x43B;&#x430;&#x442;&#x44B;</h1>

<div class="card">
    <h2>&#x417;&#x430;&#x43F;&#x440;&#x43E;&#x441;&#x44B; &#x43D;&#x430; &#x432;&#x44B;&#x43F;&#x43B;&#x430;&#x442;&#x443;</h2>
    <table>
        <tr><th>ID</th><th>&#x41F;&#x43E;&#x43B;&#x44C;&#x437;&#x43E;&#x432;&#x430;&#x442;&#x435;&#x43B;&#x44C;</th><th>&#x421;&#x443;&#x43C;&#x43C;&#x430;</th><th>&#x421;&#x442;&#x430;&#x442;&#x443;&#x441;</th><th></th></tr>
        {% for r in requests %}
        <tr>
            <td>{{ r['id'] }}</td>
            <td>{{ r['user_id'] }}</td>
            <td>{{ r['amount'] }} &#x20BD;</td>
            <td>{{ r['status'] }}</td>
            <td><a href="/admin/payouts/{{ r['id'] }}/chat" class="btn">&#x1F4AC; &#x427;&#x430;&#x442;</a></td>
        </tr>
        {% endfor %}
    </table>
</div>

<div class="card">
    <h2>&#x414;&#x43E;&#x441;&#x442;&#x443;&#x43F;&#x43D;&#x43E; &#x43A; &#x432;&#x44B;&#x43F;&#x43B;&#x430;&#x442;&#x435;</h2>
    <table>
        <tr><th>ID</th><th>&#x420;&#x43E;&#x43B;&#x44C;</th><th>Username</th><th>&#x414;&#x43E;&#x441;&#x442;&#x443;&#x43F;&#x43D;&#x43E;</th><th></th></tr>
        {% for u in users %}
        <tr>
            <td>{{ u['user_id'] }}</td>
            <td>{{ u['role'] }}</td>
            <td>{{ u['username'] or '&#x2014;' }}</td>
            <td>{{ u['balance_available'] }} &#x20BD;</td>
            <td>
                <form method="post" action="/admin/payouts/pay" style="display:inline;">
                    <input type="hidden" name="user_id" value="{{ u['user_id'] }}">
                    <input type="number" name="amount" value="{{ u['balance_available'] }}" step="0.01" style="width:100px;">
                    <button type="submit">&#x412;&#x44B;&#x43F;&#x43B;&#x430;&#x442;&#x438;&#x442;&#x44C;</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>
{% endblock %}'''

# ---------- ADMIN CHAT (&#x43F;&#x43E;&#x43B;&#x43D;&#x430;&#x44F; &#x441;&#x442;&#x440;&#x430;&#x43D;&#x438;&#x446;&#x430;) ----------
ADMIN_CHAT_TEMPLATE = r'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>&#x427;&#x430;&#x442; &#x432;&#x44B;&#x43F;&#x43B;&#x430;&#x442;&#x44B; #{{ request_id }}</title>
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
<a href="/admin/payouts" class="back-link">&#x2190; &#x41D;&#x430;&#x437;&#x430;&#x434; &#x43A; &#x441;&#x43F;&#x438;&#x441;&#x43A;&#x443; &#x432;&#x44B;&#x43F;&#x43B;&#x430;&#x442;</a>
<h1>&#x1F4AC; &#x427;&#x430;&#x442; &#x43F;&#x43E; &#x437;&#x430;&#x44F;&#x432;&#x43A;&#x435; #{{ request_id }} <span class="status-badge" id="status-badge">{{ status }}</span></h1>
<div class="chat-box" id="chat-messages">&#x417;&#x430;&#x433;&#x440;&#x443;&#x437;&#x43A;&#x430;...</div>
<div class="chat-input">
    <input type="text" id="message-text" placeholder="&#x412;&#x432;&#x435;&#x434;&#x438;&#x442;&#x435; &#x441;&#x43E;&#x43E;&#x431;&#x449;&#x435;&#x43D;&#x438;&#x435;...">
    <button onclick="sendMessage()">&#x1F4E8;</button>
</div>
<div class="action-buttons">
    <button id="send-money-btn" class="send-money" style="display:none;" onclick="sendMoney()">&#x1F4B8; &#x414;&#x435;&#x43D;&#x44C;&#x433;&#x438; &#x43E;&#x442;&#x43F;&#x440;&#x430;&#x432;&#x43B;&#x435;&#x43D;&#x44B;</button>
    <button id="decline-btn" class="decline" style="display:none;" onclick="declineRequest()">&#x274C; &#x41E;&#x442;&#x43A;&#x43B;&#x43E;&#x43D;&#x438;&#x442;&#x44C;</button>
    <button id="confirm-btn" class="confirm" style="display:none;" onclick="confirmReceipt()">&#x2705; &#x41F;&#x43E;&#x434;&#x442;&#x432;&#x435;&#x440;&#x434;&#x438;&#x442;&#x44C; &#x447;&#x435;&#x43A;</button>
</div>

    <div id="receipt-warning" style="display:none; margin-top:15px; padding:12px; background:#2a1a1a; border:1px solid #ff9800; border-radius:8px;">
        &#x26A0;&#xFE0F; <b>&#x412;&#x43D;&#x438;&#x43C;&#x430;&#x43D;&#x438;&#x435;:</b> &#x43F;&#x440;&#x43E;&#x432;&#x435;&#x440;&#x44C;&#x442;&#x435; &#x447;&#x435;&#x43A; &#x432;&#x440;&#x443;&#x447;&#x43D;&#x443;&#x44E; &#x2014; &#x441;&#x432;&#x435;&#x440;&#x44C;&#x442;&#x435; &#x441;&#x443;&#x43C;&#x43C;&#x443;, &#x434;&#x430;&#x442;&#x443; &#x438; &#x418;&#x41D;&#x41D; &#x43F;&#x43E;&#x43B;&#x443;&#x447;&#x430;&#x442;&#x435;&#x43B;&#x44F;.
    </div>

<script>
const requestId = {{ request_id }};

async function loadChat() {
    try {
        const resp = await fetch(`/admin/payouts/${requestId}/chat-data`);
        if (!resp.ok) throw new Error('&#x41E;&#x448;&#x438;&#x431;&#x43A;&#x430; &#x441;&#x435;&#x442;&#x438;');
        const data = await resp.json();

        document.getElementById('status-badge').textContent = data.status;
        document.getElementById('status-badge').className = 'status-badge status-' + data.status;

        const chatDiv = document.getElementById('chat-messages');
        if (!data.messages || data.messages.length === 0) {
            chatDiv.innerHTML = '<p style="color:#888;">&#x421;&#x43E;&#x43E;&#x431;&#x449;&#x435;&#x43D;&#x438;&#x439; &#x43F;&#x43E;&#x43A;&#x430; &#x43D;&#x435;&#x442;</p>';
        } else {
            chatDiv.innerHTML = data.messages.map(msg => {
                const side = msg.sender_role === 'admin' ? 'admin' : 'user';
 o none               let text = '';
 o none               if (msg.file_path) {
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
        document.getElementById('chat-messages').innerHTML = '<p style="color:#ff4444;">&#x41E;&#x448;&#x438;&#x431;&#x43A;&#x430; &#x437;&#x430;&#x433;&#x440;&#x443;&#x437;&#x43A;&#x438; &#x447;&#x430;&#x442;&#x430;</p>';
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

# ---------- ADMIN CPC КАМПАНИИ ----------
ADMIN_CPC_TEMPLATE = r'''{% extends "base.html" %}
{% block title %}CPC кампании{% endblock %}
{% block content %}
<div class="top-bar"><h1>👆 CPC кампании &mdash; управление</h1></div>
<p style="color:#888;margin-bottom:20px;">Здесь вы задаёте описание и правила для всех кампаний. Изменения применяются ко всем пользователям.</p>
<table>
<thead><tr><th>Кампания</th><th>Описание</th><th>Правила (ключевые слова)</th><th></th></tr></thead>
<tbody>
{% for c in campaigns %}
<tr>
    <td style="vertical-align:top;width:180px;">
        {% if c.image_url %}<img src="{{ c.image_url }}" style="width:80px;height:80px;object-fit:contain;border-radius:8px;display:block;margin-bottom:6px;" onerror="this.style.display='none'">{% endif %}
        <strong>{{ c.name }}</strong><br>
        <small style="color:#888;">ID: {{ c.campaign_id }} &bull; {{ c.user_count }} польз.</small>
    </td>
    <td style="vertical-align:top;">
        <textarea class="cpc-desc" data-cid="{{ c.campaign_id }}" style="width:100%;min-height:60px;background:#222;border:1px solid #444;color:#ddd;padding:8px;border-radius:6px;font-size:0.9em;">{{ c.description or '' }}</textarea>
    </td>
    <td style="vertical-align:top;">
        <textarea class="cpc-rules" data-cid="{{ c.campaign_id }}" style="width:100%;min-height:60px;background:#222;border:1px solid #444;color:#ddd;padding:8px;border-radius:6px;font-size:0.9em;font-family:monospace;">{{ c.rules or '' }}</textarea>
        <small style="color:#666;display:block;margin-top:4px;">Каждое правило с новой строки. Используйте: нельзя, запрещено, не допускается, бан</small>
    </td>
    <td style="vertical-align:top;width:80px;">
        <button class="btn-save" onclick="saveCpc({{ c.campaign_id }})">💾</button>
    </td>
</tr>
{% endfor %}
</tbody>
</table>
<div id="msg" style="margin-top:16px;"></div>

<style>
table { width:100%; border-collapse: collapse; }
th { text-align:left; padding:12px 8px; border-bottom:2px solid #ff4444; color:#ff4444; font-size:0.9em; }
td { padding:12px 8px; border-bottom:1px solid #333; }
.btn-save { background:#ff4444; color:white; border:none; padding:8px 20px; border-radius:6px; cursor:pointer; font-size:0.9em; }
.btn-save:hover { background:#e03333; }
.success { color:#4caf50; padding:8px 0; }
</style>
<script>
async function saveCpc(campaignId) {
    const desc = document.querySelector(`.cpc-desc[data-cid="${campaignId}"]`).value;
    const rules = document.querySelector(`.cpc-rules[data-cid="${campaignId}"]`).value;
    const f = new FormData();
    f.append('campaign_id', campaignId);
    f.append('description', desc);
    f.append('rules', rules);
    const res = await fetch('/admin/cpc-save', { method: 'POST', body: f });
    const data = await res.json();
    const msg = document.getElementById('msg');
    if (data.ok) {
        msg.innerHTML = '<div class="success">✅ Сохранено</div>';
        setTimeout(() => msg.innerHTML = '', 3000);
    }
}
</script>
{% endblock %}'''

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
    "admin_cpc.html": ADMIN_CPC_TEMPLATE,
}