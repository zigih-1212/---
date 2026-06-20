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
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any, List
from admin_panel import create_fastapi_app
import sys
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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from parser import (
    extract_video_info,
    rewrite_text_with_ai,
    get_product_data_by_token,
    fetch_telegram_channel_posts,
    find_product_links,
    process_new_video,
    is_video_processed,
)
from stats import get_blogger_stats, get_saas_channels, get_saas_channel_stats, STAT_PERIODS
print("DEBUG: all imports done", flush=True, file=sys.stderr)

DB_PATH: str = "/app/data/autopost.db"

def get_db():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL;")
    return db

def load_settings():
    """Загружает настройки из БД. Если настройки нет – берёт из переменной окружения."""
    defaults = {
        "NIGHT_START": os.getenv("NIGHT_START", "23:00"),
        "NIGHT_END": os.getenv("NIGHT_END", "08:00"),
        "RUN_INTERVAL_SECONDS": os.getenv("RUN_INTERVAL_SECONDS", "900"),
        "MIN_PAYOUT": os.getenv("MIN_PAYOUT", "2000"),
        "PAYOUT_FIXED_FEE": os.getenv("PAYOUT_FIXED_FEE", "35"),
        "PAYOUT_BANK_PCT": os.getenv("PAYOUT_BANK_PCT", "0.043"),
    }
    conn = get_db()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        for row in rows:
            if row["key"] in defaults:
                defaults[row["key"]] = row["value"]
    except:
        pass  # таблицы может ещё не быть при первом запуске
    finally:
        conn.close()
    return defaults

settings = load_settings()

def load_tariffs():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM tariffs WHERE is_active = 1 ORDER BY days").fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "days": r["days"],
                "price_rub": r["price_rub"],
                "price_stars": r["price_stars"],
                "max_channels": r["max_channels"] if "max_channels" in r.keys() else 5,
                "max_posts_per_day": r["max_posts_per_day"] if "max_posts_per_day" in r.keys() else 25,
                "max_categories": r["max_categories"] if "max_categories" in r.keys() else 3,
                "min_cashback": r["min_cashback"] if "min_cashback" in r.keys() else 0,
                "max_cashback": r["max_cashback"] if "max_cashback" in r.keys() else 0,
            }
            for r in rows
        ]
    finally:
        conn.close()

# Обновляем глобальные переменные из настроек
MIN_PAYOUT = float(settings["MIN_PAYOUT"])
PAYOUT_FIXED_FEE = float(settings["PAYOUT_FIXED_FEE"])
PAYOUT_BANK_PCT = float(settings["PAYOUT_BANK_PCT"])
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
# === КОНФИГУРАЦИЯ ===========================================================
# =============================================================================
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
]
WEBAPP_ADMIN_URL: str = os.getenv("WEBAPP_ADMIN_URL", "")
QUARANTINE_CHAT_ID: int = int(os.getenv("QUARANTINE_CHAT_ID", "0"))
ADMIN_VIP_CHANNEL_ID: int = int(os.getenv("ADMIN_VIP_CHANNEL_ID", "0"))
DEEPINFRA_API_KEY: str = os.getenv("DEEPINFRA_API_KEY", "")
STARS_PROVIDER_TOKEN: str = os.getenv("STARS_PROVIDER_TOKEN", "")
WEBAPP_HOST: str = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT: int = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8000")))
SAAS_DONOR_CHANNELS: list[str] = [
    x.strip() for x in os.getenv("SAAS_DONOR_CHANNELS", "").split(",") if x.strip()
]
TAKPRODAM_MASTER_TOKEN: str = os.getenv("TAKPRODAM_MASTER_TOKEN", "")

# Реквизиты оплаты
CARD_SBER: str = os.getenv("PAY_SBER", "2202 2081 0829 0025")
CARD_TBANK: str = os.getenv("PAY_TBANK", "2200 7013 7009 3863")
CARD_TON: str = os.getenv("PAY_CRYPTO_TON", "UQCua97IuHkQy5F5NPHBrDpay_FJRJoWZa1OOLnq-geGIbGT")
CARD_VISA_KG: str = os.getenv("PAY_VISA_KG", "4196720087839790")

# Тарифы
def kb_tariffs(traffic_source: str = "") -> InlineKeyboardMarkup:
    tariffs = load_tariffs()
    rows = []
    for t in tariffs:
        text = f"⭐ {t['name']} — {t['price_rub']:.0f} руб. / {t['price_stars']} ⭐"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"buy:{t['id']}:{t['days']}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# Ниже идут уже правильные константы, загруженные из настроек
MIN_PAYOUT = float(settings["MIN_PAYOUT"])
PAYOUT_FIXED_FEE = float(settings["PAYOUT_FIXED_FEE"])
PAYOUT_BANK_PCT = float(settings["PAYOUT_BANK_PCT"])
MAX_ACTIVE_PAYOUTS: int = 2
DB_PATH: str = "/app/data/autopost.db"


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

    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

# =============================================================================
# === FSM СОСТОЯНИЯ ===========================================================
# =============================================================================
class OnboardingStates(StatesGroup):
    waiting_role = State()
    waiting_channel = State()
    waiting_source_channel = State()
    waiting_saas_tg_channel = State()
    waiting_target_choice = State()
    waiting_video_link = State()

class AdminStates(StatesGroup):
    broadcast_text = State()
    extend_user_id = State()
    extend_days = State()

class SaasStates(StatesGroup):
    waiting_apikey = State()
    waiting_erid_override = State()
    waiting_promocode = State()          # ← добавить
    choosing_channel_for_promo = State() # ← добавить

class PaymentFSM(StatesGroup):
    choosing_tariff = State()
    choosing_method = State()
    waiting_for_receipt = State()
    waiting_promocode = State()
    choosing_channel_for_promo = State()

class PayoutStates(StatesGroup):
    waiting_for_card = State()
    waiting_for_amount = State()

  # =============================================================================
# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================================================
# =============================================================================
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

def is_night_time() -> bool:
    now = datetime.now(tz=timezone(timedelta(hours=3)))
    start_h, start_m = map(int, settings["NIGHT_START"].split(":"))
    end_h, end_m = map(int, settings["NIGHT_END"].split(":"))
    start = time(start_h, start_m)
    end = time(end_h, end_m)
    if start <= end:
        return start <= now.time() <= end
    else:
        return now.time() >= start or now.time() <= end

# =============================================================================
# === КЛАВИАТУРЫ ==============================================================
# =============================================================================
def kb_main_menu(role: str) -> InlineKeyboardMarkup:
    if role == "blogger":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💼 Личный кабинет", callback_data="cabinet:open")]
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💼 Личный кабинет", callback_data="cabinet:open")],
            [InlineKeyboardButton(text="📢 Мой канал", callback_data="menu:channel")],
            [InlineKeyboardButton(text="⚙️ Режим публикации", callback_data="menu:pub_mode")],
            [InlineKeyboardButton(text="🤝 Партнёрская программа", callback_data="menu:partner")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
            [InlineKeyboardButton(text="📖 Инструкции", callback_data="menu:instructions")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
            [InlineKeyboardButton(text="🎥 Отправить видео", callback_data="blogger:send_video")],
            [InlineKeyboardButton(text="📞 Поддержка", callback_data="support:contact")],
        ])

def kb_cabinet_menu(role: str) -> InlineKeyboardMarkup:
    if role == "saas":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Мои каналы", callback_data="menu:my_channels")],
            [InlineKeyboardButton(text="📂 Категории", callback_data="menu:categories")],
            [InlineKeyboardButton(text="💎 Продлить подписку", callback_data="menu:tariffs")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
            [InlineKeyboardButton(text="📖 Инструкции", callback_data="menu:instructions")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
            [InlineKeyboardButton(text="🎁 Активировать промокод", callback_data="promo:activate")],
            [InlineKeyboardButton(text="📞 Поддержка", callback_data="support:contact")],
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вывод средств", callback_data="payout:request")]
        ])

def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть Web-админку", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))],
        [InlineKeyboardButton(text="📣 Рассылка всем", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="💰 Запустить биллинг-чек", callback_data="admin:billing_check")],
        [InlineKeyboardButton(text="🔧 Продлить подписку", callback_data="admin:extend_sub")],
    ])

def kb_payment_methods() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💳 Банковская карта (Sber / Т-Банк / Visa KG)",
            callback_data="pay:card"
        )],
        [InlineKeyboardButton(
            text="⭐ Telegram Stars",
            callback_data="pay:stars"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
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

async def add_to_night_queue(
    user_id: int, video_id: str, description: str,
    sku: Optional[str], photo_url: Optional[str], marketplace: str = "wb"
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
    finally:
        conn.close()

async def add_to_saas_queue(
    user_id: int, channel_id: str, donor_post_id: str,
    original_text: str, photo_url: Optional[str],
    rewritten_text: Optional[str] = None,
    sku: Optional[str] = None,
    marketplace: str = "wb"
):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO saas_queue 
            (user_id, channel_id, donor_post_id, original_text, photo_url, rewritten_text, sku, marketplace)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, channel_id, donor_post_id, original_text, photo_url, rewritten_text, sku, marketplace)
        )
        conn.commit()
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
        return

    logger.info(f"🌅 Публикуем {len(rows)} отложенных постов")
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
            conn = get_db()
            conn.execute("DELETE FROM night_queue WHERE id=?", (row["id"],))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Ошибка flush_night_queue: {e}")
        await asyncio.sleep(10)


async def flush_saas_queue_for_user(bot: Bot, user_id: int):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM saas_queue WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return 0

    published_count = 0
    for row in rows:
        original_text = row["original_text"]
        channel_id = row["channel_id"]
        donor_post_id = row["donor_post_id"]
        marketplace = row["marketplace"] or "wb"

        # Проверка дневного лимита по тарифу
        conn_limit = get_db()
        try:
            tariff_row = conn_limit.execute(
                "SELECT t.max_posts_per_day FROM users u JOIN tariffs t ON u.tariff_id = t.id WHERE u.user_id = ?",
                (row["user_id"],)
            ).fetchone()
            max_posts = tariff_row["max_posts_per_day"] if tariff_row else 25
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            posts_today = conn_limit.execute(
                "SELECT COUNT(*) as cnt FROM posts WHERE user_id = ? AND channel_id = ? AND status = 'published' AND published_at >= ?",
                (row["user_id"], channel_id, today_start)
            ).fetchone()["cnt"]
        finally:
            conn_limit.close()

        if posts_today >= max_posts:
            continue  # лимит исчерпан, оставляем в очереди до следующего раза

        # Вызываем process_saas_core с оригинальным текстом, он сам найдёт URL и сгенерирует пост
        post_html = await process_saas_core(
            bot=bot,
            user_id=user_id,
            original_text=original_text,
            donor_post_id=donor_post_id,
            channel_id=channel_id,
            force_post=True
        )
        if not post_html:
            conn2 = get_db()
            conn2.execute("DELETE FROM saas_queue WHERE id = ?", (row["id"],))
            conn2.commit()
            conn2.close()
            continue

        photo_url = row["photo_url"]
        if not photo_url:
            photo_url = "https://wildberries.ru/favicon.ico" if marketplace == "WB" else "https://ozon.ru/favicon.ico"

        try:
            msg = await publish_post_with_fallback(
                bot=bot,
                channel_id=channel_id,
                caption=post_html,
                photo_url=photo_url
            )
            if not msg:
                continue

            # Авто-закреп, если включён
            conn_pin = get_db()
            try:
                pin_row = conn_pin.execute(
                    "SELECT auto_pin FROM users WHERE user_id = ?", (row["user_id"],)
                ).fetchone()
                auto_pin = bool(pin_row["auto_pin"]) if pin_row else False
            finally:
                conn_pin.close()

            if auto_pin:
                try:
                    await bot.pin_chat_message(chat_id=channel_id, message_id=msg.message_id)
                    unpin_time = datetime.now(timezone.utc) + timedelta(hours=24)
                    conn_pin2 = get_db()
                    conn_pin2.execute(
                        "INSERT INTO pinned_posts (chat_id, message_id, unpin_at) VALUES (?, ?, ?)",
                        (channel_id, msg.message_id, unpin_time.isoformat())
                    )
                    conn_pin2.commit()
                    conn_pin2.close()
                except Exception as e:
                    logger.warning(f"Не удалось закрепить пост: {e}")

            # Удаляем из очереди после успешной публикации
            conn_del = get_db()
            conn_del.execute("DELETE FROM saas_queue WHERE id = ?", (row["id"],))
            conn_del.commit()
            conn_del.close()
            published_count += 1
            await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Ошибка при публикации из очереди SaaS: {e}")

    return published_count
async def flush_all_saas_queues(bot: Bot):
    """Публикует все накопленные посты из SaaS-очереди для всех пользователей."""
    conn = get_db()
    try:
        # Получаем список уникальных user_id, у которых есть посты в saas_queue
        user_ids = conn.execute(
            "SELECT DISTINCT user_id FROM saas_queue"
        ).fetchall()
    finally:
        conn.close()

    if not user_ids:
        logger.info("🅰️ SaaS-очередь пуста")
        return

    logger.info(f"🅰️ Обрабатываю SaaS-очередь для {len(user_ids)} пользователей")
    for row in user_ids:
        await flush_saas_queue_for_user(bot, row["user_id"])
        await asyncio.sleep(2)  # небольшая пауза между пользователями
    logger.info("🅰️ Обработка SaaS-очереди завершена")


async def publish_from_categories(bot: Bot):
    """Публикует товары из API v2, а если их нет – репостит канал ТакПродам."""
    conn = get_db()
    try:
        users = conn.execute("""
            SELECT u.user_id, u.api_key
            FROM users u
            WHERE u.role = 'saas' AND u.is_active = 1
            AND u.subscription_until > datetime('now')
        """).fetchall()
    finally:
        conn.close()

    products = []   # будет наполнен, если API вернёт товары
    for user in users:
        api_key = user["api_key"]
        if not api_key:
            continue
        # Пробуем получить товары через API (WB + Ozon)
        prods = await fetch_products_from_takprodam(api_key, "Wildberries", 5)
        if prods:
            products.extend(prods)
        prods = await fetch_products_from_takprodam(api_key, "Ozon", 5)
        if prods:
            products.extend(prods)
        if products:   # если хоть один товар нашёлся – выходим
            break

    if not products:
        # API не дал товаров – забираем последний пост из канала ТакПродам
        for ch in SAAS_DONOR_CHANNELS:
            if ch.startswith("takprodam_"):
                posts = await fetch_telegram_channel_posts(ch)
                if posts:
                    last = posts[-1]
                    text = last.get("text", "")
                    photo_url = last.get("image_url")
                    if text:
                        # публикуем этот пост всем клиентам
                        for user in users:
                            conn = get_db()
                            try:
                                channels = conn.execute(
                                    "SELECT channel_id FROM channels WHERE user_id = ? AND is_active = 1",
                                    (user["user_id"],)
                                ).fetchall()
                            finally:
                                conn.close()
                            for c in channels:
                                await publish_post_with_fallback(
                                    bot=bot, channel_id=c["channel_id"],
                                    caption=text, photo_url=photo_url
                                )
                                await asyncio.sleep(1)
                        return  # закончили
                break
        return

    # Если API вернул товары – публикуем случайный
    product = random.choice(products)
    caption = (
        f"{product['title']}\n\n"
        f"💰 Цена: {product['price']}\n\n"
        f"<a href='{product['tracking_link']}'>👉 Посмотреть и заказать</a>\n\n"
        f"{product['legal_text']}"
    )
    for user in users:
        conn = get_db()
        try:
            channels = conn.execute(
                "SELECT channel_id FROM channels WHERE user_id = ? AND is_active = 1",
                (user["user_id"],)
            ).fetchall()
        finally:
            conn.close()
        for c in channels:
            await publish_post_with_fallback(
                bot=bot, channel_id=c["channel_id"],
                caption=caption, photo_url=product["image_url"]
            )
            await asyncio.sleep(1)
# =============================================================================
# === SAAS-ФУНКЦИИ (НОВЫЕ) ====================================================
# =============================================================================

async def fetch_takprodam_by_sku(token: str, sku: str) -> Optional[Dict[str, str]]:
    if not token:
        return None
    url = "https://api.takprodam.ru/v1/products/info"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params={"sku": sku})
        if resp.status_code != 200:
            logger.warning(f"ТакПродам API: статус {resp.status_code} для SKU {sku}")
            return None
        data = resp.json()
        link = data.get("link", "")
        erid = data.get("erid", "").strip()
        advertiser = data.get("advertiser", "").strip()
        image_url = data.get("image") or data.get("photo") or ""
        if not erid or not advertiser:
            logger.warning(f"ТакПродам: неполные данные для SKU {sku}: {data}")
            return None
        return {"link": link, "erid": erid, "advertiser": advertiser, "image_url": image_url}
    except Exception as e:
        logger.error(f"Ошибка при запросе к ТакПродам для SKU {sku}: {e}")
        return None
async def get_source_id(token: str) -> Optional[int]:
    """Получает source_id для токена (кэширует в БД)."""
    conn = get_db()
    try:
        cached = conn.execute("SELECT source_id FROM takprodam_sources WHERE token = ?", (token,)).fetchone()
        if cached:
            return cached["source_id"]
    finally:
        conn.close()

    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.takprodam.ru/v2/publisher/source/", headers=headers)
        if resp.status_code == 200:
            sources = resp.json().get("results", [])
            if sources:
                source_id = sources[0]["id"]
                conn = get_db()
                try:
                    conn.execute("INSERT OR REPLACE INTO takprodam_sources (token, source_id) VALUES (?, ?)", (token, source_id))
                    conn.commit()
                finally:
                    conn.close()
                return source_id
    except Exception as e:
        logger.error(f"get_source_id error: {e}")
    return None
async def fetch_products_from_takprodam(token: str, marketplace: str = "Wildberries", limit: int = 10) -> List[Dict]:
    """Получает список товаров с партнёрскими ссылками через API v2."""
    headers = {"Authorization": f"Bearer {token}"}

    # Получаем source_id (кэшируем в БД, чтобы не запрашивать каждый раз)
    conn = get_db()
    try:
        cached = conn.execute("SELECT source_id FROM takprodam_sources WHERE token = ?", (token,)).fetchone()
        if cached:
            source_id = cached["source_id"]
        else:
            # Запрашиваем список площадок
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://api.takprodam.ru/v2/publisher/source/", headers=headers)
            if resp.status_code != 200:
                logger.warning(f"Не удалось получить source_id: {resp.status_code}")
                return []
            sources = resp.json().get("results", [])
            if not sources:
                return []
            source_id = sources[0]["id"]  # берём первую площадку
            conn.execute("INSERT OR REPLACE INTO takprodam_sources (token, source_id) VALUES (?, ?)", (token, source_id))
            conn.commit()
    finally:
        conn.close()

    # Запрашиваем товары
    params = {
        "source_id": source_id,
        "marketplace": marketplace,
        "limit": limit
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get("https://api.takprodam.ru/v2/publisher/product/", headers=headers, params=params)
    if resp.status_code != 200:
        logger.warning(f"Ошибка получения товаров: {resp.status_code}")
        return []

    products = resp.json().get("results", [])
    result = []
    for p in products:
        result.append({
            "title": p.get("title"),
            "price": p.get("price"),
            "image_url": p.get("image_url"),
            "tracking_link": p.get("tracking_link"),
            "legal_text": p.get("legal_text"),  # готовая маркировка
        })
    return result
async def fetch_products_by_category(token: str, keyword: str, limit: int = 5) -> List[Dict]:
    """Получает топ товаров из ТакПродам по ключевому слову."""
    url = "https://api.takprodam.ru/v1/products/search"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"query": keyword, "limit": limit}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            logger.warning(f"Поиск ТакПродам: статус {resp.status_code}")
            return []
        data = resp.json()
        products = data.get("products", [])
        result = []
        for p in products:
            cashback = float(p.get("cashback", 0))
            result.append({
                "sku": p.get("sku"),
                "title": p.get("title"),
                "description": p.get("description"),
                "price": p.get("price"),
                "image_url": p.get("image") or p.get("photo") or "",
                "link": p.get("link"),
                "erid": p.get("erid"),
                "advertiser": p.get("advertiser"),
                "cashback": cashback,
            })
        return result
    except Exception as e:
        logger.error(f"fetch_products_by_category error: {e}")
        return []
async def resolve_erid(
    bot: Bot, user_id: int, url: str,
    donor_post_id: str = "unknown", channel_id: str = "unknown"
) -> Optional[Dict[str, str]]:
    """
    Генерирует партнёрскую ссылку через Deeplink API ТакПродам.
    Принимает прямую ссылку на товар (url), возвращает {link, erid, advertiser, image_url}.
    """
    db = get_db()
    try:
        row = db.execute(
            "SELECT api_key, client_erid_override FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    finally:
        db.close()

    if not row:
        return None

    api_key = row["api_key"] or ""
    override_erid = (row["client_erid_override"] or "").strip()

    erid = None
    advertiser = None
    partner_link = None
    image_url = None

    async def try_deeplink(token: str):
        nonlocal erid, advertiser, partner_link, image_url
        source_id = await get_source_id(token)
        if not source_id:
            logger.warning(f"Deeplink: не удалось получить source_id для токена {token[:4]}...")
            return
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"source_id": source_id, "target_url": url}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.takprodam.ru/v2/publisher/deeplink/",
                    headers=headers,
                    json=payload
                )
            if resp.status_code == 200:
                data = resp.json()
                partner_link = data.get("tracking_link") or data.get("link") or partner_link
                erid = (data.get("erid") or "").strip() or erid
                advertiser = (data.get("advertiser") or "").strip() or advertiser
                image_url = data.get("image_url") or data.get("image") or image_url
            else:
                logger.warning(f"Deeplink API error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Deeplink API exception: {e}")

    # Пробуем с клиентским токеном
    if api_key:
        await try_deeplink(api_key)

    # Если нет ERID, пробуем мастер-токен
    if not erid and TAKPRODAM_MASTER_TOKEN and TAKPRODAM_MASTER_TOKEN != api_key:
        await try_deeplink(TAKPRODAM_MASTER_TOKEN)

    # override_erid
    if not erid and override_erid:
        erid = override_erid

    if erid:
        return {
            "link": partner_link or url,
            "erid": erid,
            "advertiser": advertiser or "Рекламодатель",
            "image_url": image_url or ""
        }

    return None
  
async def prepare_post_content(original_text: str) -> Optional[dict]:
    """Находит прямую ссылку и возвращает информативный текст для рерайта."""
    products = find_product_links(original_text)
    if not products:
        return None

    # Берём первый URL
    url_item = None
    for p in products:
        if p.get("type") == "url":
            url_item = p
            break
    if not url_item:
        return None

    product_url = url_item["value"]
    marketplace = url_item.get("marketplace", "wb").upper()

    # Для рерайта берём исходный текст, но убираем только ссылки, оставляя описание товара
    clean_text = re.sub(r'https?://\S+', '', original_text).strip()
    # Если остался только мусор – возьмём фрагмент до первой ссылки
    if len(clean_text) < 15:
        clean_text = original_text.split('http')[0].strip()
    if not clean_text:
        clean_text = "Товар по ссылке"

    rewritten = await rewrite_text_with_ai(clean_text)

    return {
        "rewritten": rewritten,
        "url": product_url,
        "marketplace": marketplace
    }
async def process_saas_core(
    bot: Bot,
    user_id: int,
    original_text: str = "",
    donor_post_id: str = "unknown",
    channel_id: str = "unknown",
    force_post: bool = False,
    rewritten_text: Optional[str] = None,
    url: Optional[str] = None,
    marketplace: str = "WB"
) -> Optional[str]:
    """Формирует пост с партнёрской ссылкой и маркировкой."""

    # Ночной режим – сохраняем в очередь
    if not force_post and is_night_time():
        if not rewritten_text:
            prepared = await prepare_post_content(original_text)
            if prepared:
                await add_to_saas_queue(
                    user_id, channel_id, donor_post_id,
                    original_text, None,
                    rewritten_text=prepared["rewritten"],
                    sku=None,
                    marketplace=prepared["marketplace"]
                )
        return None

    # Подготавливаем контент, если ещё не готов
    if not rewritten_text or not url:
        prepared = await prepare_post_content(original_text)
        if not prepared:
            if force_post:
                clean_text = re.sub(r'https?://\S+', '', original_text).strip()
                rewritten = await rewrite_text_with_ai(clean_text)
                rewritten = re.sub(r'\bMAX\s*\(\s*клик\s*\)\b', '', rewritten, flags=re.IGNORECASE)
                return f"{rewritten}\n\n<i>Реклама</i>"
            return None
        rewritten_text = prepared["rewritten"]
        url = prepared["url"]
        marketplace = prepared["marketplace"]

    # Убираем из рерайта остатки ссылок и мусор
    clean_rewritten = re.sub(r'https?://\S+', '', rewritten_text).strip()
    clean_rewritten = re.sub(r'\bMAX\s*\(\s*клик\s*\)\b', '', clean_rewritten, flags=re.IGNORECASE)
    clean_rewritten = re.sub(r'\s+', ' ', clean_rewritten).strip()

    # Получаем партнёрскую ссылку через Deeplink API
    erid_data = await resolve_erid(bot, user_id, url, donor_post_id, channel_id)

    if erid_data and erid_data.get("erid"):
        link = erid_data["link"]
        advertiser = erid_data["advertiser"]
        erid = erid_data["erid"]
        post_html = (
            f"{clean_rewritten}\n\n"
            f"👉 <a href='{link}'>Посмотреть и заказать</a>\n\n"
            f"Реклама. {advertiser}. Erid: {erid}"
        )
    else:
        # Если Deeplink не сработал – просто прямая ссылка
        if force_post:
            post_html = (
                f"{clean_rewritten}\n\n"
                f"👉 <a href='{url}'>Посмотреть и заказать</a>\n\n"
                f"Реклама"
            )
        else:
            return None

    return post_html
async def scan_donor_channels(bot: Bot, force_post: bool = False) -> None:
    if not SAAS_DONOR_CHANNELS:
        return

    for channel in SAAS_DONOR_CHANNELS:
        logger.info(f"🔍 Сканирую донора: {channel}")
        try:
            posts = await fetch_telegram_channel_posts(channel)
        except Exception as e:
            logger.error(f"Ошибка получения постов из {channel}: {e}")
            continue

        for post in posts:
            post_id = post.get("id")
            if not post_id:
                continue
            full_donor_id = f"saas_{channel}_{post_id}"
            text = post.get("text", "")
            text = re.sub(r'\bMAX\s*\(\s*клик\s*\)\b', '', text, flags=re.IGNORECASE)
            photo_url = post.get("image_url")

            # Проверка дубликатов
            if not force_post:
                db = get_db()
                try:
                    row = db.execute(
                        "SELECT 1 FROM posts WHERE donor_post_id = ? LIMIT 1",
                        (full_donor_id,)
                    ).fetchone()
                    if row:
                        continue
                finally:
                    db.close()

            prepared = await prepare_post_content(text)
            if not prepared and not force_post:
                continue

            # Получаем всех активных SaaS-пользователей
            db = get_db()
            try:
                saas_rows = db.execute("""
                    SELECT u.user_id, c.channel_id
                    FROM users u
                    JOIN channels c ON c.user_id = u.user_id AND c.is_active = 1
                    WHERE u.role = 'saas'
                    AND u.is_active = 1
                    AND u.subscription_until IS NOT NULL
                    AND u.subscription_until > datetime('now')
                """).fetchall()
            finally:
                db.close()

            for row in saas_rows:
                user_id = row["user_id"]
                target_channel = row["channel_id"]

                # Проверка, чтобы донор не получал свои же посты
                if target_channel.lstrip("@").lower() == channel.lstrip("@").lower():
                    continue

                # Читаем настройку auto_pin
                conn_pin = get_db()
                try:
                    pin_row = conn_pin.execute(
                        "SELECT auto_pin FROM users WHERE user_id = ?", (user_id,)
                    ).fetchone()
                    auto_pin = bool(pin_row["auto_pin"]) if pin_row else False
                finally:
                    conn_pin.close()

                post_html = await process_saas_core(
                    bot=bot,
                    user_id=user_id,
                    donor_post_id=full_donor_id,
                    channel_id=target_channel,
                    force_post=force_post,
                    rewritten_text=prepared["rewritten"] if prepared else None,
                    url=prepared["url"] if prepared else None,
                    marketplace=prepared["marketplace"] if prepared else "WB"
                )
                if not post_html:
                    continue

                                # Пытаемся получить фото через Deeplink API
                if prepared and prepared.get("url"):
                    erid_data = await resolve_erid(bot, user_id, prepared["url"], full_donor_id, target_channel)
                    if erid_data and erid_data.get("image_url"):
                        photo_url = erid_data["image_url"]

                # Если фото нет – пробуем запросить товар через мастер-токен (он часто возвращает фото)
                if not photo_url and prepared and prepared.get("url"):
                    try:
                        product_data = await fetch_takprodam_by_sku(TAKPRODAM_MASTER_TOKEN, prepared["url"])
                        if product_data and product_data.get("image_url"):
                            photo_url = product_data["image_url"]
                    except Exception:
                        pass

                # Если и так нет – оставляем фото из донора (может сработать)
                if not photo_url:
                    photo_url = post.get("image_url")

                # Публикуем (если photo_url None – будет отправлен текст)
                msg = await publish_post_with_fallback(
                    bot=bot,
                    channel_id=target_channel,
                    caption=post_html,
                    photo_url=photo_url
                )
                if not msg:
                    continue

                # Авто-закреп
                if auto_pin:
                    try:
                        await bot.pin_chat_message(chat_id=target_channel, message_id=msg.message_id)
                        unpin_time = datetime.now(timezone.utc) + timedelta(hours=24)
                        conn_pin2 = get_db()
                        conn_pin2.execute(
                            "INSERT INTO pinned_posts (chat_id, message_id, unpin_at) VALUES (?, ?, ?)",
                            (target_channel, msg.message_id, unpin_time.isoformat())
                        )
                        conn_pin2.commit()
                        conn_pin2.close()
                    except Exception as e:
                        logger.warning(f"Не удалось закрепить пост: {e}")

                # Запись в БД
                conn_rec = get_db()
                try:
                    conn_rec.execute(
                        "INSERT INTO posts (user_id, donor_post_id, channel_id, target_channel_id, status, published_at) "
                        "VALUES (?, ?, ?, ?, 'published', ?)",
                        (user_id, full_donor_id, target_channel, target_channel,
                         datetime.now(timezone.utc).isoformat())
                    )
                    conn_rec.commit()
                finally:
                    conn_rec.close()

                logger.info(f"✅ Пост {full_donor_id} опубликован в {target_channel}")
            await asyncio.sleep(1)
          
async def publish_post_with_fallback(
    bot: Bot,
    channel_id: str,
    caption: str,
    photo_url: Optional[str] = None,
    video_url: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    if video_url:
        try:
            return await bot.send_video(
                chat_id=channel_id, video=video_url,
                caption=caption, parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        except TelegramAPIError as e:
            logger.warning(f"Видео отклонено: {e}. Пробуем фото/текст...")

    if photo_url:
        try:
            return await bot.send_photo(
                chat_id=channel_id, photo=photo_url,
                caption=caption, parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        except TelegramAPIError as e:
            if "wrong type" not in str(e).lower():
                logger.error(f"Ошибка фото: {e}")
                return None
            logger.warning(f"Фото отклонено: {e}. Пробуем текст...")

    try:
        return await bot.send_message(
            chat_id=channel_id, text=caption,
            parse_mode=ParseMode.HTML, reply_markup=reply_markup,
            disable_web_page_preview=False
        )
    except TelegramAPIError as e:
        logger.error(f"Ошибка текста: {e}")
        return None
      
# =============================================================================
# === ROUTER & HANDLERS =======================================================
# =============================================================================
print("DEBUG: creating router", flush=True, file=sys.stderr)
router = Router()

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
            await message.answer("⚠️ Вы ещё не привязали свой канал.\nПерешлите сообщение из канала.")
            await state.set_state(OnboardingStates.waiting_source_channel)
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# /cabinet, "💻 Личный кабинет"
# ---------------------------------------------------------------------------
@router.message(Command("cabinet"))
async def cmd_cabinet(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("🛠 Панель администратора:", reply_markup=kb_admin_panel())
    else:
        await show_user_cabinet(message, user_id=message.from_user.id)

@router.message(F.text.in_(["💻 Личный кабинет", "/cabinet"]))
async def show_cabinet(message: Message):
    await show_user_cabinet(message, user_id=message.from_user.id)

# ---------------------------------------------------------------------------
# Обработка роли
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("set_role:"))
async def cb_set_role(callback: CallbackQuery, state: FSMContext):
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
            "✅ Выбрана роль: <b>БЛОГЕР</b>.\n\nПришлите ссылку на ваш основной канал (YouTube, TikTok или Instagram).",
            parse_mode=ParseMode.HTML
        )
    else:
        await state.set_state(OnboardingStates.waiting_saas_tg_channel)
        await callback.message.edit_text(
            "✅ Выбрана роль: <b>SaaS-клиент</b>.\n\nПришлите @username вашего Telegram-канала.",
            parse_mode=ParseMode.HTML
        )
    await callback.answer()

# ---------------------------------------------------------------------------
# Показ личного кабинета
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
        await callback.message.answer("Главное меню:", reply_markup=kb_main_menu(role))

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

async def _show_saas_stats(callback: CallbackQuery, user_id: int, channel_idx: int, period: str) -> None:
    channels = get_saas_channels(user_id)
    if not channels:
        await callback.message.edit_text(
            "📊 <b>Статистика</b>\n\nУ вас ещё нет подключённых каналов.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
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

@router.callback_query(F.data == "menu:categories")
async def cb_categories(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        all_cats = conn.execute("SELECT id, name FROM product_categories WHERE is_active = 1").fetchall()
        user_cats = conn.execute("SELECT category_id FROM user_category_preferences WHERE user_id = ?", (user_id,)).fetchall()
        user_cat_ids = {r["category_id"] for r in user_cats}
    finally:
        conn.close()

    text = "📂 <b>Выберите категории товаров:</b>\n\n"
    kb_rows = []
    for cat in all_cats:
        emoji = "✅" if cat["id"] in user_cat_ids else "❌"
        text += f"{emoji} {cat['name']}\n"
        kb_rows.append([InlineKeyboardButton(
            text=f"{emoji} {cat['name']}",
            callback_data=f"cat_toggle:{cat['id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("cat_toggle:"))
async def cb_toggle_category(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    conn = get_db()
    try:
        existing = conn.execute("SELECT 1 FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                                (user_id, cat_id)).fetchone()
        if existing:
            conn.execute("DELETE FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                         (user_id, cat_id))
        else:
            # Проверка лимита по тарифу
            tariff = conn.execute("SELECT t.max_categories FROM users u JOIN tariffs t ON u.tariff_id = t.id WHERE u.user_id = ?",
                                  (user_id,)).fetchone()
            max_cat = tariff["max_categories"] if tariff and tariff["max_categories"] else 3
            current_count = conn.execute("SELECT COUNT(*) as cnt FROM user_category_preferences WHERE user_id = ?",
                                         (user_id,)).fetchone()["cnt"]
            if current_count >= max_cat:
                await callback.answer(f"❌ Ваш тариф позволяет выбрать не более {max_cat} категорий", show_alert=True)
                return
            conn.execute("INSERT INTO user_category_preferences (user_id, category_id) VALUES (?, ?)",
                         (user_id, cat_id))
        conn.commit()
    finally:
        conn.close()
    await cb_categories(callback)
    await callback.answer()
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
        reply_markup=kb_main_menu(role)
    )

# =============================================================================
# === РЕЖИМ ПУБЛИКАЦИИ (БЛОГЕР) ===============================================
# =============================================================================
@router.callback_query(F.data == "menu:pub_mode")
async def cb_menu_pub_mode(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT blogger_mode FROM users WHERE user_id=?", (user_id,)).fetchone()
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

@router.callback_query(F.data == "blogger:send_video")
async def cb_blogger_send_video(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎥 Отправьте ссылку на видео (YouTube, TikTok, Instagram), и бот сразу обработает его.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:main")]
        ])
    )
    await state.set_state(OnboardingStates.waiting_video_link)
    await callback.answer()

@router.message(OnboardingStates.waiting_video_link)
async def blogger_video_link_received(message: Message, state: FSMContext):
    url = message.text.strip()
    user_id = message.from_user.id

    # Проверяем, что пользователь – блогер и у него привязан канал
    conn = get_db()
    user = conn.execute("SELECT channel_id, sub_id, blogger_mode FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not user or not user["channel_id"]:
        await message.answer("❌ Сначала привяжите канал в разделе «📢 Мой канал».")
        await state.clear()
        return

    # Извлекаем информацию о видео
    info = extract_video_info(url)
    if not info:
        await message.answer("❌ Не удалось обработать ссылку. Проверьте правильность URL.")
        await state.clear()
        return

    video_id = info.get('id') or info.get('display_id')
    description = info.get('description') or info.get('title')
    photo_url = info.get('thumbnail')
    sku_list = find_product_links(description)
    sku = sku_list[0]['value'] if sku_list else None
    marketplace = sku_list[0].get('marketplace', 'wb') if sku_list else 'wb'

    # Запускаем процесс публикации
    from parser import process_new_video
    await process_new_video(
        bot=message.bot,
        user_id=user_id,
        video_id=video_id,
        description=description,
        sku=sku,
        photo_url=photo_url,
        marketplace=marketplace,
    )

    await message.answer("✅ Видео обработано! Пост отправлен в ваш канал.")
    await state.clear()

@router.callback_query(F.data.startswith("blogger_mode:"))
async def cb_set_blogger_mode(callback: CallbackQuery) -> None:
    mode = callback.data.split(":")[1]
    if mode not in ("direct", "vip_pin"):
        await callback.answer("❌ Неизвестный режим", show_alert=True)
        return
    conn = get_db()
    try:
        conn.execute("UPDATE users SET blogger_mode=? WHERE user_id=?", (mode, callback.from_user.id))
        conn.commit()
    finally:
        conn.close()
    labels = {"direct": "Напрямую в канал", "vip_pin": "VIP-закреп (24ч)"}
    await callback.answer(f"✅ Режим изменён: {labels[mode]}", show_alert=False)
    await callback.message.edit_text(
        "⚙️ <b>Режим публикации</b>\n\nВыберите как публиковать посты:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_blogger_mode(mode)
    )

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

@router.callback_query(F.data == "saas_force_post")
async def cb_saas_force_post(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer("🚀 Публикую накопленные посты...", show_alert=True)
    try:
        count = await flush_saas_queue_for_user(bot, callback.from_user.id)
        if count > 0:
            await callback.message.answer(f"✅ Опубликовано {count} постов из очереди.")
        else:
            await callback.message.answer("ℹ️ В очереди нет постов.")
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")

@router.callback_query(F.data == "saas_set:apikey")
async def cb_saas_set_apikey(callback: CallbackQuery, state: FSMContext) -> None:
    text = (
        "🔑 <b>Настройка API-ключа</b>\n\n"
        "Отправьте сообщением ваш API-ключ от ТакПродам.\n"
        "<i>Если вы хотите удалить ключ, отправьте цифру 0</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:settings")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await state.set_state(SaasStates.waiting_apikey)
    await callback.answer()

@router.message(SaasStates.waiting_apikey)
async def msg_saas_apikey_input(message: Message, state: FSMContext) -> None:
    api_key = message.text.strip()
    user_id = message.from_user.id
    if api_key == "0":
        api_key = None
        ans_text = "🗑 API-ключ удалён."
    else:
        ans_text = "✅ API-ключ успешно сохранён!"
    conn = get_db()
    try:
        conn.execute("UPDATE users SET api_key=? WHERE user_id=?", (api_key, user_id))
        conn.commit()
    finally:
        conn.close()
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Вернуться в настройки", callback_data="menu:settings")]
    ])
    await message.answer(ans_text, reply_markup=kb)

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


# =============================================================================
# === АКТИВАЦИЯ ПРОМОКОДА =====================================================
# =============================================================================
@router.callback_query(F.data == "promo:activate")
async def cb_promo_activate(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎁 Введите промокод:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")]
        ])
    )
    await state.set_state(SaasStates.waiting_promocode)
    await callback.answer()

@router.message(SaasStates.waiting_promocode)
async def promo_code_entered(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    conn = get_db()
    try:
        # Проверяем существование кода
        promo = conn.execute(
            "SELECT * FROM promocodes WHERE code = ?", (code,)
        ).fetchone()
        if not promo:
            await message.answer("❌ Неверный или несуществующий промокод.")
            await state.clear()
            return

        # Проверяем, не был ли код уже активирован
        activation = conn.execute(
            "SELECT * FROM promocode_activations WHERE code = ?", (code,)
        ).fetchone()
        if activation:
            await message.answer("❌ Этот промокод уже использован.")
            await state.clear()
            return

        # Получаем каналы пользователя
        channels = conn.execute(
            "SELECT channel_id, channel_title FROM channels WHERE user_id = ? AND is_active = 1",
            (message.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    if not channels:
        await message.answer("❌ У вас нет подключённых каналов. Сначала добавьте канал в разделе «Мои каналы».")
        await state.clear()
        return

    # Сохраняем код в FSM
    await state.update_data(promocode=code, promo_days=promo["days"])
    
    kb_rows = []
    for ch in channels:
        kb_rows.append([
            InlineKeyboardButton(
                text=ch["channel_title"] or ch["channel_id"],
                callback_data=f"promo_channel:{ch['channel_id']}"
            )
        ])
    kb_rows.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")])
    
    await message.answer(
        "🎯 Выберите канал, для которого хотите активировать промокод:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )
    await state.set_state(SaasStates.choosing_channel_for_promo)

@router.callback_query(SaasStates.choosing_channel_for_promo, F.data.startswith("promo_channel:"))
async def promo_channel_selected(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.split(":")[1]
    data = await state.get_data()
    code = data.get("promocode")
    days = data.get("promo_days", 2)
    
    conn = get_db()
    try:
        # Повторная проверка на уже совершённую активацию (защита от гонки)
        existing = conn.execute(
            "SELECT * FROM promocode_activations WHERE code = ?", (code,)
        ).fetchone()
        if existing:
            await callback.message.answer("❌ Промокод уже использован.")
            await state.clear()
            return

        # Записываем активацию
        conn.execute(
            "INSERT INTO promocode_activations (code, user_id, channel_id) VALUES (?, ?, ?)",
            (code, callback.from_user.id, channel_id)
        )
        # Активируем подписку
        new_until = datetime.now(timezone.utc) + timedelta(days=days)
        conn.execute(
            "UPDATE users SET subscription_until = ?, is_active = 1 WHERE user_id = ?",
            (new_until.isoformat(), callback.from_user.id)
        )
        conn.commit()
    finally:
        conn.close()
    
    await callback.message.edit_text(
        f"✅ Промокод активирован!\nПодписка продлена на {days} дн. до {new_until.strftime('%d.%m.%Y %H:%M')} (UTC)."
    )
    await state.clear()
    await callback.answer("Готово!", show_alert=True)


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

@router.message(Command("debug_scan"))
async def debug_scan(message: Message):
    await message.answer("🔄 Запускаю принудительное сканирование доноров...")
    try:
        await scan_donor_channels(message.bot, force_post=True)
        await message.answer("✅ Сканирование завершено. Проверь логи.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

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
# === ОНБОРДИНГ: БЛОГЕР – ПРИВЯЗКА ИСТОЧНИКА =================================
# =============================================================================
@router.message(OnboardingStates.waiting_source_channel)
async def handle_blogger_source(message: Message, state: FSMContext) -> None:
    source_link = message.text.strip()
    user_id = message.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET source_link=? WHERE user_id=?", (source_link, user_id))
        conn.commit()
    finally:
        conn.close()
    await state.set_state(OnboardingStates.waiting_target_choice)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Публиковать в свой канал", callback_data="target:own")],
        [InlineKeyboardButton(text="⭐ VIP-канал (24ч закреп)", callback_data="target:vip")],
    ])
    await message.answer(
        "✅ Источник привязан!\n\nВыберите режим публикации:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

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
    else:  # vip
        await state.clear()
        await callback.message.edit_text("✅ Регистрация завершена! Подписка на VIP-канал активна.")
        await callback.message.answer("🏠 Главное меню", reply_markup=kb_main_menu("blogger"))

# =============================================================================
# === ОНБОРДИНГ: SAAS – ДОБАВЛЕНИЕ КАНАЛА =====================================
# =============================================================================
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
        # Проверка лимита каналов по тарифу
        user = conn.execute("SELECT tariff_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user and user["tariff_id"]:
            tariff = conn.execute("SELECT max_channels FROM tariffs WHERE id = ?", (user["tariff_id"],)).fetchone()
            max_channels = tariff["max_channels"] if tariff else 5
            current_count = conn.execute("SELECT COUNT(*) as cnt FROM channels WHERE user_id = ?", (user_id,)).fetchone()["cnt"]
            if current_count >= max_channels:
                await message.answer(f"❌ Ваш тариф позволяет подключить не более {max_channels} каналов.")
                return

        conn.execute(
            """INSERT INTO channels (user_id, channel_id, channel_title)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, channel_id) DO UPDATE SET channel_title = excluded.channel_title""",
            (user_id, channel_username, channel_username)
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка добавления канала: {e}")
    finally:
        conn.close()

    await message.answer(
        f"✅ Канал <b>{html.escape(channel_username)}</b> успешно добавлен!",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu("saas")
    )
    await state.clear()

# =============================================================================
# === SAAS: МЕНЮ "МОИ КАНАЛЫ" =================================================
# =============================================================================
@router.callback_query(F.data == "menu:my_channels")
async def cb_my_channels(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        channels = conn.execute(
            "SELECT channel_title, channel_id FROM channels WHERE user_id=? AND is_active=1",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    if channels:
        text = "📢 <b>Ваши подключенные каналы:</b>\n\n"
        for i, ch in enumerate(channels, 1):
            text += f"{i}. {ch['channel_title']} (<code>{ch['channel_id']}</code>)\n"
        text += "\n<i>Для добавления нового канала отправьте его @username прямо сейчас.</i>"
    else:
        text = "📢 <b>У вас пока нет подключенных каналов.</b>\n\nДля добавления канала отправьте его @username."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except:
        pass
    await state.set_state(OnboardingStates.waiting_saas_tg_channel)
    await callback.answer()

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

    api_key_status = "✅ Установлен" if user["api_key"] else "❌ Не задан"
    auto_pin = bool(user["auto_pin"] if user["auto_pin"] is not None else 1)
    wb = bool(user["filter_wb"] if user["filter_wb"] is not None else 1)
    ozon = bool(user["filter_ozon"] if user["filter_ozon"] is not None else 1)

    text = (
        "⚙️ <b>Настройки SaaS-аккаунта</b>\n\n"
        f"🔑 <b>API-ключ (ТакПродам):</b> {api_key_status}\n"
        "<i>(Необходим для получения партнёрских ссылок и ERID)</i>\n\n"
        "Управляйте настройками автопостинга с помощью кнопок ниже:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Изменить API-ключ", callback_data="saas_set:apikey")],
        [
            InlineKeyboardButton(text=f"🛒 WB: {'✅' if wb else '❌'}", callback_data="saas_toggle:wb"),
            InlineKeyboardButton(text=f"🛒 Ozon: {'✅' if ozon else '❌'}", callback_data="saas_toggle:ozon")
        ],
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
async def cb_open_cabinet(callback: CallbackQuery) -> None:
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
        "─ Перейди в «📢 Мой канал» и отправь @username своего Telegram-канала или "
        "перешли любое сообщение из него.\n"
        "─ Бот проверит права и запомнит канал.\n\n"
        "<b>2. Отправка видео</b>\n"
        "─ Нажми «🎥 Отправить видео» в главном меню.\n"
        "─ Пришли ссылку на видео из YouTube, TikTok или Instagram.\n"
        "─ Бот найдёт артикулы (SKU) Wildberries/Ozon в описании, сделает рерайт, "
        "получит партнёрскую ссылку и опубликует готовый пост с маркировкой (ERID).\n\n"
        "<b>3. Режимы публикации</b>\n"
        "─ В разделе «⚙️ Режим публикации» можно выбрать:\n"
        "   • «Напрямую в мой канал» — пост придёт в твой Telegram-канал.\n"
        "   • «VIP-закреп в главном канале (24ч)» — пост отправится в VIP-канал, "
        "который настроил администратор, и будет закреплён на 24 часа.\n\n"
        "<b>4. Ночной режим</b>\n"
        "─ С 23:00 до 08:00 (МСК) посты не публикуются сразу, а попадают в очередь. "
        "Они будут автоматически отправлены утром в 08:00.\n\n"
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
        "─ Получи API-ключ в личном кабинете ТакПродам.\n"
        "─ Введи его в боте: «⚙️ Настройки» → «🔑 Изменить API-ключ».\n"
        "─ Оплати подписку или активируй промокод на 2 дня.\n\n"
        "<b>2. Подключение каналов</b>\n"
        "─ Перейди в «📢 Мои каналы» и отправь @username своего канала (можно несколько).\n"
        "─ Бот проверит права администратора и добавит канал.\n\n"
        "<b>3. Автоматический постинг</b>\n"
        "─ Бот сам сканирует каналы-доноры (их настраивает администратор).\n"
        "─ Каждые 15 минут он проверяет новые посты, делает рерайт и публикует их в твои каналы.\n"
        "─ Пост содержит: уникальное описание, артикул товара, партнёрскую ссылку с твоим sub_id, "
        "маркировку (ERID) и название рекламодателя.\n\n"
        "<b>4. Ночной режим и очередь</b>\n"
        "─ С 23:00 до 08:00 (МСК) посты не выходят, а сохраняются в твою личную очередь.\n"
        "─ Ты можешь в любой момент нажать «🚀 Опубликовать сейчас (Force Post)» в настройках, "
        "и все накопленные посты выйдут мгновенно (даже ночью).\n\n"
        "<b>5. Авто-закреп</b>\n"
        "─ В настройках можно включить автоматическое закрепление постов в канале.\n\n"
        "<b>6. Промокоды</b>\n"
        "─ В личном кабинете есть кнопка «🎁 Активировать промокод».\n"
        "─ Введи код и выбери канал — подписка продлится на 2 дня.\n"
        "─ Один код действует один раз на один канал.\n\n"
        "<b>7. Если нет ERID</b>\n"
        "─ Пост без ERID будет заблокирован и отправлен на проверку администратору (карантин).\n\n"
        "<i>По всем вопросам обращайся к администратору.</i>"
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
@router.callback_query(F.data == "menu:tariffs")
async def cb_tariffs(callback: CallbackQuery) -> None:
    """Показывает список тарифов для выбора."""
    await callback.message.edit_text(
        "💎 <b>Выберите тариф:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_tariffs()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("buy:"))
async def cb_select_tariff(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал тариф – сохраняем и предлагаем оплату."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return
    tariff_id = int(parts[1])
    days = int(parts[2])
    await state.update_data(chosen_tariff_id=tariff_id, chosen_days=days)
    await callback.message.edit_text(
        "💎 <b>Выберите способ оплаты:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_payment_methods()
    )
    await callback.answer()

@router.callback_query(F.data == "pay:stars")
async def cb_pay_stars(callback: CallbackQuery, state: FSMContext) -> None:
    """Оплата звёздами — выставляет счёт."""
    data = await state.get_data()
    tariff_id = data.get("chosen_tariff_id")
    days = data.get("chosen_days")
    if not tariff_id:
        await callback.answer("❌ Сначала выберите тариф", show_alert=True)
        return

    conn = get_db()
    try:
        tariff = conn.execute("SELECT name, price_stars FROM tariffs WHERE id=?", (tariff_id,)).fetchone()
        if not tariff:
            await callback.answer("Тариф не найден", show_alert=True)
            return
        stars = tariff["price_stars"]
        name = tariff["name"]
    finally:
        conn.close()

    # Отправляем счёт через Telegram Stars
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Подписка {name}",
        description=f"Доступ на {days} дней ко всем функциям AutoPost.",
        payload=f"tariff_{tariff_id}_{days}",
        currency="XTR",
        prices=[
            LabeledPrice(label=f"{name} ({days} дн.)", amount=stars)
        ],
        provider_token="",  # для XTR не нужен
        start_parameter="subscribe",
    )
    await callback.message.edit_text(
        "⭐ <b>Счёт отправлен в чат!</b>\n\nОплатите его, и подписка активируется автоматически.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tariffs")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "pay:card")
async def cb_pay_card(callback: CallbackQuery, state: FSMContext) -> None:
    """Оплата картой – показывает реквизиты и генерирует уникальный код заказа."""
    data = await state.get_data()
    tariff_id = data.get("chosen_tariff_id")
    days = data.get("chosen_days")
    if not tariff_id:
        await callback.answer("❌ Сначала выберите тариф", show_alert=True)
        return

    conn = get_db()
    try:
        tariff = conn.execute("SELECT name, price_rub FROM tariffs WHERE id=?", (tariff_id,)).fetchone()
        if not tariff:
            await callback.answer("Тариф не найден", show_alert=True)
            return
        rub = tariff["price_rub"]
        name = tariff["name"]
    finally:
        conn.close()

    # Генерируем короткий код заказа: например, T3-U7152107861
    order_code = f"T{tariff_id}-U{callback.from_user.id}"

    # Сохраняем намерение в БД (опционально, но удобно для истории)
    conn = get_db()
    conn.execute(
        "INSERT INTO payouts (user_id, amount_requested, amount_to_withdraw, amount_blogger, card, status) "
        "VALUES (?, ?, ?, ?, ?, 'pending')",
        (callback.from_user.id, rub, rub, 0, order_code)
    )
    conn.commit()
    conn.close()

    text = (
        f"💳 <b>Оплата картой</b>\n\n"
        f"Тариф: <b>{name}</b> ({days} дн.)\n"
        f"Сумма: <b>{rub:.0f} ₽</b>\n\n"
        f"💬 <b>Ваш код заказа:</b> <code>{order_code}</code>\n"
        f"<i>Обязательно укажите этот код в комментарии к платежу!</i>\n\n"
        f"Сбер: <code>{CARD_SBER}</code>\n"
        f"Т-Банк: <code>{CARD_TBANK}</code>\n"
        f"Visa KG: <code>{CARD_VISA_KG}</code>\n\n"
        f"TON: <code>{CARD_TON}</code>\n\n"
        "После оплаты пришлите чек администратору.\n"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tariffs")]
        ])
    )
    await callback.answer()
def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(run_billing_check, trigger="interval", hours=1, kwargs={"bot": bot}, id="billing_check", replace_existing=True)
    scheduler.add_job(flush_night_queue, trigger="cron", hour=8, minute=0, kwargs={"bot": bot}, id="flush_night_queue", replace_existing=True)
    scheduler.add_job(flush_all_saas_queues, trigger="cron", hour=8, minute=0, kwargs={"bot": bot}, id="flush_saas_queues", replace_existing=True)
    scheduler.add_job(unpin_old_messages, trigger="interval", minutes=30, kwargs={"bot": bot}, id="unpin_vip_posts", replace_existing=True)
    scheduler.add_job(cleanup_old_posts, trigger="cron", hour=3, minute=0, id="cleanup_old_posts", replace_existing=True)
    scheduler.add_job(scan_donor_channels, trigger="interval", minutes=15, kwargs={"bot": bot}, id="scan_donors", replace_existing=True)
    #scheduler.add_job(publish_from_categories, trigger="interval", minutes=30, kwargs={"bot": bot}, id="publish_categories", replace_existing=True)
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
    dp.include_router(router)

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планировщик (APScheduler) запущен")

    # ---------- Установка команд ----------
    # Обычные пользователи
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="cabinet", description="Личный кабинет"),
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
                    BotCommand(command="debug_scan", description="Принудительное сканирование доноров"),
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

   

if __name__ == "__main__":
    asyncio.run(main())
  
# =============================================================================
# === FASTAPI (ПОЛНАЯ АДМИН-ПАНЕЛЬ) ===========================================
# =============================================================================
