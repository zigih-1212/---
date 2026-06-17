"""
=============================================================================
  АВТОПОСТИНГ-БОТ | SaaS-платформа для монетизации Telegram-каналов
  Stack: Python 3.10+, aiogram 3.x, FastAPI, SQLite3, httpx, APScheduler
  Юридическая защита: ERID обязателен. Публикация без маркировки — запрещена.
=============================================================================
"""

# =============================================================================
# === IMPORTS & CONFIG ========================================================
# =============================================================================

import asyncio
import html
import logging
import os
import re
import secrets
import sqlite3
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional
from stats import get_blogger_stats, get_saas_channels, get_saas_channel_stats, STAT_PERIODS

import httpx
import uvicorn
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    SuccessfulPayment,
    TelegramObject,
)
from aiogram.types import (
    WebAppInfo,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from parser import (
    extract_video_info,
    find_product_links,
    process_new_video,
    is_video_processed
)

# =============================================================================
# === LOGGING =================================================================
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=5 * 1024 * 1024, backupCount=3),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("autopost_bot")

# =============================================================================
# === CONFIG ==================================================================
# =============================================================================

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
]
QUARANTINE_CHAT_ID: int = int(os.getenv("QUARANTINE_CHAT_ID", "0"))
ADMIN_VIP_CHANNEL_ID: int = int(os.getenv("ADMIN_VIP_CHANNEL_ID", "0"))
DEEPINFRA_API_KEY: str = os.getenv("DEEPINFRA_API_KEY", "")
STARS_PROVIDER_TOKEN: str = os.getenv("STARS_PROVIDER_TOKEN", "")
WEBAPP_HOST: str = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT: int = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8000")))

# ---------- Реквизиты оплаты -------------------------------------------------
CARD_SBER: str = os.getenv("PAY_SBER", "2202 2081 0829 0025")
CARD_TBANK: str = os.getenv("PAY_TBANK", "2200 7013 7009 3863")
CARD_TON: str = os.getenv("PAY_CRYPTO_TON", "UQCua97IuHkQy5F5NPHBrDpay_FJRJoWZa1OOLnq-geGIbGT")
CARD_VISA_KG: str = os.getenv("PAY_VISA_KG", "4196720087839790")

# ---------- Тарифная сетка ---------------------------------------------------
TARIFF_PLANS: dict[str, dict] = {
    "15d":  {"days": 15,  "stars": 900,   "rub": 600,  "label": "15 дней — 600 руб. / 900 ⭐"},
    "30d":  {"days": 30,  "stars": 1500,  "rub": 1000, "label": "30 дней — 1000 руб. / 1500 ⭐ (−17%)"},
    "90d":  {"days": 90,  "stars": 3800,  "rub": 2550, "label": "90 дней — 2550 руб. / 3800 ⭐ (−25%)"},
    "180d": {"days": 180, "stars": 6800,  "rub": 4500, "label": "180 дней — 4500 руб. / 6800 ⭐ (−33%)"},
    "360d": {"days": 360, "stars": 10500, "rub": 7000, "label": "360 дней — 7000 руб. / 10500 ⭐ (−42%)"},
}

MIN_PAYOUT: float = 2000.0
PAYOUT_FIXED_FEE: float = 35.0    # фиксированная комиссия Такпродам
PAYOUT_BANK_PCT: float = 0.043    # комиссия банка 4.3%
MAX_ACTIVE_PAYOUTS: int = 2       # макс. активных заявок
DB_PATH: str = "/app/data/autopost.db"


# =============================================================================
# === MIDDLEWARE ==============================================================
# =============================================================================

class ErrorLoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        try:
            return await handler(event, data)
        except Exception as e:
            logger.exception(f"Ошибка при обработке события: {e}")
            raise


# =============================================================================
# === DATABASE ================================================================
# =============================================================================

def get_db():
    db = sqlite3.connect(DB_PATH)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    return db


# =============================================================================
# === INIT DB =================================================================
# =============================================================================

def init_db() -> None:
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Создание таблиц
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            role TEXT DEFAULT 'blogger',
            channel_id TEXT,
            channel_title TEXT,
            sub_id TEXT,
            source_link TEXT,
            target_mode TEXT,
            subscription_until TIMESTAMP,
            api_key TEXT,
            client_erid_override TEXT,
            filter_wb INTEGER DEFAULT 1,
            filter_ozon INTEGER DEFAULT 1,
            blogger_mode TEXT DEFAULT 'direct',
            auto_pin INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            order_id TEXT UNIQUE,
            sub_id TEXT,
            payout REAL,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount_requested REAL NOT NULL,
            amount_to_withdraw REAL NOT NULL,
            amount_blogger REAL NOT NULL,
            card TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id TEXT,
            channel_title TEXT,
            api_key TEXT,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           user_id INTEGER NOT NULL,
           donor_post_id TEXT NOT NULL,
           channel_id TEXT,
           target_channel_id TEXT,
           traffic_source TEXT DEFAULT 'yt',
           sku TEXT,
           erid TEXT,
           status TEXT DEFAULT 'pending',
           quarantine_reason TEXT,
           published_at TIMESTAMP,
           created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
           FOREIGN KEY(user_id) REFERENCES users(user_id)
       )
   """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pinned_posts (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           chat_id TEXT NOT NULL,
           message_id INTEGER NOT NULL,
           unpin_at TIMESTAMP NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS night_queue (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           user_id INTEGER NOT NULL,
           video_id TEXT NOT NULL,
           description TEXT,
           sku TEXT,
           photo_url TEXT,
           marketplace TEXT DEFAULT 'wb',
           created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Очистка дублей
    cursor.execute("""
        DELETE FROM channels 
        WHERE id NOT IN (
            SELECT MIN(id) FROM channels GROUP BY user_id, channel_id
        )
    """)
    
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_channel ON channels(user_id, channel_id)")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_night_queue_unique "
            "ON night_queue(user_id, video_id)"
        )
    except sqlite3.OperationalError:
        pass
    
    # Миграции
    migrations = [
        "target_mode TEXT",
        "subscription_until TIMESTAMP",
        "api_key TEXT",
        "client_erid_override TEXT",
        "filter_wb INTEGER DEFAULT 1",
        "filter_ozon INTEGER DEFAULT 1",
        "blogger_mode TEXT DEFAULT 'direct'",
        "auto_pin INTEGER DEFAULT 1",
        "is_active INTEGER DEFAULT 1"
    ]
    for col in migrations:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN payout_card TEXT")
        except sqlite3.OperationalError:
            pass

        

    conn.commit()
    conn.close()
    logger.info("База данных успешно инициализирована")

# =============================================================================
# === FSM STATES ==============================================================
# =============================================================================

class OnboardingStates(StatesGroup):
    waiting_role = State()
    waiting_channel = State()
    waiting_source_channel = State()        
    waiting_saas_tg_channel = State()


class AdminStates(StatesGroup):
    broadcast_text = State()
    extend_user_id = State()
    extend_days = State()


class SaasStates(StatesGroup):
    waiting_apikey = State()
    waiting_erid_override = State()


class PaymentFSM(StatesGroup):
    choosing_tariff = State()
    choosing_method = State()
    waiting_for_receipt = State()


class PayoutStates(StatesGroup):
    waiting_for_card = State()
    waiting_for_amount = State()

# =============================================================================
# === ROUTER ==================================================================
# =============================================================================

router = Router()


# =============================================================================
# === KEYBOARD HELPERS & UTILITIES ============================================
# =============================================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def kb_main_menu(role: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
        [InlineKeyboardButton(text="📖 Инструкции", callback_data="menu:instructions")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
    ]

    if role == "blogger":
        buttons.insert(0, [InlineKeyboardButton(text="📢 Мой канал", callback_data="menu:channel")])
        buttons.insert(1, [InlineKeyboardButton(text="⚙️ Режим публикации", callback_data="menu:pub_mode")])
        buttons.insert(2, [InlineKeyboardButton(text="🤝 Партнёрская программа", callback_data="menu:partner")])
    elif role == "saas":
        buttons.insert(0, [InlineKeyboardButton(text="📢 Мои каналы", callback_data="menu:my_channels")])
        buttons.insert(1, [InlineKeyboardButton(text="💎 Продлить подписку", callback_data="menu:tariffs")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_tariffs(traffic_source: str) -> InlineKeyboardMarkup:
    rows = []
    for plan_id, plan in TARIFF_PLANS.items():
        rows.append([
            InlineKeyboardButton(
                text=f"⭐ {plan['label']}", callback_data=f"buy:stars:{plan_id}"
            )
        ])
    if traffic_source == "organic":
        rows.append([
            InlineKeyboardButton(text="💳 Карта РФ (Сбер/Т-Банк)", callback_data="buy:card:ru"),
            InlineKeyboardButton(text="💳 Visa KG", callback_data="buy:card:kg"),
        ])
        rows.append([
            InlineKeyboardButton(text="💎 TON-крипта", callback_data="buy:card:ton"),
        ])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Рассылка всем", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="💰 Запустить биллинг-чек", callback_data="admin:billing_check")],
        [InlineKeyboardButton(text="🔧 Продлить подписку", callback_data="admin:extend_sub")],
        [InlineKeyboardButton(text="🌐 Открыть WebApp", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))],
    ])


def kb_payment_methods() -> InlineKeyboardMarkup:
    """ДВЕ РАЗДЕЛЬНЫЕ кнопки оплаты"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💳 Банковская карта (Sber / Т-Банк / Visa KG)", 
            callback_data="pay:card"
        )],
        [InlineKeyboardButton(
            text="⭐ Telegram Stars", 
            callback_data="pay:stars"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")]
    ])

def calc_payout(amount_blogger: float) -> dict:
    """
    amount_blogger — сумма которую получит блогер на руки.
    Считаем сколько нужно вывести из Такпродам чтобы покрыть комиссию.
    Формула: нужно вывести X, где X - (X * 0.043 + 35) = amount_blogger * 2
    То есть: X * (1 - 0.043) - 35 = amount_blogger * 2
             X = (amount_blogger * 2 + 35) / 0.957
    """
    amount_to_withdraw = (amount_blogger * 2 + PAYOUT_FIXED_FEE) / (1 - PAYOUT_BANK_PCT)
    amount_to_blogger = amount_blogger  # получает ровно столько сколько запросил
    return {
        "amount_requested": amount_blogger,
        "amount_to_withdraw": round(amount_to_withdraw, 2),
        "amount_blogger": round(amount_to_blogger, 2),
    }




# =============================================================================
# === MESSAGE HANDLERS ========================================================
# =============================================================================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    # 1. Очистка состояния
    await state.clear()
    
    try:
        logger.info(f"DEBUG: Пользователь {message.from_user.id} нажал /start")
        
        # 2. Проверка админа
        if is_admin(message.from_user.id):
            await message.answer("👋 Панель администратора.", reply_markup=kb_admin_panel())
            return

        # 3. База данных
        conn = get_db()
        try:
            user = conn.execute("SELECT role, channel_id FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
            
            if not user:
                # Регистрация
                sub_id = generate_sub_id(message.from_user.username, message.from_user.id)
                conn.execute("INSERT INTO users (user_id, username, sub_id, role) VALUES (?, ?, ?, 'blogger')", 
                             (message.from_user.id, message.from_user.username, sub_id))
                conn.commit()
                await message.answer("👋 Добро пожаловать! Кто вы?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👤 Я блогер", callback_data="role:blogger")],
                    [InlineKeyboardButton(text="🏢 Я SaaS-клиент", callback_data="role:saas")]
                ]))
                await state.set_state(OnboardingStates.waiting_role)
            elif not user["channel_id"]:
                await message.answer("⚠️ Вы ещё не привязали канал. Перешлите сообщение или отправьте @username.")
            else:
                await show_user_cabinet(message)
                
        finally:
            conn.close()

    except Exception as e:
        # ВОТ ЭТОТ БЛОК ПОКАЖЕТ ТЕБЕ ОШИБКУ ПРЯМО В ЧАТЕ
        await message.answer(f"❌ Произошла ошибка в коде:\n{str(e)}")
        logger.error(f"Ошибка в cmd_start: {e}")


@router.message(F.text.in_(["💻 Личный кабинет", "/cabinet"]))
async def show_cabinet(message: Message) -> None:
    """Главный вход в кабинет с разделением ролей."""
    user_id = message.from_user.id
    
    if is_admin(user_id):
        await message.answer(
            "🛠 <b>Админ-панель</b>\n\nВыберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_admin_panel()
        )
    else:
        await show_user_cabinet(message)


async def show_user_cabinet(message: Message) -> None:
    """Личный кабинет обычного пользователя (SaaS / Blogger)."""
    user_id = message.from_user.id
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT role, subscription_until, username "
            "FROM users WHERE user_id=?", 
            (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not user:
        await message.answer("Пожалуйста, начните с команды /start")
        return

    role = user["role"]
    sub_until = user["subscription_until"]

    if sub_until:
        try:
            if "T" in sub_until:
                end_dt = datetime.fromisoformat(sub_until.replace("Z", "+00:00"))
            else:
                end_dt = datetime.strptime(sub_until, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                
            now_dt = datetime.now(timezone.utc)
            if now_dt < end_dt:
                diff = end_dt - now_dt
                days = diff.days
                hours = diff.seconds // 3600
                status_text = f"✅ Активна • <b>{days} дн. {hours} ч.</b>"
            else:
                status_text = "❌ Подписка истекла"
        except Exception:
            status_text = "⚠️ Ошибка чтения даты"
    else:
        status_text = "♾️ Бессрочный доступ" if role == "blogger" else "❌ Подписка не активирована"

    text = (
        f"💼 <b>Личный кабинет</b>\n\n"
        f"👤 Роль: <b>{role.upper()}</b>\n"
        f"📅 Статус подписки: {status_text}\n"
        f"🆔 ID: <code>{user_id}</code>"
    )

    await message.answer(
        text, 
        parse_mode=ParseMode.HTML, 
        reply_markup=kb_main_menu(role)
    )


@router.message(F.text.startswith(("https://", "http://")))
async def handle_user_link(message: Message):
    """Пользователь прислал ссылку на видео — сразу парсим"""
    url = message.text.strip()
    info = extract_video_info(url)
    
    if not info:
        await message.answer("❌ Не удалось обработать ссылку.")
        return

    await message.answer(
        f"✅ Видео обработано!\n"
        f"Название: {info.get('title')}\n"
        f"Найдено ссылок на товары: {len(find_product_links(info.get('description', '')))}"
    )

# =============================================================================
# === CALLBACK HANDLERS =======================================================
# =============================================================================

@router.callback_query(OnboardingStates.waiting_role, F.data.startswith("role:"))
async def cb_set_role(callback: CallbackQuery, state: FSMContext) -> None:
    role = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    conn = get_db()
    try:
        conn.execute("UPDATE users SET role=? WHERE user_id=?", (role, user_id))
        conn.commit()
    finally:
        conn.close()

    if role == "blogger":
        await state.set_state(OnboardingStates.waiting_source_channel)
        await callback.message.edit_text(
            "✅ Выбрана роль: <b>БЛОГЕР</b>.\n\n"
            "Пришлите ссылку на ваш основной канал (YouTube, TikTok или Instagram).",
            parse_mode=ParseMode.HTML
        )
    else:
        await state.set_state(OnboardingStates.waiting_saas_tg_channel)
        await callback.message.edit_text(
            "✅ Выбрана роль: <b>SaaS-клиент</b>.\n\n"
            "Пришлите @username вашего Telegram-канала.",
            parse_mode=ParseMode.HTML
        )
    
    await callback.answer()


@router.callback_query(F.data == "menu:stats")
async def cb_menu_stats(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id

    conn = get_db()
    try:
        user = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
    finally:
        conn.close()

    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    if user["role"] == "blogger":
        stats = get_blogger_stats(user_id)
        text = (
            f"📊 <b>Ваша статистика</b>\n\n"
            f"📍 Всего постов: <b>{stats['total_posts']}</b>\n"
            f"✅ Опубликовано: <b>{stats['published_posts']}</b>\n"
            f"🕒 За последние 30 дней: <b>{stats['published_last_30d']}</b>\n\n"
            f"💰 <b>Заработок</b>\n"
            f"├ Всего: <b>{stats['total_earned']} ₽</b>\n"
            f"└ За 30 дней: <b>{stats['earned_last_30d']} ₽</b>\n\n"
            f"🛍 Продаж: <b>{stats['total_sales']}</b>\n\n"
            f"<i>Данные обновляются автоматически.</i>"
        )
        kb = []
        if stats["total_earned"] >= MIN_PAYOUT:
            kb.append([InlineKeyboardButton(text="💳 Запросить выплату", callback_data="payout:request")])
        kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")])
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML,
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    else:
        await _show_saas_stats(callback, user_id, channel_idx=0, period="30d")

    await callback.answer()


async def _show_saas_stats(callback: CallbackQuery, user_id: int, channel_idx: int, period: str) -> None:
    channels = get_saas_channels(user_id)

    if not channels:
        await callback.message.edit_text(
            "📊 <b>Статистика</b>\n\nУ вас ещё нет подключённых каналов.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")]
            ])
        )
        return

    channel_idx = max(0, min(channel_idx, len(channels) - 1))
    ch = channels[channel_idx]
    s = get_saas_channel_stats(user_id, ch["channel_id"], period)
    total_ch = len(channels)
    title = ch["channel_title"] or ch["channel_id"]

    text = (
        f"📊 <b>Статистика канала</b>\n"
        f"📢 <b>{title}</b>  <i>({channel_idx + 1}/{total_ch})</i>\n"
        f"🗓 Период: <b>{s['period_label']}</b>\n\n"
        f"📬 Постов отправлено:  <b>{s['total']}</b>\n"
        f"✅ Опубликовано:       <b>{s['published']}</b>\n"
        f"⚠️ В карантине:        <b>{s['quarantine']}</b>\n"
        f"❌ Ошибок:             <b>{s['errors']}</b>\n\n"
        f"🕐 Последний пост: <b>{s['last_published_at']}</b>\n\n"
        f"<i>Данные обновляются в реальном времени.</i>"
    )

    nav_row = []
    if channel_idx > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Канал", callback_data=f"saas_stats:{channel_idx - 1}:{period}"))
    if channel_idx < total_ch - 1:
        nav_row.append(InlineKeyboardButton(text="Канал ▶️", callback_data=f"saas_stats:{channel_idx + 1}:{period}"))

    period_row = []
    for p_key, p_cfg in STAT_PERIODS.items():
        label = f"· {p_cfg['label']} ·" if p_key == period else p_cfg["label"]
        period_row.append(InlineKeyboardButton(text=label, callback_data=f"saas_stats:{channel_idx}:{p_key}"))

    kb = []
    if nav_row:
        kb.append(nav_row)
    kb.append(period_row)
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")])

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML,
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("saas_stats:"))
async def cb_saas_stats_nav(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    try:
        channel_idx = int(parts[1])
        period = parts[2]
    except (IndexError, ValueError):
        await callback.answer("❌ Ошибка навигации", show_alert=True)
        return

    if period not in STAT_PERIODS:
        period = "30d"

    await _show_saas_stats(callback, callback.from_user.id, channel_idx, period)
    await callback.answer()


@router.callback_query(F.data == "menu:tariffs")
async def cb_menu_tariffs(callback: CallbackQuery) -> None:
    """Выбор способа оплаты для SaaS"""
    await callback.message.edit_text(
        "💎 <b>Продление подписки</b>\n\n"
        "Выберите удобный способ оплаты:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_payment_methods()
    )
    await callback.answer()


@router.callback_query(F.data == "pay:stars")
async def cb_pay_stars(callback: CallbackQuery) -> None:
    """Telegram Stars"""
    await callback.message.edit_text(
        "⭐ <b>Оплата через Telegram Stars</b>\n\n"
        "Здесь будет список тарифов для оплаты Stars.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tariffs")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "pay:card")
async def cb_pay_card(callback: CallbackQuery) -> None:
    """Оплата картой"""
    text = (
        "💳 <b>Оплата банковской картой</b>\n\n"
        f"Сбер: <code>{CARD_SBER}</code>\n"
        f"Т-Банк: <code>{CARD_TBANK}</code>\n"
        f"Visa KG: <code>{CARD_VISA_KG}</code>\n\n"
        f"TON: <code>{CARD_TON}</code>\n\n"
        "После оплаты пришлите чек администратору.\n"
        f"<i>Укажите в комментарии ваш ID: <code>{callback.from_user.id}</code></i>"
    )
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tariffs")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "menu:back")
async def cb_back_to_main_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    
    user_id = callback.from_user.id
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    
    role = user["role"] if user else "blogger"
    
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(role)
    )


@router.callback_query(F.data == "menu:main")
async def cb_menu_main(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT role FROM users WHERE user_id=?", (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()
    role = row["role"] if row else "blogger"
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(role),
    )
    await callback.answer()
# =============================================================================
# === CIRCUIT BREAKER =========================================================
# =============================================================================

class CircuitBreaker:
    MAX_FAILURES: int = 5
    PAUSE_SECONDS: int = 15 * 60

    def __init__(self) -> None:
        self._failures: int = 0
        self._open_until: Optional[float] = None

    def is_open(self) -> bool:
        if self._open_until is None:
            return False
        if time.monotonic() >= self._open_until:
            self._failures = 0
            self._open_until = None
            logger.info("Circuit Breaker: схема замкнута, запросы возобновлены")
            return False
        return True

    def record_failure(self) -> None:
        self._failures += 1
        logger.warning(f"Circuit Breaker: ошибка #{self._failures}/{self.MAX_FAILURES}")
        if self._failures >= self.MAX_FAILURES:
            self._open_until = time.monotonic() + self.PAUSE_SECONDS
            logger.error(f"Circuit Breaker: РАЗОМКНУТ на {self.PAUSE_SECONDS // 60} мин")

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = None
# =============================================================================
# === API INTEGRATION (ТакПродам) =============================================
# =============================================================================

async def get_takprodam_data(sku: str, api_key: str) -> Optional[dict]:
    """Запрашивает API ТакПродам. Возвращает dict{link, erid, advertiser} или None."""
    if circuit_breaker.is_open():
        return None
    url = "https://api.takprodam.ru/v1/products/info"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params={"sku": sku})
        if resp.status_code == 500:
            circuit_breaker.record_failure()
            return None
        if resp.status_code != 200:
            logger.warning(f"API: статус {resp.status_code} для SKU={sku}")
            return None
        data = resp.json()
        circuit_breaker.record_success()
        return {
            "link":       data.get("link", ""),
            "erid":       data.get("erid", "").strip(),
            "advertiser": data.get("advertiser", "").strip(),
        }
    except httpx.TimeoutException:
        circuit_breaker.record_failure()
        return None
    except Exception as e:
        logger.exception(f"API: ошибка SKU={sku}: {e}")
        return None


# =============================================================================
# === ERID LOGIC & QUARANTINE =================================================
# =============================================================================

async def resolve_erid(
    bot: Bot,
    user_id: int,
    sku: str,
    donor_post_id: str,
    channel_id: str,
) -> Optional[dict]:
    """
    Иерархия: API ТакПродам → client_erid_override → карантин.
    Фейковые ERID ЗАПРЕЩЕНЫ. Только реальные данные или блокировка.
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT api_key, client_erid_override FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        await _send_to_quarantine(bot, user_id, donor_post_id, channel_id,
                                  reason="Пользователь не найден в БД")
        return None

    api_key: str = row["api_key"] or ""
    override_erid: str = (row["client_erid_override"] or "").strip()

    api_data: Optional[dict] = None
    if api_key:
        api_data = await get_takprodam_data(sku, api_key)

    if api_data and api_data.get("erid"):
        return api_data

    if override_erid:
        link = api_data["link"] if api_data else ""
        advertiser = api_data["advertiser"] if api_data else "Не определён"
        return {"link": link, "erid": override_erid, "advertiser": advertiser}

    reason = "API не вернул ERID, client_erid_override не задан"
    if not api_key:
        reason = "api_key не настроен, client_erid_override не задан"
    elif circuit_breaker.is_open():
        reason = "Circuit Breaker активен, client_erid_override не задан"

    await _send_to_quarantine(bot, user_id, donor_post_id, channel_id, reason=reason)
    return None


async def _send_to_quarantine(
    bot: Bot,
    user_id: int,
    donor_post_id: str,
    channel_id: str,
    reason: str,
) -> None:
    """Блокирует публикацию и уведомляет карантинный чат администратора."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO posts (user_id, donor_post_id, channel_id, status, quarantine_reason) "
            "VALUES (?, ?, ?, 'quarantine', ?)",
            (user_id, donor_post_id, channel_id, reason)
        )
        conn.commit()
    finally:
        conn.close()

    msg = (
        f"🚨 <b>КАРАНТИН — пост заблокирован</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"📢 Канал: <code>{channel_id}</code>\n"
        f"🆔 Пост донора: <code>{donor_post_id}</code>\n"
        f"❌ Причина: {html.escape(reason)}\n\n"
        f"<i>Для публикации вручную добавьте ERID и одобрите пост.</i>"
    )
    try:
        await bot.send_message(QUARANTINE_CHAT_ID, msg, parse_mode=ParseMode.HTML)
    except TelegramAPIError as e:
        logger.error(f"Не удалось отправить в карантин: {e}")
        logger.info(f"DEBUG: Попытка отправить пост в канал {channel_id}...")


# =============================================================================
# === AI REWRITE (DeepInfra) ==================================================
# =============================================================================

async def rewrite_text_with_ai(text: str) -> str:
    """Уникализирует текст поста через DeepInfra. Если ключа нет — оригинал."""
    if not DEEPINFRA_API_KEY:
        return text
    url = "https://api.deepinfra.com/v1/openai/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPINFRA_API_KEY}"}
    payload = {
        "model": "meta-llama/Meta-Llama-3-8B-Instruct",
        "messages": [{"role": "user", "content": (
            f"Перепиши текст для рекламного поста в Telegram, сохранив суть: {text}"
        )}],
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Ошибка AI-рерайта: {e}")
    return text


# =============================================================================
# === HTML SANITIZER ==========================================================
# =============================================================================

_ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre", "a"}
_OPEN_TAG_RE = re.compile(r"<([a-zA-Z]+)(?:\s[^>]*)?>")
_CLOSE_TAG_RE = re.compile(r"</([a-zA-Z]+)>")


def sanitize_html(text: str) -> str:
    """Удаляет запрещённые теги, закрывает висячие, обрезает до 4096 символов."""
    if not text:
        return ""
    text = re.sub(r"</?([a-zA-Z]+)(?:\s[^>]*)?>", lambda m: (
        m.group(0) if m.group(1).lower() in _ALLOWED_TAGS else ""
    ), text)
    open_tags: deque[str] = deque()
    for m in _OPEN_TAG_RE.finditer(text):
        tag = m.group(1).lower()
        if tag in _ALLOWED_TAGS and tag not in {"br", "hr"}:
            open_tags.append(tag)
    for m in _CLOSE_TAG_RE.finditer(text):
        tag = m.group(1).lower()
        if open_tags and open_tags[-1] == tag:
            open_tags.pop()
    text += "".join(f"</{t}>" for t in reversed(open_tags))
    return text[:4096]


def build_post_caption(
    product_title: str,
    price: str,
    affiliate_url: str,
    erid: str,
    advertiser: str,
) -> str:
    raw = (
        f"<b>{product_title}</b>\n\n"
        f"💰 Цена: {price}\n\n"
        f'<a href="{affiliate_url}">👉 Перейти к товару</a>\n\n'
        f"<i>Реклама. {advertiser}. Erid: {erid}</i>"
    )
    return sanitize_html(raw)
# =============================================================================
# === IMAGE VALIDATOR & FALLBACK ==============================================
# =============================================================================

_VALID_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_WRONG_CONTENT_RE = re.compile(r"wrong type of web page content", re.IGNORECASE)


def is_valid_image_url(url: str) -> bool:
    if not url:
        return False
    return any(url.split("?")[0].lower().endswith(ext) for ext in _VALID_IMAGE_EXTENSIONS)


async def publish_post_with_fallback(
    bot: Bot,
    channel_id: str,
    caption: str,
    photo_url: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    if photo_url and is_valid_image_url(photo_url):
        try:
            await bot.send_photo(
                chat_id=channel_id,
                photo=photo_url,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            return True
        except TelegramAPIError as e:
            err = str(e).lower()
            if not (_WRONG_CONTENT_RE.search(err) or "wrong file identifier" in err):
                logger.error(f"Ошибка публикации с фото: {e}")
                return False
            logger.warning(f"Фото отклонено Telegram, fallback → текст: {e}")
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return True
    except TelegramAPIError as e:
        logger.error(f"Ошибка публикации текста: {e}")
        return False


# =============================================================================
# === NIGHT QUEUE =============================================================
# =============================================================================

def is_night_time() -> bool:
    """True с 23:00 до 08:00 по МСК (UTC+3)."""
    now = datetime.now(tz=timezone(timedelta(hours=3)))
    return now.hour >= 23 or now.hour < 8


async def add_to_night_queue(
    user_id: int,
    video_id: str,
    description: str,
    sku: Optional[str],
    photo_url: Optional[str],
    marketplace: str = "wb",
) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO night_queue "
            "(user_id, video_id, description, sku, photo_url, marketplace) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, video_id, description, sku, photo_url, marketplace)
        )
        conn.commit()
        logger.info(f"🌙 Отложено в ночную очередь: user={user_id} video={video_id}")
    finally:
        conn.close()

async def flush_night_queue(bot: Bot) -> None:
    """Утром в 08:00 МСК публикует посты из ночной очереди."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM night_queue ORDER BY created_at ASC"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        logger.info("Ночная очередь пуста")
        return

    logger.info(f"🌅 Ночная очередь: публикуем {len(rows)} постов")

    for row in rows:
        try:
            await process_new_video(
                bot=bot,
                user_id=row["user_id"],
                video_id=row["video_id"],
                description=row["description"] or "",
                sku=row["sku"],
                photo_url=row["photo_url"],
                marketplace=row["marketplace"] or "wb",
            )
            # Удаляем из очереди только после успешной публикации
            conn = get_db()
            try:
                conn.execute("DELETE FROM night_queue WHERE id=?", (row["id"],))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"flush_night_queue ошибка для video={row['video_id']}: {e}")

        await asyncio.sleep(10)  # небольшая пауза между постами


# =============================================================================
# === TRANSLITERATION =========================================================
# =============================================================================

_TRANSLIT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def generate_sub_id(username: str, user_id: int) -> str:
    username = (username or "").lstrip("@").lower()
    result = ""
    for ch in username:
        result += _TRANSLIT_MAP.get(ch, ch if ch.isalnum() or ch == "_" else "")
    result = re.sub(r"[^a-z0-9_]", "", result)
    result = re.sub(r"_+", "_", result).strip("_") or f"user{user_id}"
    return f"{result}_uid{user_id}"


# =============================================================================
# === BOT ADMIN CHECK =========================================================
# =============================================================================

async def check_bot_admin(bot: Bot, channel_id: str) -> bool:
    try:
        bot_id = bot.id
        member = await bot.get_chat_member(chat_id=channel_id, user_id=bot_id)
        
        if member.status == "creator":
            return True
        if member.status == "administrator":
            return getattr(member, "can_post_messages", False)
        return False
    except TelegramAPIError as e:
        logger.error(f"Ошибка проверки админки в {channel_id}: {e}")
        return False


# =============================================================================
# === KEYBOARD HELPERS ========================================================
# =============================================================================

def kb_main_menu(role: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
        [InlineKeyboardButton(text="📖 Инструкции", callback_data="menu:instructions")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
    ]

    if role == "blogger":
        buttons.insert(0, [InlineKeyboardButton(text="📢 Мой канал", callback_data="menu:channel")])
        buttons.insert(1, [InlineKeyboardButton(text="⚙️ Режим публикации", callback_data="menu:pub_mode")])
        buttons.insert(2, [InlineKeyboardButton(text="🤝 Партнёрская программа", callback_data="menu:partner")])
    elif role == "saas":
        buttons.insert(0, [InlineKeyboardButton(text="📢 Мои каналы", callback_data="menu:my_channels")])
        buttons.insert(1, [InlineKeyboardButton(text="💎 Продлить подписку", callback_data="menu:tariffs")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_tariffs(traffic_source: str) -> InlineKeyboardMarkup:
    rows = []
    for plan_id, plan in TARIFF_PLANS.items():
        rows.append([
            InlineKeyboardButton(
                text=f"⭐ {plan['label']}", callback_data=f"buy:stars:{plan_id}"
            )
        ])
    if traffic_source == "organic":
        rows.append([
            InlineKeyboardButton(text="💳 Карта РФ (Сбер/Т-Банк)", callback_data="buy:card:ru"),
            InlineKeyboardButton(text="💳 Visa KG", callback_data="buy:card:kg"),
        ])
        rows.append([
            InlineKeyboardButton(text="💎 TON-крипта", callback_data="buy:card:ton"),
        ])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_filter_settings(wb: int, ozon: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅' if wb else '❌'} Wildberries", callback_data="filter:toggle:wb"
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if ozon else '❌'} Ozon", callback_data="filter:toggle:ozon"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")],
    ])


def kb_blogger_mode(mode: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅' if mode == 'direct' else '☐'} Напрямую в мой канал",
            callback_data="blogger_mode:direct",
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if mode == 'vip_pin' else '☐'} VIP-закреп в главном канале (24ч)",
            callback_data="blogger_mode:vip_pin",
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")],
    ])


def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Рассылка всем", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="💰 Запустить биллинг-чек", callback_data="admin:billing_check")],
        [InlineKeyboardButton(text="🔧 Продлить подписку", callback_data="admin:extend_sub")],
        [InlineKeyboardButton(text="🌐 Открыть WebApp", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))],
    ])


# =============================================================================
# === STATISTICS ==============================================================
# =============================================================================

def get_blogger_stats(user_id: int) -> dict:
    """Статистика для блогера (Фаза 4)"""
    conn = get_db()
    try:
        post_stats = conn.execute("""
            SELECT 
                COUNT(*) as total_posts,
                SUM(CASE WHEN status = 'published' THEN 1 ELSE 0 END) as published_posts,
                SUM(CASE WHEN published_at >= datetime('now', '-30 days') THEN 1 ELSE 0 END) as posts_last_30d,
                SUM(CASE WHEN status = 'published' AND published_at >= datetime('now', '-30 days') THEN 1 ELSE 0 END) as published_last_30d
            FROM posts 
            WHERE user_id = ?
        """, (user_id,)).fetchone()

        sales_stats = conn.execute("""
            SELECT 
                COUNT(*) as total_sales,
                COALESCE(SUM(payout), 0.0) as total_earned,
                COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-30 days') THEN payout ELSE 0 END), 0.0) as earned_last_30d
            FROM transactions 
            WHERE sub_id = (SELECT sub_id FROM users WHERE user_id = ?) 
              AND status IN ('approved', 'paid')
        """, (user_id,)).fetchone()

        return {
            "total_posts": int(post_stats["total_posts"] or 0),
            "published_posts": int(post_stats["published_posts"] or 0),
            "posts_last_30d": int(post_stats["posts_last_30d"] or 0),
            "published_last_30d": int(post_stats["published_last_30d"] or 0),
            "total_sales": int(sales_stats["total_sales"] or 0),
            "total_earned": round(float(sales_stats["total_earned"] or 0), 2),
            "earned_last_30d": round(float(sales_stats["earned_last_30d"] or 0), 2),
        }
    except Exception as e:
        logger.error(f"Ошибка get_blogger_stats для {user_id}: {e}")
        return {
            "total_posts": 0, "published_posts": 0, "posts_last_30d": 0,
            "published_last_30d": 0, "total_sales": 0, "total_earned": 0.0, "earned_last_30d": 0.0
        }
    finally:
        conn.close()
# =============================================================================
# === FSM STATES ==============================================================
# =============================================================================

class OnboardingStates(StatesGroup):
    waiting_role = State()
    waiting_channel = State()
    waiting_source_channel = State()        
    waiting_saas_tg_channel = State()


class AdminStates(StatesGroup):
    broadcast_text = State()
    extend_user_id = State()
    extend_days = State()


class SaasStates(StatesGroup):
    waiting_apikey = State()
    waiting_erid_override = State()


class PaymentFSM(StatesGroup):
    choosing_tariff = State()
    choosing_method = State()
    waiting_for_receipt = State()



# =============================================================================
# === ROUTER & HANDLERS =======================================================
# =============================================================================





@router.message(Command("force_trial"))
async def force_trial(message: Message):
    new_date = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    conn = get_db()
    conn.execute("UPDATE users SET subscription_until = ? WHERE user_id = ?", (new_date, message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer("✅ Тестовый период принудительно установлен на 3 дня.")


@router.message(Command("debug_sub"))
async def debug_subscription(message: Message):
    conn = get_db()
    user = conn.execute("SELECT role, subscription_until FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()
    
    if user:
        await message.answer(f"DEBUG:\nРоль: {user['role']}\nДата подписки: {user['subscription_until']}")
    else:
        await message.answer("Пользователь не найден в БД!")


@router.message(Command("fix_channels"))
async def fix_duplicate_channels(message: Message) -> None:
    conn = get_db()
    conn.execute("""
        DELETE FROM channels 
        WHERE id NOT IN (
            SELECT MIN(id) FROM channels GROUP BY user_id, channel_id
        )
    """)
    conn.commit()
    conn.close()
    await message.answer("✅ Дубликаты каналов удалены.")


# =============================================================================
# === ОБРАБОТЧИК ВЫБОРА РОЛИ ==================================================
# =============================================================================

@router.callback_query(OnboardingStates.waiting_role, F.data.startswith("role:"))
async def cb_set_role(callback: CallbackQuery, state: FSMContext) -> None:
    role = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    conn = get_db()
    try:
        conn.execute("UPDATE users SET role=? WHERE user_id=?", (role, user_id))
        conn.commit()
    finally:
        conn.close()

    if role == "blogger":
        await state.set_state(OnboardingStates.waiting_source_channel)
        await callback.message.edit_text(
            "✅ Выбрана роль: <b>БЛОГЕР</b>.\n\n"
            "Пришлите ссылку на ваш основной канал (YouTube, TikTok или Instagram).",
            parse_mode=ParseMode.HTML
        )
    else:
        await state.set_state(OnboardingStates.waiting_saas_tg_channel)
        await callback.message.edit_text(
            "✅ Выбрана роль: <b>SaaS-клиент</b>.\n\n"
            "Пришлите @username вашего Telegram-канала.",
            parse_mode=ParseMode.HTML
        )
    
    await callback.answer()


# =============================================================================
# === ОБРАБОТЧИК ДЛЯ БЛОГЕРА: ПРИВЯЗКА ИСТОЧНИКА ========================
# =============================================================================

@router.message(OnboardingStates.waiting_source_channel)
async def handle_blogger_source(message: Message, state: FSMContext) -> None:
    source_link = message.text
    user_id = message.from_user.id
    
    conn = get_db()
    try:
        conn.execute("UPDATE users SET source_link=? WHERE user_id=?", (source_link, user_id))
        conn.commit()
    finally:
        conn.close()
        
    await message.answer(
        "✅ Источник успешно привязан!\n\n"
        "Теперь выберите, куда публиковать:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="В мой канал", callback_data="target:own")],
            [InlineKeyboardButton(text="В VIP-канал", callback_data="target:ours")]
        ])
    )
    await state.set_state(OnboardingStates.waiting_target_choice)  # Нужно добавить состояние если отсутствует


@router.callback_query(F.data.startswith("target:"))
async def cb_select_target(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    target_type = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    conn = get_db()
    try:
        conn.execute("UPDATE users SET target_mode=? WHERE user_id=?", (target_type, user_id))
        conn.commit()
    finally:
        conn.close()
    
    if target_type == "own":
        await state.set_state(OnboardingStates.waiting_channel)
        await callback.message.edit_text("📝 Пришлите @username вашего канала:")
    else:
        await state.clear()
        await callback.message.edit_text("✅ Регистрация завершена!")
        await callback.message.answer("🏠 Главное меню", reply_markup=kb_main_menu("blogger"))
# =============================================================================
# === ОБРАБОТЧИК ДОБАВЛЕНИЯ КАНАЛА ДЛЯ SAAS ===================================
# =============================================================================

@router.callback_query(F.data == "menu:my_channels")
async def cb_list_channels(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    channels = conn.execute("SELECT * FROM channels WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    
    if not channels:
        await callback.message.edit_text(
            "У вас пока нет добавленных каналов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")]
            ])
        )
        return
        
    kb = []
    for ch in channels:
        kb.append([InlineKeyboardButton(text=f"📢 {ch['channel_title']}", callback_data=f"manage_ch:{ch['id']}")])
    
    kb.append([InlineKeyboardButton(text="➕ Добавить еще канал", callback_data="add_channel")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")])
    
    await callback.message.edit_text("Выберите канал для управления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "add_channel")
async def cb_add_channel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Пришлите @username канала или перешлите сообщение из него:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:my_channels")]
        ])
    )
    await state.set_state(OnboardingStates.waiting_saas_tg_channel)


@router.message(OnboardingStates.waiting_saas_tg_channel)
async def handle_saas_channel_addition(message: Message, state: FSMContext) -> None:
    channel_username = message.text.strip()
    user_id = message.from_user.id
    
    is_admin_ok = await check_bot_admin(message.bot, channel_username)
    if not is_admin_ok:
        await message.answer("❌ Бот не является администратором в этом канале. Добавьте его и попробуйте снова.")
        return
        
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO channels (user_id, channel_id, channel_title) 
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, channel_id) 
            DO UPDATE SET channel_title = excluded.channel_title
            """,
            (user_id, channel_username, channel_username)
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка базы данных при добавлении канала: {e}")
    finally:
        conn.close()
        
    await message.answer(
        f"✅ Канал <b>{html.escape(channel_username)}</b> успешно добавлен!",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu("saas")
    )
    await state.clear()


async def show_user_cabinet(message: Message) -> None:
    """Личный кабинет обычного пользователя (SaaS / Blogger)."""
    user_id = message.from_user.id
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT role, subscription_until, username "
            "FROM users WHERE user_id=?", 
            (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not user:
        await message.answer("Пожалуйста, начните с команды /start")
        return

    role = user["role"]
    sub_until = user["subscription_until"]

    if sub_until:
        try:
            if "T" in sub_until:
                end_dt = datetime.fromisoformat(sub_until.replace("Z", "+00:00"))
            else:
                end_dt = datetime.strptime(sub_until, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                
            now_dt = datetime.now(timezone.utc)
            if now_dt < end_dt:
                diff = end_dt - now_dt
                days = diff.days
                hours = diff.seconds // 3600
                status_text = f"✅ Активна • <b>{days} дн. {hours} ч.</b>"
            else:
                status_text = "❌ Подписка истекла"
        except Exception:
            status_text = "⚠️ Ошибка чтения даты"
    else:
        status_text = "♾️ Бессрочный доступ" if role == "blogger" else "❌ Подписка не активирована"

    text = (
        f"💼 <b>Личный кабинет</b>\n\n"
        f"👤 Роль: <b>{role.upper()}</b>\n"
        f"📅 Статус подписки: {status_text}\n"
        f"🆔 ID: <code>{user_id}</code>"
    )

    await message.answer(
        text, 
        parse_mode=ParseMode.HTML, 
        reply_markup=kb_main_menu(role)
    )


@router.message(F.text.in_(["💻 Личный кабинет", "/cabinet"]))
async def show_cabinet(message: Message) -> None:
    """Главный вход в кабинет с разделением ролей."""
    user_id = message.from_user.id
    
    if is_admin(user_id):
        await message.answer(
            "🛠 <b>Админ-панель</b>\n\nВыберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_admin_panel()
        )
    else:
        await show_user_cabinet(message)


# =============================================================================
# === ОБРАБОТЧИК КНОПКИ "НАЗАД" ==============================================
# =============================================================================

@router.callback_query(F.data == "menu:back")
async def cb_back_to_main_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    
    user_id = callback.from_user.id
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    
    role = user["role"] if user else "blogger"
    
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(role)
    )


# =============================================================================
# === ОБРАБОТЧИК ПРИВЯЗКИ КАНАЛА ==============================================
# =============================================================================

@router.message(OnboardingStates.waiting_channel)
async def handle_channel_input(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    channel_id: Optional[str] = None
    channel_title: Optional[str] = None

    if message.forward_origin and message.forward_origin.chat:
        chat = message.forward_origin.chat
        channel_id = str(chat.id)
        channel_title = chat.title
    elif message.text and message.text.startswith("@"):
        channel_id = message.text.strip()
        channel_title = channel_id

    if not channel_id:
        await message.answer("⚠️ Не удалось распознать канал. Пожалуйста, пришлите пересланное сообщение или @username.")
        return

    is_admin_ok = await check_bot_admin(message.bot, channel_id)
    if not is_admin_ok:
        await message.answer(
            "❌ Бот не имеет прав администратора в этом канале.\n"
            "Добавьте бота в администраторы (с правом публикации) и попробуйте снова."
        )
        return

    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET channel_id=?, channel_title=? WHERE user_id=?", 
            (channel_id, channel_title, user_id)
        )
        conn.commit()
        
        row = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
        role = row["role"] if row else "blogger"
        
        logger.info(f"Канал {channel_id} успешно привязан к пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка сохранения канала в БД: {e}")
        await message.answer("Ошибка при сохранении данных в базу.")
        return
    finally:
        conn.close()

    await state.clear()
    
    await message.answer(
        f"✅ <b>Канал успешно привязан:</b> {html.escape(channel_title or channel_id)}\n\n"
        "Теперь вы можете полноценно пользоваться ботом.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(role)
    )
# -----------------------------------------------------------------------------
# Главное меню
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:main")
async def cb_menu_main(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT role FROM users WHERE user_id=?", (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()
    role = row["role"] if row else "blogger"
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(role),
    )
    await callback.answer()


# -----------------------------------------------------------------------------
# Канал
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:channel")
async def cb_menu_channel(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT channel_title, channel_id FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if row and row["channel_id"]:
        await callback.message.edit_text(
            f"📢 <b>Управление каналом</b>\n\n"
            f"Привязанный канал: <b>{html.escape(row['channel_title'] or 'Без названия')}</b>\n"
            f"ID: <code>{row['channel_id']}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Изменить канал", callback_data="channel:change")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")],
            ]),
        )
    else:
        await callback.message.edit_text(
            "📢 <b>Привязка канала</b>\n\n"
            "Перешли сюда любое сообщение из твоего канала или отправь <code>@username</code>.\n\n"
            "<i>Убедись, что бот добавлен в канал как администратор с правом публикации.</i>",
            parse_mode=ParseMode.HTML,
        )
        await state.set_state(OnboardingStates.waiting_channel)
    await callback.answer()


@router.callback_query(F.data == "channel:change")
async def cb_change_channel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "📢 Введи <code>@username</code> нового канала или перешли сообщение из него:",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(OnboardingStates.waiting_channel)
    await callback.answer()


# -----------------------------------------------------------------------------
# Партнёрская программа
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:partner")
async def cb_partner_program(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT sub_id FROM users WHERE user_id=?", (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()
    sub_id = row["sub_id"] if row else "—"
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=aff_{sub_id}"
    await callback.message.edit_text(
        "🤝 <b>Партнёрская программа</b>\n\n"
        "Приводи других блогеров и получай повышенный % с их продаж!\n\n"
        f"🔗 Твоя реферальная ссылка:\n<code>{ref_link}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")]
        ]),
    )
    await callback.answer()

@router.callback_query(F.data == "menu:pub_mode")
async def cb_menu_pub_mode(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT blogger_mode FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
    finally:
        conn.close()

    mode = user["blogger_mode"] if user else "direct"
    try:
        await callback.message.edit_text(
            "⚙️ <b>Режим публикации</b>\n\nВыберите как публиковать посты:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_blogger_mode(mode)
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("blogger_mode:"))
async def cb_set_blogger_mode(callback: CallbackQuery) -> None:
    mode = callback.data.split(":")[1]
    if mode not in ("direct", "vip_pin"):
        await callback.answer("❌ Неизвестный режим", show_alert=True)
        return

    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET blogger_mode=? WHERE user_id=?",
            (mode, callback.from_user.id)
        )
        conn.commit()
    finally:
        conn.close()

    labels = {"direct": "Напрямую в канал", "vip_pin": "VIP-закреп (24ч)"}
    await callback.answer(f"✅ Режим изменён: {labels[mode]}", show_alert=False)
    await callback.message.edit_text(
        "⚙️ <b>Режим публикации</b>\n\n"
        "Выберите как публиковать посты:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_blogger_mode(mode)
    )


@router.callback_query(F.data == "menu:settings")
async def cb_menu_settings(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT filter_wb, filter_ozon FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
    finally:
        conn.close()

    wb = user["filter_wb"] if user else 1
    ozon = user["filter_ozon"] if user else 1
    try:
        await callback.message.edit_text(
            "⚙️ <b>Настройки</b>\n\nВыберите какие магазины включить в автопостинг:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_filter_settings(wb, ozon)
        )
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("filter:toggle:"))
async def cb_filter_toggle(callback: CallbackQuery) -> None:
    shop = callback.data.split(":")[2]  # wb или ozon
    user_id = callback.from_user.id

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT filter_wb, filter_ozon FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        wb = user["filter_wb"]
        ozon = user["filter_ozon"]

        if shop == "wb":
            wb = 0 if wb else 1
        elif shop == "ozon":
            ozon = 0 if ozon else 1

        conn.execute(
            "UPDATE users SET filter_wb=?, filter_ozon=? WHERE user_id=?",
            (wb, ozon, user_id)
        )
        conn.commit()
    finally:
        conn.close()

    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=kb_filter_settings(wb, ozon)
    )


# -----------------------------------------------------------------------------
# Инструкции
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:instructions")
async def cb_menu_instructions(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📖 <b>Центр инструкций</b>\n\nВыбери нужный раздел:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Для блогеров", callback_data="instr:blogger")],
            [InlineKeyboardButton(text="🔑 Для SaaS", callback_data="instr:saas")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "instr:blogger")
async def cb_instr_blogger(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📖 <b>Инструкция для блогеров</b>\n\n"
        "1. Привяжи Telegram-канал через «📢 Мой канал»\n"
        "2. Бот автоматически публикует посты с маркировкой ERID\n"
        "3. По каждому выкупу начисляется вознаграждение в «📊 Статистика»\n"
        "4. Минимальная сумма для вывода: 2000 руб.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:instructions")]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "instr:saas")
async def cb_instr_saas(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📖 <b>Инструкция для SaaS-клиентов</b>\n\n"
        "1. Введи API-ключ от ТакПродам в настройках\n"
        "2. Привяжи канал и настрой фильтры маркетплейсов\n"
        "3. Активируй подписку — посты публикуются автоматически с ERID\n"
        "4. При отсутствии ERID пост уходит в карантин на ручную проверку",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:instructions")]
        ]),
    )
    await callback.answer()



# -----------------------------------------------------------------------------
# Выплаты
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "payout:request")
async def cb_payout_request(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT payout_card FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM payouts WHERE user_id=? AND status='pending'",
            (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if active["cnt"] >= MAX_ACTIVE_PAYOUTS:
        await callback.answer(
            f"❌ У вас уже {MAX_ACTIVE_PAYOUTS} активные заявки. Дождитесь выплаты.",
            show_alert=True
        )
        return

    card = user["payout_card"] if user else None

    if card:
        await callback.message.edit_text(
            f"💳 <b>Запрос выплаты</b>\n\n"
            f"Текущая карта: <code>{card}</code>\n\n"
            f"Минимальная сумма вывода: <b>{MIN_PAYOUT:.0f} ₽</b>\n"
            f"Введите сумму для вывода или смените карту:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Сменить карту", callback_data="payout:change_card")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:stats")],
            ])
        )
        await state.set_state(PayoutStates.waiting_for_amount)
    else:
        await callback.message.edit_text(
            "💳 <b>Запрос выплаты</b>\n\n"
            "Введите номер карты РФ для получения выплаты\n"
            "<i>(сохранится в профиле, в будущем менять не придётся)</i>:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:stats")],
            ])
        )
        await state.set_state(PayoutStates.waiting_for_card)

    await callback.answer()


@router.callback_query(F.data == "payout:change_card")
async def cb_payout_change_card(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "💳 Введите новый номер карты РФ:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="payout:request")],
        ])
    )
    await state.set_state(PayoutStates.waiting_for_card)
    await callback.answer()


@router.message(PayoutStates.waiting_for_card)
async def payout_got_card(message: Message, state: FSMContext) -> None:
    card = message.text.strip().replace(" ", "")

    if not card.isdigit() or len(card) != 16:
        await message.answer("❌ Некорректный номер карты. Введите 16 цифр без пробелов:")
        return

    formatted = f"{card[:4]} {card[4:8]} {card[8:12]} {card[12:]}"

    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET payout_card=? WHERE user_id=?",
            (formatted, message.from_user.id)
        )
        conn.commit()
    finally:
        conn.close()

    await state.set_state(PayoutStates.waiting_for_amount)
    await message.answer(
        f"✅ Карта сохранена: <code>{formatted}</code>\n\n"
        f"Теперь введите сумму для вывода (минимум {MIN_PAYOUT:.0f} ₽):",
        parse_mode=ParseMode.HTML
    )


@router.message(PayoutStates.waiting_for_amount)
async def payout_got_amount(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id

    try:
        amount = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Введите число, например: 2000")
        return

    if amount < MIN_PAYOUT:
        await message.answer(f"❌ Минимальная сумма вывода — {MIN_PAYOUT:.0f} ₽")
        return

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT payout_card, sub_id FROM users WHERE user_id=?", (user_id,)
        ).fetchone()

        # Проверяем баланс из транзакций
        balance_row = conn.execute("""
            SELECT COALESCE(SUM(payout), 0.0) as total
            FROM transactions
            WHERE sub_id=? AND status IN ('approved', 'paid')
        """, (user["sub_id"],)).fetchone()

        # Вычитаем уже выведенное
        withdrawn_row = conn.execute("""
            SELECT COALESCE(SUM(amount_blogger), 0.0) as total
            FROM payouts
            WHERE user_id=? AND status IN ('pending', 'completed')
        """, (user_id,)).fetchone()

        available = float(balance_row["total"]) - float(withdrawn_row["total"])
    finally:
        conn.close()

    if amount > available:
        await message.answer(
            f"❌ Недостаточно средств.\n"
            f"Доступно для вывода: <b>{available:.2f} ₽</b>",
            parse_mode=ParseMode.HTML
        )
        return

    calc = calc_payout(amount)
    card = user["payout_card"]

    # Сохраняем заявку
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO payouts (user_id, amount_requested, amount_to_withdraw, amount_blogger, card, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (user_id, calc["amount_requested"], calc["amount_to_withdraw"], calc["amount_blogger"], card))
        payout_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        conn.commit()
    finally:
        conn.close()

    await state.clear()

    # Уведомление блогеру
    await message.answer(
        f"✅ <b>Заявка принята, ожидайте!</b>\n\n"
        f"💰 Сумма к получению: <b>{calc['amount_blogger']:.2f} ₽</b>\n"
        f"💳 На карту: <code>{card}</code>\n\n"
        f"<i>Выплата производится в течение суток.</i>",
        parse_mode=ParseMode.HTML
    )

    # Уведомление админу
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"💸 <b>Новая заявка на выплату #{payout_id}</b>\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"💳 Карта: <code>{card}</code>\n\n"
                f"📤 Вывести из Такпродам: <b>{calc['amount_to_withdraw']:.2f} ₽</b>\n"
                f"<i>(после комиссии {PAYOUT_FIXED_FEE:.0f}₽ + {PAYOUT_BANK_PCT*100:.1f}% получишь ~{calc['amount_blogger']*2:.2f} ₽)</i>\n\n"
                f"💰 Отправить блогеру: <b>{calc['amount_blogger']:.2f} ₽</b>\n"
                f"💰 Твоя доля: <b>{calc['amount_blogger']:.2f} ₽</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✅ Отправлено",
                        callback_data=f"payout:done:{payout_id}:{user_id}"
                    )],
                ])
            )
        except TelegramAPIError as e:
            logger.error(f"Не удалось уведомить админа {admin_id}: {e}")


@router.callback_query(F.data.startswith("payout:done:"))
async def cb_payout_done(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    parts = callback.data.split(":")
    payout_id = int(parts[2])
    blogger_id = int(parts[3])

    conn = get_db()
    try:
        conn.execute("""
            UPDATE payouts SET status='completed', completed_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='pending'
        """, (payout_id,))
        conn.commit()
        payout = conn.execute(
            "SELECT amount_blogger, card FROM payouts WHERE id=?", (payout_id,)
        ).fetchone()
    finally:
        conn.close()

    # Уведомление блогеру
    try:
        await callback.bot.send_message(
            blogger_id,
            f"✅ <b>Выплата отправлена!</b>\n\n"
            f"💰 Сумма: <b>{payout['amount_blogger']:.2f} ₽</b>\n"
            f"💳 На карту: <code>{payout['card']}</code>\n\n"
            f"<i>Если деньги не пришли в течение суток — напишите в поддержку.</i>",
            parse_mode=ParseMode.HTML
        )
    except TelegramAPIError as e:
        logger.error(f"Не удалось уведомить блогера {blogger_id}: {e}")

    # Обновляем сообщение у админа
    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ <b>Выплачено</b>",
        parse_mode=ParseMode.HTML
    )
    await callback.answer("✅ Выплата подтверждена")

# =============================================================================
# === ADMIN CALLBACKS =========================================================
# =============================================================================

WEBAPP_ADMIN_URL: str = os.getenv("WEBAPP_ADMIN_URL", "")

@router.callback_query(F.data.startswith("admin:"))
async def handle_admin_callbacks(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    action = call.data.split(":")[1]

    if action == "billing_check":
        await call.answer("⏳ Запускаю биллинг-чек...")
        await run_billing_check(call.message.bot)
        await call.message.answer("✅ Биллинг-чек завершён")

    elif action == "broadcast":
        await call.answer()
        await state.set_state(AdminStates.broadcast_text)
        await call.message.answer("✏️ Введи текст рассылки:")

    elif action == "extend_sub":
        await call.answer()
        await state.set_state(AdminStates.extend_user_id)
        await call.message.answer("👤 Введи user_id пользователя:")

    else:
        await call.answer("Неизвестная команда", show_alert=True)
# =============================================================================
# === FASTAPI WEBAPP (Admin Panel) ============================================
# =============================================================================

def create_fastapi_app(bot: Bot) -> FastAPI:
    app = FastAPI(title="AutoPost Admin Panel", docs_url=None, redoc_url=None)
    
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    active_sessions = {}

    def is_authenticated(request: Request):
        token = request.cookies.get("admin_token")
        if not token or token not in active_sessions:
            raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
        return True

    @app.get("/admin/login", response_class=HTMLResponse)
    async def login_page():
        return """
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"><title>Вход в админку</title>
        <style>body{font-family:Arial;background:#0f1117;color:#fff;padding:50px;}</style>
        </head>
        <body>
            <h2>🔑 Вход в AutoPost Admin</h2>
            <form action="/admin/login" method="post">
                <input type="password" name="password" placeholder="Пароль" style="padding:10px;font-size:16px;width:300px;"><br><br>
                <button type="submit" style="padding:10px 20px;font-size:16px;">Войти</button>
            </form>
        </body>
        </html>
        """

    @app.post("/admin/login")
    async def login_post(password: str = Form(...)):
        if password == ADMIN_PASSWORD:
            token = secrets.token_hex(32)
            active_sessions[token] = True
            resp = RedirectResponse("/admin/dashboard", status_code=302)
            resp.set_cookie(key="admin_token", value=token, httponly=True, 
                secure=True, samesite="strict", max_age=3600*12)
            return resp
        return HTMLResponse("<h3>❌ Неверный пароль</h3><a href='/admin/login'>Назад</a>")

    @app.get("/admin/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            users = conn.execute("""
                SELECT user_id, username, role, subscription_until, channel_title, is_active 
                FROM users ORDER BY created_at DESC
            """).fetchall()

            posts = conn.execute("""
                SELECT p.*, u.username 
                FROM posts p 
                LEFT JOIN users u ON p.user_id = u.user_id 
                ORDER BY p.id DESC LIMIT 50
            """).fetchall()

            html = f"""
            <!DOCTYPE html>
            <html lang="ru">
            <head>
                <meta charset="UTF-8">
                <title>AutoPost — Админка</title>
                <style>
                    body {{font-family: Arial, sans-serif; background:#0f1117; color:#e0e0e8; padding:20px;}}
                    table {{width:100%; border-collapse:collapse; margin:20px 0;}}
                    th, td {{padding:10px; border:1px solid #333; text-align:left;}}
                    th {{background:#1a1d27;}}
                    .active {{color:#2ecc71;}} .inactive {{color:#e74c3c;}}
                </style>
            </head>
            <body>
                <h1>AutoPost Admin Dashboard</h1>
                <a href="/admin/logout">Выход</a>
                
                <h2>Пользователи ({len(users)})</h2>
                <table>
                    <tr><th>ID</th><th>Username</th><th>Роль</th><th>Канал</th><th>Подписка до</th><th>Статус</th><th>Действие</th></tr>
            """
            for u in users:
                html += f"""
                    <tr>
                        <td>{u['user_id']}</td>
                        <td>@{u['username'] or '-'}</td>
                        <td>{u['role']}</td>
                        <td>{u['channel_title'] or '-'}</td>
                        <td>{u['subscription_until'] or '—'}</td>
                        <td class="{'active' if u['is_active'] else 'inactive'}">{"Активен" if u['is_active'] else "Неактивен"}</td>
                        <td>
                            <form action="/admin/extend" method="post" style="display:inline;">
                                <input type="hidden" name="user_id" value="{u['user_id']}">
                                <input type="text" name="days" placeholder="Дней" size="4">
                                <button type="submit">Продлить</button>
                            </form>
                        </td>
                    </tr>
                """

            html += "</table><h2>Последние посты (50)</h2><table><tr><th>ID</th><th>Пользователь</th><th>Donor ID</th><th>Статус</th><th>Дата</th></tr>"

            for p in posts:
                html += f"""
                    <tr>
                        <td>{p['id']}</td>
                        <td>@{p.get('username', '-')}</td>
                        <td>{p['donor_post_id']}</td>
                        <td>{p['status']}</td>
                        <td>{str(p.get('published_at', '-'))[:19] if p.get('published_at') else '-'}</td>
                    </tr>
                """

            html += "</table></body></html>"
            return HTMLResponse(html)
        finally:
            conn.close()

    @app.post("/admin/extend")
    async def extend_subscription(request: Request, user_id: int = Form(...), days: int = Form(...)):
        is_authenticated(request)
        conn = get_db()
        try:
            now = datetime.now(timezone.utc)
            new_date = (now + timedelta(days=days)).isoformat()
            conn.execute("UPDATE users SET subscription_until=?, is_active=1 WHERE user_id=?", 
                        (new_date, user_id))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/dashboard", status_code=302)

    @app.get("/admin/logout")
    async def logout():
        resp = RedirectResponse("/admin/login")
        resp.delete_cookie("admin_token")
        return resp

    return app


# =============================================================================
# === SCHEDULER ===============================================================
# =============================================================================

async def unpin_old_messages(bot: Bot):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        rows = conn.execute(
            "SELECT chat_id, message_id FROM pinned_posts WHERE unpin_at <= ?", 
            (now,)
        ).fetchall()
        for row in rows:
            try:
                await bot.unpin_chat_message(chat_id=row["chat_id"], message_id=row["message_id"])
            except Exception:
                pass
            conn.execute("DELETE FROM pinned_posts WHERE chat_id=? AND message_id=?", 
                        (row["chat_id"], row["message_id"]))
        conn.commit()
    finally:
        conn.close()


async def cleanup_old_posts() -> None:
    conn = get_db()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        conn.execute("DELETE FROM posts WHERE created_at < ?", (cutoff,))
        conn.commit()
        logger.info("Очистка: удалены посты старше 30 дней")
    except Exception as e:
        logger.error(f"Ошибка очистки: {e}")
    finally:
        conn.close()

async def run_billing_check(bot: Bot):
    """Ежечасная проверка истекших подписок SaaS-пользователей."""
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        # Ищем пользователей, у которых подписка истекла, но они еще числятся активными
        expired_users = conn.execute(
            "SELECT user_id FROM users WHERE role='saas' AND subscription_until < ? AND is_active=1",
            (now,)
        ).fetchall()

        for row in expired_users:
            user_id = row["user_id"]
            # Отключаем активность
            conn.execute("UPDATE users SET is_active=0 WHERE user_id=?", (user_id,))
            
            # Пытаемся уведомить пользователя
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="⚠️ <b>Ваша подписка истекла!</b>\n\nБот приостановил работу с вашими каналами. Пожалуйста, продлите подписку в /cabinet.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление юзеру {user_id}: {e}")
        
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка в run_billing_check: {e}")
    finally:
        conn.close()


async def scan_donor_channels(bot: Bot):
    """Периодическая проверка каналов-доноров для блогеров и SaaS"""
    
    # --- Блогеры ---
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT user_id, source_link as channel_url 
            FROM users 
            WHERE role='blogger' 
            AND source_link IS NOT NULL 
            AND is_active=1
        """).fetchall()
    finally:
        conn.close()

    for row in rows:
        try:
            video_info = extract_video_info(row["channel_url"])
            if not video_info:
                continue
            video_id = video_info.get("id")
            if not video_id or is_video_processed(video_id):
                continue
            description = video_info.get("description", "")
            photo_url = video_info.get("thumbnail")
            products = find_product_links(description)
            sku = None
            marketplace = "wb"
            if products:
                first = products[0]
                sku = first.get("value")
                marketplace = first.get("marketplace", "wb")
            await process_new_video(
                bot=bot, user_id=row["user_id"], video_id=video_id,
                description=description, sku=sku,
                photo_url=photo_url, marketplace=marketplace,
            )
        except Exception as e:
            logger.error(f"scan_donor_channels блогер {row['user_id']}: {e}")

    # --- SaaS доноры ---
    if not SAAS_DONOR_CHANNELS:
        return

    for channel_url in SAAS_DONOR_CHANNELS:
        try:
            info = extract_video_info(channel_url)
            if not info:
                continue
            post_id = info.get("id")
            if not post_id or is_video_processed(f"saas_{post_id}"):
                continue
            text = info.get("description") or info.get("title") or ""
            await process_saas_post(bot=bot, post_text=text, post_id=f"saas_{post_id}")
        except Exception as e:
            logger.error(f"scan_donor_channels SaaS донор {channel_url}: {e}")

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        run_billing_check, trigger="interval", hours=1,
        kwargs={"bot": bot}, id="billing_check",
    )
    scheduler.add_job(
        flush_night_queue, trigger="cron", hour=8, minute=0,
        kwargs={"bot": bot}, id="flush_night_queue",
    )
    scheduler.add_job(
        unpin_old_messages, trigger="interval", minutes=30,
        kwargs={"bot": bot}, id="unpin_vip_posts",
    )
    scheduler.add_job(
        cleanup_old_posts, trigger="cron", hour=3, minute=0,
        id="cleanup_old_posts",
    )
    scheduler.add_job(
        scan_donor_channels, trigger="interval", minutes=30,
        kwargs={"bot": bot}, id="scan_donors",
    )
    return scheduler


# =============================================================================
# === MAIN ENTRYPOINT =========================================================
# =============================================================================
async def main() -> None:
    logger.info("=== AutoPost Bot + Web Admin Panel запускается ===")
    
    init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Инициализация FSM и диспетчера
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Подключение мидлвара
    dp.update.middleware(ErrorLoggingMiddleware())
    
    # ВАЖНО: Убедись, что 'router' — это тот же самый объект, 
    # который ты импортировал в файле с обработчиками (cmd_start и др.).
    # Если ты создаешь router здесь, то в файле с функциями напиши: from main import router
    dp.include_router(router)

    # Запуск планировщика
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планировщик (APScheduler) запущен")

    # Настройка FastAPI
    fastapi_app = create_fastapi_app(bot)
    config = uvicorn.Config(
        fastapi_app,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        log_level="warning",
        loop="asyncio"
    )
    server = uvicorn.Server(config)

    logger.info(f"🌐 Web Admin Panel доступен по адресу: http://{WEBAPP_HOST}:{WEBAPP_PORT}/admin")

    # Корректный запуск
    try:
        await asyncio.gather(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
            server.serve(),
            return_exceptions=True
        )
    finally:
        # Корректное закрытие
        await bot.session.close()
        scheduler.shutdown()
        logger.info("Бот и планировщик остановлены")



# ====================== ФАЗА 2: ПЛАТЕЖИ ======================

@router.callback_query(F.data == "menu:tariffs")
async def cb_menu_tariffs(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "💎 <b>Продление подписки</b>\n\n"
        "Выберите удобный способ оплаты:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_payment_methods()
    )
    await callback.answer()


@router.callback_query(F.data == "pay:stars")
async def cb_pay_stars(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "⭐ <b>Оплата через Telegram Stars</b>\n\n"
        "Скоро здесь будет список тарифов и кнопки для прямой оплаты Stars.\n\n"
        "Пока что функция в разработке.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к тарифам", callback_data="menu:tariffs")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "pay:card")
async def cb_pay_card(callback: CallbackQuery) -> None:
    text = (
        "💳 <b>Оплата банковской картой</b>\n\n"
        f"Сбер: <code>{CARD_SBER}</code>\n"
        f"Т-Банк: <code>{CARD_TBANK}</code>\n"
        f"Visa KG: <code>{CARD_VISA_KG}</code>\n\n"
        f"TON: <code>{CARD_TON}</code>\n\n"
        "После оплаты пришлите чек администратору.\n"
        f"<i>Обязательно укажите в комментарии ваш ID: <code>{callback.from_user.id}</code></i>"
    )
    
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к тарифам", callback_data="menu:tariffs")]
        ])
    )
    await callback.answer()

# =============================================================================
# === SCHEDULER ===============================================================
# =============================================================================

async def unpin_old_messages(bot: Bot):
    """Авто-открепление старых постов"""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        rows = conn.execute(
            "SELECT chat_id, message_id FROM pinned_posts WHERE unpin_at <= ?", 
            (now,)
        ).fetchall()
        for row in rows:
            try:
                await bot.unpin_chat_message(chat_id=row["chat_id"], message_id=row["message_id"])
            except Exception:
                pass
            conn.execute("DELETE FROM pinned_posts WHERE chat_id=? AND message_id=?", 
                        (row["chat_id"], row["message_id"]))
        conn.commit()
    finally:
        conn.close()


async def cleanup_old_posts() -> None:
    conn = get_db()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        conn.execute("DELETE FROM posts WHERE created_at < ?", (cutoff,))
        conn.commit()
        logger.info("Очистка: удалены посты старше 30 дней")
    except Exception as e:
        logger.error(f"Ошибка очистки: {e}")
    finally:
        conn.close()


async def scan_donor_channels(bot: Bot):
    """Периодическая проверка каналов-доноров для блогеров и SaaS"""
    
    # --- Блогеры ---
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT user_id, source_link as channel_url 
            FROM users 
            WHERE role='blogger' 
            AND source_link IS NOT NULL 
            AND is_active=1
        """).fetchall()
    finally:
        conn.close()

    for row in rows:
        try:
            video_info = extract_video_info(row["channel_url"])
            if not video_info:
                continue
            video_id = video_info.get("id")
            if not video_id or is_video_processed(video_id):
                continue
            description = video_info.get("description", "")
            photo_url = video_info.get("thumbnail")
            products = find_product_links(description)
            sku = None
            marketplace = "wb"
            if products:
                first = products[0]
                sku = first.get("value")
                marketplace = first.get("marketplace", "wb")
            await process_new_video(
                bot=bot, user_id=row["user_id"], video_id=video_id,
                description=description, sku=sku,
                photo_url=photo_url, marketplace=marketplace,
            )
        except Exception as e:
            logger.error(f"scan_donor_channels блогер {row['user_id']}: {e}")

    # --- SaaS доноры ---
    if not SAAS_DONOR_CHANNELS:
        return

    for channel_url in SAAS_DONOR_CHANNELS:
        try:
            info = extract_video_info(channel_url)
            if not info:
                continue
            post_id = info.get("id")
            if not post_id or is_video_processed(f"saas_{post_id}"):
                continue
            text = info.get("description") or info.get("title") or ""
            await process_saas_post(bot=bot, post_text=text, post_id=f"saas_{post_id}")
        except Exception as e:
            logger.error(f"scan_donor_channels SaaS донор {channel_url}: {e}")

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        run_billing_check, trigger="interval", hours=1,
        kwargs={"bot": bot}, id="billing_check",
    )
    scheduler.add_job(
        flush_night_queue, trigger="cron", hour=8, minute=0,
        kwargs={"bot": bot}, id="flush_night_queue",
    )
    scheduler.add_job(
        unpin_old_messages, trigger="interval", minutes=30,
        kwargs={"bot": bot}, id="unpin_vip_posts",
    )
    scheduler.add_job(
        cleanup_old_posts, trigger="cron", hour=3, minute=0,
        id="cleanup_old_posts",
    )
    scheduler.add_job(
        scan_donor_channels, trigger="interval", minutes=30,
        kwargs={"bot": bot}, id="scan_donors",
    )
    return scheduler


# =============================================================================
# === FASTAPI WEBAPP (Admin Panel) ============================================
# =============================================================================

def create_fastapi_app(bot: Bot) -> FastAPI:
    app = FastAPI(title="AutoPost Admin Panel", docs_url=None, redoc_url=None)
    
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    active_sessions = {}

    def is_authenticated(request: Request):
        token = request.cookies.get("admin_token")
        if not token or token not in active_sessions:
            raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
        return True

    @app.get("/admin/login", response_class=HTMLResponse)
    async def login_page():
        return """
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"><title>Вход в админку</title>
        <style>body{font-family:Arial;background:#0f1117;color:#fff;padding:50px;}</style>
        </head>
        <body>
            <h2>🔑 Вход в AutoPost Admin</h2>
            <form action="/admin/login" method="post">
                <input type="password" name="password" placeholder="Пароль" style="padding:10px;font-size:16px;width:300px;"><br><br>
                <button type="submit" style="padding:10px 20px;font-size:16px;">Войти</button>
            </form>
        </body>
        </html>
        """

    @app.post("/admin/login")
    async def login_post(password: str = Form(...)):
        if password == ADMIN_PASSWORD:
            token = secrets.token_hex(32)
            active_sessions[token] = True
            resp = RedirectResponse("/admin/dashboard", status_code=302)
            resp.set_cookie(key="admin_token", value=token, httponly=True, 
                secure=True, samesite="strict", max_age=3600*12)
            return resp
        return HTMLResponse("<h3>❌ Неверный пароль</h3><a href='/admin/login'>Назад</a>")

    @app.get("/admin/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        is_authenticated(request)
        conn = get_db()
        try:
            users = conn.execute("""
                SELECT user_id, username, role, subscription_until, channel_title, is_active 
                FROM users ORDER BY created_at DESC
            """).fetchall()

            posts = conn.execute("""
                SELECT p.*, u.username 
                FROM posts p 
                LEFT JOIN users u ON p.user_id = u.user_id 
                ORDER BY p.id DESC LIMIT 50
            """).fetchall()

            html = f"""
            <!DOCTYPE html>
            <html lang="ru">
            <head>
                <meta charset="UTF-8">
                <title>AutoPost — Админка</title>
                <style>
                    body {{font-family: Arial, sans-serif; background:#0f1117; color:#e0e0e8; padding:20px;}}
                    table {{width:100%; border-collapse:collapse; margin:20px 0;}}
                    th, td {{padding:10px; border:1px solid #333; text-align:left;}}
                    th {{background:#1a1d27;}}
                    .active {{color:#2ecc71;}} .inactive {{color:#e74c3c;}}
                </style>
            </head>
            <body>
                <h1>AutoPost Admin Dashboard</h1>
                <a href="/admin/logout">Выход</a>
                
                <h2>Пользователи ({len(users)})</h2>
                <table>
                    <tr><th>ID</th><th>Username</th><th>Роль</th><th>Канал</th><th>Подписка до</th><th>Статус</th><th>Действие</th></tr>
            """
            for u in users:
                html += f"""
                    <tr>
                        <td>{u['user_id']}</td>
                        <td>@{u['username'] or '-'}</td>
                        <td>{u['role']}</td>
                        <td>{u['channel_title'] or '-'}</td>
                        <td>{u['subscription_until'] or '—'}</td>
                        <td class="{'active' if u['is_active'] else 'inactive'}">{"Активен" if u['is_active'] else "Неактивен"}</td>
                        <td>
                            <form action="/admin/extend" method="post" style="display:inline;">
                                <input type="hidden" name="user_id" value="{u['user_id']}">
                                <input type="text" name="days" placeholder="Дней" size="4">
                                <button type="submit">Продлить</button>
                            </form>
                        </td>
                    </tr>
                """

            html += "</table><h2>Последние посты (50)</h2><table><tr><th>ID</th><th>Пользователь</th><th>Donor ID</th><th>Статус</th><th>Дата</th></tr>"

            for p in posts:
                html += f"""
                    <tr>
                        <td>{p['id']}</td>
                        <td>@{p.get('username', '-')}</td>
                        <td>{p['donor_post_id']}</td>
                        <td>{p['status']}</td>
                        <td>{str(p.get('published_at', '-'))[:19] if p.get('published_at') else '-'}</td>
                    </tr>
                """

            html += "</table></body></html>"
            return HTMLResponse(html)
        finally:
            conn.close()

    @app.post("/admin/extend")
    async def extend_subscription(request: Request, user_id: int = Form(...), days: int = Form(...)):
        is_authenticated(request)
        conn = get_db()
        try:
            now = datetime.now(timezone.utc)
            new_date = (now + timedelta(days=days)).isoformat()
            conn.execute("UPDATE users SET subscription_until=?, is_active=1 WHERE user_id=?", 
                        (new_date, user_id))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/admin/dashboard", status_code=302)

    @app.get("/admin/logout")
    async def logout():
        resp = RedirectResponse("/admin/login")
        resp.delete_cookie("admin_token")
        return resp

    return app


# =============================================================================
# === MAIN ENTRYPOINT =========================================================
# =============================================================================

async def main() -> None:
    logger.info("=== AutoPost Bot + Web Admin Panel запускается ===")
    
    init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.update.middleware(ErrorLoggingMiddleware())
    dp.include_router(router)

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планировщик (APScheduler) запущен")

    fastapi_app = create_fastapi_app(bot)

    config = uvicorn.Config(
        fastapi_app,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        log_level="warning"
    )
    server = uvicorn.Server(config)

    logger.info(f"🌐 Web Admin Panel доступен по адресу: http://{WEBAPP_HOST}:{WEBAPP_PORT}/admin")

    await asyncio.gather(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        server.serve(),
        return_exceptions=True
    )


if __name__ == "__main__":
    asyncio.run(main())
