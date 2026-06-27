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
from admin_panel import create_fastapi_app
import sys
from keyboards.saas import kb_cabinet_menu, kb_tariffs, kb_payment_methods
from handlers.saas import router as saas_router
from services.admitad import refill_admitad_catalogs
print("DEBUG: main.py started", flush=True, file=sys.stderr)

import httpx
import uvicorn
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
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
from config import (
    settings, MIN_PAYOUT, PAYOUT_FIXED_FEE, PAYOUT_BANK_PCT, MAX_ACTIVE_PAYOUTS,
    is_night_time, load_tariffs,
    BOT_TOKEN, ADMIN_IDS, WEBAPP_ADMIN_URL, QUARANTINE_CHAT_ID,
    DEEPINFRA_API_KEY, STARS_PROVIDER_TOKEN, WEBAPP_HOST, WEBAPP_PORT,
    CARD_SBER, CARD_TBANK, CARD_TON, CARD_VISA_KG, DB_PATH
)
from services.saas_core import (
    publish_post_with_fallback,
    publish_from_catalog
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from states import OnboardingStates, SaasStates, AdminStates, PaymentFSM, PayoutStates
from stats import get_blogger_stats, get_saas_channels, get_saas_channel_stats, get_saas_overview, STAT_PERIODS
print("DEBUG: all imports done", flush=True, file=sys.stderr)

from services.db import get_db

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
# Уникальный индекс для предотвращения дубликатов
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_gdeslon_unique 
            ON gdeslon_catalog(user_id, sku)
    """)
    # Миграции
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN payout_card TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN target_channel_id TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN channel_id TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE channels ADD COLUMN max_posts_per_day INTEGER DEFAULT 25")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE tariffs ADD COLUMN max_channels INTEGER DEFAULT 5")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE tariffs ADD COLUMN max_posts_per_day INTEGER DEFAULT 25")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE tariffs ADD COLUMN max_categories INTEGER DEFAULT 3")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE tariffs ADD COLUMN min_cashback REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE tariffs ADD COLUMN max_cashback REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN tariff_id INTEGER")
    except sqlite3.OperationalError:
        pass
    # Миграция: добавляем колонку source для gdeslon_catalog
    try:
        cursor.execute("ALTER TABLE gdeslon_catalog ADD COLUMN source TEXT DEFAULT 'gdeslon'")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE channels ADD COLUMN sub_id TEXT")
    except sqlite3.OperationalError:
        pass 
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN subid1 TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN direct_link TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN balance_pending REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN balance_available REAL DEFAULT 0.0")
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
# =============================================================================


def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть Web-админку", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))],
        [InlineKeyboardButton(text="📣 Рассылка всем", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="💰 Запустить биллинг-чек", callback_data="admin:billing_check")],
        [InlineKeyboardButton(text="🔧 Продлить подписку", callback_data="admin:extend_sub")],
    ])



def kb_filter_settings(wb: int, ozon: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅' if wb else '❌'} Wildberries", callback_data="filter:toggle:wb"
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if ozon else '❌'} Ozon", callback_data="filter:toggle:ozon"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")],
    ])



# =============================================================================
# === НОВЫЕ SAAS-ФУНКЦИИ ======================================================
# =============================================================================


async def _send_to_quarantine(
    bot: Bot, user_id: int, donor_post_id: str, channel_id: str, reason: str
) -> None:
    """Блокирует публикацию и уведомляет карантинный чат."""
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


# =============================================================================
# === SAAS-ФУНКЦИИ (НОВЫЕ) ====================================================
# =============================================================================



# =============================================================================
# === ROUTER & HANDLERS =======================================================
# =============================================================================
print("DEBUG: creating router", flush=True, file=sys.stderr)
router = Router()

# ---------------------------------------------------------------------------
# /start
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
        promo = conn.execute("SELECT * FROM promocodes WHERE code = ?", (code,)).fetchone()
        if not promo:
            await message.answer("❌ Неверный или несуществующий промокод.")
            return

        activation = conn.execute("SELECT * FROM promocode_activations WHERE code = ?", (code,)).fetchone()
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

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("👋 Добро пожаловать в Панель администратора.", reply_markup=kb_admin_panel())
        return

    conn = get_db()
    try:
        user = conn.execute("SELECT role, channel_id FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
        if not user:
            sub_id = generate_sub_id(message.from_user.username, message.from_user.id)
            conn.execute(
                "INSERT INTO users (user_id, username, sub_id, role) VALUES (?, ?, ?, 'blogger')",
                (message.from_user.id, message.from_user.username, sub_id)
            )
            conn.commit()
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👤 Я блогер", callback_data="role:blogger")],
                [InlineKeyboardButton(text="🏢 Я SaaS-клиент", callback_data="role:saas")]
            ])
            await message.answer("👋 Добро пожаловать! Выберите вашу роль:", reply_markup=kb)
            await state.set_state(OnboardingStates.waiting_role)
        elif user["role"] == "blogger" and not user["channel_id"]:
            await message.answer(
                "⚠️ Вы ещё не привязали свой канал.\nПерешлите сообщение из канала или отправьте @username.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📢 Привязать канал", callback_data="menu:channel")]
                ])
            )
            await state.set_state(OnboardingStates.waiting_channel)
    finally:
        conn.close()
# ---------------------------------------------------------------------------
# /cabinet, "💻 Личный кабинет"
# ---------------------------------------------------------------------------
async def show_user_cabinet(message: Message, user_id: int = None):
    if user_id is None:
        user_id = message.from_user.id
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT role, subscription_until, username FROM users WHERE user_id=?",
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

    text = (
        f"💼 <b>Личный кабинет</b>\n\n"
        f"👤 Роль: <b>{role.upper()}</b>\n"
        f"📅 Статус подписки: {status_text}\n"
        f"🆔 ID: <code>{user_id}</code>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb_cabinet_menu(role))
@router.message(Command("cabinet"))
async def cmd_cabinet(message: Message):
    await show_user_cabinet(message, user_id=message.from_user.id)
# ---------------------------------------------------------------------------
# Обработка роли
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("set_role:"))
async def cb_set_role(callback: CallbackQuery, state: FSMContext):
    # Всегда назначаем SaaS
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET role=? WHERE user_id=?", ("saas", user_id))
        conn.commit()
    finally:
        conn.close()
    await state.set_state(OnboardingStates.waiting_saas_tg_channel)
    await callback.message.edit_text(
        "✅ Выбрана роль: <b>SaaS-клиент</b>.\n\nПришлите @username вашего Telegram-канала.",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Главное меню
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
    if role == "saas":
        await show_user_cabinet(callback.message, user_id=callback.from_user.id)
    else:
        # Для блогера показываем хотя бы какую-то клавиатуру
        await callback.message.answer("Главное меню:", reply_markup=kb_cabinet_menu(role))

@router.callback_query(F.data == "menu:my_channels")
async def cb_my_channels(callback: CallbackQuery) -> None:
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
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("channel_delete:"))
async def cb_delete_channel(callback: CallbackQuery) -> None:
    channel_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    conn = get_db()
    try:
        # Удаляем канал из БД по его внутреннему id и user_id
        conn.execute("DELETE FROM channels WHERE id=? AND user_id=?", (channel_id, user_id))
        conn.commit()
    finally:
        conn.close()

    await callback.answer("🗑 Канал удалён.", show_alert=True)
    # Перерисовываем список каналов
    await cb_my_channels(callback)
# ---------------------------------------------------------------------------
# Обработчики подписок / оплат и выплат (все остальные хендлеры из исходника
# оставляем идентичными, так как они не затрагивают новую логику SaaS)
# ---------------------------------------------------------------------------
# Здесь должны быть:
#   - обработчики для /debug_scan, /force_trial, /fix_channels
#   - все коллбэки кабинета: menu:stats, menu:channel, menu:tariffs и т.д.
#   - настройки SaaS: saas_toggle, saas_set:apikey, saas_force_post
#   - выплаты и расчёт выплат
#   - обработка ролей и добавление каналов
#   - админские коллбэки
#   - FastAPI админка и шедулер (будут добавлены отдельными шагами)

# ---------------------------------------------------------------------------
# Скелет обработчиков для переноса (вставь свои старые функции сюда)
# ---------------------------------------------------------------------------
# ... (перенеси их из твоего исходного main.py, они не менялись)

# =============================================================================
# === ОБРАБОТЧИКИ: СТАТИСТИКА =================================================
# =============================================================================
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

async def _show_saas_stats(callback: CallbackQuery, user_id: int, channel_idx: int = 0, period: str = "30d") -> None:
    channels = get_saas_channels(user_id)
    if not channels:
        # Показываем общую статистику без каналов
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
        await callback.answer()
        return

    channel_idx = max(0, min(channel_idx, len(channels) - 1))
    ch = channels[channel_idx]
    s = get_saas_channel_stats(user_id, ch["channel_id"], period)
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

    # Кнопки навигации
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
    await callback.answer()

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

@router.pre_checkout_query()
async def process_pre_checkout_query(query: PreCheckoutQuery):
    """Подтверждаем возможность оплаты."""
    await query.answer(ok=True)

@router.message(SuccessfulPayment)
async def process_successful_payment(message: Message):
    """Активация подписки после успешной оплаты звёздами."""
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
        # Проверяем тариф
        tariff = conn.execute("SELECT days FROM tariffs WHERE id=?", (tariff_id,)).fetchone()
        if not tariff:
            await message.answer("❌ Тариф не найден. Обратитесь к администратору.")
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
        f"Тариф: {tariff['name'] if tariff else '—'}\n"
        f"Действует до: {new_until.strftime('%d.%m.%Y %H:%M')} (UTC)\n\n"
        f"Спасибо за покупку!",
        parse_mode=ParseMode.HTML
    )  


# =============================================================================
# === ОБРАБОТЧИКИ КАНАЛОВ (БЛОГЕР) ============================================
# =============================================================================
@router.callback_query(F.data == "menu:channel")
async def cb_menu_channel(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        row = conn.execute("SELECT channel_title, channel_id FROM users WHERE user_id=?", (user_id,)).fetchone()
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
            ])
        )
    else:
        await callback.message.edit_text(
            "📢 <b>Привязка канала</b>\n\n"
            "Перешли сюда любое сообщение из твоего канала или отправь <code>@username</code>.\n\n"
            "<i>Убедись, что бот добавлен в канал как администратор с правом публикации.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")]
            ])
        )
        await state.set_state(OnboardingStates.waiting_channel)
    await callback.answer()

@router.callback_query(F.data == "channel:change")
async def cb_change_channel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "📢 <b>Смена канала</b>\n\n"
        "Перешли сообщение из нового канала или отправь <code>@username</code>.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="menu:main")]
        ])
    )
    await state.set_state(OnboardingStates.waiting_channel)
    await callback.answer()

@router.message(OnboardingStates.waiting_channel)
async def handle_channel_input(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    channel_id: Optional[str] = None
    channel_title: Optional[str] = None

    # Пропускаем команды
    if message.text and message.text.startswith("/"):
        return

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
    except Exception as e:
        logger.error(f"Ошибка сохранения канала: {e}")
        await message.answer("Ошибка при сохранении данных.")
        return
    finally:
        conn.close()

    await state.clear()
    await message.answer(
        f"✅ <b>Канал успешно привязан:</b> {html.escape(channel_title or channel_id)}\n\n"
        "Теперь вы можете полноценно пользоваться ботом.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_cabinet_menu(role)
    )

# =============================================================================
# === РЕЖИМ ПУБЛИКАЦИИ (БЛОГЕР) ===============================================
# =============================================================================


# =============================================================================
# === ПАРТНЁРСКАЯ ПРОГРАММА ===================================================
# =============================================================================
@router.callback_query(F.data == "menu:partner")
async def cb_partner_program(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute("SELECT sub_id FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
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

# =============================================================================
# === НАСТРОЙКИ (ФИЛЬТРЫ WB/OZON) =============================================
# =============================================================================

@router.callback_query(F.data.startswith("saas_toggle:"))
async def cb_saas_toggles(callback: CallbackQuery) -> None:
    action = callback.data.split(":")[1]
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT auto_pin, filter_wb, filter_ozon FROM users WHERE user_id=?", (user_id,)).fetchone()
        if action == "autopin":
            new_val = 0 if user["auto_pin"] else 1
            conn.execute("UPDATE users SET auto_pin=? WHERE user_id=?", (new_val, user_id))
        elif action == "wb":
            new_val = 0 if user["filter_wb"] else 1
            conn.execute("UPDATE users SET filter_wb=? WHERE user_id=?", (new_val, user_id))
        elif action == "ozon":
            new_val = 0 if user["filter_ozon"] else 1
            conn.execute("UPDATE users SET filter_ozon=? WHERE user_id=?", (new_val, user_id))
        conn.commit()
    finally:
        conn.close()
    await open_saas_settings(callback)

# =============================================================================
# === ВЫПЛАТЫ =================================================================
# =============================================================================
def calc_payout(amount_blogger: float) -> dict:
    amount_to_withdraw = (amount_blogger * 2 + PAYOUT_FIXED_FEE) / (1 - PAYOUT_BANK_PCT)
    return {
        "amount_requested": amount_blogger,
        "amount_to_withdraw": round(amount_to_withdraw, 2),
        "amount_blogger": round(amount_blogger, 2),
    }


@router.callback_query(F.data == "payout:request")
async def cb_payout_request(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT payout_card FROM users WHERE user_id=?", (user_id,)).fetchone()
        active = conn.execute("SELECT COUNT(*) as cnt FROM payouts WHERE user_id=? AND status='pending'", (user_id,)).fetchone()
    finally:
        conn.close()

    if active["cnt"] >= MAX_ACTIVE_PAYOUTS:
        await callback.answer(f"❌ У вас уже {MAX_ACTIVE_PAYOUTS} активные заявки.", show_alert=True)
        return

    card = user["payout_card"] if user else None
    if card:
        await callback.message.edit_text(
            f"💳 <b>Запрос выплаты</b>\n\n"
            f"Текущая карта: <code>{card}</code>\n\n"
            f"Минимальная сумма: <b>{MIN_PAYOUT:.0f} ₽</b>\n"
            f"Введите сумму или смените карту:",
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
            "Введите номер карты РФ для получения выплаты:",
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
        conn.execute("UPDATE users SET payout_card=? WHERE user_id=?", (formatted, message.from_user.id))
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
        user = conn.execute("SELECT payout_card, sub_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        balance_row = conn.execute("""
            SELECT COALESCE(SUM(payout), 0.0) as total
            FROM transactions
            WHERE sub_id=? AND status IN ('approved', 'paid')
        """, (user["sub_id"],)).fetchone()
        withdrawn_row = conn.execute("""
            SELECT COALESCE(SUM(amount_blogger), 0.0) as total
            FROM payouts
            WHERE user_id=? AND status IN ('pending', 'completed')
        """, (user_id,)).fetchone()
        available = (float(balance_row["total"]) - float(withdrawn_row["total"])) / 2
    finally:
        conn.close()

    if amount > available:
        await message.answer(f"❌ Недостаточно средств.\nДоступно: <b>{available:.2f} ₽</b>", parse_mode=ParseMode.HTML)
        return

    calc = calc_payout(amount)
    card = user["payout_card"]
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
    await message.answer(
        f"✅ <b>Заявка принята, ожидайте!</b>\n\n"
        f"💰 Сумма к получению: <b>{calc['amount_blogger']:.2f} ₽</b>\n"
        f"💳 На карту: <code>{card}</code>\n\n"
        f"<i>Выплата производится в течение суток.</i>",
        parse_mode=ParseMode.HTML
    )
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"💸 <b>Новая заявка на выплату #{payout_id}</b>\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"💳 Карта: <code>{card}</code>\n\n"
                f"📤 Вывести из Такпродам: <b>{calc['amount_to_withdraw']:.2f} ₽</b>\n"
                f"💰 Отправить блогеру: <b>{calc['amount_blogger']:.2f} ₽</b>\n"
                f"💰 Ваша доля: <b>{calc['amount_blogger']:.2f} ₽</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Отправлено", callback_data=f"payout:done:{payout_id}:{user_id}")]
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
        conn.execute("UPDATE payouts SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (payout_id,))
        conn.commit()
        payout = conn.execute("SELECT amount_blogger, card FROM payouts WHERE id=?", (payout_id,)).fetchone()
    finally:
        conn.close()
    try:
        await callback.bot.send_message(
            blogger_id,
            f"✅ <b>Выплата отправлена!</b>\n\n"
            f"💰 Сумма: <b>{payout['amount_blogger']:.2f} ₽</b>\n"
            f"💳 На карту: <code>{payout['card']}</code>\n\n"
            f"<i>Если деньги не пришли в течение суток — напишите в поддержку.</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить блогера {blogger_id}: {e}")
    await callback.message.edit_text(callback.message.text + f"\n\n✅ <b>Выплачено</b>", parse_mode=ParseMode.HTML)
    await callback.answer("✅ Выплата подтверждена")

  # =============================================================================
# === АДМИНСКИЕ КОЛЛБЭКИ ======================================================
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


# =============================================================================
# === ОНБОРДИНГ: SAAS – ДОБАВЛЕНИЕ КАНАЛА =====================================
# =============================================================================
@router.message(OnboardingStates.waiting_saas_tg_channel)
async def handle_saas_channel_addition(message: Message, state: FSMContext) -> None:
    channel_username = message.text.strip()

    # Пропускаем команды
    if channel_username.startswith("/"):
        return

    if not channel_username.startswith("@"):
        await message.answer("⚠️ Для добавления канала отправьте @username.")
        return

    user_id = message.from_user.id

    is_admin_ok = await check_bot_admin(message.bot, channel_username)
    if not is_admin_ok:
        await message.answer("❌ Бот не является администратором в этом канале.")
        return

    conn = get_db()
    try:
        # Проверка лимита каналов
        user = conn.execute("SELECT tariff_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user and user["tariff_id"]:
            tariff = conn.execute("SELECT max_channels FROM tariffs WHERE id = ?", (user["tariff_id"],)).fetchone()
            max_channels = tariff["max_channels"] if tariff else 5
            current_count = conn.execute("SELECT COUNT(*) as cnt FROM channels WHERE user_id = ?", (user_id,)).fetchone()["cnt"]
            if current_count >= max_channels:
                await message.answer(f"❌ Ваш тариф позволяет подключить не более {max_channels} каналов.")
                return

        # Генерируем уникальный sub_id (на основе user_id и channel_username)
        # Получаем числовой ID канала Telegram (неизменяемый)
        try:
            chat_info = await message.bot.get_chat(channel_username)
            tg_chat_id = str(chat_info.id)          # например, "-1001234567890"
            tg_title = chat_info.title or channel_username
        except Exception:
            await message.answer("❌ Не удалось получить информацию о канале. Проверьте правильность @username.")
            return

        # sub_id теперь числовой ID канала
        sub_id = tg_chat_id

        conn.execute(
            """INSERT INTO channels (user_id, channel_id, channel_title, sub_id)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, channel_id) DO UPDATE SET channel_title = excluded.channel_title""",
            (user_id, channel_username, tg_title, sub_id)
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка добавления канала: {e}")
    finally:
        conn.close()

    await message.answer(
        f"✅ Канал <b>{html.escape(channel_username)}</b> успешно добавлен!",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_cabinet_menu("saas")
    )
    await state.clear()


# =============================================================================
# === НАСТРОЙКИ ДЛЯ БЛОГЕРА (ФИЛЬТРЫ WB/OZON) =================================
# =============================================================================
@router.callback_query(F.data == "menu:settings")
async def cb_menu_settings(callback: CallbackQuery) -> None:
    """Обработчик кнопки 'Настройки' – определяет роль и показывает нужное меню."""
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT role, filter_wb, filter_ozon FROM users WHERE user_id=?", (user_id,)).fetchone()
    finally:
        conn.close()

    if not user:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    if user["role"] == "saas":
        await open_saas_settings(callback)
    else:
        # Блогерские настройки – фильтры
        wb = user["filter_wb"]
        ozon = user["filter_ozon"]
        try:
            await callback.message.edit_text(
                "⚙️ <b>Настройки</b>\n\nВыберите какие магазины включить в автопостинг:",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_filter_settings(wb, ozon)
            )
        except TelegramBadRequest:
            pass
        await callback.answer()

async def open_saas_settings(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT api_key, auto_pin, filter_wb, filter_ozon FROM users WHERE user_id=?", (user_id,)).fetchone()
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
    await callback.answer()

@router.callback_query(F.data.startswith("filter:toggle:"))
async def cb_filter_toggle(callback: CallbackQuery) -> None:
    """Переключение фильтра WB/Ozon (для блогера)."""
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

# =============================================================================
# === ГЛУБОКАЯ ССЫЛКА (РЕФЕРАЛЬНАЯ СИСТЕМА) ===================================
# =============================================================================
@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, state: FSMContext, command: CommandStart):
    """Обработка /start с параметром (например, aff_XXXX)."""
    await state.clear()
    args = command.args
    if args and args.startswith("aff_"):
        # Реферальная ссылка: просто регистрируем как обычно, но сохраняем реферера
        # При необходимости можно записать в поле пригласившего (в БД нет такого поля, упростим)
        await message.answer("🤝 Вы перешли по реферальной ссылке. Добро пожаловать!")
    # Далее стандартная логика
    await cmd_start(message, state) 

@router.callback_query(F.data == "cabinet:open")
async def cb_open_cabinet(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except:
        pass

    await show_user_cabinet(callback.message, user_id=callback.from_user.id)
    await callback.answer()

# =============================================================================
# === ПЛАНИРОВЩИК И ВСПОМОГАТЕЛЬНЫЕ ПЕРИОДИЧЕСКИЕ ФУНКЦИИ =====================
# =============================================================================

async def run_billing_check(bot: Bot):
    """Ежечасная проверка истекших подписок SaaS-пользователей."""
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

      # =============================================================================
# === ОБРАБОТЧИКИ ИНСТРУКЦИЙ ==================================================
# =============================================================================
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
    """Показывает инструкцию в зависимости от роли пользователя."""
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
        role = user["role"] if user else "blogger"
    finally:
        conn.close()

    if role == "saas":
        await show_saas_instruction(callback)
    else:
        await show_blogger_instruction(callback)
    await callback.answer()

async def show_blogger_instruction(callback: CallbackQuery):
    text = (
        "📖 <b>Инструкция для блогеров</b>\n\n"
        "<b>1. Привязка канала</b>\n"
        "─ Перейди в «📢 Мой канал» и отправь @username своего Telegram-канала или перешли любое сообщение из него.\n"
        "─ Бот проверит права и запомнит канал.\n\n"
        "<b>2. Отправка видео</b>\n"
        "─ Нажми «🎥 Отправить видео» в главном меню.\n"
        "─ Пришли ссылку на видео из YouTube, TikTok или Instagram.\n"
        "─ Бот найдёт в описании артикулы товаров (SKU) Wildberries и Ozon.\n"
        "─ Если точный товар найден в партнёрской программе — ты получишь готовый пост с маркировкой (ERID), ценой и ссылкой.\n"
        "─ Если точного товара нет — бот подберёт <b>похожий товар</b> по ключевым словам из видео, чтобы ты не остался без заработка.\n\n"
        "<b>3. Режимы публикации</b>\n"
        "─ В разделе «⚙️ Режим публикации» можно выбрать:\n"
        "   • «Напрямую в мой канал» — пост придёт в твой Telegram-канал.\n"
        "   • «VIP-закреп в главном канале (24ч)» — пост отправится в VIP-канал и будет закреплён на 24 часа.\n\n"
        "<b>4. Ночной режим</b>\n"
        "─ С 23:00 до 08:00 (МСК) посты не публикуются сразу, а попадают в очередь. Они будут автоматически отправлены утром в 08:00.\n\n"
        "<b>5. Заработок и выплаты</b>\n"
        "─ Заработок отображается в «📊 Статистика».\n"
        "─ Когда накопится минимум 2000 ₽, появится кнопка «Запросить выплату».\n"
        "─ Выплаты обрабатываются администратором вручную.\n\n"
        "<b>6. Настройки</b>\n"
        "─ В «⚙️ Настройки» можно включить/отключить фильтры по Wildberries и Ozon.\n\n"
        "<i>По всем вопросам обращайся к администратору.</i>"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")]
        ])
    )

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

# =============================================================================
# === ОБРАБОТЧИКИ ТАРИФОВ И ОПЛАТЫ ===========================================
# =============================================================================
def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(run_billing_check, trigger="interval", hours=1, kwargs={"bot": bot}, id="billing_check", replace_existing=True)
    scheduler.add_job(unpin_old_messages, trigger="interval", minutes=30, kwargs={"bot": bot}, id="unpin_vip_posts", replace_existing=True)
    scheduler.add_job(cleanup_old_posts, trigger="cron", hour=3, minute=0, id="cleanup_old_posts", replace_existing=True)
    scheduler.add_job(backup_database_to_telegram, trigger="cron", hour=3, minute=0, kwargs={"bot": bot}, id="backup_database", replace_existing=True)
    scheduler.add_job(publish_from_catalog, trigger="interval", minutes=10, kwargs={"bot": bot}, id="publish_catalog", replace_existing=True)
    scheduler.add_job(refill_admitad_catalogs, trigger="interval", minutes=15, id="refill_admitad", replace_existing=True)
    return scheduler

# =============================================================================
# === MAIN ====================================================================
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

# Сначала общий, потом специализированный
    dp.include_router(router)           # основной
    dp.include_router(saas_router)      # саас (промокоды, магазины и т.д.)

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планировщик (APScheduler) запущен")

    # ---------- Установка команд ----------
    # Обычные пользователи
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="cabinet", description="Личный кабинет"),
            BotCommand(command="promo", description="Активировать промокод"),
        ],
        scope=BotCommandScopeDefault(),
    )

    # Администраторы (каждого отдельно, с защитой)
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
    # ---------- Конец команд ----------

    fastapi_app = create_fastapi_app(bot)

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
    """Отправляет копию базы данных администратору (первому из списка)."""
    db_path = DB_PATH  # "/app/data/autopost.db"
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
