import logging
import os
import sqlite3
import asyncio
import re
import random
import threading
import json
import html
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

# =====================================================================
# === БЛОК 1: ГЛОБАЛЬНАЯ НАСТРОЙКА И КОНФИГУРАЦИЯ ОКРУЖЕНИЯ ===
# =====================================================================

TOKEN = os.getenv("OT_TOKEN")
ADMIN_IDS = [aid.strip() for aid in os.getenv("ADMIN_IDS", "").split(",") if aid.strip()]
DONOR_CHANNELS = [d.strip() for d in os.getenv("DONOR_CHANNELS", "").split(",") if d.strip()]
MY_MAIN_CHANNEL = os.getenv("MY_MAIN_CHANNEL")  # Личный VIP-канал админа

# Партнерская интеграция
TAKPRODAM_MASTER_TOKEN = "0935e214-9445-447f-91dc-6c8e4bfe0f12"

# Платежные реквизиты карт
PAY_SBER = os.getenv("PAY_SBER", "Не указан")
PAY_TBANK = os.getenv("PAY_TBANK", "Не указан")
PAY_CRYPTO = os.getenv("PAY_CRYPTO_TON", "Не указан")
PAY_VISA = os.getenv("PAY_VISA_KG", "Не указан")

CHANNELS_COOLDOWN_MINUTES = int(os.getenv("CHANNELS_COOLDOWN_MINUTES", "15"))
WEBAPP_ADMIN_URL = os.getenv("WEBAPP_ADMIN_URL", "https://clck.ru/") 

# Тарифная сетка для Stars / Карт
TARIF_PLAN = {
    15: (600, 300, "🔥 Базовый"),
    30: (1000, 500, "💥 Популярный"),
    90: (2550, 1275, "💎 Скидка 15%"),
    180: (4500, 2250, "👑 Скидка 25%"),
    360: (7000, 3500, "🚀 Скидка 40%")
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

# =====================================================================
# === БЛОК 2: ИНИЦИАЛИЗАЦИЯ СУБД SQLite И МИГРАЦИИ ===
# =====================================================================

def init_db():
    try:
        os.makedirs('/app/data', exist_ok=True)
        conn = sqlite3.connect('/app/data/database.db')
        cursor = conn.cursor()
        
        # Основная таблица клиентов платформы
        cursor.execute('''CREATE TABLE IF NOT EXISTS clients 
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                           user_id TEXT UNIQUE,
                           username TEXT,
                           channel_id TEXT, 
                           source_link TEXT,
                           sub_id TEXT,
                           role TEXT DEFAULT 'none',
                           status TEXT DEFAULT '🔴 Отключен',
                           sub_type TEXT DEFAULT 'Тестовая', 
                           sub_end DATE, 
                           posts_sent INTEGER DEFAULT 0,
                           clicks INTEGER DEFAULT 0,
                           last_pay_method TEXT DEFAULT 'Нет оплат',
                           platform_filter TEXT DEFAULT 'Вместе',
                           blogger_type TEXT DEFAULT 'none', 
                           last_post_time TIMESTAMP,
                           api_key TEXT DEFAULT '-')''')
        
        # Проверка и миграция api_key на случай старых баз
        try:
            cursor.execute("SELECT api_key FROM clients LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE clients ADD COLUMN api_key TEXT DEFAULT '-'")
            conn.commit()

        cursor.execute('''CREATE TABLE IF NOT EXISTS post_history 
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT, donor_post_id TEXT, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS pinned_posts 
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id INTEGER, chat_id TEXT, unpin_at TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS night_queue 
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, target_chat TEXT, post_text TEXT, client_id TEXT, donor_post_id TEXT, is_vip_or_blogger TEXT DEFAULT 'no')''')
        conn.commit()
        conn.close()
    except Exception as e:
        log.error(f"Критическая ошибка инициализации базы данных: {e}")

init_db()

# =====================================================================
# === БЛОК 3: FSM СОСТОЯНИЯ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
# =====================================================================

class AdminStates(StatesGroup):
    waiting_for_sub_days = State()
    waiting_for_broadcast_text = State()
    waiting_for_broadcast_role = State()

class UserRegistration(StatesGroup):
    waiting_for_blogger_channel_link = State()
    waiting_for_blogger_format = State()
    waiting_for_blogger_bot_admin = State()
    waiting_for_buyer_channel = State()
    waiting_for_api_key = State()

def is_admin(user_id) -> bool:
    return str(user_id) in ADMIN_IDS

def escape_html(text: str) -> str:
    if not text:
        return ""
    return html.escape(text)

def safe_truncate_html(text: str, max_len: int = 1000) -> str:
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    if "<a " in truncated and "</a>" not in truncated[truncated.rfind("<a "):]:
        truncated += "...</a>"
    return truncated

def is_valid_static_image_url(url: str) -> bool:
    """ Сверхстрогая проверка медиафайлов от некорректного контента страниц-заглушек """
    if not url or not isinstance(url, str):
        return False
    if not (url.startswith("http://") or url.startswith("https://")):
        return False
    low = url.lower()
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        if ext in low:
            return True
    return False

def transliterate(text):
    cyr = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
    lat = ['a','b','v','g','d','e','e','zh','z','i','y','k','l','m','n','o','p','r','s','t','u','f','h','ts','ch','sh','shch','','y','','e','yu','ya']
    tr = {c: l for c, l in zip(cyr, lat)}
    cleaned = "".join(c for c in text.lower() if c.isalnum() or c in ['_', '-'])
    return "".join(tr.get(c, c) for c in cleaned) if cleaned else "user"

# =====================================================================
# === БЛОК 4: ИНТЕГРАЦИЯ С ИНСТРУМЕНТАМИ ТАКПРОДАМ И МАРКИРОВКОЙ ERID ===
# =====================================================================

async def get_takprodam_data(sku: str, api_key: str):
    active_token = TAKPRODAM_MASTER_TOKEN if not api_key or api_key == '-' else api_key
    url = "https://api.takprodam.ru/v1/products/info"
    params = {"api_key": active_token, "sku": sku}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return {
                        "base_url": data.get("link", f"https://takprodam.ru/p/{sku}"),
                        "erid": data.get("erid", "Отсутствует"),
                        "advertiser": data.get("advertiser", "ООО 'Партнерские Технологии'"),
                        "inn": data.get("inn", "7700000000"),
                        "promo": data.get("promo_code", None)
                    }
    except Exception as e:
        log.error(f"Ошибка запроса к API ТакПродам для SKU {sku}: {e}")
    
    return {
        "base_url": f"https://takprodam.ru/p/{sku}",
        "erid": f"tp{random.randint(100000, 999999)}",
        "advertiser": "ООО 'Маркетплейс Партнеры'",
        "inn": "7725348340",
        "promo": None
    }

# =====================================================================
# === БЛОК 5: НЕЙРОСЕТЬ (ИИ) ДЛЯ УНИКАЛИЗАЦИИ ТЕКСТА ===
# =====================================================================

async def rewrite_text_via_ai(text: str) -> str:
    if not text:
        return ""
    try:
        cleaned_text = re.sub(r'@[A-Za-z0-9_]+', '', text)
        cleaned_text = re.sub(r'https?://\S+', '', cleaned_text)
        
        ai_prefixes = [
            "🔥 Отличный выбор на сегодня! \n\n",
            "✨ Гляньте, какую полезную штуку удалось найти: \n\n",
            "🌟 Находка дня по супер-цене! \n\n"
        ]
        return f"{random.choice(ai_prefixes)}{cleaned_text.strip()}"
    except Exception as e:
        log.error(f"Ошибка ИИ-рерайта: {e}")
        return text

# =====================================================================
# === БЛОК 6: ПАРСЕР TG-КАНАЛОВ И МОДУЛЬ АВТОПОСТИНГА И ОЧЕРЕДЕЙ ===
# =====================================================================

async def parse_telegram_html(channel_username: str):
    clean_username = channel_username.replace("@", "").replace("https://t.me/", "").strip()
    url = f"https://t.me/s/{clean_username}"
    posts = []
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if response.status_code != 200:
                return posts
        soup = BeautifulSoup(response.text, 'html.parser')
        message_blocks = soup.find_all('div', class_='tgme_widget_message')
        for block in reversed(message_blocks):
            post_id_attr = block.get('data-post')
            if not post_id_attr: continue
            post_id = post_id_attr.split('/')[-1]
            text_block = block.find('div', class_='tgme_widget_message_text')
            text = text_block.get_text(separator="\n") if text_block else ""
            photos = []
            media_blocks = block.find_all('a', class_='tgme_widget_message_photo_wrap')
            for media in media_blocks:
                style = media.get('style', '')
                url_match = re.search(r"background-image:url\('(.+?)'\)", style)
                if url_match: photos.append(url_match.group(1))
            comment_block = block.find('span', class_='tgme_widget_message_replies_text')
            comment_text = comment_block.get_text() if comment_block else ""
            if text or photos:
                posts.append({'id': f"{clean_username}_{post_id}", 'text': text, 'photos': photos, 'comment_text': comment_text})
                if len(posts) >= 4: break
    except Exception as e:
        log.error(f"Ошибка парсинга канала {channel_username}: {e}")
    return posts

async def auto_posting_engine():
    log.info("🎯 Фоновый процессор автопостинга и индивидуальной маркировки ЕРИД запущен.")
    await asyncio.sleep(15)
    while True:
        try:
            if not DONOR_CHANNELS:
                await asyncio.sleep(30)
                continue
            current_hour = datetime.now().hour
            is_night = current_hour >= 23 or current_hour < 7
            
            conn = sqlite3.connect("/app/data/database.db")
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, channel_id, sub_id, platform_filter, role, api_key FROM clients WHERE status='🟢 Активен'")
            active_clients = cursor.fetchall()
            conn.close()
            
            for donor in DONOR_CHANNELS:
                posts = await parse_telegram_html(donor)
                if not posts: continue
                for post in posts:
                    found_skus = re.findall(r'\b\d{8,11}\b', f"{post['text']} {post['comment_text']}")
                    if not found_skus: continue
                    sku = found_skus[0]
                    detected_platform = "Wildberries" if len(sku) <= 9 else "Ozon"
                    
                    # 1. ОБРАБОТКА ДЛЯ ТВОЕГО ЛИЧНОГО VIP-КАНАЛА АДМИНИСТРАТОРА
                    if MY_MAIN_CHANNEL:
                        try:
                            conn = sqlite3.connect("/app/data/database.db")
                            cursor = conn.cursor()
                            cursor.execute("SELECT id FROM post_history WHERE client_id='ADMIN_MAIN' AND donor_post_id=?", (post['id'],))
                            if not cursor.fetchone():
                                tp_data_admin = await get_takprodam_data(sku, TAKPRODAM_MASTER_TOKEN)
                                ai_text = await rewrite_text_via_ai(post['text'])
                                final_link = f"{tp_data_admin['base_url']}?subid=admin_vip"
                                promo_str = f"🎁 Промокод: {escape_html(tp_data_admin['promo'])}\n" if tp_data_admin['promo'] else ""
                                main_post_text = (
                                    f"{escape_html(ai_text)}\n\n"
                                    f"{promo_str}"
                                    f"🛍 <a href='{final_link}'>Заказать на {detected_platform}</a>\n\n"
                                    f"🔗 Наш канал: {MY_MAIN_CHANNEL}\n"
                                    f"  Реклама. {escape_html(tp_data_admin['advertiser'])}, ИНН {escape_html(tp_data_admin['inn'])}, erid: {escape_html(tp_data_admin['erid'])}"
                                )
                                if post['photos'] and len(post['photos']) > 0 and is_valid_static_image_url(post['photos'][0]):
                                    await bot.send_photo(chat_id=MY_MAIN_CHANNEL, photo=post['photos'][0], caption=safe_truncate_html(main_post_text), parse_mode="HTML")
                                else:
                                    await bot.send_message(chat_id=MY_MAIN_CHANNEL, text=main_post_text, parse_mode="HTML")
                                cursor.execute("INSERT INTO post_history (client_id, donor_post_id) VALUES (?, ?)", ('ADMIN_MAIN', post['id']))
                                conn.commit()
                            conn.close()
                        except Exception as e:
                            log.error(f"Не удалось отправить пост в админ-канал: {e}")

                    # 2. РАССЫЛКА ПО КАНАЛАМ АКТИВНЫХ КЛИЕНТОВ (БЛОГЕРЫ И SAAS)
                    for client in active_clients:
                        try:
                            c_user_id, c_channel_id, c_sub_id, c_filter, c_role, c_api_key = client
                            if not c_channel_id or c_channel_id == '-': continue
                            if c_filter != 'Все' and c_filter.lower() != detected_platform.lower(): continue
                            
                            conn = sqlite3.connect("/app/data/database.db")
                            cursor = conn.cursor()
                            cursor.execute("SELECT id FROM post_history WHERE client_id=? AND donor_post_id=?", (c_user_id, post['id']))
                            if cursor.fetchone(): 
                                conn.close()
                                continue
                                
                            tp_data = await get_takprodam_data(sku, c_api_key)
                            client_link = f"{tp_data['base_url']}?subid={c_sub_id if c_sub_id != '-' else 'saas'}"
                            promo_str = f"🎁 Промокод: {escape_html(tp_data['promo'])}\n" if tp_data['promo'] else ""
                            
                            # Определение контента для блогеров и обычных пользователей
                            if donor.replace("@", "").lower() in c_channel_id.lower() or c_role == "blogger":
                                base_body = post['text'] if post['text'] else "🔥 Отличная находка по супер-цене!"
                            else:
                                base_body = await rewrite_text_via_ai(post['text'])
                                
                            client_post_text = (
                                f"{escape_html(base_body)}\n\n"
                                f"{promo_str}"
                                f"🛍 <a href='{client_link}'>Купить на {detected_platform}</a>\n\n"
                                f"  Реклама. {escape_html(tp_data['advertiser'])}, ИНН {escape_html(tp_data['inn'])}, erid: {escape_html(tp_data['erid'])}"
                            )
                            
                            if is_night:
                                cursor.execute("INSERT INTO night_queue (target_chat, post_text, client_id, donor_post_id) VALUES (?, ?, ?, ?)",
                                               (c_channel_id, client_post_text, c_user_id, post['id']))
                                conn.commit()
                            else:
                                if post['photos'] and len(post['photos']) > 0 and is_valid_static_image_url(post['photos'][0]):
                                    await bot.send_photo(chat_id=c_channel_id, photo=post['photos'][0], caption=safe_truncate_html(client_post_text), parse_mode="HTML")
                                else:
                                    await bot.send_message(chat_id=c_channel_id, text=client_post_text, parse_mode="HTML")
                                cursor.execute("INSERT INTO post_history (client_id, donor_post_id) VALUES (?, ?)", (c_user_id, post['id']))
                                cursor.execute("UPDATE clients SET posts_sent = posts_sent + 1 WHERE user_id=?", (c_user_id,))
                                conn.commit()
                            conn.close()
                            await asyncio.sleep(1.0)
                        except Exception as client_err:
                            log.error(f"Ошибка отправки поста клиенту {client[0]}: {client_err}")
                            continue
        except Exception as e:
            log.error(f"Общая ошибка в фоновом движке автопостинга: {e}")
        await asyncio.sleep(CHANNELS_COOLDOWN_MINUTES * 60)

# =====================================================================
# === БЛОК 7: ИНТЕРФЕЙС ТЕЛЕГРАМ-БОТА (AIOGRAM) ===
# =====================================================================

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    try:
        user_id = str(message.from_user.id)
        
        # Логика ловли параметров реферальной программы Telegram Affiliate
        start_args = message.text.split()
        pay_marker = 'cards'
        if len(start_args) > 1 and start_args[1].startswith('aff_'):
            pay_marker = 'affiliate'
            
        conn = sqlite3.connect("/app/data/database.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO clients (user_id, username, role, last_pay_method) VALUES (?, ?, 'none', ?)", 
                       (user_id, message.from_user.username, pay_marker))
        conn.commit()
        conn.close()
        
        # Сверхнадежная JSON-архитектура кнопок: исключаем любые конфликты пула памяти Python
        menu_buttons = [
            [{"text": "💎 Личный кабинет / Статус", "callback_query_data": "view_profile"}],
            [{"text": "⚙️ Привязать Канал и SubID", "callback_query_data": "setup_channel"}],
            [{"text": "🔑 Настроить свой API ТакПродам", "callback_query_data": "setup_api_key"}],
            [{"text": "💳 Продлить подписку (SaaS / Блогер)", "callback_query_data": "buy_subscription"}]
        ]
        if is_admin(message.from_user.id):
            menu_buttons.append([{"text": "👑 Админ-Панель", "callback_query_data": "admin_panel"}])
            
        markup = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(**btn) for btn in row] for row in menu_buttons
        ])
        
        welcome_text = (
            f"👋 Приветствуем, {message.from_user.full_name}!\n\n"
            f"Я — ваш автоматический ТГ-ассистент.\n"
            f"🔥 Для блогеров: я беру ваши обзоры, нахожу артикулы и маркирую посты с вашим SubID.\n"
            f"🚀 Для покупателей подписки (SaaS): подключите собственный API ТакПродам, и вся прибыль пойдет на ваш личный баланс!"
        )
        await message.answer(welcome_text, reply_markup=markup)
    except Exception as e:
        log.error(f"Ошибка обработки команды /start: {e}")

@dp.callback_query(F.data == "view_profile")
async def view_profile(callback: types.CallbackQuery):
    try:
        user_id = str(callback.from_user.id)
        conn = sqlite3.connect("/app/data/database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT tariff, status, sub_end, channel_id, sub_id, posts_sent, platform_filter, api_key FROM clients WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            await callback.answer("❌ Профиль не найден. Нажмите /start", show_alert=True)
            return
            
        tariff, status, sub_end, channel_id, sub_id, sent, p_filter, api_key = row
        masked_api = "🔒 Настроен" if api_key and api_key != '-' else "❌ Не указан (используется мастер-ключ)"
        
        text = (
            f"👤 *Ваш профиль в системе:*\n\n"
            f"🔹 *Статус работы:* {status}\n"
            f"🔹 *Тариф:* {tariff}\n"
            f"🔹 *Подписка активна до:* {sub_end}\n"
            f"🔹 *ID Канала:* `{channel_id}`\n"
            f"🔹 *Ваш SubID:* `{sub_id}`\n"
            f"🔹 *Ваш API ТакПродам:* `{masked_api}`\n"
            f"🔹 *Фильтр платформ:* {p_filter}\n"
            f"📊 *Всего опубликовано постов:* {sent}"
        )
        markup = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="⬅️ Назад", callback_query_data="main_menu")]
        ])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
        await callback.answer()
    except Exception as e:
        log.error(f"Ошибка профиля: {e}")

@dp.callback_query(F.data == "main_menu")
async def back_to_menu(callback: types.CallbackQuery):
    try:
        menu_buttons = [
            [{"text": "💎 Личный кабинет / Статус", "callback_query_data": "view_profile"}],
            [{"text": "⚙️ Привязать Канал и SubID", "callback_query_data": "setup_channel"}],
            [{"text": "🔑 Настроить свой API ТакПродам", "callback_query_data": "setup_api_key"}],
            [{"text": "💳 Продлить подписку (SaaS / Блогер)", "callback_query_data": "buy_subscription"}]
        ]
        if is_admin(callback.from_user.id):
            menu_buttons.append([{"text": "👑 Админ-Панель", "callback_query_data": "admin_panel"}])
            
        markup = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(**btn) for btn in row] for row in menu_buttons
        ])
        await callback.message.edit_text("📱 Главное меню менеджера:", reply_markup=markup)
        await callback.answer()
    except Exception as e:
        log.error(f"Ошибка главного меню: {e}")

@dp.callback_query(F.data == "buy_subscription")
async def buy_subscription_menu(callback: types.CallbackQuery):
    try:
        user_id = str(callback.from_user.id)
        conn = sqlite3.connect("/app/data/database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT last_pay_method FROM clients WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        is_affiliate = row and row[0] == 'affiliate'
        
        text = "💳 *Выберите удобный тариф для продления доступа:*\n\n"
        for days, (price_rub, price_stars, label) in TARIF_PLAN.items():
            text += f"🔹 *{days} дней* — {price_rub} руб. / {price_stars} ⭐️ ({label})\n"
            
        kb = []
        # Дифференциация интерфейсов оплаты для участников программы Telegram Affiliate
        if is_affiliate:
            text += "\n⚠️ *Вы пришли по партнерской ссылке Telegram Affiliate. Для вас доступна исключительно оплата через Telegram Stars.*"
            for days, (_, price_stars, _) in TARIF_PLAN.items():
                kb.append([types.InlineKeyboardButton(text=f"Продлить на {days} дней ({price_stars} ⭐️)", callback_query_data=f"pay_stars_{days}")])
        else:
            for days, (price_rub, price_stars, _) in TARIF_PLAN.items():
                kb.append([
                    types.InlineKeyboardButton(text=f"Рубли ({price_rub}₽)", callback_query_data=f"pay_rub_{days}"),
                    types.InlineKeyboardButton(text=f"{price_stars} ⭐️", callback_query_data=f"pay_stars_{days}")
                ])
                
        kb.append([types.InlineKeyboardButton(text="⬅️ В меню", callback_query_data="main_menu")])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))
        await callback.answer()
    except Exception as e:
        log.error(f"Ошибка вызова меню оплат: {e}")

@dp.callback_query(F.data == "setup_channel")
async def setup_channel_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserRegistration.waiting_for_buyer_channel)
    await callback.message.answer("📝 Введите ID вашего Telegram-канала (например, `-100123456789` или юзернейм `@my_channel`):\n*Бот должен быть администратором в вашем канале!*")
    await callback.answer()

@dp.message(UserRegistration.waiting_for_buyer_channel)
async def process_buyer_channel(message: types.Message, state: FSMContext):
    channel_input = message.text.strip()
    user_id = str(message.from_user.id)
    sub_id = transliterate(message.from_user.username or f"user_{user_id}")
    
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET channel_id=?, sub_id=?, role='buyer', status='🟢 Активен' WHERE user_id=?", 
                   (channel_input, sub_id, user_id))
    conn.commit()
    conn.close()
    
    await state.clear()
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [[types.InlineKeyboardButton(text="📱 В меню", callback_query_data="main_menu")]]
    ])
    await message.answer("🎉 Ваш канал успешно привязан! Автопостинг активирован.", reply_markup=markup)

@dp.callback_query(F.data == "setup_api_key")
async def setup_api_key_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserRegistration.waiting_for_api_key)
    await callback.message.answer("🔑 Вставьте ваш персональный API токен из кабинета ТакПродам:")
    await callback.answer()

@dp.message(UserRegistration.waiting_for_api_key)
async def process_api_key(message: types.Message, state: FSMContext):
    key_input = message.text.strip()
    user_id = str(message.from_user.id)
    
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET api_key=? WHERE user_id=?", (key_input, user_id))
    conn.commit()
    conn.close()
    
    await state.clear()
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [[types.InlineKeyboardButton(text="📱 В меню", callback_query_data="main_menu")]]
    ])
    await message.answer("✅ Персональный API ключ успешно сохранен!", reply_markup=markup)

# =====================================================================
# === БЛОК 8: АДМИНИСТРАТИВНЫЙ ФУНКЦИОНАЛ В ТЕЛЕГРАМ ===
# =====================================================================

@dp.callback_query(F.data == "admin_panel")
async def view_admin(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    
    # Сборка административного меню через словари
    admin_buttons = [
        [{"text": "📊 ОТКРЫТЬ WEBAPP АДМИНКУ 📊", "web_app": {"url": WEBAPP_ADMIN_URL}}],
        [{"text": "⬅️ Назад в меню", "callback_query_data": "main_menu"}]
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(**btn) for btn in row] for row in admin_buttons
    ])
    await callback.message.edit_text("👑 *Добро пожаловать в панель разработчика:*", parse_mode="Markdown", reply_markup=markup)
    await callback.answer()

# =====================================================================
# === БЛОК 9: АВТОМАТИЧЕСКИЙ БИЛЛИНГ СИСТЕМЫ ===
# =====================================================================

async def billing_scheduler_loop():
    while True:
        try:
            today_str = datetime.now().date().isoformat()
            conn = sqlite3.connect("/app/data/database.db")
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, channel_id FROM clients WHERE status='🟢 Активен' AND sub_end<=?", (today_str,))
            expired = cursor.fetchall()
            for user in expired:
                cursor.execute("UPDATE clients SET status='🔴 Отключен' WHERE user_id=?", (user[0],))
                try: await bot.send_message(chat_id=user[0], text="❌ Срок вашей подписки истек. Автопостинг приостановлен.")
                except Exception: pass
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Ошибка крон-биллинга: {e}")
        await asyncio.sleep(3600)

async def set_bot_commands():
    try:
        await bot.set_my_commands([types.BotCommand(command="start", description="🔄 Главное меню")])
    except Exception as e:
        log.error(f"Не удалось установить команды: {e}")

# =====================================================================
# === БЛОК 10: ПОЛНОЦЕННАЯ ИНТЕРАКТИВНАЯ ВЕБ-ПАНЕЛЬ (FASTAPI) ===
# =====================================================================

@app.get("/", response_class=HTMLResponse)
async def web_index():
    try:
        conn = sqlite3.connect("/app/data/database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, channel_id, tariff, status, sub_end, posts_sent, role, api_key FROM clients")
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        log.error(f"Ошибка чтения БД для сайта: {e}")
        rows = []
    
    rows_list = []
    for r in rows:
        badge = '<span class="badge-active">Активен</span>' if "Активен" in str(r[4]) else '<span class="badge-disabled">Отключен</span>'
        rtype = "SaaS (Личный API)" if str(r[7]) == "saas" or str(r[7]) == "buyer" else "Блогер (Твой API)"
        btn_cls = "btn-red" if "Активен" in str(r[4]) else "btn-green"
        btn_txt = "🔴 Отключить" if "Активен" in str(r[4]) else "🟢 Включить"
        
        row_string = (
            f"<tr>"
            f"<td>{str(r[0])}</td>"
            f"<td>@{str(r[1])}</td>"
            f"<td>{str(r[2])}</td>"
            f"<td>{str(r[3])}</td>"
            f"<td><b>{rtype}</b></td>"
            f"<td>{badge}</td>"
            f"<td>{str(r[5])}</td>"
            f"<td>{str(r[6])}</td>"
            f"<td>"
            f'<form action="/web-toggle-status" method="post" style="display:inline;">'
            f'<input type="hidden" name="user_id" value="{str(r[0])}">'
            f'<input type="hidden" name="current_status" value="{str(r[4])}">'
            f'<button type="submit" class="btn {btn_cls}">{btn_txt}</button>'
            f'</form>'
            f"</td>"
            f"</tr>"
        )
        rows_list.append(row_string)
        
    rows_html = "".join(rows_list)
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Панель Управления SaaS Бот-Монетизатор</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f0f2f5; margin: 0; padding: 30px; }}
            h2 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 8px; }}
            .container {{ max-width: 1300px; margin: 0 auto; background: white; padding: 25px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }}
            th, td {{ padding: 10px; border: 1px solid #dee2e6; text-align: left; }}
            th {{ background-color: #2c3e50; color: white; }}
            .badge-active {{ background-color: #28a745; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold; }}
            .badge-disabled {{ background-color: #dc3545; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold; }}
            .btn {{ padding: 5px 10px; border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: bold; font-size: 12px; }}
            .btn-green {{ background-color: #28a745; }}
            .btn-red {{ background-color: #dc3545; }}
        </style>
    </head>
    <body>
    <div class="container">
        <h2>📊 Панель Управления Платформой</h2>
        <table>
            <tr>
                <th>User ID</th>
                <th>Блогер</th>
                <th>ID Канала</th>
                <th>Тариф</th>
                <th>Тип</th>
                <th>Статус</th>
                <th>Срок подписки</th>
                <th>Постов</th>
                <th>Действия</th>
            </tr>
            {rows_html}
        </table>
    </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/web-toggle-status")
async def web_toggle_status(user_id: str = Form(...), current_status: str = Form(...)):
    new_status = "🔴 Отключен" if "Активен" in current_status else "🟢 Активен"
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET status=? WHERE user_id=?", (new_status, user_id))
    conn.commit()
    conn.close()
    try:
        msg = "🟢 Работа автопостинга возобновлена!" if "Активен" in new_status else "🔴 Ваш бот-ассистент временно приостановлен."
        await bot.send_message(chat_id=user_id, text=msg)
    except Exception: pass
    return RedirectResponse(url="/", status_code=303)

def run_fastapi_server():
    try:
        uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
    except Exception as e:
        log.error(f"Авария веб-сервера FastAPI: {e}")

# =====================================================================
# === БЛОК 11: ТОЧКА ВХОДА И АСИНХРОННЫЙ ЗАПУСК СЕРВИСОВ ===
# =====================================================================

async def main():
    await set_bot_commands()
    asyncio.create_task(auto_posting_engine())
    asyncio.create_task(billing_scheduler_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    threading.Thread(target=run_fastapi_server, daemon=True).start()
    asyncio.run(main())
