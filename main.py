"""
=============================================================================
  АВТОПОСТИНГ-БОТ | SaaS-платформа для монетизации Telegram-каналов
  Stack: Python 3.10+, aiogram 3.x, FastAPI, SQLite3, httpx, APScheduler
  Юридическая защита: ERID обязателен. Публикация без маркировки — запрещена.
=============================================================================
"""

import asyncio
import html
import logging
import os
import re
import secrets
import sqlite3
import time
import random
import hashlib
import os
from aiogram.types import FSInputFile
from datetime import datetime
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any, List
from webapp import create_app
import sys
from keyboards.saas import kb_cabinet_menu, kb_tariffs, kb_payment_methods
from handlers.saas import router as saas_router
from services.admitad import refill_admitad_catalogs, update_all_store_data_from_feed
from webapp.auth import generate_admin_token, generate_user_token
from config import (
    settings, MIN_PAYOUT, PAYOUT_FIXED_FEE, PAYOUT_BANK_PCT, MAX_ACTIVE_PAYOUTS,
    is_night_time, load_tariffs,
    BOT_TOKEN, ADMIN_IDS, WEBAPP_ADMIN_URL, WEBAPP_BASE_URL, QUARANTINE_CHAT_ID,
    DEEPINFRA_API_KEY, STARS_PROVIDER_TOKEN, WEBAPP_HOST, WEBAPP_PORT,
    CARD_SBER, CARD_TBANK, CARD_TON, CARD_VISA_KG, DB_PATH
)
from services.saas_core import (
    publish_post_with_fallback,
    publish_from_catalog
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, Request, HTTPException
from states import OnboardingStates, SaasStates, AdminStates, PaymentFSM, PayoutStates
from stats import get_saas_channels, get_saas_channel_stats_new, get_saas_overview, STAT_PERIODS
from services.db import get_db


# ---------------------------------------------------------------------------

print("DEBUG: main.py started", flush=True, file=sys.stderr)

import httpx
import uvicorn
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    SuccessfulPayment,
    TelegramObject,
    WebAppInfo,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
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
# === MIDDLEWARE ==============================================================
# =============================================================================
print("DEBUG: starting class definitions", flush=True, file=sys.stderr)
class ErrorLoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        try:
            return await handler(event, data)
        except Exception as e:
            logger.exception(f"Ошибка при обработке события: {e}")
            raise


# =============================================================================
# === ИНИЦИАЛИЗАЦИЯ БД ========================================================
# =============================================================================
def init_db() -> None:
    print("DEBUG: init_db done, starting bot...", flush=True, file=sys.stderr)
    conn = get_db()
    cursor = conn.cursor()

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
            payout_card TEXT,
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
            max_posts_per_day INTEGER DEFAULT 25,
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saas_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id TEXT NOT NULL,
            donor_post_id TEXT NOT NULL,
            original_text TEXT,
            photo_url TEXT,
            rewritten_text TEXT,
            sku TEXT,
            marketplace TEXT DEFAULT 'wb',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tariffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            days INTEGER NOT NULL,
            price_rub REAL NOT NULL,
            price_stars INTEGER NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promocodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            days INTEGER NOT NULL DEFAULT 2,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promocode_activations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id TEXT NOT NULL,
            activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            keyword TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_category_preferences (
            user_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, category_id),
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(category_id) REFERENCES product_categories(id)
        )
    """)
    # Создание таблицы gdeslon_catalog, если её ещё нет
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gdeslon_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT,
            user_id INTEGER,
            title TEXT,
            price REAL,
            currency TEXT,
            partner_url TEXT,
            erid TEXT,
            advertiser TEXT,
            image_url TEXT,
            category_keyword TEXT,
            used INTEGER DEFAULT 0
        )
    """)
    # Таблица для хранения транзакций из Admitad (вебхуки)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admitad_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admitad_id INTEGER UNIQUE,
            user_id INTEGER,
            channel_id TEXT,
            action TEXT,
            action_id INTEGER,
            payment_sum REAL,
            currency TEXT DEFAULT 'RUB',
            payment_status TEXT,
            order_id INTEGER,
            click_time INTEGER,
            time INTEGER,
            subid1 TEXT,
            subid2 TEXT,
            subid3 TEXT,
            subid4 TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_promocodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            promocode TEXT NOT NULL,
            description TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Уникальный индекс для предотвращения дубликатов
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_gdeslon_unique 
            ON gdeslon_catalog(user_id, sku)
    """)
    # Миграции
    migrations = [
        "ALTER TABLE users ADD COLUMN payout_card TEXT",
        "ALTER TABLE posts ADD COLUMN target_channel_id TEXT",
        "ALTER TABLE posts ADD COLUMN channel_id TEXT",
        "ALTER TABLE channels ADD COLUMN max_posts_per_day INTEGER DEFAULT 25",
        "ALTER TABLE tariffs ADD COLUMN max_channels INTEGER DEFAULT 5",
        "ALTER TABLE tariffs ADD COLUMN max_posts_per_day INTEGER DEFAULT 25",
        "ALTER TABLE tariffs ADD COLUMN max_categories INTEGER DEFAULT 3",
        "ALTER TABLE tariffs ADD COLUMN min_cashback REAL DEFAULT 0",
        "ALTER TABLE tariffs ADD COLUMN max_cashback REAL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN tariff_id INTEGER",
        "ALTER TABLE gdeslon_catalog ADD COLUMN source TEXT DEFAULT 'gdeslon'",
        "ALTER TABLE channels ADD COLUMN sub_id TEXT",
        "ALTER TABLE posts ADD COLUMN subid1 TEXT",
        "ALTER TABLE posts ADD COLUMN direct_link TEXT",
        "ALTER TABLE users ADD COLUMN balance_pending REAL DEFAULT 0.0",
        "ALTER TABLE users ADD COLUMN balance_available REAL DEFAULT 0.0",
        "ALTER TABLE admitad_transactions ADD COLUMN payment_status TEXT DEFAULT 'pending'",
        "ALTER TABLE users ADD COLUMN oferta_accepted INTEGER DEFAULT 0",
        "ALTER TABLE gdeslon_catalog ADD COLUMN old_price REAL",
        "ALTER TABLE gdeslon_catalog ADD COLUMN discount_percent INTEGER",
        "ALTER TABLE users ADD COLUMN min_discount INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN stats_token TEXT",
        "ALTER TABLE users ADD COLUMN stats_token_expires TIMESTAMP",
        # Миграция для города в user_category_preferences
        "ALTER TABLE user_category_preferences ADD COLUMN city TEXT",
    ]
    for mig in migrations:
        try:
            cursor.execute(mig)
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")


# =============================================================================
# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================================================
def log_admin_action(admin_id: int, action: str, details: str = ""):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO admin_audit (admin_id, action, details) VALUES (?, ?, ?)",
            (admin_id, action, details)
        )
        conn.commit()
    finally:
        conn.close()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def generate_sub_id(username: str, user_id: int) -> str:
    _TRANSLIT_MAP = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    username = (username or "").lstrip("@").lower()
    result = ""
    for ch in username:
        result += _TRANSLIT_MAP.get(ch, ch if ch.isalnum() or ch == "_" else "")
    result = re.sub(r"[^a-z0-9_]", "", result)
    result = re.sub(r"_+", "_", result).strip("_") or f"user{user_id}"
    return f"{result}_uid{user_id}"

def sanitize_html(text: str) -> str:
    if not text:
        return ""
    _ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre", "a"}
    text = re.sub(r"</?([a-zA-Z]+)(?:\s[^>]*)?>", lambda m: (
        m.group(0) if m.group(1).lower() in _ALLOWED_TAGS else ""
    ), text)
    return text[:4096]

async def check_bot_admin(bot: Bot, channel_id: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=bot.id)
        if member.status == "creator":
            return True
        if member.status == "administrator":
            return getattr(member, "can_post_messages", False)
        return False
    except TelegramAPIError as e:
        logger.error(f"Ошибка проверки админки в {channel_id}: {e}")
        return False


# =============================================================================
# === КЛАВИАТУРЫ ==============================================================
def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть Web-админку", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))],
        [InlineKeyboardButton(text="📣 Рассылка всем", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="💰 Запустить биллинг-чек", callback_data="admin:billing_check")],
        [InlineKeyboardButton(text="🔧 Продлить подписку", callback_data="admin:extend_sub")],
    ])

# =============================================================================
# === ROUTER & HANDLERS =======================================================
print("DEBUG: creating router", flush=True, file=sys.stderr)
router = Router()

# ---------------------------------------------------------------------------
# /promo
# ---------------------------------------------------------------------------
@router.message(Command("promo"))
async def promo_handler(message: Message, state: FSMContext):
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "🎁 Введите команду в формате: /promo КОД\nНапример: /promo D2075RPD",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")]
            ])
        )
        return

    code = args[1].strip().upper()
    logger.info(f"[PROMO] Пользователь {message.from_user.id} ввёл код: {code}")

    conn = get_db()
    try:
        promo = conn.execute("SELECT * FROM promocodes WHERE UPPER(code) = ?", (code,)).fetchone()
        if not promo:
            await message.answer("❌ Неверный или несуществующий промокод.")
            return

        activation = conn.execute("SELECT * FROM promocode_activations WHERE UPPER(code) = ?", (code,)).fetchone()
        if activation:
            await message.answer("❌ Этот промокод уже использован.")
            return

        channels = conn.execute(
            "SELECT channel_id, channel_title FROM channels WHERE user_id = ? AND is_active = 1",
            (message.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    if not channels:
        await message.answer("❌ У вас нет подключённых каналов.")
        return

    days = int(promo["days"])

    if len(channels) == 1:
        channel_id = channels[0]["channel_id"]
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO promocode_activations (code, user_id, channel_id) VALUES (?, ?, ?)",
                (code, message.from_user.id, channel_id)
            )
            new_until = datetime.now(timezone.utc) + timedelta(days=days)
            conn.execute(
                "UPDATE users SET subscription_until = ?, is_active = 1 WHERE user_id = ?",
                (new_until.isoformat(), message.from_user.id)
            )
            conn.commit()
        finally:
            conn.close()

        await message.answer(f"✅ Промокод активирован!\nПодписка продлена на {days} дней.")
        return

    # Несколько каналов – показываем выбор
    await state.update_data(promocode=code, promo_days=days)
    kb_rows = []
    for ch in channels:
        kb_rows.append([InlineKeyboardButton(
            text=ch["channel_title"] or ch["channel_id"],
            callback_data=f"promo_channel:{ch['channel_id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")])

    await message.answer(
        "🎯 Выберите канал для активации промокода:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )

# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("👋 Добро пожаловать в Панель администратора.", reply_markup=kb_admin_panel())
        return

    conn = get_db()
    try:
        user = conn.execute("SELECT role FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
        if not user:
            # Новый пользователь – создаём запись и запускаем онбординг
            sub_id = generate_sub_id(message.from_user.username, message.from_user.id)
            conn.execute(
                "INSERT INTO users (user_id, username, sub_id, role) VALUES (?, ?, ?, 'saas')",
                (message.from_user.id, message.from_user.username, sub_id)
            )
            conn.commit()
            await message.answer(
                "👋 Добро пожаловать! Для начала работы отправьте @username вашего Telegram-канала."
            )
            await state.set_state(OnboardingStates.waiting_saas_tg_channel)
        else:
            # Пользователь уже зарегистрирован – не показываем кабинет
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💼 Открыть кабинет", callback_data="cabinet:open")]
            ])
            await message.answer(
                "✅ Вы уже зарегистрированы. Для управления ботом используйте команду /cabinet.",
                reply_markup=kb
            )
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# /cabinet
# ---------------------------------------------------------------------------
@router.message(Command("cabinet"))
async def cmd_cabinet(message: Message):
    await show_user_cabinet(message, user_id=message.from_user.id)

# ---------------------------------------------------------------------------
# Личный кабинет (общая функция)
# ---------------------------------------------------------------------------
async def show_user_cabinet(message: Message, user_id: int = None):
    if user_id is None:
        user_id = message.from_user.id

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT role, subscription_until, username, balance_pending, balance_available, oferta_accepted "
            "FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not user:
        await message.answer("Пожалуйста, начните с команды /start")
        return

    # Если оферта не принята – показываем только оферту
    if not user["oferta_accepted"]:
        text_oferta = (
            "📜 <b>Публичная оферта</b>\n\n"
            "Для использования бота необходимо принять условия Пользовательского соглашения.\n\n"
            "<b>ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ (ПУБЛИЧНАЯ ОФЕРТА)</b>\n"
            "<i>Последняя редакция: 28 июня 2026 года</i>\n\n"
            "Нажимая «Принимаю», вы соглашаетесь с условиями.\n\n"
            "<b>1. Термины</b>\n"
            "• Сервис – данный Telegram-бот.\n"
            "• CPA-сеть – партнёрская сеть Admitad.\n"
            "• SubID – уникальный цифровой идентификатор вашего канала.\n"
            "• Баланс – справочные данные о вознаграждении, не электронные деньги.\n\n"
            "<b>2. Предмет</b>\n"
            "Вы получаете доступ к автопостингу товаров с партнёрскими ссылками. "
            "Сервис удерживает комиссию <b>5%</b> от подтверждённого вознаграждения.\n\n"
            "<b>3. Учёт и выплаты</b>\n"
            "• Единственный источник данных о заказах – CPA-сеть.\n"
            "• <b>В ожидании</b> – заказы на проверке у рекламодателя (30–90 дней).\n"
            "• <b>Доступно к выводу</b> – подтверждённые заказы, готовые к выплате.\n"
            "• Выплата производится по запросу, за вычетом 5%.\n\n"
            "<b>4. Запрещено</b>\n"
            "Спам, накрутка, самовыкупы, мотивированный трафик, брендовая реклама. "
            "Публикация ссылок разрешена только в добавленных каналах.\n\n"
            "<b>5. Ответственность</b>\n"
            "• Выплаты ограничены суммами, реально полученными от CPA-сети.\n"
            "• При фроде или блокировке аккаунта баланс аннулируется.\n"
            "• Администрация может заморозить выплаты на время проверки (до 90 дней).\n\n"
            "<b>6. Изменения</b>\n"
            "Администрация может менять условия. Продолжение использования – согласие с новой редакцией."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принимаю", callback_data="oferta:accept")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="start")]
        ])
        await message.answer(text_oferta, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    role = user["role"]
    sub_until = user["subscription_until"]
    if sub_until:
        try:
            end_dt = datetime.fromisoformat(sub_until.replace("Z", "+00:00"))
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

    # Финансовый блок
    finance_text = ""
    if role == "saas":
        pending = user["balance_pending"] or 0.0
        available = user["balance_available"] or 0.0
        finance_text = (
            f"\n\n💰 <b>Баланс</b>\n"
            f"⏳ В ожидании: <b>{pending:.2f} ₽</b>\n"
            f"💳 Доступно к выводу: <b>{available:.2f} ₽</b>"
        )

    text = (
        f"💼 <b>Личный кабинет</b>\n\n"
        f"👤 Роль: <b>{role.upper()}</b>\n"
        f"📅 Статус подписки: {status_text}\n"
        f"🆔 ID: <code>{user_id}</code>"
        f"{finance_text}"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb_cabinet_menu(role))

# ---------------------------------------------------------------------------
# Главное меню (колбэк)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:main")
async def cb_menu_main(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except:
        pass
    conn = get_db()
    try:
        user = conn.execute("SELECT role FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
        role = user["role"] if user else "blogger"
    finally:
        conn.close()
    await show_user_cabinet(callback.message, user_id=callback.from_user.id)

# ---------------------------------------------------------------------------
# Мои каналы (SaaS)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:my_channels")
async def cb_my_channels(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        channels = conn.execute(
            "SELECT id, channel_title, channel_id FROM channels WHERE user_id=? AND is_active=1",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    if channels:
        text = "📢 <b>Ваши подключенные каналы:</b>\n\n"
        kb_rows = []
        for i, ch in enumerate(channels, 1):
            text += f"{i}. {ch['channel_title']} (<code>{ch['channel_id']}</code>)\n"
            kb_rows.append([InlineKeyboardButton(
                text=f"🗑 Удалить {ch['channel_title']}",
                callback_data=f"channel_delete:{ch['id']}"
            )])
        text += "\n<i>Для добавления нового канала отправьте его @username.</i>"
        kb_rows.append([InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    else:
        text = "📢 <b>У вас пока нет подключенных каналов.</b>\n\nДля добавления канала отправьте его @username."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")]
        ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        await state.set_state(OnboardingStates.waiting_saas_tg_channel)
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("channel_delete:"))
async def cb_delete_channel(callback: CallbackQuery) -> None:
    channel_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    conn = get_db()
    try:
        conn.execute("DELETE FROM channels WHERE id=? AND user_id=?", (channel_id, user_id))
        conn.commit()
    finally:
        conn.close()

    await callback.answer("🗑 Канал удалён.", show_alert=True)
    await cb_my_channels(callback)

# ---------------------------------------------------------------------------
# Статистика SaaS
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:stats")
async def cb_menu_stats(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    await _show_saas_stats(callback, user_id, channel_idx=0, period="30d")
    await callback.answer()

async def _show_saas_stats(callback: CallbackQuery, user_id: int, channel_idx: int = 0, period: str = "30d") -> None:
    channels = get_saas_channels(user_id)
    if not channels:
        overview = get_saas_overview(user_id)
        text = (
            f"📊 <b>Общая статистика</b>\n\n"
            f"📬 Всего постов: <b>{overview['total_posts']}</b>\n"
            f"📅 За 30 дней: <b>{overview['posts_30d']}</b>\n\n"
            f"🏪 <b>По магазинам (все время):</b>\n"
        )
        if overview['by_store']:
            for store, count in overview['by_store'].items():
                text += f"  {store}: {count}\n"
        else:
            text += "  Нет данных\n"
        text += f"\n<i>Подключите каналы для детальной статистики.</i>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")]
        ])
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    channel_idx = max(0, min(channel_idx, len(channels) - 1))
    ch = channels[channel_idx]
    s = get_saas_channel_stats_new(user_id, ch["channel_id"], period)
    total_ch = len(channels)

    text = (
        f"📊 <b>Статистика канала</b>\n"
        f"📢 <b>{ch['channel_title'] or ch['channel_id']}</b>  <i>({channel_idx + 1}/{total_ch})</i>\n"
        f"🗓 Период: <b>{s['period_label']}</b>\n\n"
        f"📬 Всего постов: <b>{s['total']}</b>\n"
        f"✅ Опубликовано: <b>{s['published']}</b>\n"
        f"❌ Ошибок: <b>{s['errors']}</b>\n"
        f"🕐 Последний: <b>{s['last_published_at']}</b>\n\n"
        f"🏪 <b>По магазинам:</b>\n"
    )
    if s['by_store']:
        for store, count in s['by_store'].items():
            text += f"  {store}: {count}\n"
    else:
        text += "  Нет данных\n"

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
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")])

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


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    token = generate_admin_token(message.from_user.id)
    base = WEBAPP_ADMIN_URL.rstrip('/')
    login_url = f"{base}/login?token={token}"
    await message.answer(
        f"🔑 <a href='{login_url}'>Открыть админку</a>\n\n"
        f"Или скопируйте ссылку:\n{login_url}",
        disable_web_page_preview=True
    )

@router.callback_query(F.data == "menu:webstats")
async def cb_webstats(callback: CallbackQuery):
    user_id = callback.from_user.id
    token = generate_user_token(user_id)
    link = f"{WEBAPP_BASE_URL}/my-stats?token={token}"
    await callback.message.answer(
        f"📊 <a href='{link}'>Открыть статистику</a>\n\n"
        "Ссылка действительна 24 часа.\n"
        "Если вы не можете перейти, скопируйте адрес:\n"
        f"<code>{link}</code>",
        disable_web_page_preview=True,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:settings")
async def cb_menu_settings(callback: CallbackQuery) -> None:
    await open_saas_settings(callback)
    await callback.answer()

async def open_saas_settings(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT api_key, auto_pin FROM users WHERE user_id=?", (user_id,)).fetchone()
    finally:
        conn.close()
    if not user:
        await callback.answer("❌ Ошибка загрузки настроек", show_alert=True)
        return

    auto_pin = bool(user["auto_pin"] if user["auto_pin"] is not None else 1)

    text = (
        "⚙️ <b>Настройки SaaS-аккаунта</b>\n\n"
        "📦 <b>Товары поступают автоматически из магазинов-партнёров Admitad.</b>\n"
        "Вы выбираете магазины в разделе «🏪 Магазины». Бот сам пополняет каталог и публикует посты с маркировкой ERID.\n\n"
        "🔑 Ручной ввод API-ключей не требуется.\n\n"
        "⚡ Дополнительные возможности:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ℹ️ Об источнике товаров", callback_data="saas_set:gdeslon_apikey")],
        [InlineKeyboardButton(text=f"📌 Авто-закреп постов: {'✅' if auto_pin else '❌'}", callback_data="saas_toggle:autopin")],
        [InlineKeyboardButton(text="🚀 Опубликовать сейчас (Force Post)", callback_data="saas_force_post")],
        [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except TelegramBadRequest:
        pass

@router.callback_query(F.data.startswith("saas_toggle:"))
async def cb_saas_toggles(callback: CallbackQuery) -> None:
    action = callback.data.split(":")[1]
    if action != "autopin":
        return
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT auto_pin FROM users WHERE user_id=?", (user_id,)).fetchone()
        if user:
            new_val = 0 if user["auto_pin"] else 1
            conn.execute("UPDATE users SET auto_pin=? WHERE user_id=?", (new_val, user_id))
            conn.commit()
    finally:
        conn.close()
    await open_saas_settings(callback)

# ---------------------------------------------------------------------------
# Успешная оплата (звёзды)
# ---------------------------------------------------------------------------
@router.pre_checkout_query()
async def process_pre_checkout_query(query: PreCheckoutQuery):
    await query.answer(ok=True)

@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    if not payload.startswith("tariff_"):
        return

    parts = payload.split("_")
    if len(parts) != 3:
        return
    tariff_id = int(parts[1])
    days = int(parts[2])

    conn = get_db()
    try:
        tariff = conn.execute("SELECT days FROM tariffs WHERE id=?", (tariff_id,)).fetchone()
        if not tariff:
            await message.answer("❌ Тариф не найден.")
            return
        days = tariff["days"]

        new_until = datetime.now(timezone.utc) + timedelta(days=days)
        conn.execute(
            "UPDATE users SET subscription_until = ?, is_active = 1, tariff_id = ? WHERE user_id = ?",
            (new_until.isoformat(), tariff_id, message.from_user.id)
        )
        conn.commit()
    finally:
        conn.close()

    await message.answer(
        f"✅ <b>Подписка активирована!</b>\n\n"
        f"Действует до: {new_until.strftime('%d.%m.%Y %H:%M')} (UTC)",
        parse_mode=ParseMode.HTML
    )

# ---------------------------------------------------------------------------
# ОНБОРДИНГ: SAAS – ДОБАВЛЕНИЕ КАНАЛА (ключевой обработчик)
# ---------------------------------------------------------------------------
@router.message(OnboardingStates.waiting_saas_tg_channel)
async def handle_saas_channel_addition(message: Message, state: FSMContext) -> None:
    """Обработчик принимает @username или пересланное сообщение из канала."""
    try:
        user_id = message.from_user.id
        channel_username = None
        tg_chat_id = None
        tg_title = None

        if message.forward_origin:
            origin = message.forward_origin
            if hasattr(origin, 'chat'):
                chat = origin.chat
                tg_chat_id = str(chat.id)
                tg_title = chat.title or chat.username or tg_chat_id
                channel_username = f"@{chat.username}" if chat.username else tg_chat_id
                logger.info(f"Пользователь {user_id} переслал сообщение из канала {tg_chat_id}")
        else:
            channel_username = message.text.strip()
            if channel_username.startswith("/"):
                await message.answer("Пожалуйста, отправьте @username канала или перешлите сообщение из него.")
                return
            if not channel_username.startswith("@"):
                await message.answer(
                    "⚠️ Отправьте корректный @username (например, @mychannel) или перешлите любое сообщение из вашего канала."
                )
                return

            logger.info(f"Пользователь {user_id} пытается добавить канал {channel_username}")
            try:
                chat_info = await message.bot.get_chat(channel_username)
                tg_chat_id = str(chat_info.id)
                tg_title = chat_info.title or channel_username
            except Exception as e:
                logger.error(f"Ошибка получения информации о канале {channel_username}: {e}")
                await message.answer("❌ Не удалось получить информацию о канале. Проверьте правильность @username.")
                return

        chat_identifier = channel_username if channel_username else tg_chat_id
        is_admin_ok = await check_bot_admin(message.bot, tg_chat_id if tg_chat_id else chat_identifier)
        if not is_admin_ok:
            logger.warning(f"Бот не админ в канале {chat_identifier}")
            await message.answer(
                "❌ Бот не является администратором в этом канале. "
                "Добавьте бота в администраторы канала с правом публикации сообщений и попробуйте снова."
            )
            return

        conn = get_db()
        try:
            user = conn.execute("SELECT tariff_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if user and user["tariff_id"]:
                tariff = conn.execute("SELECT max_channels FROM tariffs WHERE id = ?", (user["tariff_id"],)).fetchone()
                max_channels = tariff["max_channels"] if tariff else 5
                current_count = conn.execute("SELECT COUNT(*) as cnt FROM channels WHERE user_id = ?", (user_id,)).fetchone()["cnt"]
                if current_count >= max_channels:
                    await message.answer(f"❌ Ваш тариф позволяет подключить не более {max_channels} каналов.")
                    return

            conn.execute(
                """INSERT INTO channels (user_id, channel_id, channel_title, sub_id)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, channel_id) DO UPDATE SET channel_title = excluded.channel_title""",
                (user_id, channel_username if channel_username else tg_chat_id, tg_title, tg_chat_id)
            )
            conn.commit()
            logger.info(f"Канал {chat_identifier} успешно добавлен для пользователя {user_id}")
        except sqlite3.Error as e:
            logger.error(f"Ошибка БД при добавлении канала: {e}")
            await message.answer("❌ Ошибка при добавлении канала в базу данных. Попробуйте позже.")
            return
        finally:
            conn.close()

        display_name = channel_username if channel_username else tg_title
        await message.answer(
            f"✅ Канал <b>{html.escape(display_name)}</b> успешно добавлен!",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_cabinet_menu("saas")
        )
        await state.clear()
        await show_user_cabinet(message, user_id=user_id)

    except Exception as e:
        logger.exception(f"Критическая ошибка при обработке добавления канала: {e}")
        await message.answer(
            "❌ Произошла внутренняя ошибка. Администратор уже уведомлён. Попробуйте позже или свяжитесь с поддержкой."
        )
        await state.clear()

# ---------------------------------------------------------------------------
# Обработчики инструкций и поддержки
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "support:contact")
async def cb_support_contact(callback: CallbackQuery):
    text = (
        "📞 <b>Связь с администратором</b>\n\n"
        "По любым вопросам, ошибкам, багам, предложениям и для оплаты пишите:\n"
        "👉 <a href='https://t.me/Zigih90'>@Zigih90</a>\n\n"
        "<i>Стараюсь отвечать быстро 😊</i>"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "menu:instructions")
async def cb_menu_instructions(callback: CallbackQuery) -> None:
    await show_saas_instruction(callback)
    await callback.answer()

async def show_saas_instruction(callback: CallbackQuery):
    text = (
        "📖 <b>Инструкция для SaaS-клиентов</b>\n\n"
        "<b>1. Подготовка</b>\n"
        "─ Бот автоматически получает товары из проверенных магазинов (Admitad).\n"
        "─ Вам не нужно вводить API-ключи.\n"
        "─ Оплатите подписку или активируйте промокод.\n\n"
        "<b>2. Подключение каналов</b>\n"
        "─ Перейдите в «📢 Мои каналы» и отправьте @username вашего канала.\n"
        "─ Для каждого канала автоматически создаётся уникальный идентификатор, который позволяет отслеживать продажи.\n\n"
        "<b>3. Выбор магазинов</b>\n"
        "─ Нажмите «🏪 Магазины» и отметьте интересующие вас магазины.\n"
        "─ От выбранных магазинов зависит, какие товары будут публиковаться.\n\n"
        "<b>4. Автоматический постинг и доход</b>\n"
        "─ Бот самостоятельно наполняет каталог товарами с маркировкой ERID.\n"
        "─ Посты выходят автоматически с партнёрскими ссылками, в которые встроен идентификатор вашего канала.\n"
        "─ Доход от продаж поступает владельцу бота, который раз в месяц переводит вам заработанную сумму за вычетом 5% комиссии.\n\n"
        "<b>5. Ночной режим и очередь</b>\n"
        "─ С 23:00 до 08:00 (МСК) посты сохраняются в очередь и выходят утром.\n\n"
        "<b>6. Авто-закреп</b>\n"
        "─ В настройках можно включить автоматическое закрепление постов.\n\n"
        "<b>7. Промокоды</b>\n"
        "─ Нажмите «🎁 Активировать промокод» и введите код.\n\n"
        "<i>По всем вопросам обращайтесь к администратору.</i>"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
        ])
    )

# ---------------------------------------------------------------------------
# Административные команды
# ---------------------------------------------------------------------------
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
        await message.answer(f"DEBUG:\nРоль: {user['role']}\nПодписка до: {user['subscription_until']}")
    else:
        await message.answer("Пользователь не найден в БД!")

@router.message(Command("fix_channels"))
async def fix_duplicate_channels(message: Message) -> None:
    conn = get_db()
    conn.execute("DELETE FROM channels WHERE id NOT IN (SELECT MIN(id) FROM channels GROUP BY user_id, channel_id)")
    conn.commit()
    conn.close()
    await message.answer("✅ Дубликаты каналов удалены.")

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

# ---------------------------------------------------------------------------
# Колбэк "cabinet:open" (из интерфейса)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "cabinet:open")
async def cb_open_cabinet(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except:
        pass
    await show_user_cabinet(callback.message, user_id=callback.from_user.id)
    await callback.answer()

# ---------------------------------------------------------------------------
# Планировщик и периодические задачи
# ---------------------------------------------------------------------------
async def run_billing_check(bot: Bot):
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        expired_users = conn.execute(
            "SELECT user_id FROM users WHERE role='saas' AND subscription_until < ? AND is_active=1",
            (now,)
        ).fetchall()
        for row in expired_users:
            user_id = row["user_id"]
            conn.execute("UPDATE users SET is_active=0 WHERE user_id=?", (user_id,))
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="⚠️ <b>Ваша подписка истекла!</b>\n\nБот приостановил работу с вашими каналами. Продлите подписку в /cabinet.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить об истечении подписки: {e}")
        conn.commit()
    finally:
        conn.close()

async def unpin_old_messages(bot: Bot):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        rows = conn.execute("SELECT chat_id, message_id FROM pinned_posts WHERE unpin_at <= ?", (now,)).fetchall()
        for row in rows:
            try:
                await bot.unpin_chat_message(chat_id=row["chat_id"], message_id=row["message_id"])
            except Exception:
                pass
            conn.execute("DELETE FROM pinned_posts WHERE chat_id=? AND message_id=?", (row["chat_id"], row["message_id"]))
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

async def daily_report(bot: Bot):
    import csv, os as _os, pathlib
    reports_dir = "/app/data/reports"
    pathlib.Path(reports_dir).mkdir(parents=True, exist_ok=True)

    conn = get_db()
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        rows = conn.execute("""
            SELECT c.channel_id, p.subid1, p.direct_link, p.published_at, c.channel_title
            FROM posts p
            JOIN channels c ON p.channel_id = c.channel_id AND p.user_id = c.user_id
            WHERE p.status = 'published' AND p.published_at >= ?
            ORDER BY p.published_at ASC
        """, (since,)).fetchall()
        active_channels = conn.execute(
            "SELECT COUNT(DISTINCT channel_id) FROM posts WHERE status='published' AND published_at >= ?",
            (since,)
        ).fetchone()[0] or 0
        total_posts = len(rows) if rows else 0
        new_tx = conn.execute(
            "SELECT COUNT(*) FROM admitad_transactions WHERE created_at >= ?",
            (since,)
        ).fetchone()[0] or 0
    finally:
        conn.close()

    date_str = datetime.now().strftime('%Y%m%d')
    filename = f"daily_posts_{date_str}.csv"
    filepath = _os.path.join(reports_dir, filename)

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Канал (ID)", "SubID", "Прямая ссылка на пост", "Время (UTC)", "Название канала"])
        for ch_id, subid, link, ts, title in rows:
            writer.writerow([ch_id, subid or "", link or "", ts or "", title or ""])

    caption = (
        f"📊 <b>Ежедневный отчёт</b>\n"
        f"📅 {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC\n\n"
        f"🟢 Активных каналов: <b>{active_channels}</b>\n"
        f"📬 Всего постов: <b>{total_posts}</b>\n"
        f"💰 Новых транзакций: <b>{new_tx}</b>\n\n"
        f"📎 Файл сохранён на сервере: <code>{filepath}</code>"
    )

    admin_id = ADMIN_IDS[0] if ADMIN_IDS else None
    if admin_id:
        try:
            from aiogram.types import FSInputFile
            doc = FSInputFile(filepath, filename=filename)
            await bot.send_document(admin_id, document=doc, caption=caption, parse_mode="HTML")
            logger.info(f"Ежедневный отчёт отправлен и сохранён как {filepath}")
        except Exception as e:
            logger.error(f"Ошибка отправки ежедневного отчёта: {e}")

async def send_subscription_reminders(bot: Bot):
    now_utc = datetime.now(timezone.utc)
    target_date = now_utc + timedelta(days=3)
    target_iso = target_date.strftime("%Y-%m-%d")
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT user_id FROM users
            WHERE role='saas'
            AND is_active=1
            AND subscription_until IS NOT NULL
            AND DATE(subscription_until) = ?
        """, (target_iso,)).fetchall()
        for row in rows:
            user_id = row["user_id"]
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="⏰ <b>Напоминание</b>\n\n"
                         "Ваша подписка истекает <b>через 3 дня</b>. "
                         "Чтобы не потерять доступ к авто-постингу, продлите подписку в /cabinet.",
                    parse_mode="HTML"
                )
                logger.info(f"Отправлено напоминание пользователю {user_id}")
            except Exception as e:
                logger.error(f"Не удалось отправить напоминание {user_id}: {e}")
    finally:
        conn.close()

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(run_billing_check, trigger="interval", hours=1, kwargs={"bot": bot}, id="billing_check", replace_existing=True)
    scheduler.add_job(unpin_old_messages, trigger="interval", minutes=30, kwargs={"bot": bot}, id="unpin_vip_posts", replace_existing=True)
    scheduler.add_job(cleanup_old_posts, trigger="cron", hour=3, minute=0, id="cleanup_old_posts", replace_existing=True)
    scheduler.add_job(backup_database_to_telegram, trigger="cron", hour=3, minute=0, kwargs={"bot": bot}, id="backup_database", replace_existing=True)
    scheduler.add_job(publish_from_catalog, trigger="interval", minutes=10, jitter=30, kwargs={"bot": bot}, id="publish_catalog", replace_existing=True)
    scheduler.add_job(refill_admitad_catalogs, trigger="interval", minutes=15, id="refill_admitad", replace_existing=True)
    scheduler.add_job(daily_report, trigger="cron", hour=9, minute=0, kwargs={"bot": bot}, id="daily_report", replace_existing=True)
    scheduler.add_job(send_subscription_reminders, trigger="cron", hour=10, minute=0, kwargs={"bot": bot}, id="subscription_reminders", replace_existing=True)
    scheduler.add_job(update_all_store_data_from_feed, trigger="cron", hour=4, minute=0, id="update_coupons_feed", replace_existing=True)
    return scheduler

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
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

    dp.include_router(router)           # основной
    dp.include_router(saas_router)      # саас (промокоды, магазины и т.д.)

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планировщик (APScheduler) запущен")

    # Установка команд
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="cabinet", description="Личный кабинет"),
            BotCommand(command="promo", description="Активировать промокод"),
        ],
        scope=BotCommandScopeDefault(),
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(
                commands=[
                    BotCommand(command="start", description="Панель администратора"),
                    BotCommand(command="cabinet", description="Панель администратора"),
                    BotCommand(command="debug_sub", description="Проверить подписку пользователя"),
                    BotCommand(command="force_trial", description="Выдать тестовые 3 дня"),
                    BotCommand(command="fix_channels", description="Удалить дубликаты каналов"),
                ],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except TelegramBadRequest as e:
            logger.warning(f"Не удалось установить команды для админа {admin_id}: {e}")

    fastapi_app = create_app(bot)

    config = uvicorn.Config(
        fastapi_app,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        log_level="warning"
    )
    server = uvicorn.Server(config)

    logger.info(f"🌐 Web Admin Panel доступен по адресу: http://{WEBAPP_HOST}:{WEBAPP_PORT}/admin")

    try:
        await asyncio.gather(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
            server.serve(),
            return_exceptions=True
        )
    finally:
        await bot.session.close()
        scheduler.shutdown()
        logger.info("Бот и планировщик остановлены")

async def backup_database_to_telegram(bot: Bot):
    db_path = DB_PATH
    if not os.path.exists(db_path):
        logger.error("Бэкап: файл базы данных не найден")
        return

    admin_id = ADMIN_IDS[0] if ADMIN_IDS else None
    if not admin_id:
        logger.error("Бэкап: не указан администратор")
        return

    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"autopost_backup_{timestamp}.db"
        db_file = FSInputFile(db_path, filename=filename)
        await bot.send_document(
            chat_id=admin_id,
            document=db_file,
            caption=f"📦 Ежедневный бэкап базы данных ({timestamp})"
        )
        logger.info("Бэкап базы данных отправлен администратору")
    except Exception as e:
        logger.error(f"Ошибка при отправке бэкапа: {e}")

if __name__ == "__main__":
    asyncio.run(main())
