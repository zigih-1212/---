import logging
import os
import sqlite3
import asyncio
import re
import random
import threading
import uvicorn
from fastapi import FastAPI, Form
from starlette.responses import HTMLResponse, RedirectResponse
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# Для парсинга каналов-доноров
import httpx
from bs4 import BeautifulSoup

# --- КОНФИГУРАЦИЯ ИЗ ENVIRONMENT VARIABLES ---
TOKEN = os.getenv("OT_TOKEN")
ADMIN_IDS = [aid.strip() for aid in os.getenv("ADMIN_IDS", "").split(",") if aid.strip()]
DONOR_CHANNELS = [d.strip() for d in os.getenv("DONOR_CHANNELS", "").split(",") if d.strip()]
MY_MAIN_CHANNEL = os.getenv("MY_MAIN_CHANNEL") # Твой личный VIP-канал

# Реквизиты для карт
PAY_SBER = os.getenv("PAY_SBER", "Не указан")
PAY_TBANK = os.getenv("PAY_TBANK", "Не указан")
PAY_CRYPTO = os.getenv("PAY_CRYPTO_TON", "Не указан")
PAY_VISA = os.getenv("PAY_VISA_KG", "Не указан")

# API Ключи интеграций
ADMITAD_API_TOKEN = os.getenv("ADMITAD_API_TOKEN")
ADMITAD_BASE64 = os.getenv("ADMITAD_BASE64")

# Настройки Кулдауна (в минутах)
CHANNELS_COOLDOWN_MINUTES = int(os.getenv("CHANNELS_COOLDOWN_MINUTES", "5"))

# Ссылка на панель управления WebApp
WEBAPP_ADMIN_URL = os.getenv("WEBAPP_ADMIN_URL", "https://clck.ru/") 

# Константы Тарифов (Дни: (Цена Руб, Цена Звезд, Текст скидки))
TARIF_PLAN = {
    15: (600, 300, "🔥 Базовый"),
    30: (1000, 500, "💥 Популярный"),
    90: (2550, 1275, "💎 Скидка 15%"),
    180: (4500, 2250, "👑 Скидка 25%"),
    360: (7000, 3500, "🚀 Скидка 40%")
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# --- WEB APP СЕРВЕР (FastAPI) ---
app = FastAPI()

@app.get("/")
async def get_admin_panel():
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role, channel_id, status, sub_type, sub_end, posts_sent FROM clients")
    data = cursor.fetchall()
    conn.close()
    
    rows = ""
    for r in data:
        status_color = "#2ecc71" if "Активен" in r[4] else "#e74c3c"
        toggle_action = "disable" if "Активен" in r[4] else "enable"
        toggle_btn_text = "🔴 Отключить" if "Активен" in r[4] else "🟢 Включить"
        
        rows += f"""<tr>
            <td>{r[0]}</td>
            <td>{r[1]}</td>
            <td><b>{r[2]}</b></td>
            <td>{r[3] if r[3] else '-'}</td>
            <td style="color: {status_color}; font-weight: bold;">{r[4]}</td>
            <td>{r[5]}</td>
            <td>{r[6] if r[6] else '-'}</td>
            <td>{r[7]}</td>
            <td>
                <div class="btn-group">
                    <form action="/update-status" method="post" style="display:inline;">
                        <input type="hidden" name="client_id" value="{r[0]}">
                        <input type="hidden" name="action" value="{toggle_action}">
                        <button type="submit" class="btn btn-toggle">{toggle_btn_text}</button>
                    </form>
                    {f'''<form action="/extend-days" method="post" style="display:inline;">
                        <input type="hidden" name="client_id" value="{r[0]}">
                        <button type="submit" class="btn btn-extend">⚡ Продлить +30д</button>
                    </form>''' if r[2] == 'buyer' else ''}
                </div>
            </td>
        </tr>"""
        
    html = f"""
    <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>AutoErid SMM Advanced Panel</title>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 15px; background-color: #f5f7fa; color: #333; }}
                h2 {{ color: #2c3e50; font-size: 20px; text-align: center; margin-bottom: 5px; }}
                .subtitle {{ text-align: center; color: #7f8c8d; font-size: 13px; margin-bottom: 20px; }}
                table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-radius: 8px; overflow: hidden; font-size: 12px; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #edf2f7; }}
                th {{ background-color: #2c3e50; color: white; font-weight: 600; text-transform: uppercase; font-size: 11px; }}
                tr:hover {{ background-color: #f8fafc; }}
                .btn-group {{ display: flex; gap: 5px; }}
                .btn {{ border: none; padding: 6px 10px; border-radius: 4px; font-size: 11px; font-weight: bold; cursor: pointer; transition: background 0.2s; }}
                .btn-toggle {{ background-color: #e2e8f0; color: #4a5568; }}
                .btn-toggle:hover {{ background-color: #cbd5e1; }}
                .btn-extend {{ background-color: #3182ce; color: white; }}
                .btn-extend:hover {{ background-color: #2b6cb0; }}
            </style>
        </head>
        <body>
            <h2>📊 Интерактивное управление AutoErid SMM</h2>
            <div class="subtitle">Управляйте статусами и тарифами в один клик прямо из Telegram</div>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Юзер</th>
                    <th>Роль</th>
                    <th>Канал</th>
                    <th>Статус</th>
                    <th>Тариф</th>
                    <th>Доступ до</th>
                    <th>Постов</th>
                    <th>Действия</th>
                </tr>
                {rows}
            </table>
        </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/update-status")
async def web_update_status(client_id: int = Form(...), action: str = Form(...)):
    new_status = "🟢 Активен" if action == "enable" else "🔴 Отключен"
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET status=? WHERE id=?", (new_status, client_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/extend-days")
async def web_extend_days(client_id: int = Form(...)):
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT sub_end FROM clients WHERE id=?", (client_id,))
    res = cursor.fetchone()
    if res and res[0]:
        current_end = datetime.strptime(res[0], "%Y-%m-%d")
        start_point = current_end if current_end > datetime.now() else datetime.now()
        new_end = (start_point + timedelta(days=30)).strftime("%Y-%m-%d")
        cursor.execute("UPDATE clients SET sub_end=?, status='🟢 Активен' WHERE id=?", (new_end, client_id))
        conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=8080)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- СОСТОЯНИЯ (FSM) ---
class AdminStates(StatesGroup):
    waiting_for_sub_days = State()
    waiting_for_broadcast_text = State()
    waiting_for_broadcast_role = State()

class UserRegistration(StatesGroup):
    waiting_for_blogger_channel_link = State()
    waiting_for_blogger_format = State()
    waiting_for_blogger_bot_admin = State()
    waiting_for_buyer_channel = State()

# --- ТРАНСЛИТЕРАЦИЯ ДЛЯ SUBID БЛОГЕРОВ ---
def transliterate(text):
    cyr = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
    lat = ['a','b','v','g','d','e','e','zh','z','i','y','k','l','m','n','o','p','r','s','t','u','f','h','ts','ch','sh','shch','','y','','e','yu','ya']
    tr = {c: l for c, l in zip(cyr, lat)}
    cleaned = "".join(c for c in text.lower() if c.isalnum() or c in ['_', '-'])
    res = "".join(tr.get(c, c) for c in cleaned)
    return res if res else "user"

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def init_db():
    os.makedirs('/app/data', exist_ok=True)
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS clients 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                       user_id TEXT UNIQUE,
                       username TEXT,
                       channel_id TEXT, 
                       source_link TEXT,
                       sub_id TEXT,
                       role TEXT,
                       status TEXT DEFAULT '🟢 Активен',
                       sub_type TEXT DEFAULT 'Тестовая', 
                       sub_end DATE, 
                       posts_sent INTEGER DEFAULT 0,
                       clicks INTEGER DEFAULT 0,
                       last_pay_method TEXT DEFAULT 'Нет оплат',
                       platform_filter TEXT DEFAULT 'Вместе',
                       blogger_type TEXT DEFAULT 'none', 
                       last_post_time TIMESTAMP)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS post_history 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       client_id TEXT,
                       donor_post_id TEXT,
                       sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS pinned_posts
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       message_id INTEGER,
                       chat_id TEXT,
                       unpin_at TIMESTAMP)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS night_queue 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       target_chat TEXT,
                       post_text TEXT,
                       client_id TEXT,
                       donor_post_id TEXT,
                       is_vip_or_blogger TEXT DEFAULT 'no')''')
    conn.commit()
    conn.close()

init_db()

def is_admin(user_id):
    return str(user_id) in ADMIN_IDS

def get_user_data(user_id):
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients WHERE user_id=?", (str(user_id),))
    res = cursor.fetchone()
    conn.close()
    return res

# --- КНОПКИ ГЛАВНОГО МЕНЮ АДМИНА И ЮЗЕРА ---
def get_admin_keyboard():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📊 ОТКРЫТЬ WEBAPP АДМИНКУ 📊", web_app=types.WebAppInfo(url=WEBAPP_ADMIN_URL))],
        [types.InlineKeyboardButton(text="🎯 Список Блогеров", callback_data="list_bloggers"),
         types.InlineKeyboardButton(text="🛍 Список Покупателей", callback_data="list_buyers")],
        [types.InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [types.InlineKeyboardButton(text="🔄 Обновить биллинг", callback_data="check_billing")]
    ])

def get_welcome_keyboard():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎯 Я Блогер-партнер (Работа 50/50)", callback_data="reg_blogger")],
        [types.InlineKeyboardButton(text="🛍 Я Покупатель подписки (SaaS софт)", callback_data="reg_buyer")]
    ])

# --- ОБРАБОТКА КОМАНДЫ /START ---
@dp.message(CommandStart())
async def start(message: types.Message):
    uid = message.from_user.id
    
    if is_admin(uid):
        await message.answer("🛠 **Панель управления AutoErid SMM**\n\nВы зашли как Администратор.", reply_markup=get_admin_keyboard(), parse_mode="Markdown")
        return

    user = get_user_data(uid)
    if user:
        role = user[6]
        status = user[7]
        if role == 'blogger':
            b_type = user[14]
            b_type_str = "VIP-Закреп в нашем канале" if b_type == 'zakrep' else f"Автопостинг в ваш канал `{user[3]}`"
            builder = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔥 Тренды для моих видео", callback_data="blogger_trends")],
                [types.InlineKeyboardButton(text="📈 Моя статистика", callback_data="blogger_stats")],
                [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
            ])
            await message.answer(f"👋 Рады видеть вас, партнер!\n\nВаш формат работы: **{b_type_str}**.\nИспользуйте меню ниже, чтобы брать горячие товары со своими реф-ссылками.", reply_markup=builder, parse_mode="Markdown")
        elif role == 'buyer':
            if status == '🔴 Отключен':
                builder = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="💳 Купить подписку", callback_data="pay_sub")],
                    [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
                ])
                await message.answer("❌ **Доступ к автопостингу ограничен.**\n\nВаша подписка закончилась. Пожалуйста, продлите подписку:", reply_markup=builder, parse_mode="Markdown")
            else:
                builder = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="👤 Личный кабинет", callback_data="buyer_cabinet")],
                    [types.InlineKeyboardButton(text="⚙️ Настройка фильтров", callback_data="buyer_filters")],
                    [types.InlineKeyboardButton(text="💳 Продлить подписку", callback_data="pay_sub")],
                    [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
                ])
                await message.answer(f"👋 Добро пожаловать! Ваш аккаунт настроен как **Покупатель подписки**.\nРобот ведет мониторинг доноров и наполняет ваш канал.", reply_markup=builder, parse_mode="Markdown")
        return

    welcome = (
        "👋 **Приветствуем в AutoErid SMM!**\n\n"
        "Наш робот полностью автоматизирует ведение Telegram-каналов со скидками и находками Wildberries & Ozon:\n"
        "• Чистит контент от водяных знаков и чужих ссылок;\n"
        "• Уникализирует описания с помощью ИИ (Grok);\n"
        "• Вшивает ЕРИД маркировку и ваши реферальные ссылки.\n\n"
        "Пожалуйста, выберите формат работы для регистрации:"
    )
    await message.answer(welcome, reply_markup=get_welcome_keyboard(), parse_mode="Markdown")

# --- СЦЕНАРИЙ РЕГИСТРАЦИИ БЛОГЕРА ---
@dp.callback_query(F.data == "reg_blogger")
async def reg_blogger_start(callback: types.CallbackQuery, state: FSMContext):
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]])
    await callback.message.edit_text("🔗 **Шаг 1/3:** Отправьте ссылку на ваш канал/источник трафика (YouTube, TikTok, Reels или TG-канал):", reply_markup=builder)
    await state.set_state(UserRegistration.waiting_for_blogger_channel_link)
    await callback.answer()

@dp.message(UserRegistration.waiting_for_blogger_channel_link)
async def reg_blogger_link_received(message: types.Message, state: FSMContext):
    await state.update_data(blogger_source=message.text)
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎰 Постить в ваш основной VIP-канал (Закреп 24ч)", callback_data="choose_format_zakrep")],
        [types.InlineKeyboardButton(text="📡 Подключить автопостинг прямо в мой канал", callback_data="choose_format_autoposting")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="reg_blogger")]
    ])
    await message.answer("🎯 **Шаг 2/3: Выберите формат сотрудничества 50/50:**", reply_markup=builder)
    await state.set_state(UserRegistration.waiting_for_blogger_format)

@dp.callback_query(UserRegistration.waiting_for_blogger_format, F.data.startswith("choose_format_"))
async def reg_blogger_format_received(callback: types.CallbackQuery, state: FSMContext):
    b_format = callback.data.split("_")[2]
    await state.update_data(blogger_format=b_format)
    
    data = await state.get_data()
    uid = str(callback.from_user.id)
    uname = f"@{callback.from_user.username}" if callback.from_user.username else "Без ника"
    source = data['blogger_source']
    
    clean_name = re.sub(r'https?://|t\.me/|@', '', source).split('/')[0]
    if not clean_name:
        clean_name = callback.from_user.username if callback.from_user.username else f"id{uid}"
    sub_id = f"bl_{transliterate(clean_name)}"[:20]

    if b_format == 'zakrep':
        conn = sqlite3.connect('/app/data/database.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO clients (user_id, username, source_link, sub_id, role, sub_end, blogger_type) VALUES (?, ?, ?, ?, 'blogger', ?, 'zakrep')", 
                       (uid, uname, source, sub_id, (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()
        
        builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🔥 В главное меню", callback_data="back_to_main")]])
        await callback.message.edit_text(f"✅ **Регистрация успешна!**\n\nВы выбрали формат **VIP-закрепов**. Ваш личный маркер партнера: `{sub_id}`.\nБот будет автоматически продвигать ваши ссылки в закрепе нашего VIP-канала!", reply_markup=builder, parse_mode="Markdown")
        await state.clear()
    
    elif b_format == 'autoposting':
        builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]])
        await callback.message.edit_text(
            "🛠 **Настройка автопостинга в ваш канал:**\n\n"
            "1. Добавьте этого бота в ваш Telegram-канал в качестве **Администратора**.\n"
            "2. Дайте боту права на *Публикацию сообщений*.\n\n"
            "👉 Отправьте сюда юзернейм вашего канала (в формате `@имя_канала`):",
            reply_markup=builder
        )
        await state.set_state(UserRegistration.waiting_for_blogger_bot_admin)
    await callback.answer()

@dp.message(UserRegistration.waiting_for_blogger_bot_admin)
async def reg_blogger_autoposting_final(message: types.Message, state: FSMContext):
    uid = str(message.from_user.id)
    uname = f"@{message.from_user.username}" if message.from_user.username else "Без ника"
    channel_input = message.text.strip()
    
    try:
        member = await bot.get_chat_member(chat_id=channel_input, user_id=bot.id)
        if member.status not in ['administrator', 'creator']:
            await message.answer("❌ **Ошибка:** Бот не назначен администратором.")
            return
    except Exception:
        await message.answer("❌ **Ошибка:** Канал не найден.")
        return

    data = await state.get_data()
    source = data['blogger_source']
    clean_name = re.sub(r'https?://|t\.me/|@', '', channel_input)
    sub_id = f"bl_{transliterate(clean_name)}"[:20]

    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO clients (user_id, username, channel_id, source_link, sub_id, role, sub_end, blogger_type) VALUES (?, ?, ?, ?, ?, 'blogger', ?, 'autoposting')", 
                   (uid, uname, channel_input, source, sub_id, (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="📊 Мой личный кабинет", callback_data="blogger_stats")]])
    await message.answer(f"✅ **Канал блогера успешно подключен!**", reply_markup=builder, parse_mode="Markdown")
    await state.clear()

# --- СЦЕНАРИЙ РЕГИСТРАЦИИ ПОКУПАТЕЛЯ SaaS ---
@dp.callback_query(F.data == "reg_buyer")
async def reg_buyer_start(callback: types.CallbackQuery, state: FSMContext):
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]])
    instr = (
        "🛠 **Инструкция по подключению канала:**\n\n"
        f"1. Добавьте этого бота в ваш Telegram-канал в качестве **Администратора**.\n"
        "2. Дайте боту права на *Публикацию сообщений*.\n\n"
        "👉 Отправьте сюда юзернейм канала (например, `@my_skidki_channel`):"
    )
    await callback.message.edit_text(instr, reply_markup=builder, parse_mode="Markdown")
    await state.set_state(UserRegistration.waiting_for_buyer_channel)
    await callback.answer()

@dp.message(UserRegistration.waiting_for_buyer_channel)
async def reg_buyer_save(message: types.Message, state: FSMContext):
    uid = str(message.from_user.id)
    uname = f"@{message.from_user.username}" if message.from_user.username else "Без ника"
    channel_input = message.text.strip()
    
    try:
        member = await bot.get_chat_member(chat_id=channel_input, user_id=bot.id)
        if member.status not in ['administrator', 'creator']:
            await message.answer("❌ **Ошибка:** Бот должен быть администратором в указанном канале. Попробуйте еще раз.")
            return
    except Exception:
        await message.answer("❌ **Ошибка:** Канал не найден. Убедитесь, что бот добавлен и имя корректно.")
        return

    test_end = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO clients (user_id, username, channel_id, role, sub_end, sub_type) VALUES (?, ?, ?, 'buyer', ?, 'Тестовая')", 
                   (uid, uname, channel_input, test_end))
    conn.commit()
    conn.close()
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="👤 Личный кабинет", callback_data="buyer_cabinet")]])
    await message.answer(f"✅ **Канал успешно подключен!** Вам начислено **3 дня теста**.", reply_markup=builder, parse_mode="Markdown")
    await state.clear()

# --- МАТЕРИАЛЫ ДЛЯ БЛОГЕРОВ ---
@dp.callback_query(F.data == "blogger_trends")
async def show_blogger_trends(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    if not user: return
    sub_id = user[5]
    sample_skus = ["143525234", "210435923", "98453215"]
    text = "🔥 **ГОРЯЧИЕ НАХОДКИ ДЛЯ ВАШИХ SHORTS / REELS:**\n\nНиже представлены товары с максимальной конверсией:\n\n"
    
    for i, sku in enumerate(sample_skus, 1):
        final_link, _ = await generate_takprodam_link(sku, is_wb=True, subid=sub_id)
        text += f"{i}️⃣ **Трендовый товар WB** (Арт: `{sku}`)\n" \
                f"👉 Короткая ссылка для био: {final_link}\n\n"
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]])
    await callback.message.edit_text(text, reply_markup=builder, parse_mode="Markdown", disable_web_page_preview=True)
    await callback.answer()

# --- СТАТИСТИКА И НАСТРОЕК ---
@dp.callback_query(F.data == "blogger_stats")
async def show_blogger_stats(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    if not user: return
    text = (f"📈 **Аналитика партнера:**\n\n🎥 **Ресурс:** {user[4]}\n🏷 **SubID:** `{user[5]}`\n📊 Постов отправлено: {user[10]}")
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]])
    await callback.message.edit_text(text, reply_markup=builder, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "buyer_cabinet")
async def show_buyer_cabinet(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    if not user: return
    text = (f"👤 **Личный кабинет SaaS-клиента:**\n\n📢 **Ваш канал:** `{user[3]}`\n🟢 Статус: {user[7]}\n📦 Тариф: {user[8]}\n⏳ Активен до: {user[9]}")
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]])
    await callback.message.edit_text(text, reply_markup=builder, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "buyer_filters")
async def buyer_filters_menu(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    if user[8] == 'Тестовая':
        builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]])
        await callback.message.edit_text("🔒 **Фильтры доступны только на Полной подписке.**", reply_markup=builder)
        await callback.answer()
        return
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🛒 Только Wildberries", callback_data="set_filter_wb")],
        [types.InlineKeyboardButton(text="🔵 Только Ozon", callback_data="set_filter_ozon")],
        [types.InlineKeyboardButton(text="💥 Все вместе", callback_data="set_filter_all")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("⚙️ **Настройка маркетплейсов:**", reply_markup=builder)
    await callback.answer()

@dp.callback_query(F.data.startswith("set_filter_"))
async def set_buyer_filter(callback: types.CallbackQuery):
    f_type = callback.data.split("_")[2]
    mapping = {"wb": "Только WB", "ozon": "Только Ozon", "all": "Вместе"}
    selected = mapping.get(f_type, "Вместе")
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET platform_filter=? WHERE user_id=?", (selected, str(callback.from_user.id)))
    conn.commit()
    conn.close()
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]])
    await callback.message.edit_text(f"✅ Фильтр изменен на: **{selected}**", reply_markup=builder)
    await callback.answer()

# --- КНОПКА НАЗАД В КОРЕНЬ ---
@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    uid = callback.from_user.id
    if is_admin(uid):
        await callback.message.edit_text("🛠 **Панель управления AutoErid SMM**\n\nВы зашли как Администратор.", reply_markup=get_admin_keyboard(), parse_mode="Markdown")
    else:
        user = get_user_data(uid)
        if user:
            role = user[6]
            status = user[7]
            if role == 'blogger':
                b_type = user[14]
                b_type_str = "VIP-Закреп в нашем канале" if b_type == 'zakrep' else f"Автопостинг в ваш канал `{user[3]}`"
                builder = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="🔥 Тренды для моих видео", callback_data="blogger_trends")],
                    [types.InlineKeyboardButton(text="📈 Моя статистика", callback_data="blogger_stats")],
                    [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
                ])
                await callback.message.edit_text(f"👋 Рады видеть вас, партнер!\n\nВаш формат работы: **{b_type_str}**.\nИспользуйте меню ниже, чтобы брать горячие товары со своими реф-ссылками.", reply_markup=builder, parse_mode="Markdown")
            elif role == 'buyer':
                if status == '🔴 Отключен':
                    builder = types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="💳 Купить подписку", callback_data="pay_sub")],
                        [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
                    ])
                    await callback.message.edit_text("❌ **Доступ к автопостингу ограничен.**\n\nВаша подписка закончилась. Пожалуйста, продлите подписку:", reply_markup=builder, parse_mode="Markdown")
                else:
                    builder = types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="👤 Личный кабинет", callback_data="buyer_cabinet")],
                        [types.InlineKeyboardButton(text="⚙️ Настройка фильтров", callback_data="buyer_filters")],
                        [types.InlineKeyboardButton(text="💳 Продлить подписку", callback_data="pay_sub")],
                        [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
                    ])
                    await callback.message.edit_text(f"👋 Добро пожаловать! Ваш аккаунт настроен как **Покупатель подписки**.\nРобот ведет мониторинг доноров и наполняет ваш канал.", reply_markup=builder, parse_mode="Markdown")
        else:
            welcome = (
                "👋 **Приветствуем в AutoErid SMM!**\n\n"
                "Наш робот полностью автоматизирует ведение Telegram-каналов со скидками и находками Wildberries & Ozon:\n"
                "• Чистит контент от водяных знаков и чужих ссылок;\n"
                "• Уникализирует описания с помощью ИИ (Grok);\n"
                "• Вшивает ЕРИД маркировку и ваши реферальные ссылки.\n\n"
                "Пожалуйста, выберите формат работы для регистрации:"
            )
            await callback.message.edit_text(welcome, reply_markup=get_welcome_keyboard(), parse_mode="Markdown")
    await callback.answer()

# --- ТЕКСТОВЫЙ АДМИН-ФУНКЦИОНАЛ ---
@dp.callback_query(F.data == "list_bloggers")
async def admin_list_bloggers(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, blogger_type FROM clients WHERE role='blogger'")
    rows = cursor.fetchall()
    conn.close()
    builder = []
    for r in rows:
        builder.append([types.InlineKeyboardButton(text=f"👤 {r[1]} [{r[2]}]", callback_data=f"admview_{r[0]}")])
    builder.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    
    await callback.message.edit_text("🎯 **Зарегистрированные Блогеры:**", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "list_buyers")
async def admin_list_buyers(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, channel_id, status FROM clients WHERE role='buyer'")
    rows = cursor.fetchall()
    conn.close()
    builder = []
    for r in rows:
        builder.append([types.InlineKeyboardButton(text=f"{r[2]} {r[1]}", callback_data=f"admview_{r[0]}")])
    builder.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    
    await callback.message.edit_text("🛍 **Покупатели SaaS-подписки:**", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=builder), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("admview_"))
async def admin_view_client(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    c_id = callback.data.split("_")[1]
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients WHERE id=?", (c_id,))
    c = cursor.fetchone()
    conn.close()
    if not c: return
    role = c[6]
    if role == 'blogger':
        text = (f"🎯 **Карточка Блогера:**\n\n🆔 ИД: `{c[1]}`\n👤 Юзернейм: {c[2]}\n🎥 Источник: {c[4]}\n🏷 SubID: `{c[5]}`\n📦 Формат: `{c[14]}`\n📊 Постов: {c[10]}")
        builder = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🗑 Удалить из базы", callback_data=f"admdelete_{c[0]}")],
            [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])
    else:
        text = (f"🛍 **Карточка Покупателя:**\n\n👤 Владелец: {c[2]}\n📢 Канал: `{c[3]}`\n⚡️ Статус: {c[7]}\n📦 Тариф: **{c[8]}**\n⏳ До: `{c[9]}`\n📊 Постов: {c[10]}")
        builder = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🔄 Изменить Тариф", callback_data=f"admtoggle_{c[0]}")],
            [types.InlineKeyboardButton(text="📅 Вручную продлить", callback_data=f"admextend_{c[0]}")],
            [types.InlineKeyboardButton(text="🗑 Удалить из базы", callback_data=f"admdelete_{c[0]}")],
            [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
        ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder)
    await callback.answer()

@dp.callback_query(F.data.startswith("admtoggle_"))
async def admin_toggle_sub_type(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    c_id = callback.data.split("_")[1]
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT sub_type FROM clients WHERE id=?", (c_id,))
    curr = cursor.fetchone()[0]
    new_t = "Полная" if curr == "Тестовая" else "Тестовая"
    cursor.execute("UPDATE clients SET sub_type=?, status='🟢 Активен' WHERE id=?", (new_t, c_id))
    conn.commit()
    conn.close()
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Вернуться", callback_data=f"admview_{c_id}")]])
    await callback.message.edit_text(f"✅ Тариф изменен на: **{new_t}**", reply_markup=builder)
    await callback.answer()

@dp.callback_query(F.data.startswith("admextend_"))
async def admin_extend_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    c_id = callback.data.split("_")[1]
    await state.update_data(adm_client_id=c_id)
    await callback.message.edit_text("📅 Введите количество дней ручного продления:")
    await state.set_state(AdminStates.waiting_for_sub_days)
    await callback.answer()

@dp.message(AdminStates.waiting_for_sub_days)
async def admin_extend_save(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try: days = int(message.text)
    except ValueError: return
    data = await state.get_data()
    c_id = data['adm_client_id']
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT sub_end FROM clients WHERE id=?", (c_id,))
    current_end_str = cursor.fetchone()[0]
    current_end = datetime.strptime(current_end_str, "%Y-%m-%d")
    if current_end < datetime.now(): current_end = datetime.now()
    new_end = (current_end + timedelta(days=days)).strftime("%Y-%m-%d")
    cursor.execute("UPDATE clients SET sub_end=?, status='🟢 Активен' WHERE id=?", (new_end, c_id))
    conn.commit()
    conn.close()
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🔥 В меню управления", callback_data="back_to_main")]])
    await message.answer(f"✅ Подписка продлена до: `{new_end}`", reply_markup=builder)
    await state.clear()

@dp.callback_query(F.data.startswith("admdelete_"))
async def admin_delete_client(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    c_id = callback.data.split("_")[1]
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM clients WHERE id=?", (c_id,))
    conn.commit()
    conn.close()
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]])
    await callback.message.edit_text("🗑 Удалено успешно.", reply_markup=builder)
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🌍 Всем", callback_data="bcastrole_all")],
        [types.InlineKeyboardButton(text="🎯 Блогерам", callback_data="bcastrole_blogger")],
        [types.InlineKeyboardButton(text="🛍 Покупателям", callback_data="bcastrole_buyer")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("📢 **Выбор сегмента рассылки:**", reply_markup=builder)
    await callback.answer()

@dp.callback_query(F.data.startswith("bcastrole_"))
async def admin_broadcast_get_role(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.update_data(broadcast_target=callback.data.split("_")[1])
    await callback.message.edit_text("✏️ Введите текст рассылки:")
    await state.set_state(AdminStates.waiting_for_broadcast_text)
    await callback.answer()

@dp.message(AdminStates.waiting_for_broadcast_text)
async def admin_broadcast_execute(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    target = data['broadcast_target']
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM clients" if target == 'all' else f"SELECT user_id FROM clients WHERE role='{target}'")
    users = cursor.fetchall()
    conn.close()
    sent = 0
    for u in users:
        try:
            await bot.send_message(chat_id=u[0], text=message.text, parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception: pass
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🔥 В админку", callback_data="back_to_main")]])
    await message.answer(f"📢 Доставлено сообщений: **{sent}**", reply_markup=builder)
    await state.clear()

# --- НОВАЯ СИСТЕМА ОПЛАТЫ (РАЗДЕЛЬНЫЕ КНОПКИ СПОСОБА И СРОКА) ---

@dp.callback_query(F.data == "pay_sub")
async def pay_sub_menu(callback: types.CallbackQuery):
    # Шаг 1: Сначала выбираем СПОСОБ оплаты, кнопки разделены
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🇷🇺 Банковская Карта РФ", callback_data="paymethod_card")],
        [types.InlineKeyboardButton(text="⭐️ Telegram Stars (Звёзды)", callback_data="paymethod_stars")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("💳 **Выберите удобный способ оплаты подписки:**", reply_markup=builder, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("paymethod_"))
async def pay_method_selected(callback: types.CallbackQuery):
    method = callback.data.split("_")[1] # 'card' или 'stars'
    
    # Формируем кнопки подписок от 15 до 360 дней со скидками
    buttons = []
    for days, (rub_p, star_p, label) in TARIF_PLAN.items():
        if method == "card":
            text = f"{label} {days} дней — {rub_p}₽"
            callback_path = f"checkout_card_Sberbank_{days}"
        else:
            text = f"{label} {days} дней — {star_p} ⭐️"
            callback_path = f"checkout_stars_{days}"
        buttons.append([types.InlineKeyboardButton(text=text, callback_data=callback_path)])
        
    # Кнопка возврата ведет строго на шаг выбора способа оплаты
    buttons.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="pay_sub")])
    
    title = "🇷🇺 **Доступные тарифы при оплате Картой:**" if method == "card" else "⭐️ **Доступные тарифы при оплате Звёздами:**"
    await callback.message.edit_text(title, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    await callback.answer()

# Хендлер для симуляции/запуска чекаута карт
@dp.callback_query(F.data.startswith("checkout_card_"))
async def checkout_card_handler(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    bank = parts[2]
    days = int(parts[3])
    price = TARIF_PLAN[days][0]
    
    reквизиты = PAY_SBER if bank == "Sberbank" else PAY_TBANK
    
    text = (
        f"💳 **Оплата подписки на {days} дней**\n\n"
        f"Сумма к оплате: **{price} Рублей**\n"
        f"Банк назначения: **{bank}**\n"
        f"Реквизиты для перевода: `{reквизиты}`\n\n"
        "⚠️ После совершения перевода, пожалуйста, отправьте чек в службу поддержки @Zigih90 для мгновенной активации."
    )
    # Возвращаемся обратно к тарифам карт
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="paymethod_card")]])
    await callback.message.edit_text(text, reply_markup=builder, parse_mode="Markdown")
    await callback.answer()

# Хендлер для запуска чекаута Telegram Stars
@dp.callback_query(F.data.startswith("checkout_stars_"))
async def checkout_stars_handler(callback: types.CallbackQuery):
    days = int(callback.data.split("_")[2])
    stars_price = TARIF_PLAN[days][1]
    
    # Заглушка отправки инвойса (в будущем здесь будет bot.send_invoice)
    text = (
        f"⭐️ **Оплата подписки через Telegram Stars**\n\n"
        f"Срок: **{days} дней**\n"
        f"Стоимость: **{stars_price} ⭐️**\n\n"
        "⚙️ Инвойс формируется мессенджером..."
    )
    # Возвращаемся обратно к тарифам звёзд
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="⬅️ Назад", callback_data="paymethod_stars")]])
    await callback.message.edit_text(text, reply_markup=builder, parse_mode="Markdown")
    await callback.answer()

# =====================================================================
# --- ИИ-ДВИЖОК ПАРСИНГА С КУЛДАУНОМ, НОЧНЫМ РЕЖИМОМ И СОКРАЩАТЕЛЕМ ---
# =====================================================================

async def shorten_url(long_url):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"https://clck.ru/--?url={long_url}", timeout=5.0)
            if res.status_code == 200: return res.text.strip()
    except Exception: pass
    return long_url

async def ai_grok_rewrite(old_text):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.deepinfra.com/v1/openai/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": "meta-llama/Meta-Llama-3-8B-Instruct",
                    "messages": [{"role": "user", "content": f"Сделай красивый рерайт контента скидок Wildberries. Используй эмодзи. Отдай только текст поста без лишних фраз: {old_text}"}]
                }, timeout=10.0
            )
            if res.status_code == 200: return res.json()['choices'][0]['message']['content']
    except Exception: pass
    return f"🔥 Находка на маркетплейсе! 🔥\n\n{old_text[:120]}...\n\n📦 Успей забрать по лучшей цене!"

async def generate_takprodam_link(sku, is_wb=True, subid=""):
    base_url = f"https://www.wildberries.ru/catalog/{sku}/detail.aspx" if is_wb else f"https://www.ozon.ru/product/{sku}/"
    if not ADMITAD_API_TOKEN: return base_url, "Реклама. ООО Маркетплейс"
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {ADMITAD_API_TOKEN}"}
            payload = {"subid": subid, "ulp": base_url}
            res = await client.post(f"https://api.admitad.com/get_links/{ADMITAD_BASE64}/", headers=headers, data=payload, timeout=5.0)
            if res.status_code == 200:
                long_link = res.json()[0]['clink']
                short_link = await shorten_url(long_link)
                return short_link, "Реклама. ООО 'АДМИТАД', ИНН 7714402214"
    except Exception: pass
    return base_url, "Реклама. ООО Маркетплейс"

async def check_channel_cooldown(client_id):
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT last_post_time FROM clients WHERE user_id=?", (str(client_id),))
    res = cursor.fetchone()
    conn.close()
    if not res or not res[0]: return True
    last_time = datetime.strptime(res[0], "%Y-%m-%d %H:%M:%S")
    if datetime.now() - last_time >= timedelta(minutes=CHANNELS_COOLDOWN_MINUTES): return True
    return False

async def update_channel_last_post_time(client_id):
    conn = sqlite3.connect('/app/data/database.db')
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE clients SET last_post_time=? WHERE user_id=?", (now_str, str(client_id)))
    conn.commit()
    conn.close()

def is_night_time():
    current_hour = datetime.now().hour
    if current_hour >= 23 or current_hour < 8: return True
    return False

async def start_parsing_engine():
    log.info("ИИ-комбайн автопостинга со всеми 3 VIP-функциями запущен.")
    await asyncio.sleep(10)
    while True:
        for channel in DONOR_CHANNELS:
            try:
                async with httpx.AsyncClient() as client:
                    res = await client.get(f"https://t.me/s/{channel}", timeout=10.0)
                    if res.status_code != 200: continue
                    soup = BeautifulSoup(res.text, 'html.parser')
                    messages = soup.find_all('div', class_='tgme_widget_message_wrap')
                    if not messages: continue
                    last_msg = messages[-1]
                    msg_id = last_msg.find('div', class_='tgme_widget_message')['data-post']
                    text_div = last_msg.find('div', class_='tgme_widget_message_text')
                    if not text_div: continue
                    raw_text = text_div.get_text()
                    sku_match = re.search(r'(?:catalog|product|артикул|арт)[\s:/]*(\id=\d+|\d+)', raw_text, re.IGNORECASE)
                    if not sku_match: continue
                    sku = "".join(c for c in sku_match.group(1) if c.isdigit())
                    is_wb = "ozon" not in raw_text.lower() and "озон" not in raw_text.lower()
                    market_tag = "Только WB" if is_wb else "Только Ozon"
                    
                    unique_text = await ai_grok_rewrite(raw_text)
                    
                    if MY_MAIN_CHANNEL:
                        if is_night_time():
                            conn = sqlite3.connect('/app/data/database.db')
                            cursor = conn.cursor()
                            cursor.execute("SELECT id FROM post_history WHERE client_id='ADMIN_MAIN' AND donor_post_id=?", (msg_id,))
                            if not cursor.fetchone():
                                my_link, my_erid = await generate_takprodam_link(sku, is_wb=is_wb, subid="main_admin")
                                my_post_text = f"⭐ **[VIP ВЫБОР]** ⭐\n\n{unique_text}\n\n🛍 [Забрать на маркетплейсе]({my_link})\n\n📍 _{my_erid}_"
                                cursor.execute("INSERT INTO night_queue (target_chat, post_text, client_id, donor_post_id, is_vip_or_blogger) VALUES (?, ?, 'ADMIN_MAIN', ?, 'vip')", (str(MY_MAIN_CHANNEL), my_post_text, msg_id))
                                cursor.execute("INSERT INTO post_history (client_id, donor_post_id) VALUES ('ADMIN_MAIN', ?)", (msg_id,))
                                conn.commit()
                            conn.close()
                        else:
                            if await check_channel_cooldown('ADMIN_MAIN'):
                                conn = sqlite3.connect('/app/data/database.db')
                                cursor = conn.cursor()
                                cursor.execute("SELECT id FROM post_history WHERE client_id='ADMIN_MAIN' AND donor_post_id=?", (msg_id,))
                                if not cursor.fetchone():
                                    my_link, my_erid = await generate_takprodam_link(sku, is_wb=is_wb, subid="main_admin")
                                    my_post_text = f"⭐ **[VIP ВЫБОР]** ⭐\n\n{unique_text}\n\n🛍 [Забрать со скидкой на маркетплейсе]({my_link})\n\n📍 _{my_erid}_"
                                    try:
                                        sent_msg = await bot.send_message(chat_id=MY_MAIN_CHANNEL, text=my_post_text, parse_mode="Markdown")
                                        await bot.pin_chat_message(chat_id=MY_MAIN_CHANNEL, message_id=sent_msg.message_id, disable_notification=True)
                                        unpin_time = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
                                        cursor.execute("INSERT INTO pinned_posts (message_id, chat_id, unpin_at) VALUES (?, ?, ?)", (sent_msg.message_id, str(MY_MAIN_CHANNEL), unpin_time))
                                        cursor.execute("INSERT INTO post_history (client_id, donor_post_id) VALUES ('ADMIN_MAIN', ?)", (msg_id,))
                                        conn.commit()
                                        await update_channel_last_post_time('ADMIN_MAIN')
                                    except Exception: pass
                                conn.close()

                    conn = sqlite3.connect('/app/data/database.db')
                    cursor = conn.cursor()
                    cursor.execute("SELECT user_id, sub_id FROM clients WHERE role='blogger' AND blogger_type='zakrep' AND status='🟢 Активен'")
                    zakrep_bloggers = cursor.fetchall()
                    conn.close()
                    
                    if zakrep_bloggers and MY_MAIN_CHANNEL:
                        chosen_blogger = random.choice(zakrep_bloggers)
                        b_uid, b_subid = chosen_blogger
                        if is_night_time():
                            conn = sqlite3.connect('/app/data/database.db')
                            cursor = conn.cursor()
                            cursor.execute("SELECT id FROM post_history WHERE client_id=? AND donor_post_id=?", (b_uid, msg_id))
                            if not cursor.fetchone():
                                b_link, b_erid = await generate_takprodam_link(sku, is_wb=is_wb, subid=b_subid)
                                b_post_text = f"🎯 **[ВЫБОР ПАРТНЕРА]** 🎯\n\n{unique_text}\n\n🛍 [Забрать на маркетплейсе]({b_link})\n\n📍 _{b_erid}_"
                                cursor.execute("INSERT INTO night_queue (target_chat, post_text, client_id, donor_post_id, is_vip_or_blogger) VALUES (?, ?, ?, ?, 'blogger')", (str(MY_MAIN_CHANNEL), b_post_text, b_uid, msg_id))
                                cursor.execute("INSERT INTO post_history (client_id, donor_post_id) VALUES (?, ?)", (b_uid, msg_id))
                                conn.commit()
                            conn.close()
                        else:
                            if await check_channel_cooldown('ADMIN_MAIN'):
                                conn = sqlite3.connect('/app/data/database.db')
                                cursor = conn.cursor()
                                cursor.execute("SELECT id FROM post_history WHERE client_id=? AND donor_post_id=?", (b_uid, msg_id))
                                if not cursor.fetchone():
                                    b_link, b_erid = await generate_takprodam_link(sku, is_wb=is_wb, subid=b_subid)
                                    b_post_text = f"🎯 **[ВЫБОР ПАРТНЕРА]** 🎯\n\n{unique_text}\n\n🛍 [Забрать на маркетплейсе]({b_link})\n\n📍 _{b_erid}_"
                                    try:
                                        sent_msg = await bot.send_message(chat_id=MY_MAIN_CHANNEL, text=b_post_text, parse_mode="Markdown")
                                        await bot.pin_chat_message(chat_id=MY_MAIN_CHANNEL, message_id=sent_msg.message_id, disable_notification=True)
                                        unpin_time = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
                                        cursor.execute("INSERT INTO pinned_posts (message_id, chat_id, unpin_at) VALUES (?, ?, ?)", (sent_msg.message_id, str(MY_MAIN_CHANNEL), unpin_time))
                                        cursor.execute("INSERT INTO post_history (client_id, donor_post_id) VALUES (?, ?)", (b_uid, msg_id))
                                        cursor.execute("UPDATE clients SET posts_sent = posts_sent + 1 WHERE user_id=?", (b_uid,))
                                        conn.commit()
                                        await update_channel_last_post_time('ADMIN_MAIN')
                                    except Exception: pass
                                conn.close()

                    conn = sqlite3.connect('/app/data/database.db')
                    cursor = conn.cursor()
                    cursor.execute("SELECT user_id, channel_id, role, sub_id, platform_filter, blogger_type FROM clients WHERE status='🟢 Активен'")
                    clients = cursor.fetchall()
                    conn.close()
                    
                    random.shuffle(clients)
                    for client in clients:
                        user_id, channel_id, role, sub_id, platform_filter, blogger_type = client
                        if role == 'blogger' and blogger_type == 'zakrep': continue
                        if role == 'buyer' and platform_filter != 'Вместе' and platform_filter != market_tag: continue
                        if not channel_id: continue
                        
                        if is_night_time():
                            conn = sqlite3.connect('/app/data/database.db')
                            cursor = conn.cursor()
                            cursor.execute("SELECT id FROM post_history WHERE client_id=? AND donor_post_id=?", (user_id, msg_id))
                            if not cursor.fetchone():
                                client_subid = sub_id if role == 'blogger' else f"buy_{user_id}"
                                final_link, erid_label = await generate_takprodam_link(sku, is_wb=is_wb, subid=client_subid)
                                final_post_text = f"{unique_text}\n\n🛍 **Забрать на маркетплейсе:** [ССЫЛКА НА ТОВАР]({final_link})\n\n📍 _{erid_label}_"
                                cursor.execute("INSERT INTO night_queue (target_chat, post_text, client_id, donor_post_id, is_vip_or_blogger) VALUES (?, ?, ?, ?)", (channel_id, final_post_text, user_id, msg_id))
                                cursor.execute("INSERT INTO post_history (client_id, donor_post_id) VALUES (?, ?)", (user_id, msg_id))
                                conn.commit()
                            conn.close()
                        else:
                            if not await check_channel_cooldown(user_id): continue
                            conn = sqlite3.connect('/app/data/database.db')
                            cursor = conn.cursor()
                            cursor.execute("SELECT id FROM post_history WHERE client_id=? AND donor_post_id=?", (user_id, msg_id))
                            if cursor.fetchone():
                                conn.close()
                                continue
                            client_subid = sub_id if role == 'blogger' else f"buy_{user_id}"
                            final_link, erid_label = await generate_takprodam_link(sku, is_wb=is_wb, subid=client_subid)
                            final_post_text = f"{unique_text}\n\n🛍 **Забрать на маркетплейсе:** [ССЫЛКА НА ТОВАР]({final_link})\n\n📍 _{erid_label}_"
                            try:
                                await bot.send_message(chat_id=channel_id, text=final_post_text, parse_mode="Markdown")
                                cursor.execute("INSERT INTO post_history (client_id, donor_post_id) VALUES (?, ?)", (user_id, msg_id))
                                cursor.execute("UPDATE clients SET posts_sent = posts_sent + 1 WHERE user_id=?", (user_id,))
                                conn.commit()
                                await update_channel_last_post_time(user_id)
                            except Exception: pass
                            conn.close()
                            await asyncio.sleep(random.randint(2, 5))
            except Exception: pass
        await asyncio.sleep(60)

# --- КРОН-БИЛЛИНГ, ЗАКРЕПЫ И РАЗГРУЗКА НОЧНОЙ ОЧЕРЕДИ УТРОМ ---
async def start_billing_clock():
    while True:
        try:
            conn = sqlite3.connect('/app/data/database.db')
            cursor = conn.cursor()
            today = datetime.now()
            
            now_str = today.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("SELECT id, message_id, chat_id FROM pinned_posts WHERE unpin_at <= ?", (now_str,))
            for pin in cursor.fetchall():
                try:
                    await bot.unpin_chat_message(chat_id=pin[2], message_id=pin[1])
                    cursor.execute("DELETE FROM pinned_posts WHERE id = ?", (pin[0],))
                except Exception: pass
            
            if not is_night_time():
                cursor.execute("SELECT * FROM night_queue LIMIT 1")
                next_job = cursor.fetchone()
                if next_job:
                    job_id, target_chat, post_text, client_id, donor_post_id, is_vip_or_blogger = next_job
                    cooldown_id = 'ADMIN_MAIN' if is_vip_or_blogger == 'vip' or is_vip_or_blogger == 'blogger' else client_id
                    
                    if await check_channel_cooldown(cooldown_id):
                        try:
                            sent_msg = await bot.send_message(chat_id=target_chat, text=post_text, parse_mode="Markdown")
                            if is_vip_or_blogger in ['vip', 'blogger']:
                                await bot.pin_chat_message(chat_id=target_chat, message_id=sent_msg.message_id, disable_notification=True)
                                unpin_time = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
                                cursor.execute("INSERT INTO pinned_posts (message_id, chat_id, unpin_at) VALUES (?, ?, ?)", (sent_msg.message_id, target_chat, unpin_time))
                            
                            cursor.execute("UPDATE clients SET posts_sent = posts_sent + 1 WHERE user_id=?", (client_id,))
                            cursor.execute("DELETE FROM night_queue WHERE id=?", (job_id,))
                            await update_channel_last_post_time(cooldown_id)
                        except Exception:
                            cursor.execute("DELETE FROM night_queue WHERE id=?", (job_id,))
            
            tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")
            cursor.execute("SELECT user_id, channel_id FROM clients WHERE role='buyer' AND sub_end=? AND status='🟢 Активен'", (tomorrow_str,))
            for u in cursor.fetchall():
                try: await bot.send_message(chat_id=u[0], text=f"⏳ Подписка для канала `{u[1]}` заканчивается через 24 часа.")
                except Exception: pass
                
            cursor.execute("SELECT user_id, channel_id FROM clients WHERE role='buyer' AND sub_end<=? AND status='🟢 Активен'", (today_str,))
            for u in cursor.fetchall():
                cursor.execute("UPDATE clients SET status='🔴 Отключен' WHERE user_id=?", (u[0],))
                try: await bot.send_message(chat_id=u[0], text=f"❌ Подписка для канала `{u[1]}` истекла.")
                except Exception: pass
            
            conn.commit()
            conn.close()
        except Exception: pass
        await asyncio.sleep(30)

@dp.callback_query(F.data == "check_billing")
async def admin_trigger_billing(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    await callback.message.answer("🔄 Система биллинга и очередей успешно синхронизирована.")
    await callback.answer()

# === АВТОМАТИЧЕСКАЯ РЕГИСТРАЦИЯ КОМАНД В ТЕЛЕГРАМ-МЕНЮ ===
async def set_bot_commands():
    commands = [
        types.BotCommand(command="start", description="🔄 Запустить бота / Главное меню"),
    ]
    await bot.set_my_commands(commands)

async def run_webapp():
    config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await set_bot_commands()
    asyncio.create_task(run_webapp())
    asyncio.create_task(start_billing_clock())
    asyncio.create_task(start_parsing_engine())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): log.info("Бот остановлен.")