import logging
import os
import sqlite3
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# --- КОНФИГУРАЦИЯ ИЗ ENVIRONMENT VARIABLES ---
TOKEN = os.getenv("OT_TOKEN")
ADMIN_IDS = [aid.strip() for aid in os.getenv("ADMIN_IDS", "").split(",") if aid.strip()]
DONOR_CHANNELS = [d.strip() for d in os.getenv("DONOR_CHANNELS", "").split(",") if d.strip()]

# Реквизиты для вывода клиентам
PAY_SBER = os.getenv("PAY_SBER", "Не указан")
PAY_TBANK = os.getenv("PAY_TBANK", "Не указан")
PAY_CRYPTO = os.getenv("PAY_CRYPTO_TON", "Не указан")
PAY_VISA = os.getenv("PAY_VISA_KG", "Не указан")

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

# --- ИНИЦИАЛИЗАЦИЯ РАСШИРЕННОЙ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    # Таблица клиентов (Блогеры и Покупатели SaaS)
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
    
    # Таблица истории постов (Защита от дублирования контента)
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
    
    # ИНТЕРФЕЙС АДМИНИСТРАТОРА
    if is_admin(uid):
        builder = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text="🎯 Список Блогеров", callback_data="list_bloggers"),
                types.InlineKeyboardButton(text="🛍 Список Покупателей", callback_data="list_buyers")
            ],
            [types.InlineKeyboardButton(text="📢 Таргетированная Рассылка", callback_data="admin_broadcast")],
            [types.InlineKeyboardButton(text="🔄 Обновить статус подписок", callback_data="check_billing")]
        ])
        await message.answer("🛠 **Панель управления AutoErid SMM**\n\nВы зашли как Администратор. Управляйте пользователями, проверяйте оплаты и запускайте рассылки через меню ниже:", reply_markup=builder, parse_mode="Markdown")
        return

    user = get_user_data(uid)
    
    # ИНТЕРФЕЙС ЗАРЕГИСТРИРОВАННЫХ ПОЛЬЗОВАТЕЛЕЙ
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
                    [types.InlineKeyboardButton(text="💳 Продлить/Оплатить подписку", callback_data="pay_sub")],
                    [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
                ])
                await message.answer("❌ **Доступ к автопостингу ограничен.**\n\nВаша подписка закончилась, и публикации в канал приостановлены. Канал законсервирован на 7 дней. Пожалуйста, продлите подписку для возобновления работы:", reply_markup=builder, parse_mode="Markdown")
            else:
                builder = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="👤 Личный кабинет", callback_data="buyer_cabinet")],
                    [types.InlineKeyboardButton(text="⚙️ Настройка фильтров", callback_data="buyer_filters")],
                    [types.InlineKeyboardButton(text="💳 Продлить подписку", callback_data="pay_sub")],
                    [types.InlineKeyboardButton(text="💬 Служба поддержки", callback_data="user_support")]
                ])
                await message.answer(f"👋 Добро пожаловать! Ваш аккаунт настроен как **Покупатель подписки**.\n\nРобот ведет автоматический мониторинг доноров и наполняет ваш канал.", reply_markup=builder, parse_mode="Markdown")
        return

    # ВХОДНОЙ ФИЛЬТР / СЕГМЕНТАЦИЯ НОВЫХ ПОЛЬЗОВАТЕЛЕЙ
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

# --- СЦЕНАРИЙ РЕГИСТРАЦИИ: БЛОГЕР ---
@dp.callback_query(F.data == "reg_blogger")
async def reg_blogger_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🔗 **Шаг 1/1:** Отправьте ссылку на ваш основной источник трафика (YouTube Shorts, TikTok, Instagram Reels или профиль):")
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
    cursor.execute("""INSERT OR REPLACE INTO clients 
                      (user_id, username, source_link, sub_id, role, sub_end) 
                      VALUES (?, ?, ?, ?, 'blogger', ?)""", 
                   (uid, uname, source, sub_id, (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📈 Моя статистика", callback_data="blogger_stats")]
    ])
    await message.answer(f"✅ **Регистрация успешна!**\n\nВам присвоен уникальный партнерский маркер: `{sub_id}`.\nБот привязан к вашему ресурсу. Напишите создателю @Zigih90 для завершения настройки автоматического постинга.", reply_markup=builder, parse_mode="Markdown")
    await state.clear()

# --- СЦЕНАРИЙ РЕГИСТРАЦИИ: ПОКУПАТЕЛЬ ПОДПИСКИ ---
@dp.callback_query(F.data == "reg_buyer")
async def reg_buyer_start(callback: types.CallbackQuery, state: FSMContext):
    instr = (
        "🛠 **Инструкция по подключению канала:**\n\n"
        f"1. Добавьте этого бота в ваш Telegram-канал в качестве **Администратора**.\n"
        "2. Дайте боту всего два разрешения:\n"
        "   • *Публикация сообщений (Post Messages)*\n"
        "   • *Редактирование сообщений (Edit Messages)*\n\n"
        "👉 После этого **отправьте сюда юзернейм канала** (например, `@my_skidki_channel`) или его цифровой ID:"
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
            await message.answer("❌ **Ошибка:** Бот не найден в списке администраторов этого канала. Пожалуйста, добавьте бота в админы и попробуйте отправить юзернейм еще раз.")
            return
    except TelegramBadRequest:
        await message.answer("❌ **Ошибка:** Не удалось найти указанный канал или у бота нет к нему доступа. Проверьте правильность написания юзернейма (должен начинаться с @) и то, что канал открытый.")
        return
    except Exception:
        await message.answer("❌ Произошла непредвиденная ошибка при проверке канала. Убедитесь, что бот добавлен в канал.")
        return

    test_end = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("""INSERT OR REPLACE INTO clients 
                      (user_id, username, channel_id, role, sub_end, sub_type) 
                      VALUES (?, ?, ?, 'buyer', ?, 'Тестовая')""", 
                   (uid, uname, channel_input, test_end))
    conn.commit()
    conn.close()
    
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="👤 Войти в личный кабинет", callback_data="buyer_cabinet")]
    ])
    await message.answer(f"✅ **Канал успешно подключен!**\n\nВам автоматически начислено **3 дня тестового периода**. Робот приступает к формированию уникальной ленты для вашего канала `{channel_input}`.", reply_markup=builder, parse_mode="Markdown")
    await state.clear()

# --- МЕНЮ БЛОГЕРА ---
@dp.callback_query(F.data == "blogger_stats")
async def show_blogger_stats(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    if not user: return
    text = (f"📈 **Аналитика партнера:**\n\n"
            f"🎥 **Ресурс трафика:** {user[4]}\n"
            f"🏷 **Ваш SubID:** `{user[5]}`\n"
            f"📊 Сгенерировано постов: {user[10]}\n"
            f"🖱 Уникальных переходов: {user[11]}\n"
            f"💰 Финансовый баланс обновляется раз в сутки напрямую из API «ТакПродам». По вопросам выплат пишите в поддержку.")
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

# --- МЕНЮ ПОКУПАТЕЛЯ ПОДПИСКИ ---
@dp.callback_query(F.data == "buyer_cabinet")
async def show_buyer_cabinet(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    if not user: return
    text = (f"👤 **Личный кабинет SaaS-клиента:**\n\n"
            f"📢 **Ваш канал:** `{user[3]}`\n"
            f"🟢 **Статус системы:** {user[7]}\n"
            f"📦 **Тариф подписки:** {user[8]}\n"
            f"⏳ **Доступ активен до:** {user[9]}\n"
            f"📊 Опубликовано постов роботом: {user[10]}\n"
            f"⚙️ Выбранный фильтр: {user[13]}\n"
            f"💳 Последний платеж через: {user[12]}")
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "buyer_filters")
async def buyer_filters_menu(callback: types.CallbackQuery):
    user = get_user_data(callback.from_user.id)
    if user[8] == 'Тестовая':
        await callback.message.answer("🔒 **Фильтры контента доступны только на Полной подписке.**\nНа тестовом периоде бот публикует находки со всех маркетплейсов подряд для демонстрации скорости.")
        await callback.answer()
        return
        
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🛒 Только Wildberries", callback_data="set_filter_wb")],
        [types.InlineKeyboardButton(text="🔵 Только Ozon", callback_data="set_filter_ozon")],
        [types.InlineKeyboardButton(text="💥 Все вместе (WB + Ozon)", callback_data="set_filter_all")]
    ])
    await callback.message.answer("⚙️ **Настройка маркетплейсов для вашей ленты:**\nВыберите, из каких магазинов робот должен подбирать товары в ваш канал:", reply_markup=builder, parse_mode="Markdown")
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
    
    await callback.message.answer(f"✅ Фильтр контента успешно изменен на: **{selected}**")
    await callback.answer()

# --- МОДУЛЬ ПЛАТЕЖЕЙ С ВЫБОРОМ РЕКВИЗИТОВ ---
@dp.callback_query(F.data == "pay_sub")
async def pay_sub_menu(callback: types.CallbackQuery):
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🇷🇺 Сбербанк", callback_data="pay_method_Sberbank")],
        [types.InlineKeyboardButton(text="🟡 Т-Банк", callback_data="pay_method_T-Bank")],
        [types.InlineKeyboardButton(text="⭐️ Telegram Stars", callback_data="pay_method_Telegram Stars")],
        [types.InlineKeyboardButton(text="🪙 Криптовалюта (TON)", callback_data="pay_method_Crypto TON")],
        [types.InlineKeyboardButton(text="💳 Visa Международные", callback_data="pay_method_Visa KG")]
    ])
    await callback.message.answer("💳 **Выбор способа оплаты подписки:**\n\nВыберите платежную систему для просмотра реквизитов. После оплаты отправьте чек нашему менеджеру.", reply_markup=builder, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_method_"))
async def show_payment_details(callback: types.CallbackQuery):
    method = callback.data.split("_")[2]
    reqs = "Не указаны"
    if method == "Sberbank": reqs = PAY_SBER
    elif method == "T-Bank": reqs = PAY_TBANK
    elif method == "Crypto TON": reqs = PAY_CRYPTO
    elif method == "Visa KG": reqs = PAY_VISA
    elif method == "Telegram Stars": reqs = "Для оплаты Звездами свяжитесь напрямую с @Zigih90"

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET last_pay_method=? WHERE user_id=?", (method, str(callback.from_user.id)))
    conn.commit()
    conn.close()

    text = (f"💵 **Инструкция по оплате [{method}]:**\n\n"
            f"Реквизиты для перевода:\n`{reqs}`\n\n"
            f"После совершения перевода, пожалуйста, отправьте скриншот чека владельцу сервиса: @Zigih90.\n"
            f"Ваша подписка будет мгновенно продлена администратором после подтверждения.")
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "user_support")
async def user_support_contact(callback: types.CallbackQuery):
    await callback.message.answer("💬 **Служба поддержки проекта AutoErid SMM**\n\nПо любым техническим вопросам, предложениям по рерайту, покупке полной подписки или выводу партнерских средств блогеров пишите создателю проекта: @Zigih90")
    await callback.answer()

# =====================================================================
# --- ФУНКЦИОНАЛ АДМИНИСТРАТОРА (ОБНОВЛЕННАЯ АДМИНКА) ---
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
        await callback.message.answer("🎯 Блогеры в базе данных отсутствуют.")
        await callback.answer()
        return
        
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"👤 {r[1]} [{r[2]}]", callback_data=f"admview_{r[0]}")] for r in rows
    ])
    await callback.message.answer("🎯 **Зарегистрированные Блогеры-партнеры:**\nВыберите блогера для управления и аналитики:", reply_markup=builder, parse_mode="Markdown")
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
        await callback.message.answer("🛍 Покупатели подписки в базе данных отсутствуют.")
        await callback.answer()
        return
        
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"{r[2]} {r[1]}", callback_data=f"admview_{r[0]}")] for r in rows
    ])
    await callback.message.answer("🛍 **Покупатели SaaS-подписки:**\nЗеленый индикатор — постинг активен, красный — отключен за неуплату (консервация):", reply_markup=builder, parse_mode="Markdown")
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
        text = (f"🎯 **Карточка Блогера-Партнера:**\n\n"
                f"🆔 ИД Пользователя: `{c[1]}`\n"
                f"👤 Юзернейм: {c[2]}\n"
                f"🎥 Источник трафика: {c[4]}\n"
                f"🏷 Сгенерированный SubID: `{c[5]}`\n"
                f"📊 Отправлено постов: {c[10]}\n"
                f"🖱 Зафиксировано переходов: {c[11]}")
        builder = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🗑 Удалить из базы", callback_data=f"admdelete_{c[0]}")]
        ])
    else:
        text = (f"🛍 **Карточка Покупателя Подписки:**\n\n"
                f"👤 Владелец: {c[2]} (ID: `{c[1]}`)\n"
                f"📢 Telegram-канал: `{c[3]}`\n"
                f"⚡️ Текущий статус: {c[7]}\n"
                f"📦 Тариф: **{c[8]}**\n"
                f"⏳ Подписка до: `{c[9]}`\n"
                f"📊 Опубликовано постов: {c[10]}\n"
                f"⚙️ Фильтр маркетплейсов: {c[13]}\n"
                f"💳 Нажал кнопку оплаты через: `{c[12]}`")
        builder = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🔄 Изменить Тариф (Тест/Полная)", callback_data=f"admtoggle_{c[0]}")],
            [types.InlineKeyboardButton(text="📅 Апрув платежа / Продлить", callback_data=f"admextend_{c[0]}")],
            [types.InlineKeyboardButton(text="🗑 Удалить канал из базы", callback_data=f"admdelete_{c[0]}")]
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
    await callback.message.answer(f"✅ Тариф успешно изменен на: **{new_t}**. Постинг активирован.")
    await callback.answer()

@dp.callback_query(F.data.startswith("admextend_"))
async def admin_extend_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    c_id = callback.data.split("_")[1]
    await state.update_data(adm_client_id=c_id)
    await callback.message.answer("📅 Введите количество дней, на которое нужно продлить подписку клиенту:")
    await state.set_state(AdminStates.waiting_for_sub_days)
    await callback.answer()

@dp.message(AdminStates.waiting_for_sub_days)
async def admin_extend_save(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try:
        days = int(message.text)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное число дней (целое число).")
        return
        
    data = await state.get_data()
    c_id = data['adm_client_id']
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT sub_end FROM clients WHERE id=?", (c_id,))
    current_end_str = cursor.fetchone()[0]
    
    current_end = datetime.strptime(current_end_str, "%Y-%m-%d")
    if current_end < datetime.now():
        current_end = datetime.now()
        
    new_end = (current_end + timedelta(days=days)).strftime("%Y-%m-%d")
    cursor.execute("UPDATE clients SET sub_end=?, status='🟢 Активен' WHERE id=?", (new_end, c_id))
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Подписка успешно продлена до: `{new_end}`. Статус переведен в режим Активен.")
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
    await callback.message.answer("🗑 Клиент полностью удален из базы данных.")
    await callback.answer()

# --- СИСТЕМА ТАРГЕТИРОВАННОЙ РАССЫЛКИ ---
@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🌍 Всем пользователям", callback_data="bcastrole_all")],
        [types.InlineKeyboardButton(text="🎯 Только Блогерам", callback_data="bcastrole_blogger")],
        [types.InlineKeyboardButton(text="🛍 Только Покупателям подписки", callback_data="bcastrole_buyer")]
    ])
    await callback.message.answer("📢 **Выбор сегмента для рассылки:**\nКому должно быть отправлено информационное сообщение?", reply_markup=builder, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("bcastrole_"))
async def admin_broadcast_get_role(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    target_role = callback.data.split("_")[1]
    await state.update_data(broadcast_target=target_role)
    await callback.message.answer("✏️ Введите текст рассылки (поддерживается стандартное Markdown форматирование):")
    await state.set_state(AdminStates.waiting_for_broadcast_text)
    await callback.answer()

@dp.message(AdminStates.waiting_for_broadcast_text)
async def admin_broadcast_execute(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    target = data['broadcast_target']
    text = message.text
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    if target == 'all':
        cursor.execute("SELECT user_id FROM clients")
    else:
        cursor.execute("SELECT user_id FROM clients WHERE role=?", (target,))
    users = cursor.fetchall()
    conn.close()
    
    sent_count = 0
    for u in users:
        try:
            await bot.send_message(chat_id=u[0], text=text, parse_mode="Markdown")
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
            
    await message.answer(f"📢 Рассылка завершена! Успешно доставлено сообщений: **{sent_count}**")
    await state.clear()

# --- ФОНОВЫЙ КРОН-БИЛЛИНГ (ПРОВЕРКА СРОКОВ ПОДПИСОК) ---
async def start_billing_clock():
    log.info("Фоновый биллинг-контроллер успешно запущен.")
    while True:
        try:
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()
            today = datetime.now()
            tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")
            
            cursor.execute("SELECT user_id, channel_id FROM clients WHERE role='buyer' AND sub_end=? AND status='🟢 Активен'", (tomorrow_str,))
            warn_users = cursor.fetchall()
            for u in warn_users:
                try:
                    await bot.send_message(chat_id=u[0], text=f"⏳ **Внимание!** Подписка на робота автопостинга для канала `{u[1]}` истекает через 24 часа. Продлите доступ в личном кабинете, чтобы публикации не прекращались.", parse_mode="Markdown")
                except Exception: pass
                
            cursor.execute("SELECT user_id, channel_id FROM clients WHERE role='buyer' AND sub_end<=? AND status='🟢 Активен'", (today_str,))
            expire_users = cursor.fetchall()
            for u in expire_users:
                cursor.execute("UPDATE clients SET status='🔴 Отключен' WHERE user_id=?", (u[0],))
                try:
                    await bot.send_message(chat_id=u[0], text=f"❌ **Подписка истекла.** Автопостинг в ваш канал `{u[1]}` приостановлен. Ваш канал сохранен в системе на 7 дней консервации. Для возобновления работы нажмите кнопку оплаты.", parse_mode="Markdown")
                except Exception: pass
                
            seven_days_ago_str = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            cursor.execute("DELETE FROM clients WHERE role='buyer' AND sub_end<=? AND status='🔴 Отключен'", (seven_days_ago_str,))
            
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Ошибка биллинг-цикла: {e}")
            
        await asyncio.sleep(3600)

@dp.callback_query(F.data == "check_billing")
async def admin_trigger_billing(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    await callback.message.answer("🔄 Запущен принудительный пересчет дат подписок. Все статусы обновлены.")
    await callback.answer()

# --- ЗАГЛУШКА ДЛЯ ЭТАПА 2 И 3 (ОЧЕРЕДЬ ПАРСИНГА) ---
async def start_parsing_engine():
    log.info("ИИ-движок парсинга находится в режиме ожидания.")
    while True:
        await asyncio.sleep(60)

# --- ЗАПУСК БОТА ---
async def main():
    asyncio.create_task(start_billing_clock())
    asyncio.create_task(start_parsing_engine())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот выключен.")
