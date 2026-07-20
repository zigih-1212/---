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
import xlsxwriter
from aiogram.types import FSInputFile
from aiogram.filters import Command, CommandStart
from datetime import datetime
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any, List
from webapp import create_app
from webapp.routes_user import collect_views_for_user
import sys
from handlers.saas import router as saas_router
from services.admitad import refill_admitad_catalogs, update_all_store_data_from_feed
from webapp.auth import generate_admin_token, generate_user_token
from config import (
    settings, MIN_PAYOUT, PAYOUT_FIXED_FEE, PAYOUT_BANK_PCT,
    is_night_time,
    BOT_TOKEN, ADMIN_IDS, WEBAPP_ADMIN_URL, WEBAPP_BASE_URL, QUARANTINE_CHAT_ID,
    DEEPINFRA_API_KEY, WEBAPP_HOST, WEBAPP_PORT, DB_PATH
)
from services.saas_core import (
    publish_post_with_fallback,
    publish_from_catalog
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, Request, HTTPException
from states import OnboardingStates, SaasStates, AdminStates, PaymentFSM, PayoutStates, BloggerStates
from stats import get_saas_channels, get_saas_channel_stats_new, get_saas_overview, STAT_PERIODS
from services.db import get_db
from config import BOT_USERNAME
from states import TaxStates 
from keyboards.saas import kb_cabinet_menu
from helpers import check_rss_and_publish, generate_success_text, collect_views_for_user
from utils.feature_flags import (
    is_feature_enabled,
    can_use_beta_commands,
    add_beta_tester,
    remove_beta_tester,
    get_beta_testers,
)
from io import BytesIO
from aiogram.types import BufferedInputFile
from helpers import is_admin, get_block_reason
from helpers import show_user_cabinet, open_saas_settings, safe_edit

logger = logging.getLogger("autopost_bot.referral")
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
            # НЕ перевыбрасываем исключение — один сбойный хендлер не должен валить весь бот
            return


# =============================================================================
# === ИНИЦИАЛИЗАЦИЯ БД ========================================================
# =============================================================================
def init_db() -> None:
    print("DEBUG: init_db done, starting bot...", flush=True, file=sys.stderr)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
  
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
            notify_posts INTEGER DEFAULT 1,
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
        CREATE TABLE IF NOT EXISTS payout_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
        CREATE TABLE IF NOT EXISTS features (
            name TEXT PRIMARY KEY,
            status TEXT DEFAULT 'dev' CHECK(status IN ('dev', 'beta', 'released')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_gdeslon_unique 
            ON gdeslon_catalog(user_id, sku)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS social_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            channel_url TEXT,
            last_video_id TEXT,
            is_active INTEGER DEFAULT 1,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    conn.commit()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subid_stats (
            subid1 TEXT PRIMARY KEY,
            clicks_count INTEGER DEFAULT 0,
            leads_count INTEGER DEFAULT 0,
            earnings_pending REAL DEFAULT 0.0,
            earnings_approved REAL DEFAULT 0.0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER NOT NULL,
            referral_id INTEGER NOT NULL,
            total_brought_profit REAL DEFAULT 0.0,
            PRIMARY KEY (referrer_id, referral_id),
            FOREIGN KEY(referrer_id) REFERENCES users(user_id),
            FOREIGN KEY(referral_id) REFERENCES users(user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payout_chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            sender_role TEXT NOT NULL CHECK(sender_role IN ('user','admin')),
            message TEXT,
            file_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(request_id) REFERENCES payout_requests(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_consents (
            user_id INTEGER PRIMARY KEY,
            consent_given INTEGER DEFAULT 0,
            consent_timestamp TIMESTAMP,
            policy_version TEXT
        )
    """)  
    conn.commit()  
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
        "ALTER TABLE user_category_preferences ADD COLUMN city TEXT",
    ]
    for mig in migrations:
        try:
            cursor.execute(mig)
        except sqlite3.OperationalError:
            pass

    # Дополнительные миграции (каждая в своём try/except)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN post_interval_minutes INTEGER DEFAULT 60")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN commission_rate REAL DEFAULT 0.95")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN product_template TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN video_template TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN template_preview_data TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN force_preview_confirmed INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN payout_notified INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN tax_status TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE payout_requests ADD COLUMN receipt_photo TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE subid_stats ADD COLUMN leads_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE subid_stats ADD COLUMN earnings_pending REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE subid_stats ADD COLUMN earnings_approved REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN caption TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    # Новые миграции для выплат (напоминания о чеке)
    try:
        cursor.execute("ALTER TABLE payout_requests ADD COLUMN sent_at TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE payout_requests ADD COLUMN receipt_reminded INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # В функции init_db() после создания таблицы posts добавить миграцию:
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN views_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN subid2 TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE admitad_transactions ADD COLUMN decline_reason TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN erid TEXT")
    except sqlite3.OperationalError:
        pass      
    # Добавляем колонку beta_tester для управления доступом к новым функциям
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN beta_tester INTEGER DEFAULT 0")
        logger.info("✅ Колонка beta_tester добавлена")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e):
            logger.warning(f"⚠️ Не удалось добавить beta_tester: {e}")
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN notify_posts INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE posts ADD COLUMN auto_delete_hours INTEGER DEFAULT 168")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN default_auto_delete_hours INTEGER DEFAULT 168")
    except sqlite3.OperationalError:
        pass
    conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cyclic_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            interval_days INTEGER DEFAULT 1,
            last_posted_at TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, store_id),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    conn.commit()
    
    # Инициализация фич (если их нет в БД)
    try:
        features_to_init = [
            ("preview_post", "beta"),
            ("my_posts_gallery", "dev"),
            ("instructions", "released"),
            ("announcements", "dev"),
            ("admin_analytics", "released"),
            ("smart_rotation", "dev"),
            ("ab_testing", "dev"),
            ("pwa", "dev"),
            ("debug_mode", "dev"),
            ("achievements", "dev"),
        ]
        
        for feature_name, default_status in features_to_init:
            existing = cursor.execute(
                "SELECT name FROM features WHERE name = ?", 
                (feature_name,)
            ).fetchone()
            if not existing:
                cursor.execute(
                    "INSERT INTO features (name, status) VALUES (?, ?)",
                    (feature_name, default_status),
                )
                logger.info(f"✅ Фича '{feature_name}' инициализирована со статусом '{default_status}'")
        conn.commit()
    except Exception as e:
        logger.warning(f"⚠️ Ошибка инициализации фич: {e}")
    
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

def generate_sub_id(username: str, user_id: int, role: str = "blogger") -> str:
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
    prefix = "saas_" if role == "saas" else "blogger_"
    return f"{prefix}{result}_uid{user_id}"


def generate_subid2(user_id: int, channel_id: str) -> str:
    """Генерирует уникальный subid2 для связки пользователь-канал."""
    clean_channel = channel_id.lstrip("@").replace(" ", "_")
    return f"u{user_id}_ch_{clean_channel[:20]}"
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

@router.callback_query(F.data == "blogger:post_interval")
async def cb_blogger_post_interval(callback: CallbackQuery, state: FSMContext):
    # Показываем текущий интервал (или по умолчанию 60 минут)
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT post_interval_minutes FROM users WHERE user_id = ?", (user_id,)).fetchone()
        interval = user["post_interval_minutes"] if user and user["post_interval_minutes"] else 60
    finally:
        conn.close()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕐 1 пост в час", callback_data="blogger_set_interval:60")],
        [InlineKeyboardButton(text="🕐 2 поста в час", callback_data="blogger_set_interval:30")],
        [InlineKeyboardButton(text="🕐 4 поста в час", callback_data="blogger_set_interval:15")],
        [InlineKeyboardButton(text="🕐 6 постов в час", callback_data="blogger_set_interval:10")],
        [InlineKeyboardButton(text="✏️ Свой интервал", callback_data="blogger_custom_interval")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")],
    ])
    await safe_edit(callback.message, f"⚙️ <b>Периодичность постов</b>\n\n"
        f"Сейчас: <b>{interval} минут</b>\n\n"
        "Выберите частоту публикаций:",
        reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data == "privacy:accept")
async def cb_privacy_accept(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO user_consents 
               (user_id, consent_given, consent_timestamp, policy_version) 
               VALUES (?, 1, ?, '2026-07-20')""",
            (user_id, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
    finally:
        conn.close()
    await safe_edit(callback.message, "✅ Спасибо! Теперь вы можете пользоваться ботом.")
    await show_user_cabinet(callback.message, user_id=user_id)
    await callback.answer()

@router.callback_query(F.data == "privacy:decline")
async def cb_privacy_decline(callback: CallbackQuery):
    await safe_edit(callback.message,
        "❌ Без согласия на обработку данных бот не может работать.\n"
        "Если передумаете — напишите /start."
    )
    await callback.answer()

@router.callback_query(F.data == "blogger_custom_interval")
async def cb_blogger_custom_interval(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")]
    ])
    await callback.message.answer(
        "✏️ Введите интервал в минутах (минимум 5):",
        reply_markup=kb
    )
    await state.set_state(BloggerStates.waiting_post_interval)
    await callback.answer()

@router.callback_query(F.data.startswith("blogger_set_interval:"))
async def cb_blogger_set_interval(callback: CallbackQuery):
    minutes = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET post_interval_minutes = ? WHERE user_id = ?", (minutes, user_id))
        conn.commit()
    finally:
        conn.close()
    await callback.answer(f"✅ Интервал установлен: {minutes} минут", show_alert=True)
    await cb_blogger_post_interval(callback)

@router.message(BloggerStates.waiting_post_interval)
async def process_blogger_interval_input(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    if text in ("отмена", "отмен", "cancel", "назад"):
        await state.clear()
        await show_user_cabinet(message, user_id=message.from_user.id)
        return
    try:
        minutes = int(text)
        if minutes < 5:
            await message.answer("❌ Минимальный интервал — 5 минут.")
            return
        user_id = message.from_user.id
        conn = get_db()
        try:
            conn.execute("UPDATE users SET post_interval_minutes = ? WHERE user_id = ?", (minutes, user_id))
            conn.commit()
        finally:
            conn.close()
        await message.answer(f"✅ Интервал установлен: {minutes} минут")
        await state.clear()
        await show_user_cabinet(message, user_id=user_id)
    except ValueError:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")]
        ])
        await message.answer("❌ Введите число (минут) или нажмите «Отмена».", reply_markup=kb)
@router.callback_query(F.data == "blogger:referral")
async def cb_blogger_referral(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT role, sub_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        sub_id = user["sub_id"]
        role = user["role"]
    finally:
        conn.close()
    ref_link = f"https://t.me/{BOT_USERNAME}?start={sub_id}"
    if role == "saas":
        invite_text = "Приглашайте других SaaS-клиентов по этой ссылке.\nКогда они начнут зарабатывать, вы будете получать 10% от их дохода (эта сумма вычитается из их заработка)."
    else:
        invite_text = "Приглашайте других блогеров по этой ссылке.\nКогда они начнут зарабатывать, вы будете получать 10% от их дохода (эта сумма вычитается из их заработка)."
    await safe_edit(callback.message,
        f"🔗 <b>Ваша реферальная ссылка:</b>\n\n"
        f"<code>{ref_link}</code>\n\n{invite_text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "share_success")
async def cb_share_success_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        role = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()["role"]
    finally:
        conn.close()
    text = await generate_success_text(user_id, role)
    await callback.message.answer(text, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data.startswith("tax:"), TaxStates.waiting_tax_status)
async def process_tax_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":")[1]
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET tax_status=? WHERE user_id=?", (status, user_id))
        conn.commit()
    finally:
        conn.close()
    if status == "individual":
        await callback.message.answer(
            "ℹ️ Вы можете использовать бота, но для заказа выплат от 3000₽ вам потребуется получить статус Самозанятого "
            "(это бесплатно за 1 минуту в приложении «Мой налог»)."
        )
    else:
        await callback.message.answer("✅ Статус сохранён. Теперь вам доступен вывод средств при достижении порога.")
    await state.clear()
    await show_user_cabinet(callback.message, user_id=user_id)
    await callback.answer()

async def handle_payout_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT role, balance_available, tax_status, oferta_accepted FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user:
            await message.answer("Сначала зарегистрируйтесь через /start")
            return
        if user["oferta_accepted"] != 1:
            await message.answer("Примите оферту в личном кабинете.")
            return
        if user["role"] not in ("blogger", "saas"):
            await message.answer("Вывод средств доступен только блогерам и SaaS-клиентам.")
            return
        if user["tax_status"] != "business":
            await message.answer("Вывод средств доступен только самозанятым/ИП.")
            return
        available = user["balance_available"] or 0.0
        if available < MIN_PAYOUT:
            await message.answer(f"❌ Минимальная сумма вывода: {MIN_PAYOUT} ₽")
            return
        # Проверка активной заявки
        active = conn.execute(
            "SELECT id FROM payout_requests WHERE user_id=? AND status IN ('processing','awaiting_receipt','receipt_uploaded')",
            (user_id,)
        ).fetchone()
        if active:
            await message.answer("❌ У вас уже есть активная заявка на выплату.")
            return
    finally:
        conn.close()

    await message.answer(
        f"💸 Укажите реквизиты для выплаты (номер карты, банк, TON-кошелёк или другие данные):\n"
        f"Доступно: <b>{available:.2f} ₽</b>\n\n"
        f"Пример: <i>Сбербанк 2202 2081 0829 0025</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")]
        ])
    )
    await state.set_state(PayoutStates.waiting_for_card)


async def update_post_views(bot: Bot):
    """Обновляет количество просмотров для постов, опубликованных 30+ дней назад."""
    conn = get_db()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        posts = conn.execute("""
            SELECT p.id, p.channel_id, p.target_channel_id, p.direct_link,
                   CAST(substr(p.direct_link, instr(p.direct_link, '/')+1) AS INTEGER) as message_id
            FROM posts p
            WHERE p.status = 'published' 
              AND p.published_at <= ?
              AND p.views_count = 0
        """, (cutoff,)).fetchall()

        updated = 0
        for post in posts:
            try:
                chat_id = post["channel_id"]
                msg_id = post["message_id"]
                if not chat_id or not msg_id:
                    continue
                messages = await bot.get_messages(chat_id=chat_id, message_ids=[msg_id])
                if messages and messages[0].views:
                    conn.execute("UPDATE posts SET views_count = ? WHERE id = ?", (messages[0].views, post["id"]))
                    updated += 1
            except Exception as e:
                logger.warning(f"Не удалось получить просмотры для поста {post['id']}: {e}")
        conn.commit()
        logger.info(f"Обновлено просмотров: {updated}")
    finally:
        conn.close()
# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: Command = None):
    # 1. Проверка запроса выплаты из веб-статистики
    if command.args == "payout":
        await handle_payout_start(message, state)
        return  

    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("👋 Добро пожаловать в Панель администратора.", reply_markup=kb_admin_panel())
        return

    # Проверяем реферальную ссылку (deep linking)
    referrer_id = None
    if command.args:
        ref_sub_id = command.args.strip()
        conn = get_db()
        try:
            referrer = conn.execute(
                "SELECT user_id FROM users WHERE sub_id = ? AND role = 'blogger'",
                (ref_sub_id,)
            ).fetchone()
            if referrer:
                referrer_id = referrer["user_id"]
        finally:
            conn.close()
        if referrer_id:
            await state.update_data(referrer_id=referrer_id)

    conn = get_db()
    try:
        user = conn.execute("SELECT role FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
        if not user:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💼 SaaS-клиент", callback_data="role:saas")],
                [InlineKeyboardButton(text="👤 Блогер", callback_data="role:blogger")],
            ])
            await message.answer(
                "👋 <b>Добро пожаловать в AutoPost!</b>\n\n"
                "Бот автоматически публикует товары из партнёрских магазинов в ваш Telegram-канал "
                "и приносит вам <b>70% комиссии</b> с каждой продажи.\n\n"
                "<b>Как это работает:</b>\n"
                "1. Добавляете канал\n"
                "2. Выбираете магазины\n"
                "3. Бот публикует посты с вашими партнёрскими ссылками\n"
                "4. Получаете доход за каждую покупку\n\n"
                "Выберите вашу роль:",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            await state.set_state(OnboardingStates.waiting_role)
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💼 Открыть кабинет", callback_data="cabinet:open")]
            ])
            await message.answer(
                "✅ Вы уже зарегистрированы. Для управления ботом используйте команду /cabinet.",
                reply_markup=kb
            )
    finally:
        conn.close()

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Справка — AutoPost Bot</b>\n\n"
        "<b>Основные команды:</b>\n"
        "/start — Главное меню\n"
        "/cabinet — Личный кабинет\n"
        "/help — Эта справка\n\n"
        "<b>Дополнительно:</b>\n"
        "/promo — Активировать промокод\n"
        "/privacy — Политика конфиденциальности\n"
        "/delete — Удалить аккаунт и все данные\n\n"
        "<b>Как начать зарабатывать:</b>\n"
        "1. Добавьте канал в «Кабинете»\n"
        "2. Добавьте бота админом в канал с правами на постинг\n"
        "3. Выберите магазины в разделе «Магазины»\n"
        "4. Бот начнёт публикации автоматически!\n\n"
        "<b>Выплаты:</b>\n"
        "Минимальная выплата — 3000 ₽.\n"
        "Доступен для самозанятых.\n\n"
        "<b>Поддержка:</b> напишите /start и нажмите «💬 Поддержка»",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("preview"))
async def cmd_preview(message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id) and not is_feature_enabled(user_id, "preview_post"):
        await message.answer("⏳ Эта функция в бета-тесте. Скоро станет доступна всем!")
        return
    
    # Отправляем ссылку на веб-статистику с предпросмотром
    token = generate_user_token(user_id)
    link = f"{WEBAPP_BASE_URL}/my-stats?token={token}"
    await message.answer(
        f"👀 <b>Предпросмотр поста</b>\n\n"
        f"Перейдите в веб-статистику и найдите блок «Предпросмотр поста»:\n"
        f"<a href='{link}'>Открыть статистику</a>\n\n"
        f"Там вы сможете:\n"
        f"• Посмотреть, как пост будет выглядеть в канале\n"
        f"• Опубликовать его в один клик",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

@router.message(Command("privacy"))
async def cmd_privacy(message: Message):
    await message.answer(
        "📄 Политика конфиденциальности:\n https://teletype.in/@miliron/yYN0SEGfm5l",
        disable_web_page_preview=True
    )

_pending_deletes: dict[int, float] = {}

@router.message(Command("delete"))
async def cmd_delete(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "без username"

    import time
    now = time.time()
    pending_until = _pending_deletes.get(user_id, 0)

    if now < pending_until:
        del _pending_deletes[user_id]
        state = message.state
        if state:
            await state.clear()
        _delete_user_data(user_id)
        for admin_id in ADMIN_IDS:
            try:
                await message.bot.send_message(
                    admin_id,
                    f"🗑 <b>Пользователь удалил аккаунт</b>\n\n"
                    f"User ID: <code>{user_id}</code>\n"
                    f"Username: @{username}\n"
                    f"Все данные удалены из базы.",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить админа {admin_id}: {e}")
        await message.answer(
            "✅ Все ваши данные удалены в соответствии со ст. 21 152-ФЗ.\n\n"
            "Если вы захотите вернуться — просто напишите /start."
        )
    else:
        _pending_deletes[user_id] = now + 60
        await message.answer(
            "⚠️ <b>Внимание!</b>\n\n"
            "Это действие удалит <b>все ваши данные</b> из бота:\n"
            "• Профиль и подписка\n"
            "• Каналы и посты\n"
            "• Баланс и транзакции\n"
            "• Шаблоны и настройки\n\n"
            "Это действие <b>необратимо</b>.\n\n"
            "Для подтверждения отправьте <code>/delete</code> ещё раз в течение 60 секунд.",
            parse_mode=ParseMode.HTML
        )


def _delete_user_data(user_id: int) -> None:
    conn = get_db()
    try:
        user_sub_ids = [row["sub_id"] for row in conn.execute("SELECT sub_id FROM users WHERE user_id=?", (user_id,)).fetchall()]
        channel_ids = [row["channel_id"] for row in conn.execute("SELECT channel_id FROM channels WHERE user_id=?", (user_id,)).fetchall()]

        for table, col in [
            ("payout_chat", None),
            ("payout_requests", "user_id"),
            ("payouts", "user_id"),
            ("saas_queue", "user_id"),
            ("night_queue", "user_id"),
            ("promocode_activations", "user_id"),
            ("user_category_preferences", "user_id"),
            ("gdeslon_catalog", "user_id"),
            ("admitad_transactions", "user_id"),
            ("social_channels", "user_id"),
        ]:
            if col:
                conn.execute(f"DELETE FROM {table} WHERE {col}=?", (user_id,))

        conn.execute("DELETE FROM referrals WHERE referrer_id=? OR referral_id=?", (user_id, user_id))
        conn.execute("DELETE FROM posts WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM channels WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM user_consents WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE user_id=?", (user_id,))

        for sub_id in user_sub_ids:
            conn.execute("DELETE FROM transactions WHERE sub_id=?", (sub_id,))
            conn.execute("DELETE FROM subid_stats WHERE subid1=?", (sub_id,))
        for channel_id in channel_ids:
            conn.execute("DELETE FROM pinned_posts WHERE chat_id=?", (channel_id,))

        conn.commit()
    finally:
        conn.close()



# ---------------------------------------------------------------------------
# /cabinet
# ---------------------------------------------------------------------------
@router.message(Command("cabinet"))
async def cmd_cabinet(message: Message):
    await show_user_cabinet(message, user_id=message.from_user.id)


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
        await safe_edit(callback.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
        await state.set_state(OnboardingStates.waiting_saas_tg_channel)
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("channel_delete:"))
async def cb_delete_channel(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    channel_id = parts[1]
    user_id = callback.from_user.id

    if len(parts) > 2 and parts[2] == "confirm":
        conn = get_db()
        try:
            conn.execute("DELETE FROM channels WHERE id=? AND user_id=?", (channel_id, user_id))
            conn.commit()
        finally:
            conn.close()
        await callback.answer("🗑 Канал удалён.", show_alert=True)
        await cb_my_channels(callback)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Да, удалить", callback_data=f"delete_channel:{channel_id}:confirm")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")],
        ])
        await callback.message.answer("⚠️ Вы уверены, что хотите удалить канал?", reply_markup=kb)
        await callback.answer()

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
        await safe_edit(callback.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
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

    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode=ParseMode.HTML)

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

@router.callback_query(F.data == "menu:privacy")
async def cb_menu_privacy(callback: CallbackQuery):
    await callback.message.answer(
        "📄 Политика конфиденциальности:\nhttps://teletype.in/@miliron/yYN0SEGfm5l",
        disable_web_page_preview=True
    )
    await callback.answer()
# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:settings")
async def cb_menu_settings(callback: CallbackQuery) -> None:
    await open_saas_settings(callback)
    await callback.answer()

@router.callback_query(F.data == "saas_toggle:force_preview_enable")
async def cb_force_preview_enable(callback: CallbackQuery):
    """Включает режим предпросмотра (force_preview_confirmed = 1)"""
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET force_preview_confirmed = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    await callback.answer("✅ Предпросмотр включен (посты теперь публикуются сразу)", show_alert=True)
    await open_saas_settings(callback)

@router.callback_query(F.data == "saas_toggle:force_preview_reset")
async def cb_force_preview_reset(callback: CallbackQuery):
    """Выключает режим предпросмотра (force_preview_confirmed = 0)"""
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET force_preview_confirmed = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    await callback.answer("🔍 Предпросмотр выключен (будет показываться каждый раз)", show_alert=True)
    await open_saas_settings(callback)
  
@router.callback_query(F.data.startswith("saas_toggle:"))
async def cb_saas_toggles(callback: CallbackQuery) -> None:
    action = callback.data.split(":")[1]
    user_id = callback.from_user.id
    conn = get_db()
    try:
        if action == "autopin":
            user = conn.execute("SELECT auto_pin FROM users WHERE user_id=?", (user_id,)).fetchone()
            if user:
                new_val = 0 if user["auto_pin"] else 1
                conn.execute("UPDATE users SET auto_pin=? WHERE user_id=?", (new_val, user_id))
                conn.commit()
        elif action == "notifyposts":
            user = conn.execute("SELECT notify_posts FROM users WHERE user_id=?", (user_id,)).fetchone()
            if user:
                new_val = 0 if user["notify_posts"] else 1
                conn.execute("UPDATE users SET notify_posts=? WHERE user_id=?", (new_val, user_id))
                conn.commit()
        else:
            return
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
            # Проверка лимита каналов
            user = conn.execute("SELECT role, tariff_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
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

@router.callback_query(OnboardingStates.waiting_role)
async def process_role_selection(callback: CallbackQuery, state: FSMContext):
    role = callback.data.split(":")[1]  # "saas" или "blogger"
    user_id = callback.from_user.id
    data = await state.get_data()
    referrer_id = data.get("referrer_id")

    conn = get_db()
    try:
        sub_id = generate_sub_id(callback.from_user.username, user_id, role)
        conn.execute(
            "INSERT INTO users (user_id, username, sub_id, role, referrer_id) VALUES (?, ?, ?, ?, ?)",
            (user_id, callback.from_user.username, sub_id, role, referrer_id)
        )
        if role == "blogger":
            conn.execute("UPDATE users SET commission_rate = 0.70 WHERE user_id = ?", (user_id,))
        else:
            conn.execute("UPDATE users SET commission_rate = 0.70 WHERE user_id = ?", (user_id,))
        # Реферальная связь
        if referrer_id:
            conn.execute("""
                INSERT OR IGNORE INTO referrals (referrer_id, referral_id, total_brought_profit)
                VALUES (?, ?, 0)
            """, (referrer_id, user_id))
        conn.commit()
    finally:
        conn.close()

    # Уведомление рефереру
    if referrer_id:
        try:
            await callback.bot.send_message(
                referrer_id,
                f"🎉 По вашей реферальной ссылке зарегистрировался новый блогер (ID {user_id})!\n"
                "Вы будете получать 10% от его заработка."
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить реферера {referrer_id}: {e}")

    if role == "saas":
        await safe_edit(callback.message,
            "👋 Добро пожаловать! Для начала работы отправьте @username вашего Telegram-канала."
        )
        await state.set_state(OnboardingStates.waiting_saas_tg_channel)
    else:  # blogger
        await safe_edit(callback.message,
            "👋 Добро пожаловать, блогер! Для начала отправьте @username вашего Telegram-канала."
        )
        await state.set_state(OnboardingStates.waiting_saas_tg_channel)  # то же состояние, но без лимитов

    await callback.answer()
# ---------------------------------------------------------------------------
# Обработчики инструкций и поддержки
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "support:contact")
async def cb_support_contact(callback: CallbackQuery):
    text = (
        "📞 <b>Связь с администратором</b>\n\n"
        "По любым вопросам пишите:\n"
        "👉 <a href='https://t.me/Zigih90'>@Zigih90</a>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "❓ <b>Частые вопросы:</b>\n\n"
        "<b>Бот не публикует посты?</b>\n"
        "Убедитесь, что бот — админ канала с правами на публикацию.\n\n"
        "<b>Нет дохода?</b>\n"
        "Доход появляется после подтверждения покупок рекламодателем (30–90 дней).\n\n"
        "<b>Не могу вывести деньги?</b>\n"
        "Нужен статус самозанятого и баланс от 3000 ₽.\n\n"
        "<b>Какие магазины доступны?</b>\n"
        "Откройте «Кабинет» → «Магазины» — там весь список.\n\n"
        "<i>Стаюсь отвечать быстро</i>"
    )
    await safe_edit(callback.message, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "menu:instructions")
async def cb_menu_instructions(callback: CallbackQuery) -> None:
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

async def show_saas_instruction(callback: CallbackQuery):
    text = (
        "📖 <b>Инструкция для SaaS-клиентов</b>\n\n"
        "<b>1. Подготовка</b>\n"
        "─ Бот автоматически получает товары из проверенных магазинов (Admitad).\n"
        "─ Вам не нужно вводить API-ключи или оплачивать подписку — доступ бессрочный и бесплатный.\n\n"
        "<b>2. Подключение каналов</b>\n"
        "─ Перейдите в «📢 Мои каналы» и отправьте @username вашего канала.\n"
        "─ Для каждого канала автоматически создаётся уникальный идентификатор, который позволяет отслеживать продажи.\n\n"
        "<b>3. Выбор магазинов</b>\n"
        "─ Нажмите «🏪 Магазины» и отметьте интересующие вас магазины.\n"
        "─ От выбранных магазинов зависит, какие товары будут публиковаться.\n\n"
        "<b>4. Автоматический постинг и доход</b>\n"
        "─ Бот самостоятельно наполняет каталог товарами с маркировкой ERID.\n"
        "─ Посты выходят автоматически с партнёрскими ссылками, в которые встроен идентификатор вашего канала.\n"
        "─ Доход от продаж распределяется в пропорции: 70% – вам, 30% – сервису.\n\n"
        "<b>5. Интервал постов</b>\n"
        "─ Вы можете настроить частоту публикаций в разделе «⚙️ Периодичность постов».\n\n"
        "<b>6. Циклический постинг</b>\n"
        "─ В настройках SaaS нажмите «⏰ Циклический постинг» и задайте периодичность для каждого магазина.\n"
        "─ Бот будет публиковать товары из нужного магазина через заданные интервалы (от 1 дня до 1 месяца).\n"
        "─ Если расписание не настроено — магазины чередуются автоматически.\n\n"
        "<b>7. Автоудаление постов</b>\n"
        "─ В настройках SaaS нажмите «🗑 Автоудаление постов» и выберите время жизни поста.\n"
        "─ По умолчанию посты удаляются через 7 дней. Можно выключить или установить от 1 часа до 30 дней.\n"
        "─ Переходы засчитываются в течение 30 дней (кука Admitad), даже если пост уже удалён.\n\n"
        "<b>8. Шаблоны и финансы</b>\n"
        "─ Настройка шаблонов постов и запрос выплат доступны в веб-статистике (кнопка «📊 Веб-статистика» в кабинете).\n\n"
        "<b>9. Реферальная программа</b>\n"
        "─ Вы можете приглашать других пользователей по реферальной ссылке и получать 10% от их дохода.\n\n"
        "<i>По всем вопросам обращайтесь к администратору.</i>"
    )
    await safe_edit(callback.message, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
        ]),
        parse_mode=ParseMode.HTML
    )
async def show_blogger_instruction(callback: CallbackQuery):
    text = (
        "📖 <b>Инструкция: Как зарабатывать с ботом</b>\n\n"
        "Бот сам публикует товары от брендов в ваш Telegram‑канал, а вы получаете <b>70%</b> "
        "от комиссии за каждую покупку. Чтобы работа была стабильной и легальной, следуйте трём шагам.\n\n"
        "<b>⏳ Шаг 1. Как устроен баланс</b>\n"
        "Когда подписчик переходит по ссылке и покупает товар, в веб-статистике (кнопка «📊 Веб-статистика») обновляется баланс:\n"
        "• <b>«В ожидании»</b> — магазин проверяет заказ (30–90 дней).\n"
        "• <b>«Доступно к выводу»</b> — деньги подтверждены, можно забирать.\n\n"
        "<b>💳 Шаг 2. Вывод средств и налоги</b>\n"
        "Минимальная сумма для вывода — <b>3000 ₽</b>. Сервис работает официально, поэтому вы обязаны "
        "иметь статус <b>Самозанятого</b> (оформляется бесплатно в приложении «Мой Налог») или <b>ИП</b>.\n"
        "Когда накопится 3000 ₽, откройте веб-статистику и нажмите «💸 Запросить выплату», укажите реквизиты.\n\n"
        "<b>🛡️ Шаг 3. Чек и защита выплаты</b>\n"
        "• Администратор отправляет деньги.\n"
        "• В веб-статистике появится чат с кнопкой «📤 Отправить чек». <b>Вы обязаны в течение 24 часов</b> "
        "сформировать чек в приложении «Мой Налог» (тип: Продажа физ.лицу, услуга: Рекламные услуги) "
        "и загрузить его.\n"
        "• После проверки администратором заявка закрывается.\n\n"
        "<b>⚠️ ВАЖНО:</b> Если вы не пришлёте чек за 24 часа, аккаунт будет <b>заблокирован навсегда</b>, "
        "а невыплаченные средства аннулированы.\n\n"
        "<b>🚫 Запрещено (бан без выплат):</b>\n"
        "• Спам ссылками в чужих каналах, комментариях, личных сообщениях.\n"
        "• Мотивированный трафик (просьбы «купи по ссылке, я верну деньги»).\n"
        "• Самовыкупы и накрутка.\n"
        "• Размещение ссылок в каналах с запрещённым контентом (казино, пиратство, треш).\n\n"
        "<b>🚀 С чего начать:</b>\n"
        "1. Добавьте канал через «📢 Мои Telegram‑каналы».\n"
        "2. Назначьте бота администратором с правом публикации.\n"
        "3. Выберите магазины в «🏪 Магазины».\n"
        "4. Настройте интервал постов.\n"
        "5. Настройте шаблоны и следите за доходом в «📊 Веб‑статистика».\n\n"
        "<b>⏰ Циклический постинг (в настройках SaaS):</b>\n"
        "─ Задайте периодичность для каждого магазина (1 день – 1 месяц).\n"
        "─ Бот будет публиковать товары из нужного магазина по расписанию.\n\n"
        "<b>🗑 Автоудаление постов:</b>\n"
        "─ По умолчанию посты удаляются через 7 дней. Можно изменить (от 1 часа до 30 дней) или выключить.\n"
        "─ Переходы засчитываются 30 дней (кука Admitad), даже после удаления поста.\n\n"
        "По вопросам пишите: 👉 <a href='https://t.me/Zigih90'>@Zigih90</a>"
    )
    await safe_edit(callback.message, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
        ]),
        parse_mode=ParseMode.HTML
    )

# ---------------------------------------------------------------------------
# Административные команды
# ---------------------------------------------------------------------------


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
    if action == "broadcast":
        await call.answer()
        await state.set_state(AdminStates.broadcast_text)
        await call.message.answer("✏️ Введи текст рассылки:")
    elif action == "extend_sub":
        await call.answer()
        await state.set_state(AdminStates.extend_user_id)
        await call.message.answer("👤 Введи user_id пользователя:")
    else:
        await call.answer("Неизвестная команда", show_alert=True)


@router.callback_query(F.data == "payout:request")
async def cb_payout_request(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT balance_available, tax_status FROM users WHERE user_id=?", (user_id,)).fetchone()
        available = user["balance_available"]
        tax_status = user["tax_status"]
        # Проверка налогового статуса
        if tax_status != "business":
            await callback.answer("❌ Вывод средств доступен только самозанятым/ИП.", show_alert=True)
            return
        # Проверка активных заявок
        active = conn.execute(
            "SELECT id FROM payout_requests WHERE user_id=? AND status IN ('processing','awaiting_receipt','receipt_uploaded')",
            (user_id,)
        ).fetchone()
        if active:
            await callback.answer("❌ У вас уже есть активная заявка на выплату.", show_alert=True)
            return
        if available < MIN_PAYOUT:
            await callback.answer(f"❌ Минимальная сумма вывода: {MIN_PAYOUT} ₽", show_alert=True)
            return
    finally:
        conn.close()

    await callback.message.answer(
        f"💸 Укажите реквизиты для выплаты (номер карты, банк, TON-кошелёк или другие данные):\n"
        f"Доступно: <b>{available:.2f} ₽</b>\n\n"
        f"Пример: <i>Сбербанк 2202 2081 0829 0025</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:finance")]
        ])
    )
    await state.set_state(PayoutStates.waiting_for_card)
    await callback.answer()
@router.message(PayoutStates.waiting_for_card)
async def process_payout_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()

    if len(text) < 3 or len(text) > 100:
        await message.answer(
            "❌ Реквизиты слишком короткие или длинные (3–100 символов).\n"
            "Пример: <i>Сбербанк 2202 2081 0829 0025</i> или <i>UQAbc123...</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    conn = get_db()
    try:
        user = conn.execute("SELECT balance_available, tax_status FROM users WHERE user_id=?", (user_id,)).fetchone()
        available = user["balance_available"]
        if user["tax_status"] != "business":
            await message.answer("❌ Вывод средств недоступен для вашего налогового статуса.")
            await state.clear()
            return
        if available < MIN_PAYOUT:
            await message.answer("❌ Недостаточно средств.")
            await state.clear()
            return
        # Списание баланса сразу
        conn.execute("UPDATE users SET balance_available = balance_available - ? WHERE user_id=?", (available, user_id))
        # Создание заявки со статусом processing
        conn.execute(
            "INSERT INTO payout_requests (user_id, amount, message, status) VALUES (?, ?, ?, 'processing')",
            (user_id, available, text)
        )
        conn.commit()
        request_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()

    await message.answer(
        f"✅ Заявка на выплату <b>{available:.2f} ₽</b> создана и передана администратору. "
        f"Номер заявки: <b>#{request_id}</b>.\nОжидайте уведомления о переводе.",
        parse_mode=ParseMode.HTML
    )

    # Уведомление админам
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"🔔 Новый запрос на выплату!\n"
                f"Пользователь: {user_id}\n"
                f"Сумма: {available:.2f} ₽\n"
                f"Заявка #{request_id}\n"
                f"Реквизиты: {text[:200]}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🌐 Открыть админку", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))]
                ])
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить админа {admin_id}: {e}")

    await state.clear()
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
        draft_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        published_cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        conn.execute("DELETE FROM posts WHERE status != 'published' AND created_at < ?", (draft_cutoff,))
        draft_count = conn.execute("SELECT changes()").fetchone()[0]
        conn.execute("DELETE FROM posts WHERE status = 'published' AND created_at < ?", (published_cutoff,))
        pub_count = conn.execute("SELECT changes()").fetchone()[0]
        conn.execute("DELETE FROM subid_stats WHERE subid1 NOT IN (SELECT DISTINCT subid1 FROM posts WHERE subid1 IS NOT NULL AND subid1 != '')")
        orphan_count = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        logger.info(f"Очистка: {draft_count} черновиков, {pub_count} опубликованных, {orphan_count} orphan subid_stats")
    except Exception as e:
        logger.error(f"Ошибка очистки: {e}")
    finally:
        conn.close()

async def cleanup_old_report_files() -> None:
    import pathlib
    reports_dir = pathlib.Path("/app/data/reports")
    if not reports_dir.exists():
        return
    cutoff = datetime.now() - timedelta(days=90)
    removed = 0
    for f in reports_dir.iterdir():
        if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink()
            removed += 1
    if removed:
        logger.info(f"Очистка отчётов: удалено {removed} файлов старше 90 дней")

async def auto_delete_posts(bot: Bot):
    conn = get_db()
    try:
        now = datetime.now(timezone.utc)
        rows = conn.execute("""
            SELECT p.id, p.channel_id, p.direct_link, p.user_id, p.auto_delete_hours, p.published_at
            FROM posts p
            WHERE p.status = 'published'
              AND p.auto_delete_hours IS NOT NULL
              AND p.auto_delete_hours > 0
              AND p.published_at IS NOT NULL
        """).fetchall()
        deleted_count = 0
        for row in rows:
            try:
                published_at = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
            except Exception:
                continue
            hours_elapsed = (now - published_at).total_seconds() / 3600
            if hours_elapsed < (row["auto_delete_hours"] or 168):
                continue
            channel_id = row["channel_id"]
            message_id = None
            if row["direct_link"] and "/" in row["direct_link"]:
                try:
                    message_id = int(row["direct_link"].rstrip("/").split("/")[-1])
                except (ValueError, IndexError):
                    pass
            if channel_id and message_id:
                try:
                    await bot.delete_message(chat_id=channel_id, message_id=message_id)
                    deleted_count += 1
                except Exception:
                    pass
            conn.execute("UPDATE posts SET status = 'deleted' WHERE id = ?", (row["id"],))
        conn.commit()
        if deleted_count:
            logger.info(f"Автоудаление: удалено {deleted_count} постов из каналов")
    except Exception as e:
        logger.error(f"Ошибка автоудаления: {e}")
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


async def check_receipt_reminders(bot: Bot):
    """Напоминает блогерам о необходимости загрузить чек через 12 часов после отправки денег."""
    conn = get_db()
    try:
        now = datetime.now(timezone.utc)
        twelve_hours_ago = (now - timedelta(hours=12)).isoformat()
        rows = conn.execute("""
            SELECT id, user_id, amount FROM payout_requests
            WHERE status = 'awaiting_receipt'
            AND sent_at IS NOT NULL
            AND sent_at <= ?
            AND receipt_reminded = 0
        """, (twelve_hours_ago,)).fetchall()
        for row in rows:
            try:
                await bot.send_message(
                    row["user_id"],
                    f"⏰ <b>Напоминание о чеке</b>\n\n"
                    f"Вам был отправлен перевод на сумму <b>{row['amount']} ₽</b>.\n"
                    "Согласно оферте, вы обязаны загрузить чек из приложения «Мой налог» в течение 24 часов.\n"
                    "Пожалуйста, перейдите в веб-статистику и нажмите «📤 Отправить чек».",
                    parse_mode=ParseMode.HTML
                )
                conn.execute("UPDATE payout_requests SET receipt_reminded = 1 WHERE id = ?", (row["id"],))
                conn.commit()
                logger.info(f"Отправлено напоминание о чеке по заявке #{row['id']}")
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания для заявки #{row['id']}: {e}")
    finally:
        conn.close()

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    logger.info("🔄 Настройка планировщика...")
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    
    scheduler.add_job(unpin_old_messages, trigger="interval", minutes=30, kwargs={"bot": bot}, id="unpin_vip_posts", replace_existing=True)
    scheduler.add_job(cleanup_old_posts, trigger="cron", hour=3, minute=0, id="cleanup_old_posts", replace_existing=True)
    scheduler.add_job(cleanup_old_report_files, trigger="cron", hour=3, minute=5, id="cleanup_report_files", replace_existing=True)
    scheduler.add_job(backup_database_to_telegram, trigger="cron", hour=3, minute=10, kwargs={"bot": bot}, id="backup_database", replace_existing=True)
    scheduler.add_job(publish_from_catalog, trigger="interval", minutes=10, jitter=30, kwargs={"bot": bot}, id="publish_catalog", replace_existing=True)
    scheduler.add_job(refill_admitad_catalogs, trigger="interval", minutes=15, id="refill_admitad", replace_existing=True)
    scheduler.add_job(daily_report, trigger="cron", hour=9, minute=0, kwargs={"bot": bot}, id="daily_report", replace_existing=True)
    scheduler.add_job(update_all_store_data_from_feed, trigger="cron", hour=4, minute=0, id="update_coupons_feed", replace_existing=True)
    scheduler.add_job(check_rss_and_publish, trigger="interval", minutes=15, kwargs={"bot": bot}, id="check_rss", replace_existing=True)
    scheduler.add_job(check_receipt_reminders, trigger="interval", minutes=30, kwargs={"bot": bot}, id="receipt_reminders", replace_existing=True)
    scheduler.add_job(update_post_views, 'cron', hour=3, minute=30, kwargs={"bot": bot}, id="update_views", replace_existing=True)
    scheduler.add_job(generate_monthly_ord_reports, trigger="cron", day=1, hour=0, minute=5, kwargs={"bot": bot}, id="monthly_ord_reports", replace_existing=True)
    scheduler.add_job(auto_delete_posts, trigger="interval", minutes=15, kwargs={"bot": bot}, id="auto_delete_posts", replace_existing=True)
    
    logger.info("✅ Все задачи добавлены в планировщик")
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

    dp.include_router(router)
    dp.include_router(saas_router)

    from handlers.social import router as social_router
    dp.include_router(social_router)
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планировщик (APScheduler) запущен")

    # ===== КОМАНДЫ ДЛЯ ВСЕХ ПОЛЬЗОВАТЕЛЕЙ =====
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="cabinet", description="Личный кабинет"),
            BotCommand(command="help", description="Справка и контакты"),
        ],
        scope=BotCommandScopeDefault(),
    )

    # ===== КОМАНДЫ ДЛЯ АДМИНОВ =====
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(
                commands=[
                    BotCommand(command="start", description="Панель администратора"),
                    BotCommand(command="cabinet", description="Панель администратора"),
                    BotCommand(command="debug_sub", description="Проверить подписку пользователя"),
                    BotCommand(command="fix_channels", description="Удалить дубликаты каналов"),
                    BotCommand(command="beta", description="Управление бета-тестерами"),
                    BotCommand(command="preview", description="Предпросмотр поста"),
                ],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except TelegramBadRequest as e:
            logger.warning(f"Не удалось установить команды для админа {admin_id}: {e}")

    # ===== КОМАНДЫ ДЛЯ БЕТА-ТЕСТЕРОВ =====
    for tester in get_beta_testers():
        user_id = tester["user_id"]
        if user_id in ADMIN_IDS:
            continue
        try:
            await bot.set_my_commands(
                commands=[
                    BotCommand(command="start", description="Главное меню"),
                    BotCommand(command="cabinet", description="Личный кабинет"),
                    BotCommand(command="preview", description="Предпросмотр поста"),
                ],
                scope=BotCommandScopeChat(chat_id=user_id),
            )
            logger.info(f"Команды для бета-тестера {user_id} установлены")
        except Exception as e:
            logger.warning(f"Не удалось установить команды для {user_id}: {e}")

    # ===== ЗАПУСК FASTAPI =====
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

async def generate_monthly_ord_reports(bot: Bot):
    """Генерирует отчёт ОРД за прошедший месяц и отправляет пользователям в Telegram"""
    now = datetime.now(timezone.utc)
    first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = first_of_this_month - timedelta(seconds=1)
    last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    start_iso = last_month_start.isoformat()
    end_iso = last_month_end.isoformat()
    month_label = last_month_start.strftime("%B %Y")

    conn = get_db()
    try:
        users = conn.execute("""
            SELECT DISTINCT user_id FROM posts
            WHERE status = 'published' AND erid IS NOT NULL AND erid != ''
              AND published_at >= ? AND published_at <= ?
        """, (start_iso, end_iso)).fetchall()
    finally:
        conn.close()

    for user_row in users:
        user_id = user_row["user_id"]
        try:
            await collect_views_for_user(user_id, bot)

            conn = get_db()
            try:
                posts = conn.execute("""
                    SELECT p.published_at, p.erid, p.views_count, p.direct_link, p.channel_id,
                           COALESCE(c.channel_title, '') AS channel_title
                    FROM posts p
                    LEFT JOIN channels c ON c.user_id = p.user_id AND c.channel_id = p.channel_id
                    WHERE p.user_id = ? AND p.status = 'published' AND p.erid IS NOT NULL AND p.erid != ''
                      AND p.published_at >= ? AND p.published_at <= ?
                    ORDER BY p.published_at DESC
                """, (user_id, start_iso, end_iso)).fetchall()
            finally:
                conn.close()

            if not posts:
                continue

            output = BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True, 'remove_timezone': True})
            worksheet = workbook.add_worksheet("ORD")
            headers = [
                "ERID", "Площадка (Telegram)", "Тип площадки",
                "Количество показов", "Количество переходов", "Сумма потраченная",
                "Дата начала", "Дата окончания", "Ссылка на пост", "Название канала"
            ]
            for col, header in enumerate(headers):
                worksheet.write(0, col, header)

            date_format = workbook.add_format({'num_format': 'dd.mm.yyyy'})

            for row_idx, p in enumerate(posts, start=1):
                views = p["views_count"] or 0
                direct_link = p["direct_link"] or ""
                channel_title = p["channel_title"] or "Telegram"

                try:
                    pub_date = datetime.fromisoformat(p["published_at"].replace("Z", "+00:00"))
                    if pub_date.tzinfo is not None:
                        pub_date = pub_date.replace(tzinfo=None)
                except Exception:
                    pub_date = datetime.now()

                worksheet.write(row_idx, 0, p["erid"])
                worksheet.write(row_idx, 1, "Telegram")
                worksheet.write(row_idx, 2, channel_title)
                worksheet.write(row_idx, 3, views)
                worksheet.write(row_idx, 4, 0)
                worksheet.write(row_idx, 5, 0)
                worksheet.write_datetime(row_idx, 6, pub_date, date_format)
                worksheet.write_datetime(row_idx, 7, pub_date, date_format)
                worksheet.write(row_idx, 8, direct_link)
                worksheet.write(row_idx, 9, channel_title)

            worksheet.set_column(0, 0, 30)
            worksheet.set_column(1, 2, 18)
            worksheet.set_column(3, 5, 20)
            worksheet.set_column(6, 7, 14)
            worksheet.set_column(8, 9, 40)

            workbook.close()
            output.seek(0)

            filename = f"ORD_Report_{last_month_start.strftime('%Y%m')}.xlsx"
            from aiogram.types import BufferedInputFile
            document = BufferedInputFile(output.getvalue(), filename=filename)
            await bot.send_document(
                chat_id=user_id,
                document=document,
                caption=f"📊 Отчёт ОРД за {month_label}\n\nВсего постов: {len(posts)}"
            )
            logger.info(f"Отчёт ОРД за {month_label} отправлен пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка генерации отчёта для user_id={user_id}: {e}")
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

@router.message(Command("beta"))
async def cmd_beta(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "📋 Использование:\n"
            "/beta add USER_ID — добавить тестера\n"
            "/beta remove USER_ID — убрать тестера\n"
            "/beta list — список тестеров"
        )
        return
    
    action = args[1]
    try:
        if action == "add":
            if len(args) < 3:
                await message.answer("❌ Укажите USER_ID")
                return
            user_id = int(args[2])
            if add_beta_tester(user_id):
                await message.answer(f"✅ Пользователь {user_id} добавлен в бета-тестеры")
            else:
                await message.answer(f"❌ Не удалось добавить пользователя {user_id}")
        elif action == "remove":
            if len(args) < 3:
                await message.answer("❌ Укажите USER_ID")
                return
            user_id = int(args[2])
            if remove_beta_tester(user_id):
                await message.answer(f"✅ Пользователь {user_id} удалён из бета-тестеров")
            else:
                await message.answer(f"❌ Не удалось удалить пользователя {user_id}")
        elif action == "list":
            testers = get_beta_testers()
            if testers:
                text = "👥 Бета-тестеры:\n"
                for t in testers:
                    text += f"- {t['user_id']} ({t['username'] or 'без username'})\n"
                await message.answer(text)
            else:
                await message.answer("❌ Нет бета-тестеров")
        else:
            await message.answer("❌ Неизвестное действие")
    except ValueError:
        await message.answer("❌ USER_ID должен быть числом")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logger.critical(f"Критическая ошибка: {e}. Перезапуск через 5 секунд...")
            import time as _time
            _time.sleep(5)
            continue
        break
