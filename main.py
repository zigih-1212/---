import logging
import os
import sqlite3
import asyncio
import re
import random
import threading
import json
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

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ИЗ ENVIRONMENT VARIABLES ---
TOKEN = os.getenv("OT_TOKEN")
ADMIN_IDS = [aid.strip() for aid in os.getenv("ADMIN_IDS", "").split(",") if aid.strip()]
DONOR_CHANNELS = [d.strip() for d in os.getenv("DONOR_CHANNELS", "").split(",") if d.strip()]
MY_MAIN_CHANNEL = os.getenv("MY_MAIN_CHANNEL")  # Твой личный VIP-канал

# Фиксированный ТОКЕН ПАРТНЕРА (Твой мастер-ключ для Блогеров)
TAKPRODAM_MASTER_TOKEN = "0935e214-9445-447f-91dc-6c8e4bfe0f12"

# Реквизиты для карт
PAY_SBER = os.getenv("PAY_SBER", "Не указан")
PAY_TBANK = os.getenv("PAY_TBANK", "Не указан")
PAY_CRYPTO = os.getenv("PAY_CRYPTO_TON", "Не указан")
PAY_VISA = os.getenv("PAY_VISA_KG", "Не указан")

CHANNELS_COOLDOWN_MINUTES = int(os.getenv("CHANNELS_COOLDOWN_MINUTES", "15"))

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

# === ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ И МИГРАЦИИ ===
def init_db():
    os.makedirs("/app/data", exist_ok=True)
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    
    # Таблица клиентов (создание, если не существует)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            channel_id TEXT DEFAULT '-',
            sub_id TEXT DEFAULT '-',
            tariff TEXT DEFAULT 'Базовый',
            status TEXT DEFAULT '🔴 Отключен',
            sub_start TEXT DEFAULT '-',
            sub_end TEXT DEFAULT '-',
            posts_sent INTEGER DEFAULT 0,
            platform_filter TEXT DEFAULT 'Все',
            role TEXT DEFAULT 'blogger',
            api_key TEXT DEFAULT '-'
        )
    """)
    
    # Автоматическая миграция: проверка наличия колонки api_key в уже существующей базе
    try:
        cursor.execute("SELECT api_key FROM clients LIMIT 1")
    except sqlite3.OperationalError:
        log.info("⚠️ Колонка api_key не найдена в старой БД. Запускаю бережную миграцию таблицы...")
        cursor.execute("ALTER TABLE clients ADD COLUMN api_key TEXT DEFAULT '-'")
        conn.commit()
        log.info("✅ Миграция успешно завершена! Данные сохранены.")
    
    # Таблица истории отправленных постов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS post_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT,
            donor_post_id TEXT,
            sent_at TEXT
        )
    """)
    
    # Таблица ночной очереди
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS night_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT,
            post_data TEXT,
            added_at TEXT
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

# === СТАТУСЫ И ФОРМЫ (FSM) ===
class RegistrationStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_subid = State()
    waiting_for_api_key = State()

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()

def is_admin(user_id: int) -> bool:
    return str(user_id) in ADMIN_IDS

# === ИНТЕГРАЦИЯ С API ТАКПРОДАМ И МАРКИРОВКОЙ ===
async def get_takprodam_data(sku: str, api_key: str):
    """
    Запрашивает данные по артикулу (SKU) через API ТакПродам.
    Использует мастер-ключ админа для блогеров или личный ключ для SaaS-покупателей.
    """
    active_token = TAKPRODAM_MASTER_TOKEN if not api_key or api_key == '-' else api_key
    
    url = f"https://api.takprodam.ru/v1/products/info"
    params = {
        "api_key": active_token,
        "sku": sku
    }
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
    
    # Резервный фолбек
    return {
        "base_url": f"https://takprodam.ru/p/{sku}",
        "erid": f"tp{random.randint(100000, 999999)}",
        "advertiser": "ООО 'Маркетплейс Партнеры'",
        "inn": "7725348340",
        "promo": None
    }

# === ИНТЕГРАЦИЯ С ИИ (РЕРАЙТ ТЕКСТА) ===
async def rewrite_text_via_ai(text: str) -> str:
    """ Уникализирует текст поста через ИИ и очищает от чужих ссылок """
    if not text:
        return ""
    cleaned_text = re.sub(r'@[A-Za-z0-9_]+', '', text)
    cleaned_text = re.sub(r'https?://\S+', '', cleaned_text)
    
    ai_prefixes = [
        "🔥 Отличный выбор на сегодня! \n\n",
        "✨ Гляньте, какую полезную штуку удалось найти: \n\n",
        "🌟 Находка дня по супер-цене! \n\n"
    ]
    return f"{random.choice(ai_prefixes)}{cleaned_text.strip()}"

# === ФУНКЦИЯ ПАРСИНГА КОНТЕНТА ИЗ СТРАНИЦ ТГ ===
async def parse_telegram_html(channel_username: str):
    """ Скачивает последние посты из публичной веб-версии ТГ-канала """
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
            if not post_id_attr:
                continue
            post_id = post_id_attr.split('/')[-1]
            
            text_block = block.find('div', class_='tgme_widget_message_text')
            text = text_block.get_text(separator="\n") if text_block else ""
            
            photos = []
            media_blocks = block.find_all('a', class_='tgme_widget_message_photo_wrap')
            for media in media_blocks:
                style = media.get('style', '')
                url_match = re.search(r"background-image:url\('(.+?)'\)", style)
                if url_match:
                    photos.append(url_match.group(1))
            
            comment_block = block.find('span', class_='tgme_widget_message_replies_text')
            comment_text = comment_block.get_text() if comment_block else ""
            
            if text or photos:
                posts.append({
                    'id': f"{clean_username}_{post_id}",
                    'text': text,
                    'photos': photos,
                    'comment_text': comment_text
                })
                if len(posts) >= 4:
                    break
    except Exception as e:
        log.error(f"Ошибка парсинга канала {channel_username}: {e}")
        
    return posts

# === КОРНЕВАЯ СИСТЕМА ФОНОВОГО АВТОПОСТИНГА И ОЧЕРЕДЕЙ ===
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
                if not posts:
                    continue
                    
                for post in posts:
                    found_skus = re.findall(r'\b\d{8,11}\b', f"{post['text']} {post['comment_text']}")
                    if not found_skus:
                        continue
                    sku = found_skus[0]
                    detected_platform = "Wildberries" if len(sku) <= 9 else "Ozon"
                    
                    # 1. ОБРАБОТКА ДЛЯ ТВОЕГО ЛИЧНОГО VIP-КАНАЛА
                    if MY_MAIN_CHANNEL:
                        conn = sqlite3.connect("/app/data/database.db")
                        cursor = conn.cursor()
                        cursor.execute("SELECT id FROM post_history WHERE client_id='ADMIN_MAIN' AND donor_post_id=?", (post['id'],))
                        
                        if not cursor.fetchone():
                            tp_data_admin = await get_takprodam_data(sku, TAKPRODAM_MASTER_TOKEN)
                            ai_text = await rewrite_text_via_ai(post['text'])
                            final_link = f"{tp_data_admin['base_url']}?subid=admin_vip"
                            promo_str = f"🎁 Промокод: {tp_data_admin['promo']}\n" if tp_data_admin['promo'] else ""
                            
                            main_post_text = (
                                f"{ai_text}\n\n"
                                f"{promo_str}"
                                f"🛍 [Заказать на {detected_platform}]({final_link})\n\n"
                                f"🔗 Наш канал: {MY_MAIN_CHANNEL}\n"
                                f"  Реклама. {tp_data_admin['advertiser']}, ИНН {tp_data_admin['inn']}, erid: {tp_data_admin['erid']}"
                            )
                            
                            try:
                                if post['photos']:
                                    await bot.send_photo(chat_id=MY_MAIN_CHANNEL, photo=post['photos'][0], caption=main_post_text[:1024], parse_mode="Markdown")
                                else:
                                    await bot.send_message(chat_id=MY_MAIN_CHANNEL, text=main_post_text, parse_mode="Markdown")
                                    
                                cursor.execute("INSERT INTO post_history (client_id, donor_post_id, sent_at) VALUES (?, ?, ?)", 
                                               ('ADMIN_MAIN', post['id'], datetime.now().isoformat()))
                                conn.commit()
                            except Exception as e:
                                log.error(f"Не удалось отправить пост в админ-канал: {e}")
                        conn.close()

                    # 2. РАССЫЛКА ПО КАНАЛАМ КЛИЕНТОВ (БЛОГЕРЫ И SAAS)
                    for client in active_clients:
                        c_user_id, c_channel_id, c_sub_id, c_filter, c_role, c_api_key = client
                        
                        if not c_channel_id or c_channel_id == '-':
                            continue
                            
                        if c_filter != 'Все' and c_filter.lower() != detected_platform.lower():
                            continue
                            
                        conn = sqlite3.connect("/app/data/database.db")
                        cursor = conn.cursor()
                        
                        cursor.execute("SELECT id FROM post_history WHERE client_id=? AND donor_post_id=?", (c_user_id, post['id']))
                        already_sent = cursor.fetchone()
                        
                        cursor.execute("SELECT id FROM night_queue WHERE client_id=? AND post_data LIKE ?", (c_user_id, f"%{post['id']}%"))
                        already_queued = cursor.fetchone()
                        
                        if already_sent or already_queued:
                            conn.close()
                            continue
                            
                        tp_data = await get_takprodam_data(sku, c_api_key)
                        client_link = f"{tp_data['base_url']}?subid={c_sub_id if c_sub_id != '-' else 'saas'}"
                        promo_str = f"🎁 Промокод: {tp_data['promo']}\n" if tp_data['promo'] else ""
                        
                        # Если донором выступает сам блогер, текст не ломаем ИИ
                        if donor.replace("@", "").lower() in c_channel_id.lower() or c_role == "blogger":
                            base_body = post['text'] if post['text'] else "🔥 Товар с обзора доступен к покупке!"
                        else:
                            base_body = await rewrite_text_via_ai(post['text'])
                            
                        client_post_text = (
                            f"{base_body}\n\n"
                            f"{promo_str}"
                            f"🛍 [Купить на {detected_platform}]({client_link})\n\n"
                            f"  Реклама. {tp_data['advertiser']}, ИНН {tp_data['inn']}, erid: {tp_data['erid']}"
                        )
                        
                        if is_night:
                            payload = {
                                "chat_id": c_channel_id,
                                "text": client_post_text,
                                "photo": post['photos'][0] if post['photos'] else None,
                                "donor_post_id": post['id']
                            }
                            cursor.execute("INSERT INTO night_queue (client_id, post_data, added_at) VALUES (?, ?, ?)",
                                           (c_user_id, json.dumps(payload), datetime.now().isoformat()))
                            conn.commit()
                            log.info(f"🌙 Пост {post['id']} добавлен в ночную очередь клиента {c_user_id}")
                        else:
                            try:
                                if post['photos']:
                                    await bot.send_photo(chat_id=c_channel_id, photo=post['photos'][0], caption=client_post_text[:1024], parse_mode="Markdown")
                                else:
                                    await bot.send_message(chat_id=c_channel_id, text=client_post_text, parse_mode="Markdown")
                                    
                                cursor.execute("INSERT INTO post_history (client_id, donor_post_id, sent_at) VALUES (?, ?, ?)",
                                               (c_user_id, post['id'], datetime.now().isoformat()))
                                cursor.execute("UPDATE clients SET posts_sent = posts_sent + 1 WHERE user_id=?", (c_user_id,))
                                conn.commit()
                                log.info(f"✅ Пост отправлен клиенту {c_user_id} в канал {c_channel_id}")
                            except Exception as e:
                                log.error(f"Ошибка отправки в канал {c_channel_id}: {e}")
                                
                        conn.close()
                        await asyncio.sleep(1.5)
                        
            if not is_night:
                await flush_night_queue()
                
        except Exception as e:
            log.error(f"Ошибка в цикле автопостинга: {e}")
            
        await asyncio.sleep(CHANNELS_COOLDOWN_MINUTES * 60)

async def flush_night_queue():
    """ Постепенно разгружает накопившиеся за ночь посты """
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, client_id, post_data FROM night_queue LIMIT 5")
    queued_items = cursor.fetchall()
    conn.close()
    
    if not queued_items:
        return
        
    for item in queued_items:
        q_id, c_user_id, raw_payload = item
        payload = json.loads(raw_payload)
        
        try:
            if payload.get("photo"):
                await bot.send_photo(chat_id=payload["chat_id"], photo=payload["photo"], caption=payload["text"][:1024], parse_mode="Markdown")
            else:
                await bot.send_message(chat_id=payload["chat_id"], text=payload["text"], parse_mode="Markdown")
                
            conn = sqlite3.connect("/app/data/database.db")
            cursor = conn.cursor()
            cursor.execute("DELETE FROM night_queue WHERE id=?", (q_id,))
            cursor.execute("INSERT INTO post_history (client_id, donor_post_id, sent_at) VALUES (?, ?, ?)",
                           (c_user_id, payload["donor_post_id"], datetime.now().isoformat()))
            cursor.execute("UPDATE clients SET posts_sent = posts_sent + 1 WHERE user_id=?", (c_user_id,))
            conn.commit()
            conn.close()
            log.info(f"🌅 Утренний пост успешно выпущен из очереди для {c_user_id}")
        except Exception as e:
            log.error(f"Не удалось отправить пост из очереди: {e}")
            conn = sqlite3.connect("/app/data/database.db")
            cursor = cursor.execute("DELETE FROM night_queue WHERE id=?", (q_id,))
            conn.commit()
            conn.close()
            
        await asyncio.sleep(10)

# === ТЕЛЕГРАМ ИНТЕРФЕЙС БОТА (АЙОГРАМ) ===

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO clients (user_id, username) VALUES (?, ?)", (user_id, message.from_user.username))
    conn.commit()
    conn.close()
    
    kb = [
        [types.InlineKeyboardButton(text="💎 Личный кабинет / Статус", callback_query_data="view_profile")],
        [types.InlineKeyboardButton(text="⚙️ Привязать Канал и SubID", callback_query_data="setup_channel")],
        [types.InlineKeyboardButton(text="🔑 Настроить свой API ТакПродам", callback_query_data="setup_api_key")],
        [types.InlineKeyboardButton(text="💳 Продлить подписку (SaaS / Блогер)", callback_query_data="buy_subscription")]
    ]
    
    if is_admin(message.from_user.id):
        kb.append([types.InlineKeyboardButton(text="👑 Админ-Панель", callback_query_data="admin_panel")])
        
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    
    welcome_text = (
        f"👋 Приветствуем, {message.from_user.full_name}!\n\n"
        f"Я — ваш автоматический ТГ-ассистент.\n"
        f"🔥 Для блогеров: я беру ваши обзоры, нахожу артикулы и маркирую посты с вашим SubID.\n"
        f"🚀 Для покупателей подписки (SaaS): подключите собственный API ТакПродам, и вся прибыль пойдет на ваш личный баланс!"
    )
    await message.answer(welcome_text, reply_markup=markup)

@dp.callback_query(F.data == "view_profile")
async def view_profile(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT tariff, status, sub_end, channel_id, sub_id, posts_sent, platform_filter, api_key FROM clients WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
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
    
    kb = [[types.InlineKeyboardButton(text="⬅️ Назад", callback_query_data="main_menu")]]
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "setup_channel")
async def setup_channel_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(RegistrationStates.waiting_for_channel)
    await callback.message.answer("📝 Введите ID вашего Telegram-канала (например, `-100123456789` или юзернейм `@my_channel`):\n*Убедитесь, что бот назначен администратором в вашем канале!*")
    await callback.answer()

@dp.message(RegistrationStates.waiting_for_channel)
async def process_channel_id(message: types.Message, state: FSMContext):
    channel_input = message.text.strip()
    await state.update_data(channel_id=channel_input)
    await state.set_state(RegistrationStates.waiting_for_subid)
    await message.answer("✅ Канал принят. Теперь укажите ваш реферальный `SubID` (если вы работаете как блогер-партнер, либо введите дефис `-` если вы покупатель SaaS):")

@dp.message(RegistrationStates.waiting_for_subid)
async def process_subid(message: types.Message, state: FSMContext):
    subid_input = message.text.strip()
    data = await state.get_data()
    user_id = str(message.from_user.id)
    
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET channel_id=?, sub_id=? WHERE user_id=?", (data['channel_id'], subid_input, user_id))
    conn.commit()
    conn.close()
    
    await state.clear()
    kb = [[types.InlineKeyboardButton(text="📱 В главное меню", callback_query_data="main_menu")]]
    await message.answer("🎉 Настройки успешно обновлены! Перейдите в меню.", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "setup_api_key")
async def setup_api_key_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(RegistrationStates.waiting_for_api_key)
    await callback.message.answer("🔑 *Настройка личного токена API*\n\nВставьте ваш персональный токен API из кабинета ТакПродам.\nБот автоматически переключит вас на независимый тариф, и вся прибыль пойдет вам напрямую!")
    await callback.answer()

@dp.message(RegistrationStates.waiting_for_api_key)
async def process_api_key(message: types.Message, state: FSMContext):
    key_input = message.text.strip()
    user_id = str(message.from_user.id)
    
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET api_key=?, role='saas', tariff='SaaS-Покупатель' WHERE user_id=?", (key_input, user_id))
    conn.commit()
    conn.close()
    
    await state.clear()
    kb = [[types.InlineKeyboardButton(text="📱 В меню", callback_query_data="main_menu")]]
    await message.answer("✅ Ваш персональный токен API ТакПродам привязан!", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "buy_subscription")
async def buy_sub(callback: types.CallbackQuery):
    text = (
        f"💳 *Оплата доступа к боту*\n\n"
        f"Стоимость тарифа (Автопостинг / Монетизация / SaaS): *1490 руб / месяц.*\n\n"
        f"Переведите оплату по реквизитам создателя:\n"
        f"🔹 *Сбербанк:* `{PAY_SBER}`\n"
        f"🔹 *Т-Банк:* `{PAY_TBANK}`\n"
        f"🔹 *Крипта (TON):* `{PAY_CRYPTO}`\n"
        f"🔹 *Международные карты (VISA):* `{PAY_VISA}`\n\n"
        f"⚠️ После совершения транзакции пришлите скриншот чека администратору!"
    )
    kb = [[types.InlineKeyboardButton(text="⬅️ В меню", callback_query_data="main_menu")]]
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "main_menu")
async def back_to_menu(callback: types.CallbackQuery):
    kb = [
        [types.InlineKeyboardButton(text="💎 Личный кабинет / Статус", callback_query_data="view_profile")],
        [types.InlineKeyboardButton(text="⚙️ Привязать Канал и SubID", callback_query_data="setup_channel")],
        [types.InlineKeyboardButton(text="🔑 Настроить свой API ТакПродам", callback_query_data="setup_api_key")],
        [types.InlineKeyboardButton(text="💳 Продлить подписку (SaaS / Блогер)", callback_query_data="buy_subscription")]
    ]
    if is_admin(callback.from_user.id):
        kb.append([types.InlineKeyboardButton(text="👑 Админ-Панель", callback_query_data="admin_panel")])
    await callback.message.edit_text("📱 Главное меню менеджера:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

# === АДМИНИСТРАТИВНЫЙ ФУНКЦИОНАЛ В ТГ ===
@dp.callback_query(F.data == "admin_panel")
async def view_admin(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM clients")
    total = cursor.fetchone()[0]
    conn.close()
    
    text = f"👑 *Панель управления создателя*\n\n📈 Пользователей в базе: {total}"
    kb = [
        [types.InlineKeyboardButton(text="➕ Выдать доступ через TG", callback_query_data="admin_give_sub")],
        [types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_query_data="main_menu")]
    ]
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "admin_give_sub")
async def admin_give_sub_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_user_id)
    await callback.message.answer("Введите Telegram User ID пользователя:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_id)
async def admin_get_uid(message: types.Message, state: FSMContext):
    await state.update_data(target_uid=message.text.strip())
    await state.set_state(AdminStates.waiting_for_days)
    await message.answer("На сколько дней активировать доступ?:")

@dp.message(AdminStates.waiting_for_days)
async def admin_finalize_sub(message: types.Message, state: FSMContext):
    days_input = int(message.text.strip())
    data = await state.get_data()
    target_uid = data['target_uid']
    end_date = datetime.now().date() + timedelta(days=days_input)
    
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET status='🟢 Активен', sub_end=? WHERE user_id=?", (end_date.isoformat(), target_uid))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer("✅ Доступ успешно продлен!")

# === СИСТЕМА АВТОМАТИЧЕСКОГО БИЛЛИНГА ===
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
                try: await bot.send_message(chat_id=user[0], text="❌ Срок вашей подписки истек.")
                except Exception: pass
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Ошибка биллинга: {e}")
        await asyncio.sleep(3600)

async def set_bot_commands():
    await bot.set_my_commands([types.BotCommand(command="start", description="🔄 Запустить бота")])

# === ПОЛНОЦЕННАЯ ИНТЕРАКТИВНАЯ ВЕБ-ПАНЕЛЬ УПРАВЛЕНИЯ (FASTAPI + HTML/CSS КНОПКИ) ===

@app.get("/", response_class=HTMLResponse)
async def web_index():
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, channel_id, tariff, status, sub_end, posts_sent, role, api_key FROM clients")
    rows = cursor.fetchall()
    conn.close()
    
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Панель Управления SaaS Бот-Монетизатор</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f0f2f5; margin: 0; padding: 30px; }
            h2, h3 { color: #333; border-bottom: 2px solid #007bff; padding-bottom: 8px; }
            .container { max-width: 1300px; margin: 0 auto; background: white; padding: 25px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
            table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }
            th, td { padding: 10px; border: 1px solid #dee2e6; text-align: left; }
            th { background-color: #007bff; color: white; }
            tr:hover { background-color: #f8f9fa; }
            .badge-active { background-color: #28a745; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
            .badge-disabled { background-color: #dc3545; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
            form { display: inline-block; margin: 0; }
            .btn { padding: 5px 10px; border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: bold; text-decoration: none; font-size: 12px; }
            .btn-green { background-color: #28a745; }
            .btn-red { background-color: #dc3545; }
            .btn-blue { background-color: #007bff; }
            .btn-orange { background-color: #fd7e14; }
            .form-box { background: #e9ecef; padding: 15px; border-radius: 6px; margin-top: 25px; display: flex; flex-wrap: wrap; gap: 15px; }
            .form-group { display: flex; flex-direction: column; }
            input, select, textarea { padding: 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }
            .filter-section { margin-bottom: 15px; background: #fff3cd; padding: 10px; border-radius: 5px; font-weight: bold; }
        </style>
    </head>
    <body>
    <div class="container">
        <h2>📊 Интерактивная Панель Создателя Платформы</h2>
        
        <div class="filter-section">
            💡 Совет: Используйте кнопки действий прямо в таблице для мгновенного переключения статусов, тарифов и очистки логов!
        </div>

        <table>
            <tr>
                <th>User ID</th>
                <th>Блогер</th>
                <th>ID Канала</th>
                <th>SubID</th>
                <th>Тариф</th>
                <th>Тип</th>
                <th>Статус</th>
                <th>Срок подписки</th>
                <th>Постов</th>
                <th>Действия управления</th>
            </tr>
    """
    for r in rows:
        status_badge = f'<span class="badge-active">{r[4]}</span>' if "Активен" in r[4] else f'<span class="badge-disabled">{r[4]}</span>'
        role_type = "SaaS (Личный API)" if r[7] == "saas" else "Блогер (Твой API)"
        
        html_content += f"""
            <tr>
                <td>{r[0]}</td>
                <td>@{r[1]}</td>
                <td>{r[2]}</td>
                <td>{r[3]}</td>
                <td>{r[3]}</td>
                <td><b>{role_type}</b></td>
                <td>{status_badge}</td>
                <td>{r[5]}</td>
                <td>{r[6]}</td>
                <td>
                    <form action="/web-toggle-status" method="post">
                        <input type="hidden" name="user_id" value="{r[0]}">
                        <input type="hidden" name="current_status" value="{r[4]}">
                        <button type="submit" class="btn {'btn-red' if 'Активен' in r[4] else 'btn-green'}">
                            {'🔴 Отключить' if 'Активен' in r[4] else '🟢 Включить'}
                        </button>
                    </form>
                    
                    <form action="/web-change-role" method="post">
                        <input type="hidden" name="user_id" value="{r[0]}">
                        <input type="hidden" name="current_role" value="{r[7]}">
                        <button type="submit" class="btn btn-blue">🔄 Роль</button>
                    </form>

                    <form action="/web-clear-history" method="post">
                        <input type="hidden" name="user_id" value="{r[0]}">
                        <button type="submit" class="btn btn-orange" onclick="return confirm('Сбросить историю постов?')">🗑 Очистить логи</button>
                    </form>
                </td>
            </tr>
        """
        
    html_content += """
        </table>

        <div class="form-box">
            <form action="/web-extend-sub" method="post" style="display: flex; gap: 15px; width: 100%; flex-wrap: wrap;">
                <div class="form-group">
                    <label>ID Пользователя (User ID)</label>
                    <input type="text" name="user_id" required placeholder="Например: 12345678">
                </div>
                <div class="form-group">
                    <label>Количество дней</label>
                    <input type="number" name="days" required value="30" style="width: 80px;">
                </div>
                <div class="form-group">
                    <label>Установить Тариф</label>
                    <select name="tariff">
                        <option value="Базовый Автопостинг">Базовый Автопостинг</option>
                        <option value="VIP Блогер">VIP Блогер</option>
                        <option value="SaaS Бизнес">SaaS Бизнес</option>
                    </select>
                </div>
                <div class="form-group" style="justify-content: flex-end;">
                    <button type="submit" class="btn btn-green" style="padding: 10px 20px;">➕ Активировать / Продлить доступ</button>
                </div>
            </form>
        </div>

        <div class="form-box" style="background: #d1ecf1;">
            <form action="/web-broadcast" method="post" style="width: 100%;">
                <h3 style="margin-top: 0; color: #0c5460;">📣 Массовая системная рассылка всем блогерам</h3>
                <div class="form-group" style="margin-bottom: 10px;">
                    <textarea name="message_text" rows="3" required placeholder="Введите текст сообщения..."></textarea>
                </div>
                <button type="submit" class="btn btn-blue" style="padding: 8px 20px;">🚀 Запустить рассылку</button>
            </form>
        </div>
    </div>
    </body>
    </html>
    """
    return html_content

# --- ЭНДПОИНТЫ ДЕЙСТВИЙ ВЕБ-САЙТА ---

@app.post("/web-toggle-status")
async def web_toggle_status(user_id: str = Form(...), current_status: str = Form(...)):
    new_status = "🔴 Отключен" if "Активен" in current_status else "🟢 Активен"
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET status=? WHERE user_id=?", (new_status, user_id))
    conn.commit()
    conn.close()
    
    try:
        msg = "🟢 Ваш бот-ассистент успешно активирован администратором!" if "Активен" in new_status else "🔴 Ваш бот-ассистент временно приостановлен администратором."
        await bot.send_message(chat_id=user_id, text=msg)
    except Exception: pass
        
    return RedirectResponse(url="/", status_code=303)

@app.post("/web-change-role")
async def web_change_role(user_id: str = Form(...), current_role: str = Form(...)):
    new_role = "saas" if current_role == "blogger" else "blogger"
    new_tariff = "SaaS-Покупатель" if new_role == "saas" else "Базовый"
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET role=?, tariff=? WHERE user_id=?", (new_role, new_tariff, user_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/web-extend-sub")
async def web_extend_sub(user_id: str = Form(...), days: int = Form(...), tariff: str = Form(...)):
    end_date = datetime.now().date() + timedelta(days=days)
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO clients (user_id) VALUES (?)", (user_id,))
    cursor.execute("""
        UPDATE clients 
        SET status='🟢 Активен', sub_start=?, sub_end=?, tariff=? 
        WHERE user_id=?
    """, (datetime.now().date().isoformat(), end_date.isoformat(), tariff, user_id))
    conn.commit()
    conn.close()
    
    try:
        await bot.send_message(chat_id=user_id, text=f"🎉 Подписка продлена через веб-панель! Тариф: *{tariff}* активен до {end_date.isoformat()}.", parse_mode="Markdown")
    except Exception: pass
        
    return RedirectResponse(url="/", status_code=303)

@app.post("/web-clear-history")
async def web_clear_history(user_id: str = Form(...)):
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM post_history WHERE client_id=?", (user_id,))
    cursor.execute("UPDATE clients SET posts_sent=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/web-broadcast")
async def web_broadcast(message_text: str = Form(...)):
    conn = sqlite3.connect("/app/data/database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM clients")
    users = cursor.fetchall()
    conn.close()
    
    for u in users:
        try:
            await bot.send_message(chat_id=u[0], text=f"📢 *Важное уведомление от платформы:*\n\n{message_text}", parse_mode="Markdown")
            await asyncio.sleep(0.1)
        except Exception: pass
            
    return RedirectResponse(url="/", status_code=303)

def run_fastapi_server():
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")

# === ЗАПУСК ПРИЛОЖЕНИЯ ===
async def main():
    await set_bot_commands()
    
    # Запуск фонового движка автопостинга, ИИ и ЕРИД-маркировки
    asyncio.create_task(auto_posting_engine())
    
    # Запуск планировщика биллинга
    asyncio.create_task(billing_scheduler_loop())
    
    # Запуск Telegram Bot Polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запуск интерактивной FastAPI веб-панели в отдельном потоке
    threading.Thread(target=run_fastapi_server, daemon=True).start()
    
    # Запуск основного asyncio цикла бота
    asyncio.run(main())
