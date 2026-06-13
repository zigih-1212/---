import logging
import os
import sqlite3
import asyncio
import re
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
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

# Реквизиты для карт
PAY_SBER = os.getenv("PAY_SBER", "Не указан")
PAY_TBANK = os.getenv("PAY_TBANK", "Не указан")
PAY_CRYPTO = os.getenv("PAY_CRYPTO_TON", "Не указан")
PAY_VISA = os.getenv("PAY_VISA_KG", "Не указан")

# API Ключи интеграций
ADMITAD_API_TOKEN = os.getenv("ADMITAD_API_TOKEN")
ADMITAD_BASE64 = os.getenv("ADMITAD_BASE64")

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

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- СОСТОЯНИЯ (FSM) ---
class AdminStates(StatesGroup):
    waiting_for_sub_days = State()
    waiting_for_broadcast_text = State()
    waiting_for_broadcast_role = State()

class UserRegistration(StatesGroup):
    waiting_for_blogger_source = State()
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
    conn = sqlite3.connect('database.db')
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
                       platform_filter TEXT DEFAULT 'Вместе')''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS post_history 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       client_id TEXT,
                       donor_post_id TEXT,
                       sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

def is_admin(user_id):
    return str(user_id) in ADMIN_IDS

def get_user_data(user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients WHERE user_id=?", (str(user_id),))
    res = cursor.fetchone()
    conn.close()
    return res

# --- ОБРАБОТКА КОМАНДЫ /START ---
@dp.message(CommandStart())
async def start(message: types.Message):
    uid = message.from_user.id
    
    if is_admin(uid):
        builder = types.InlineKeyboardMarkup(inline_keyboard=[
            [[types.InlineKeyboardButton(text="🎯 Список Блогеров", callback_data="list_bloggers"),
              types.InlineKeyboardButton(text="🛍 Список Покупателей", callback_data="list_buyers")],
             [types.InlineKeyboardButton(text="📢 Таргетированная Рассылка", callback_data="admin_broadcast")],
             [types.InlineKeyboardButton(text="🔄 Обновить статус подписок", callback_data="check_billing")]]
        ][0])
        await message.answer("🛠 **Панель управления AutoErid SMM**\n\nВы зашли как Администратор. Управляйте пользователями, проверяйте оплаты и запускайте рассылки через меню ниже:", reply_markup=builder, parse_mode="Markdown")
        return

    user = get_user_data(uid)
    if user:
        role = user[6]
        status = user[7]
        if role == 'blogger':
            builder = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="📈 Моя статистика", callback_data="blogger_stats")],
                [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
            ])
            await message.answer(f"👋 Рады видеть вас, партнер! Ваш аккаунт настроен как **Блогер-партнер**.\n\nБот автоматически отслеживает ваши медиа-ресурсы и генерирует промо-посты.", reply_markup=builder, parse_mode="Markdown")
        elif role == 'buyer':
            if status == '🔴 Отключен':
                builder = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="💳 Купить/Продлить подписку", callback_data="pay_sub")],
                    [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
                ])
                await message.answer("❌ **Доступ к автопостингу ограничен.**\n\nВаша подписка закончилась. Пожалуйста, продлите подписку для возобновления работы софта:", reply_markup=builder, parse_mode="Markdown")
            else:
                builder = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="👤 Личный кабинет", callback_data="buyer_cabinet")],
                    [types.InlineKeyboardButton(text="⚙️ Настройка фильтров", callback_data="buyer_filters")],
                    [types.InlineKeyboardButton(text="💳 Продлить подписку", callback_data="pay_sub")],
                    [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
                ])
                await message.answer(f"👋 Добро пожаловать! Ваш аккаунт настроен как **Покупатель подписки**.\n\nРобот ведет автоматический мониторинг доноров и наполняет ваш канал.", reply_markup=builder, parse_mode="Markdown")
        return

    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎯 Я Блогер-партнер (Работа 50/50)", callback_data="reg_blogger")],
        [types.InlineKeyboardButton(text="🛍 Я Покупатель подписки (SaaS софт)", callback_data="reg_buyer")]
    ])
    welcome = (
        "👋 **Приветствуем в AutoErid SMM!**\n\n"
        "Наш робот полностью автоматизирует ведение Telegram-каналов со скидками и находками Wildberries & Ozon:\n"
        "• Чистит контент от водяных знаков и чужих ссылок;\n"
        "• Уникализирует описания с помощью ИИ (Grok);\n"
        "• Вшивает ЕРИД маркировку и ваши реферальные ссылки.\n\n"
        "Пожалуйста, выберите формат работы для регистрации:"
    )
    await message.answer(welcome, reply_markup=builder, parse_mode="Markdown")

# --- СЦЕНАРИИ РЕГИСТРАЦИИ (БЛОГЕР / ПОКУПАТЕЛЬ) ---
@dp.callback_query(F.data == "reg_blogger")
async def reg_blogger_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🔗 **Шаг 1/1:** Отправьте ссылку на ваш основной источник трафика (YouTube Shorts, TikTok, Instagram Reels):")
    await state.set_state(UserRegistration.waiting_for_blogger_source)
    await callback.answer()

@dp.message(UserRegistration.waiting_for_blogger_source)
async def reg_blogger_save(message: types.Message, state: FSMContext):
    uid = str(message.from_user.id)
    uname = f"@{message.from_user.username}" if message.from_user.username else "Без ника"
    source = message.text
    raw_name = message.from_user.username if message.from_user.username else f"id{uid}"
    sub_id = f"bl_{transliterate(raw_name)}"
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO clients (user_id, username, source_link, sub_id, role, sub_end) VALUES (?, ?, ?, ?, 'blogger', ?)", 
                   (uid, uname, source, sub_id, (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="📈 Моя статистика", callback_data="blogger_stats")]])
    await message.answer(f"✅ **Регистрация успешна!**\n\nВам присвоен маркер: `{sub_id}`. Напишите создателю @Zigih90 для активации стрима постов под ваши видео.", reply_markup=builder, parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data == "reg_buyer")
async def reg_buyer_start(callback: types.CallbackQuery, state: FSMContext):
    instr = (
        "🛠 **Инструкция по подключению канала:**\n\n"
        f"1. Добавьте этого бота в ваш Telegram-канал в качестве **Администратора**.\n"
        "2. Дайте боту права на *Публикацию сообщений* и *Редактирование сообщений*.\n\n"
        "👉 Отправьте сюда юзернейм канала (например, `@my_skidki_channel`):"
    )
    await callback.message.answer(instr, parse_mode="Markdown")
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
            await message.answer("❌ **Ошибка:** Бот не админ в этом канале. Дайте права и отправьте юзернейм еще раз.")
            return
    except TelegramBadRequest:
        await message.answer("❌ **Ошибка:** Канал не найден или бот заблокирован. Проверьте имя канала.")
        return
    except Exception:
        await message.answer("❌ Ошибка проверки. Убедитесь, что канал публичный и бот там присутствует.")
        return

    test_end = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO clients (user_id, username, channel_id, role, sub_end, sub_type) VALUES (?, ?, ?, 'buyer', ?, 'Тестовая')""", 
                   (uid, uname, channel_input, test_end))
    conn.commit()
    conn.close()
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="👤 Войти в личный кабинет", callback_data="buyer_cabinet")]])
    await message.answer(f"✅ **Канал успешно подключен!**\n\nВам начислено **3 дня тестового периода (Бесплатно)**. Скоро бот пришлет первый контент в `{channel_input}`.", reply_markup=builder, parse_mode="Markdown")
    await state.clear()

# --- МЕНЮ СТАТИСТИКИ И НАСТРОЕК ---
@dp.callback_query(F.data == "blogger_stats")
async def show_blogger_stats(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    if not user: return
    text = (f"📈 **Аналитика партнера:**\n\n"
            f"🎥 **Ресурс:** {user[4]}\n"
            f"🏷 **SubID:** `{user[5]}`\n"
            f"📊 Постов сделано: {user[10]}\n"
            f"鼠标 Переходов: {user[11]}\n"
            f"💰 Данные баланса обновляются раз в сутки напрямую из API «ТакПродам».")
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "buyer_cabinet")
async def show_buyer_cabinet(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    if not user: return
    text = (f"👤 **Личный кабинет SaaS-клиента:**\n\n"
            f"📢 **Ваш канал:** `{user[3]}`\n"
            f"🟢 Статус: {user[7]}\n"
            f"📦 Тариф: {user[8]}\n"
            f"⏳ Активен до: {user[9]}\n"
            f"📊 Опубликовано постов: {user[10]}\n"
            f"⚙️ Фильтр: {user[13]}")
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "buyer_filters")
async def buyer_filters_menu(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    if user[8] == 'Тестовая':
        await callback.message.answer("🔒 **Фильтры доступны только на Полной подписке.**")
        await callback.answer()
        return
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🛒 Только Wildberries", callback_data="set_filter_wb")],
        [types.InlineKeyboardButton(text="🔵 Только Ozon", callback_data="set_filter_ozon")],
        [types.InlineKeyboardButton(text="💥 Все вместе", callback_data="set_filter_all")]
    ])
    await callback.message.answer("⚙️ **Настройка маркетплейсов:**", reply_markup=builder)
    await callback.answer()

@dp.callback_query(F.data.startswith("set_filter_"))
async def set_buyer_filter(callback: types.CallbackQuery):
    f_type = callback.data.split("_")[2]
    mapping = {"wb": "Только WB", "ozon": "Только Ozon", "all": "Вместе"}
    selected = mapping.get(f_type, "Вместе")
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET platform_filter=? WHERE user_id=?", (selected, str(callback.from_user.id)))
    conn.commit()
    conn.close()
    await callback.message.answer(f"✅ Фильтр изменен на: **{selected}**")
    await callback.answer()

# --- ТАРИФНЫЕ СЕТКИ И ВЫБОР СПОСОБА ОПЛАТЫ ---
@dp.callback_query(F.data == "pay_sub")
async def pay_sub_menu(callback: types.CallbackQuery):
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"📅 15 дней — {TARIF_PLAN[15][0]}₽ / {TARIF_PLAN[15][1]}⭐️", callback_data="select_days_15")],
        [types.InlineKeyboardButton(text=f"📅 30 дней — {TARIF_PLAN[30][0]}₽ / {TARIF_PLAN[30][1]}⭐️ ({TARIF_PLAN[30][2]})", callback_data="select_days_30")],
        [types.InlineKeyboardButton(text=f"📅 90 дней — {TARIF_PLAN[90][0]}₽ / {TARIF_PLAN[90][1]}⭐️ ({TARIF_PLAN[90][2]})", callback_data="select_days_90")],
        [types.InlineKeyboardButton(text=f"📅 180 дней — {TARIF_PLAN[180][0]}₽ / {TARIF_PLAN[180][1]}⭐️ ({TARIF_PLAN[180][2]})", callback_data="select_days_180")],
        [types.InlineKeyboardButton(text=f"📅 360 дней — {TARIF_PLAN[360][0]}₽ / {TARIF_PLAN[360][1]}⭐️ ({TARIF_PLAN[360][2]})", callback_data="select_days_360")]
    ])
    await callback.message.answer("📦 **Выберите желаемый срок продления подписки:**\nЧем больше период — тем выше ваша скидка!", reply_markup=builder)
    await callback.answer()

@dp.callback_query(F.data.startswith("select_days_"))
async def select_payment_method(callback: types.CallbackQuery):
    days = int(callback.data.split("_")[2])
    rub_p, star_p, _ = TARIF_PLAN[days]
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"⭐️ Оплатить Звездами ({star_p} ⭐️) — Автоматически", callback_data=f"checkout_stars_{days}")],
        [types.InlineKeyboardButton(text=f"🇷🇺 Сбербанк ({rub_p}₽)", callback_data=f"checkout_card_Sberbank_{days}")],
        [types.InlineKeyboardButton(text=f"🟡 Т-Банк ({rub_p}₽)", callback_data=f"checkout_card_T-Bank_{days}")],
        [types.InlineKeyboardButton(text=f"💳 Visa Международные ({rub_p}₽)", callback_data=f"checkout_card_Visa KG_{days}")],
        [types.InlineKeyboardButton(text=f"🪙 Криптовалюта TON", callback_data=f"checkout_card_Crypto TON_{days}")]
    ])
    await callback.message.answer(f"💳 **Вы выбрали тариф на {days} дней.**\nВыберите удобный способ оплаты:", reply_markup=builder)
    await callback.answer()

# --- СЦЕНАРИЙ АВТО-ОПЛАТЫ ЧЕРЕЗ TELEGRAM STARS ---
@dp.callback_query(F.data.startswith("checkout_stars_"))
async def checkout_stars(callback: types.CallbackQuery):
    days = int(callback.data.split("_")[2])
    _, star_price, _ = TARIF_PLAN[days]
    
    await callback.message.answer_invoice(
        title=f"Подписка AutoErid SMM [{days} дней]",
        description=f"Автоматическое продление доступа к ИИ-автопостингу на {days} дней.",
        payload=f"sub_extend_{days}_days",
        provider_token="", 
        currency="XTR",    
        prices=[types.LabeledPrice(label=f"Доступ на {days} дн.", amount=star_price)]
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    uid = str(message.from_user.id)
    payload = message.successful_payment.invoice_payload
    # Извлекаем количество дней из payload инвойса
    days = int(re.search(r'\d+', payload).group())
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT sub_end FROM clients WHERE user_id=?", (uid,))
    res = cursor.fetchone()
    
    if res:
        current_end = datetime.strptime(res[0], "%Y-%m-%d")
        start_point = current_end if current_end > datetime.now() else datetime.now()
        new_end = (start_point + timedelta(days=days)).strftime("%Y-%m-%d")
        
        cursor.execute("UPDATE clients SET sub_end=?, sub_type='Полная', status='🟢 Активен', last_pay_method='⭐️ Stars' WHERE user_id=?", (new_end, uid))
        conn.commit()
        
        await message.answer(f"🎉 **Оплата зачислена автоматически!**\nВаша подписка успешно продлена на **{days} дней** (до `{new_end}`). Спасибо за доверие нашему сервису!")
        
        for admin_id in ADMIN_IDS:
            try: await bot.send_message(chat_id=admin_id, text=f"💰 **Авто-продажа!** Юзер @{message.from_user.username} купил тариф на {days} дней через Stars.")
            except Exception: pass
    conn.close()

# --- СЦЕНАРИЙ ОПЛАТЫ ПО КАРТАМ (РУЧНАЯ ПРОВЕРКА ЧЕКА) ---
@dp.callback_query(F.data.startswith("checkout_card_"))
async def checkout_card(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    method = parts[2]
    days = int(parts[3])
    rub_price, _, _ = TARIF_PLAN[days]
    
    reqs = PAY_SBER if method == "Sberbank" else PAY_TBANK if method == "T-Bank" else PAY_CRYPTO if method == "Crypto TON" else PAY_VISA
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET last_pay_method=? WHERE user_id=?", (f"{method} ({days} дн)", str(callback.from_user.id)))
    conn.commit()
    conn.close()
    
    text = (f"💵 **Инструкция по ручной оплате тарифа ({days} дней):**\n\n"
            f"Сумма к переводу: **{rub_price} рублей** (или эквивалент)\n"
            f"Реквизиты платежной системы [{method}]:\n`{reqs}`\n\n"
            f"👉 После совершения перевода пришлите скриншот чека создателю проекта: @Zigih90. "
            f"Администратор подтвердит оплату в системе, и ваша подписка мгновенно станет активной на {days} дней.")
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "user_support")
async def user_support_contact(callback: types.CallbackQuery):
    await callback.message.answer("💬 По всем техническим вопросам пишите создателю проекта: @Zigih90")
    await callback.answer()

# =====================================================================
# --- ИИ-ДВИЖОК ПАРСИНГА, РЕРАЙТА И ИНТЕГРАЦИИ API ТАКПРОДАМ ---
# =====================================================================

async def ai_grok_rewrite(old_text):
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.deepinfra.com/v1/openai/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": "meta-llama/Meta-Llama-3-8B-Instruct",
                    "messages": [{"role": "user", "content": f"Сделай красивый рерайт этого рекламного текста для Telegram канала скидок Wildberries. Сделай его уникальным, используй смайлики. Напиши ТОЛЬКО готовый текст поста, без лишних фраз автора: {old_text}"}]
                },
                timeout=10.0
            )
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content']
    except Exception as e:
        log.error(f"Ошибка ИИ-рерайта: {e}")
    return f"🔥 Находка на маркетплейсе! 🔥\n\n{old_text[:150]}...\n\n📦 Успей забрать по лучшей цене!"

async def generate_takprodam_link(sku, is_wb=True, subid=""):
    base_url = f"https://www.wildberries.ru/catalog/{sku}/detail.aspx" if is_wb else f"https://www.ozon.ru/product/{sku}/"
    if not ADMITAD_API_TOKEN:
        return base_url, "Реклама. ООО Маркетплейс"
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {ADMITAD_API_TOKEN}"}
            payload = {"subid": subid, "ulp": base_url}
            res = await client.post(f"https://api.admitad.com/get_links/{ADMITAD_BASE64}/", headers=headers, data=payload, timeout=5.0)
            if res.status_code == 200:
                return res.json()[0]['clink'], "Реклама. ООО 'АДМИТАД', ИНН 7714402214"
    except Exception as e:
        log.error(f"Ошибка API ТакПродам: {e}")
    return base_url, "Реклама. ООО Маркетплейс"

async def start_parsing_engine():
    log.info("ИИ-движок автоматического парсинга запущен.")
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
                    
                    conn = sqlite3.connect('database.db')
                    cursor = conn.cursor()
                    cursor.execute("SELECT user_id, channel_id, role, sub_id, platform_filter FROM clients WHERE status='🟢 Активен'")
                    clients = cursor.fetchall()
                    conn.close()
                    
                    random.shuffle(clients)
                    for client in clients:
                        user_id, channel_id, role, sub_id, platform_filter = client
                        if role == 'buyer' and platform_filter != 'Вместе' and platform_filter != market_tag: continue
                        
                        conn = sqlite3.connect('database.db')
                        cursor = conn.cursor()
                        cursor.execute("SELECT id FROM post_history WHERE client_id=? AND donor_post_id=?", (user_id, msg_id))
                        if cursor.fetchone():
                            conn.close()
                            continue
                            
                        client_subid = sub_id if role == 'blogger' else f"buy_{user_id}"
                        final_link, erid_label = await generate_takprodam_link(sku, is_wb=is_wb, subid=client_subid)
                        final_post_text = f"{unique_text}\n\n🛍 **Забрать на маркетплейсе:** [ССЫЛКА НА ТОВАР]({final_link})\n\n📍 _{erid_label}_"
                        
                        target_chat = channel_id if role == 'buyer' else user_id
                        try:
                            await bot.send_message(chat_id=target_chat, text=final_post_text, parse_mode="Markdown")
                            cursor.execute("INSERT INTO post_history (client_id, donor_post_id) VALUES (?, ?)", (user_id, msg_id))
                            cursor.execute("UPDATE clients SET posts_sent = posts_sent + 1 WHERE user_id=?", (user_id,))
                            conn.commit()
                        except Exception: pass
                        conn.close()
                        await asyncio.sleep(random.randint(5, 15))
            except Exception: pass
        await asyncio.sleep(600)

# =====================================================================
# --- ФУНКЦИОНАЛ АДМИНИСТРАТОРА (КОНТРОЛЬ СИСТЕМЫ) ---
# =====================================================================

@dp.callback_query(F.data == "list_bloggers")
async def admin_list_bloggers(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, sub_id FROM clients WHERE role='blogger'")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        await callback.message.answer("🎯 Блогеры отсутствуют.")
        await callback.answer()
        return
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text=f"👤 {r[1]} [{r[2]}]", callback_data=f"admview_{r[0]}")] for r in rows])
    await callback.message.answer("🎯 **Зарегистрированные Блогеры:**", reply_markup=builder, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "list_buyers")
async def admin_list_buyers(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, channel_id, status FROM clients WHERE role='buyer'")
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        await callback.message.answer("🛍 Покупатели отсутствуют.")
        await callback.answer()
        return
    builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text=f"{r[2]} {r[1]}", callback_data=f"admview_{r[0]}")] for r in rows])
    await callback.message.answer("🛍 **Покупатели SaaS-подписки:**", reply_markup=builder, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("admview_"))
async def admin_view_client(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    c_id = callback.data.split("_")[1]
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients WHERE id=?", (c_id,))
    c = cursor.fetchone()
    conn.close()
    if not c: return
    role = c[6]
    if role == 'blogger':
        text = (f"🎯 **Карточка Блогера:**\n\n🆔 ИД: `{c[1]}`\n👤 Юзернейм: {c[2]}\n🎥 Источник: {c[4]}\n🏷 SubID: `{c[5]}`\n📊 Постов: {c[10]}")
        builder = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🗑 Удалить из базы", callback_data=f"admdelete_{c[0]}")]])
    else:
        text = (f"🛍 **Карточка Покупателя:**\n\n👤 Владелец: {c[2]}\n📢 Канал: `{c[3]}`\n⚡️ Статус: {c[7]}\n📦 Тариф: **{c[8]}**\n⏳ До: `{c[9]}`\n📊 Постов: {c[10]}\n⚙️ Фильтр: {c[13]}\n💳 Оплата: `{c[12]}`")
        builder = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🔄 Изменить Тариф", callback_data=f"admtoggle_{c[0]}")],
            [types.InlineKeyboardButton(text="📅 Вручную продлить", callback_data=f"admextend_{c[0]}")],
            [types.InlineKeyboardButton(text="🗑 Удалить из базы", callback_data=f"admdelete_{c[0]}")]
        ])
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=builder)
    await callback.answer()

@dp.callback_query(F.data.startswith("admtoggle_"))
async def admin_toggle_sub_type(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    c_id = callback.data.split("_")[1]
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT sub_type FROM clients WHERE id=?", (c_id,))
    curr = cursor.fetchone()[0]
    new_t = "Полная" if curr == "Тестовая" else "Тестовая"
    cursor.execute("UPDATE clients SET sub_type=?, status='🟢 Активен' WHERE id=?", (new_t, c_id))
    conn.commit()
    conn.close()
    await callback.message.answer(f"✅ Тариф изменен на: **{new_t}**")
    await callback.answer()

@dp.callback_query(F.data.startswith("admextend_"))
async def admin_extend_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    c_id = callback.data.split("_")[1]
    await state.update_data(adm_client_id=c_id)
    await callback.message.answer("📅 Введите количество дней ручного продления:")
    await state.set_state(AdminStates.waiting_for_sub_days)
    await callback.answer()

@dp.message(AdminStates.waiting_for_sub_days)
async def admin_extend_save(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try: days = int(message.text)
    except ValueError: return
    data = await state.get_data()
    c_id = data['adm_client_id']
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT sub_end FROM clients WHERE id=?", (c_id,))
    current_end_str = cursor.fetchone()[0]
    current_end = datetime.strptime(current_end_str, "%Y-%m-%d")
    if current_end < datetime.now(): current_end = datetime.now()
    new_end = (current_end + timedelta(days=days)).strftime("%Y-%m-%d")
    cursor.execute("UPDATE clients SET sub_end=?, status='🟢 Активен' WHERE id=?", (new_end, c_id))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Подписка продлена до: `{new_end}`")
    await state.clear()

@dp.callback_query(F.data.startswith("admdelete_"))
async def admin_delete_client(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    c_id = callback.data.split("_")[1]
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM clients WHERE id=?", (c_id,))
    conn.commit()
    conn.close()
    await callback.message.answer("🗑 Удалено успешно.")
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🌍 Всем", callback_data="bcastrole_all")],
        [types.InlineKeyboardButton(text="🎯 Блогерам", callback_data="bcastrole_blogger")],
        [types.InlineKeyboardButton(text="🛍 Покупателям", callback_data="bcastrole_buyer")]
    ])
    await callback.message.answer("📢 **Выбор сегмента рассылки:**", reply_markup=builder)
    await callback.answer()

@dp.callback_query(F.data.startswith("bcastrole_"))
async def admin_broadcast_get_role(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.update_data(broadcast_target=callback.data.split("_")[1])
    await callback.message.answer("✏️ Введите текст рассылки:")
    await state.set_state(AdminStates.waiting_for_broadcast_text)
    await callback.answer()

@dp.message(AdminStates.waiting_for_broadcast_text)
async def admin_broadcast_execute(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    target = data['broadcast_target']
    conn = sqlite3.connect('database.db')
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
    await message.answer(f"📢 Доставлено сообщений: **{sent}**")
    await state.clear()

async def start_billing_clock():
    while True:
        try:
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()
            today = datetime.now()
            tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")
            
            cursor.execute("SELECT user_id, channel_id FROM clients WHERE role='buyer' AND sub_end=? AND status='🟢 Активен'", (tomorrow_str,))
            for u in cursor.fetchall():
                try: await bot.send_message(chat_id=u[0], text=f"⏳ Подписка для канала `{u[1]}` заканчивается через 24 часа. Продлите доступ прямо в боте.")
                except Exception: pass
                
            cursor.execute("SELECT user_id, channel_id FROM clients WHERE role='buyer' AND sub_end<=? AND status='🟢 Активен'", (today_str,))
            for u in cursor.fetchall():
                cursor.execute("UPDATE clients SET status='🔴 Отключен' WHERE user_id=?", (u[0],))
                try: await bot.send_message(chat_id=u[0], text=f"❌ Подписка для канала `{u[1]}` истекла. Постинг приостановлен.")
                except Exception: pass
                
            seven_days_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            cursor.execute("DELETE FROM clients WHERE role='buyer' AND sub_end<=? AND status='🔴 Отключен'", (seven_days_ago,))
            conn.commit()
            conn.close()
        except Exception: pass
        await asyncio.sleep(3600)

@dp.callback_query(F.data == "check_billing")
async def admin_trigger_billing(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    await callback.message.answer("🔄 Статусы подписок успешно актуализированы.")
    await callback.answer()

async def main():
    asyncio.create_task(start_billing_clock())
    asyncio.create_task(start_parsing_engine())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): log.info("Бот остановлен.")
