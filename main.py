"""
=============================================================================
  РђР’РўРћРџРћРЎРўРРќР“-Р‘РћРў | SaaS-РїР»Р°С‚С„РѕСЂРјР° РґР»СЏ РјРѕРЅРµС‚РёР·Р°С†РёРё Telegram-РєР°РЅР°Р»РѕРІ
  Stack: Python 3.10+, aiogram 3.x, FastAPI, SQLite3, httpx, APScheduler
  Р®СЂРёРґРёС‡РµСЃРєР°СЏ Р·Р°С‰РёС‚Р°: ERID РѕР±СЏР·Р°С‚РµР»РµРЅ. РџСѓР±Р»РёРєР°С†РёСЏ Р±РµР· РјР°СЂРєРёСЂРѕРІРєРё вЂ” Р·Р°РїСЂРµС‰РµРЅР°.
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
import hashlib
import xlsxwriter
from aiogram.types import FSInputFile
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET
from logging.handlers import RotatingFileHandler
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
    publish_from_catalog,
    publish_cpc_campaigns
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, Request, HTTPException
from states import OnboardingStates, SaasStates, AdminStates, PaymentFSM, PayoutStates
from services.db import get_db
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
from helpers import show_user_cabinet, safe_edit

logger = logging.getLogger("autopost_bot.referral")
# ---------------------------------------------------------------------------

print("DEBUG: main.py started", flush=True, file=sys.stderr)

import httpx
import uvicorn
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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
            logger.exception(f"РћС€РёР±РєР° РїСЂРё РѕР±СЂР°Р±РѕС‚РєРµ СЃРѕР±С‹С‚РёСЏ: {e}")
            # РќР• РїРµСЂРµРІС‹Р±СЂР°СЃС‹РІР°РµРј РёСЃРєР»СЋС‡РµРЅРёРµ вЂ” РѕРґРёРЅ СЃР±РѕР№РЅС‹Р№ С…РµРЅРґР»РµСЂ РЅРµ РґРѕР»Р¶РµРЅ РІР°Р»РёС‚СЊ РІРµСЃСЊ Р±РѕС‚
            return


# =============================================================================
# === РРќРР¦РРђР›РР—РђР¦РРЇ Р‘Р” ========================================================
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
        CREATE TABLE IF NOT EXISTS store_delivery (
            store TEXT PRIMARY KEY,
            delivery_text TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    # РњРёРіСЂР°С†РёРё
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

    # Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Рµ РјРёРіСЂР°С†РёРё (РєР°Р¶РґР°СЏ РІ СЃРІРѕС‘Рј try/except)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN post_interval_minutes INTEGER DEFAULT 60")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN commission_rate REAL DEFAULT 0.70")
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
        cursor.execute("ALTER TABLE users ADD COLUMN cpc_template TEXT DEFAULT ''")
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

    # РќРѕРІС‹Рµ РјРёРіСЂР°С†РёРё РґР»СЏ РІС‹РїР»Р°С‚ (РЅР°РїРѕРјРёРЅР°РЅРёСЏ Рѕ С‡РµРєРµ)
    try:
        cursor.execute("ALTER TABLE payout_requests ADD COLUMN sent_at TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE payout_requests ADD COLUMN receipt_reminded INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Р’ С„СѓРЅРєС†РёРё init_db() РїРѕСЃР»Рµ СЃРѕР·РґР°РЅРёСЏ С‚Р°Р±Р»РёС†С‹ posts РґРѕР±Р°РІРёС‚СЊ РјРёРіСЂР°С†РёСЋ:
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
    # Р”РѕР±Р°РІР»СЏРµРј РєРѕР»РѕРЅРєСѓ beta_tester РґР»СЏ СѓРїСЂР°РІР»РµРЅРёСЏ РґРѕСЃС‚СѓРїРѕРј Рє РЅРѕРІС‹Рј С„СѓРЅРєС†РёСЏРј
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN beta_tester INTEGER DEFAULT 0")
        logger.info("вњ… РљРѕР»РѕРЅРєР° beta_tester РґРѕР±Р°РІР»РµРЅР°")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e):
            logger.warning(f"вљ пёЏ РќРµ СѓРґР°Р»РѕСЃСЊ РґРѕР±Р°РІРёС‚СЊ beta_tester: {e}")
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admitad_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_token TEXT NOT NULL,
            expires_at REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cpc_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            campaign_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            cpc_link TEXT NOT NULL,
            text TEXT DEFAULT '',
            is_active INTEGER DEFAULT 0,
            interval_hours INTEGER DEFAULT 24,
            last_posted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    conn.commit()

    try:
        cursor.execute("ALTER TABLE channels ADD COLUMN admitad_website_id INTEGER")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    
    # РРЅРёС†РёР°Р»РёР·Р°С†РёСЏ С„РёС‡ (РµСЃР»Рё РёС… РЅРµС‚ РІ Р‘Р”)
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
                logger.info(f"вњ… Р¤РёС‡Р° '{feature_name}' РёРЅРёС†РёР°Р»РёР·РёСЂРѕРІР°РЅР° СЃРѕ СЃС‚Р°С‚СѓСЃРѕРј '{default_status}'")
        conn.commit()
    except Exception as e:
        logger.warning(f"вљ пёЏ РћС€РёР±РєР° РёРЅРёС†РёР°Р»РёР·Р°С†РёРё С„РёС‡: {e}")
    
    conn.close()
    logger.info("Р‘Р°Р·Р° РґР°РЅРЅС‹С… РёРЅРёС†РёР°Р»РёР·РёСЂРѕРІР°РЅР°")


# =============================================================================
# === Р’РЎРџРћРњРћР“РђРўР•Р›Р¬РќР«Р• Р¤РЈРќРљР¦РР =================================================
def generate_sub_id(username: str, user_id: int, role: str = "blogger") -> str:
    _TRANSLIT_MAP = {
        "Р°": "a", "Р±": "b", "РІ": "v", "Рі": "g", "Рґ": "d", "Рµ": "e", "С‘": "yo",
        "Р¶": "zh", "Р·": "z", "Рё": "i", "Р№": "y", "Рє": "k", "Р»": "l", "Рј": "m",
        "РЅ": "n", "Рѕ": "o", "Рї": "p", "СЂ": "r", "СЃ": "s", "С‚": "t", "Сѓ": "u",
        "С„": "f", "С…": "kh", "С†": "ts", "С‡": "ch", "С€": "sh", "С‰": "shch",
        "СЉ": "", "С‹": "y", "СЊ": "", "СЌ": "e", "СЋ": "yu", "СЏ": "ya",
    }
    username = (username or "").lstrip("@").lower()
    result = ""
    for ch in username:
        result += _TRANSLIT_MAP.get(ch, ch if ch.isalnum() or ch == "_" else "")
    result = re.sub(r"[^a-z0-9_]", "", result)
    result = re.sub(r"_+", "_", result).strip("_") or f"user{user_id}"
    prefix = "saas_" if role == "saas" else "blogger_"
    return f"{prefix}{result}_uid{user_id}"


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
        logger.error(f"РћС€РёР±РєР° РїСЂРѕРІРµСЂРєРё Р°РґРјРёРЅРєРё РІ {channel_id}: {e}")
        return False

# =============================================================================
# === РљР›РђР’РРђРўРЈР Р« ==============================================================
def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="рџЊђ РћС‚РєСЂС‹С‚СЊ Web-Р°РґРјРёРЅРєСѓ", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))],
        [InlineKeyboardButton(text="рџ“Ј Р Р°СЃСЃС‹Р»РєР° РІСЃРµРј", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="рџ”§ РџСЂРѕРґР»РёС‚СЊ РїРѕРґРїРёСЃРєСѓ", callback_data="admin:extend_sub")],
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
            "рџЋЃ Р’РІРµРґРёС‚Рµ РєРѕРјР°РЅРґСѓ РІ С„РѕСЂРјР°С‚Рµ: /promo РљРћР”\nРќР°РїСЂРёРјРµСЂ: /promo D2075RPD",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="рџ”™ РћС‚РјРµРЅР°", callback_data="cabinet:open")]
            ])
        )
        return

    code = args[1].strip().upper()
    logger.info(f"[PROMO] РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ {message.from_user.id} РІРІС‘Р» РєРѕРґ: {code}")

    conn = get_db()
    try:
        promo = conn.execute("SELECT * FROM promocodes WHERE UPPER(code) = ?", (code,)).fetchone()
        if not promo:
            await message.answer("вќЊ РќРµРІРµСЂРЅС‹Р№ РёР»Рё РЅРµСЃСѓС‰РµСЃС‚РІСѓСЋС‰РёР№ РїСЂРѕРјРѕРєРѕРґ.")
            return

        activation = conn.execute("SELECT * FROM promocode_activations WHERE UPPER(code) = ?", (code,)).fetchone()
        if activation:
            await message.answer("вќЊ Р­С‚РѕС‚ РїСЂРѕРјРѕРєРѕРґ СѓР¶Рµ РёСЃРїРѕР»СЊР·РѕРІР°РЅ.")
            return

        channels = conn.execute(
            "SELECT channel_id, channel_title FROM channels WHERE user_id = ? AND is_active = 1",
            (message.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    if not channels:
        await message.answer("вќЊ РЈ РІР°СЃ РЅРµС‚ РїРѕРґРєР»СЋС‡С‘РЅРЅС‹С… РєР°РЅР°Р»РѕРІ.")
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

        await message.answer(f"вњ… РџСЂРѕРјРѕРєРѕРґ Р°РєС‚РёРІРёСЂРѕРІР°РЅ!\nРџРѕРґРїРёСЃРєР° РїСЂРѕРґР»РµРЅР° РЅР° {days} РґРЅРµР№.")
        return

    # РќРµСЃРєРѕР»СЊРєРѕ РєР°РЅР°Р»РѕРІ вЂ“ РїРѕРєР°Р·С‹РІР°РµРј РІС‹Р±РѕСЂ
    await state.update_data(promocode=code, promo_days=days)
    kb_rows = []
    for ch in channels:
        kb_rows.append([InlineKeyboardButton(
            text=ch["channel_title"] or ch["channel_id"],
            callback_data=f"promo_channel:{ch['channel_id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="рџ”™ РћС‚РјРµРЅР°", callback_data="cabinet:open")])

    await message.answer(
        "рџЋЇ Р’С‹Р±РµСЂРёС‚Рµ РєР°РЅР°Р» РґР»СЏ Р°РєС‚РёРІР°С†РёРё РїСЂРѕРјРѕРєРѕРґР°:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )


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
    await safe_edit(callback.message, "вњ… РЎРїР°СЃРёР±Рѕ! РўРµРїРµСЂСЊ РІС‹ РјРѕР¶РµС‚Рµ РїРѕР»СЊР·РѕРІР°С‚СЊСЃСЏ Р±РѕС‚РѕРј.")
    await show_user_cabinet(callback.message, user_id=user_id)
    await callback.answer()

@router.callback_query(F.data == "privacy:decline")
async def cb_privacy_decline(callback: CallbackQuery):
    await safe_edit(callback.message,
        "вќЊ Р‘РµР· СЃРѕРіР»Р°СЃРёСЏ РЅР° РѕР±СЂР°Р±РѕС‚РєСѓ РґР°РЅРЅС‹С… Р±РѕС‚ РЅРµ РјРѕР¶РµС‚ СЂР°Р±РѕС‚Р°С‚СЊ.\n"
        "Р•СЃР»Рё РїРµСЂРµРґСѓРјР°РµС‚Рµ вЂ” РЅР°РїРёС€РёС‚Рµ /start."
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
            "в„№пёЏ Р’С‹ РјРѕР¶РµС‚Рµ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ Р±РѕС‚Р°, РЅРѕ РґР»СЏ Р·Р°РєР°Р·Р° РІС‹РїР»Р°С‚ РѕС‚ 3000в‚Ѕ РІР°Рј РїРѕС‚СЂРµР±СѓРµС‚СЃСЏ РїРѕР»СѓС‡РёС‚СЊ СЃС‚Р°С‚СѓСЃ РЎР°РјРѕР·Р°РЅСЏС‚РѕРіРѕ "
            "(СЌС‚Рѕ Р±РµСЃРїР»Р°С‚РЅРѕ Р·Р° 1 РјРёРЅСѓС‚Сѓ РІ РїСЂРёР»РѕР¶РµРЅРёРё В«РњРѕР№ РЅР°Р»РѕРіВ»)."
        )
    else:
        await callback.message.answer("вњ… РЎС‚Р°С‚СѓСЃ СЃРѕС…СЂР°РЅС‘РЅ. РўРµРїРµСЂСЊ РІР°Рј РґРѕСЃС‚СѓРїРµРЅ РІС‹РІРѕРґ СЃСЂРµРґСЃС‚РІ РїСЂРё РґРѕСЃС‚РёР¶РµРЅРёРё РїРѕСЂРѕРіР°.")
    await state.clear()
    await show_user_cabinet(callback.message, user_id=user_id)
    await callback.answer()

async def handle_payout_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT role, balance_available, tax_status, oferta_accepted FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user:
            await message.answer("РЎРЅР°С‡Р°Р»Р° Р·Р°СЂРµРіРёСЃС‚СЂРёСЂСѓР№С‚РµСЃСЊ С‡РµСЂРµР· /start")
            return
        if user["oferta_accepted"] != 1:
            await message.answer("РџСЂРёРјРёС‚Рµ РѕС„РµСЂС‚Сѓ РІ Р»РёС‡РЅРѕРј РєР°Р±РёРЅРµС‚Рµ.")
            return
        if user["role"] not in ("blogger", "saas"):
            await message.answer("Р’С‹РІРѕРґ СЃСЂРµРґСЃС‚РІ РґРѕСЃС‚СѓРїРµРЅ С‚РѕР»СЊРєРѕ Р±Р»РѕРіРµСЂР°Рј Рё SaaS-РєР»РёРµРЅС‚Р°Рј.")
            return
        if user["tax_status"] != "business":
            await message.answer("Р’С‹РІРѕРґ СЃСЂРµРґСЃС‚РІ РґРѕСЃС‚СѓРїРµРЅ С‚РѕР»СЊРєРѕ СЃР°РјРѕР·Р°РЅСЏС‚С‹Рј/РРџ.")
            return
        available = user["balance_available"] or 0.0
        if available < MIN_PAYOUT:
            await message.answer(f"вќЊ РњРёРЅРёРјР°Р»СЊРЅР°СЏ СЃСѓРјРјР° РІС‹РІРѕРґР°: {MIN_PAYOUT} в‚Ѕ")
            return
        # РџСЂРѕРІРµСЂРєР° Р°РєС‚РёРІРЅРѕР№ Р·Р°СЏРІРєРё
        active = conn.execute(
            "SELECT id FROM payout_requests WHERE user_id=? AND status IN ('processing','awaiting_receipt','receipt_uploaded')",
            (user_id,)
        ).fetchone()
        if active:
            await message.answer("вќЊ РЈ РІР°СЃ СѓР¶Рµ РµСЃС‚СЊ Р°РєС‚РёРІРЅР°СЏ Р·Р°СЏРІРєР° РЅР° РІС‹РїР»Р°С‚Сѓ.")
            return
    finally:
        conn.close()

    await message.answer(
        f"рџ’ё РЈРєР°Р¶РёС‚Рµ СЂРµРєРІРёР·РёС‚С‹ РґР»СЏ РІС‹РїР»Р°С‚С‹ (РЅРѕРјРµСЂ РєР°СЂС‚С‹, Р±Р°РЅРє, TON-РєРѕС€РµР»С‘Рє РёР»Рё РґСЂСѓРіРёРµ РґР°РЅРЅС‹Рµ):\n"
        f"Р”РѕСЃС‚СѓРїРЅРѕ: <b>{available:.2f} в‚Ѕ</b>\n\n"
        f"РџСЂРёРјРµСЂ: <i>РЎР±РµСЂР±Р°РЅРє 2202 2081 0829 0025</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="рџ”™ РћС‚РјРµРЅР°", callback_data="cabinet:open")]
        ])
    )
    await state.set_state(PayoutStates.waiting_for_card)


async def update_post_views(bot: Bot):
    """РћР±РЅРѕРІР»СЏРµС‚ РєРѕР»РёС‡РµСЃС‚РІРѕ РїСЂРѕСЃРјРѕС‚СЂРѕРІ РґР»СЏ РїРѕСЃС‚РѕРІ, РѕРїСѓР±Р»РёРєРѕРІР°РЅРЅС‹С… 30+ РґРЅРµР№ РЅР°Р·Р°Рґ."""
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
                logger.warning(f"РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РїСЂРѕСЃРјРѕС‚СЂС‹ РґР»СЏ РїРѕСЃС‚Р° {post['id']}: {e}")
        conn.commit()
        logger.info(f"РћР±РЅРѕРІР»РµРЅРѕ РїСЂРѕСЃРјРѕС‚СЂРѕРІ: {updated}")
    finally:
        conn.close()
# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: Command = None):
    # 1. РџСЂРѕРІРµСЂРєР° Р·Р°РїСЂРѕСЃР° РІС‹РїР»Р°С‚С‹ РёР· РІРµР±-СЃС‚Р°С‚РёСЃС‚РёРєРё
    if command.args == "payout":
        await handle_payout_start(message, state)
        return  

    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer("рџ‘‹ Р”РѕР±СЂРѕ РїРѕР¶Р°Р»РѕРІР°С‚СЊ РІ РџР°РЅРµР»СЊ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР°.", reply_markup=kb_admin_panel())
        return

    # РџСЂРѕРІРµСЂСЏРµРј СЂРµС„РµСЂР°Р»СЊРЅСѓСЋ СЃСЃС‹Р»РєСѓ (deep linking)
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
                [InlineKeyboardButton(text="рџ’ј SaaS-РєР»РёРµРЅС‚", callback_data="role:saas")],
                [InlineKeyboardButton(text="рџ‘¤ Р‘Р»РѕРіРµСЂ", callback_data="role:blogger")],
            ])
            await message.answer(
                "рџ‘‹ <b>Р”РѕР±СЂРѕ РїРѕР¶Р°Р»РѕРІР°С‚СЊ РІ AutoPost!</b>\n\n"
                "Р‘РѕС‚ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РїСѓР±Р»РёРєСѓРµС‚ С‚РѕРІР°СЂС‹ РёР· РїР°СЂС‚РЅС‘СЂСЃРєРёС… РјР°РіР°Р·РёРЅРѕРІ РІ РІР°С€ Telegram-РєР°РЅР°Р» "
                "Рё РїСЂРёРЅРѕСЃРёС‚ РІР°Рј <b>70% РєРѕРјРёСЃСЃРёРё</b> СЃ РєР°Р¶РґРѕР№ РїСЂРѕРґР°Р¶Рё.\n\n"
                "<b>РљР°Рє СЌС‚Рѕ СЂР°Р±РѕС‚Р°РµС‚:</b>\n"
                "1. Р”РѕР±Р°РІР»СЏРµС‚Рµ РєР°РЅР°Р»\n"
                "2. Р’С‹Р±РёСЂР°РµС‚Рµ РјР°РіР°Р·РёРЅС‹\n"
                "3. Р‘РѕС‚ РїСѓР±Р»РёРєСѓРµС‚ РїРѕСЃС‚С‹ СЃ РІР°С€РёРјРё РїР°СЂС‚РЅС‘СЂСЃРєРёРјРё СЃСЃС‹Р»РєР°РјРё\n"
                "4. РџРѕР»СѓС‡Р°РµС‚Рµ РґРѕС…РѕРґ Р·Р° РєР°Р¶РґСѓСЋ РїРѕРєСѓРїРєСѓ\n\n"
                "Р’С‹Р±РµСЂРёС‚Рµ РІР°С€Сѓ СЂРѕР»СЊ:",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            await state.set_state(OnboardingStates.waiting_role)
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="рџ’ј РћС‚РєСЂС‹С‚СЊ РєР°Р±РёРЅРµС‚", callback_data="cabinet:open")]
            ])
            await message.answer(
                "вњ… Р’С‹ СѓР¶Рµ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅС‹. Р”Р»СЏ СѓРїСЂР°РІР»РµРЅРёСЏ Р±РѕС‚РѕРј РёСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРѕРјР°РЅРґСѓ /cabinet.",
                reply_markup=kb
            )
    finally:
        conn.close()

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "рџ“– <b>РЎРїСЂР°РІРєР° вЂ” AutoPost Bot</b>\n\n"
        "<b>РћСЃРЅРѕРІРЅС‹Рµ РєРѕРјР°РЅРґС‹:</b>\n"
        "/start вЂ” Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ\n"
        "/cabinet вЂ” Р›РёС‡РЅС‹Р№ РєР°Р±РёРЅРµС‚\n"
        "/help вЂ” Р­С‚Р° СЃРїСЂР°РІРєР°\n\n"
        "<b>Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅРѕ:</b>\n"
        "/promo вЂ” РђРєС‚РёРІРёСЂРѕРІР°С‚СЊ РїСЂРѕРјРѕРєРѕРґ\n"
        "/privacy вЂ” РџРѕР»РёС‚РёРєР° РєРѕРЅС„РёРґРµРЅС†РёР°Р»СЊРЅРѕСЃС‚Рё\n"
        "/delete вЂ” РЈРґР°Р»РёС‚СЊ Р°РєРєР°СѓРЅС‚ Рё РІСЃРµ РґР°РЅРЅС‹Рµ\n\n"
        "<b>РљР°Рє РЅР°С‡Р°С‚СЊ Р·Р°СЂР°Р±Р°С‚С‹РІР°С‚СЊ:</b>\n"
        "1. Р”РѕР±Р°РІСЊС‚Рµ РєР°РЅР°Р» РІ В«РљР°Р±РёРЅРµС‚РµВ»\n"
        "2. Р”РѕР±Р°РІСЊС‚Рµ Р±РѕС‚Р° Р°РґРјРёРЅРѕРј РІ РєР°РЅР°Р» СЃ РїСЂР°РІР°РјРё РЅР° РїРѕСЃС‚РёРЅРі\n"
        "3. Р’С‹Р±РµСЂРёС‚Рµ РјР°РіР°Р·РёРЅС‹ РІ СЂР°Р·РґРµР»Рµ В«РњР°РіР°Р·РёРЅС‹В»\n"
        "4. Р‘РѕС‚ РЅР°С‡РЅС‘С‚ РїСѓР±Р»РёРєР°С†РёРё Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё!\n\n"
        "<b>Р’С‹РїР»Р°С‚С‹:</b>\n"
        "РњРёРЅРёРјР°Р»СЊРЅР°СЏ РІС‹РїР»Р°С‚Р° вЂ” 3000 в‚Ѕ.\n"
        "Р”РѕСЃС‚СѓРїРµРЅ РґР»СЏ СЃР°РјРѕР·Р°РЅСЏС‚С‹С….\n\n"
        "<b>РџРѕРґРґРµСЂР¶РєР°:</b> РЅР°РїРёС€РёС‚Рµ /start Рё РЅР°Р¶РјРёС‚Рµ В«рџ’¬ РџРѕРґРґРµСЂР¶РєР°В»",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("preview"))
async def cmd_preview(message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id) and not is_feature_enabled(user_id, "preview_post"):
        await message.answer("вЏі Р­С‚Р° С„СѓРЅРєС†РёСЏ РІ Р±РµС‚Р°-С‚РµСЃС‚Рµ. РЎРєРѕСЂРѕ СЃС‚Р°РЅРµС‚ РґРѕСЃС‚СѓРїРЅР° РІСЃРµРј!")
        return
    
    # РћС‚РїСЂР°РІР»СЏРµРј СЃСЃС‹Р»РєСѓ РЅР° РІРµР±-СЃС‚Р°С‚РёСЃС‚РёРєСѓ СЃ РїСЂРµРґРїСЂРѕСЃРјРѕС‚СЂРѕРј
    token = generate_user_token(user_id)
    link = f"{WEBAPP_BASE_URL}/my-stats?token={token}"
    await message.answer(
        f"рџ‘Ђ <b>РџСЂРµРґРїСЂРѕСЃРјРѕС‚СЂ РїРѕСЃС‚Р°</b>\n\n"
        f"РџРµСЂРµР№РґРёС‚Рµ РІ РІРµР±-СЃС‚Р°С‚РёСЃС‚РёРєСѓ Рё РЅР°Р№РґРёС‚Рµ Р±Р»РѕРє В«РџСЂРµРґРїСЂРѕСЃРјРѕС‚СЂ РїРѕСЃС‚Р°В»:\n"
        f"<a href='{link}'>РћС‚РєСЂС‹С‚СЊ СЃС‚Р°С‚РёСЃС‚РёРєСѓ</a>\n\n"
        f"РўР°Рј РІС‹ СЃРјРѕР¶РµС‚Рµ:\n"
        f"вЂў РџРѕСЃРјРѕС‚СЂРµС‚СЊ, РєР°Рє РїРѕСЃС‚ Р±СѓРґРµС‚ РІС‹РіР»СЏРґРµС‚СЊ РІ РєР°РЅР°Р»Рµ\n"
        f"вЂў РћРїСѓР±Р»РёРєРѕРІР°С‚СЊ РµРіРѕ РІ РѕРґРёРЅ РєР»РёРє",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

@router.message(Command("privacy"))
async def cmd_privacy(message: Message):
    await message.answer(
        "рџ“„ РџРѕР»РёС‚РёРєР° РєРѕРЅС„РёРґРµРЅС†РёР°Р»СЊРЅРѕСЃС‚Рё:\n https://teletype.in/@miliron/yYN0SEGfm5l",
        disable_web_page_preview=True
    )

_pending_deletes: dict[int, float] = {}

@router.message(Command("delete"))
async def cmd_delete(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Р±РµР· username"

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
                    f"рџ—‘ <b>РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ СѓРґР°Р»РёР» Р°РєРєР°СѓРЅС‚</b>\n\n"
                    f"User ID: <code>{user_id}</code>\n"
                    f"Username: @{username}\n"
                    f"Р’СЃРµ РґР°РЅРЅС‹Рµ СѓРґР°Р»РµРЅС‹ РёР· Р±Р°Р·С‹.",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"РќРµ СѓРґР°Р»РѕСЃСЊ СѓРІРµРґРѕРјРёС‚СЊ Р°РґРјРёРЅР° {admin_id}: {e}")
        await message.answer(
            "вњ… Р’СЃРµ РІР°С€Рё РґР°РЅРЅС‹Рµ СѓРґР°Р»РµРЅС‹ РІ СЃРѕРѕС‚РІРµС‚СЃС‚РІРёРё СЃРѕ СЃС‚. 21 152-Р¤Р—.\n\n"
            "Р•СЃР»Рё РІС‹ Р·Р°С…РѕС‚РёС‚Рµ РІРµСЂРЅСѓС‚СЊСЃСЏ вЂ” РїСЂРѕСЃС‚Рѕ РЅР°РїРёС€РёС‚Рµ /start."
        )
    else:
        _pending_deletes[user_id] = now + 60
        await message.answer(
            "вљ пёЏ <b>Р’РЅРёРјР°РЅРёРµ!</b>\n\n"
            "Р­С‚Рѕ РґРµР№СЃС‚РІРёРµ СѓРґР°Р»РёС‚ <b>РІСЃРµ РІР°С€Рё РґР°РЅРЅС‹Рµ</b> РёР· Р±РѕС‚Р°:\n"
            "вЂў РџСЂРѕС„РёР»СЊ Рё РїРѕРґРїРёСЃРєР°\n"
            "вЂў РљР°РЅР°Р»С‹ Рё РїРѕСЃС‚С‹\n"
            "вЂў Р‘Р°Р»Р°РЅСЃ Рё С‚СЂР°РЅР·Р°РєС†РёРё\n"
            "вЂў РЁР°Р±Р»РѕРЅС‹ Рё РЅР°СЃС‚СЂРѕР№РєРё\n\n"
            "Р­С‚Рѕ РґРµР№СЃС‚РІРёРµ <b>РЅРµРѕР±СЂР°С‚РёРјРѕ</b>.\n\n"
            "Р”Р»СЏ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ РѕС‚РїСЂР°РІСЊС‚Рµ <code>/delete</code> РµС‰С‘ СЂР°Р· РІ С‚РµС‡РµРЅРёРµ 60 СЃРµРєСѓРЅРґ.",
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
# Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ (РєРѕР»Р±СЌРє)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:main")
async def cb_menu_main(callback: CallbackQuery):
    conn = get_db()
    try:
        user = conn.execute("SELECT role FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
        role = user["role"] if user else "blogger"
    finally:
        conn.close()
    await show_user_cabinet(callback.message, user_id=callback.from_user.id, edit_message=callback.message)
    await callback.answer()

# ---------------------------------------------------------------------------
# РњРѕРё РєР°РЅР°Р»С‹ (SaaS)
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
        text = "рџ“ў <b>Р’Р°С€Рё РїРѕРґРєР»СЋС‡РµРЅРЅС‹Рµ РєР°РЅР°Р»С‹:</b>\n\n"
        kb_rows = []
        for i, ch in enumerate(channels, 1):
            text += f"{i}. {ch['channel_title']} (<code>{ch['channel_id']}</code>)\n"
            kb_rows.append([InlineKeyboardButton(
                text=f"рџ—‘ РЈРґР°Р»РёС‚СЊ {ch['channel_title']}",
                callback_data=f"channel_delete:{ch['id']}"
            )])
        text += "\n<i>Р”Р»СЏ РґРѕР±Р°РІР»РµРЅРёСЏ РЅРѕРІРѕРіРѕ РєР°РЅР°Р»Р° РѕС‚РїСЂР°РІСЊС‚Рµ РµРіРѕ @username.</i>"
        kb_rows.append([InlineKeyboardButton(text="рџ”™ РќР°Р·Р°Рґ РІ РєР°Р±РёРЅРµС‚", callback_data="cabinet:open")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    else:
        text = "рџ“ў <b>РЈ РІР°СЃ РїРѕРєР° РЅРµС‚ РїРѕРґРєР»СЋС‡РµРЅРЅС‹С… РєР°РЅР°Р»РѕРІ.</b>\n\nР”Р»СЏ РґРѕР±Р°РІР»РµРЅРёСЏ РєР°РЅР°Р»Р° РѕС‚РїСЂР°РІСЊС‚Рµ РµРіРѕ @username."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="рџ”™ РќР°Р·Р°Рґ РІ РєР°Р±РёРЅРµС‚", callback_data="cabinet:open")]
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
        await callback.answer("рџ—‘ РљР°РЅР°Р» СѓРґР°Р»С‘РЅ.", show_alert=True)
        await cb_my_channels(callback)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="вќЊ Р”Р°, СѓРґР°Р»РёС‚СЊ", callback_data=f"channel_delete:{channel_id}:confirm")],
            [InlineKeyboardButton(text="рџ”™ РћС‚РјРµРЅР°", callback_data="cabinet:open")],
        ])
        await safe_edit(callback.message, "вљ пёЏ Р’С‹ СѓРІРµСЂРµРЅС‹, С‡С‚Рѕ С…РѕС‚РёС‚Рµ СѓРґР°Р»РёС‚СЊ РєР°РЅР°Р»?", reply_markup=kb)
        await callback.answer()

# ---------------------------------------------------------------------------
# РЎС‚Р°С‚РёСЃС‚РёРєР° SaaS
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
            f"рџ“Љ <b>РћР±С‰Р°СЏ СЃС‚Р°С‚РёСЃС‚РёРєР°</b>\n\n"
            f"рџ“¬ Р’СЃРµРіРѕ РїРѕСЃС‚РѕРІ: <b>{overview['total_posts']}</b>\n"
            f"рџ“… Р—Р° 30 РґРЅРµР№: <b>{overview['posts_30d']}</b>\n\n"
            f"рџЏЄ <b>РџРѕ РјР°РіР°Р·РёРЅР°Рј (РІСЃРµ РІСЂРµРјСЏ):</b>\n"
        )
        if overview['by_store']:
            for store, count in overview['by_store'].items():
                text += f"  {store}: {count}\n"
        else:
            text += "  РќРµС‚ РґР°РЅРЅС‹С…\n"
        text += f"\n<i>РџРѕРґРєР»СЋС‡РёС‚Рµ РєР°РЅР°Р»С‹ РґР»СЏ РґРµС‚Р°Р»СЊРЅРѕР№ СЃС‚Р°С‚РёСЃС‚РёРєРё.</i>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="рџ”™ РќР°Р·Р°Рґ", callback_data="menu:main")]
        ])
        await safe_edit(callback.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    channel_idx = max(0, min(channel_idx, len(channels) - 1))
    ch = channels[channel_idx]
    s = get_saas_channel_stats_new(user_id, ch["channel_id"], period)
    total_ch = len(channels)

    text = (
        f"рџ“Љ <b>РЎС‚Р°С‚РёСЃС‚РёРєР° РєР°РЅР°Р»Р°</b>\n"
        f"рџ“ў <b>{ch['channel_title'] or ch['channel_id']}</b>  <i>({channel_idx + 1}/{total_ch})</i>\n"
        f"рџ—“ РџРµСЂРёРѕРґ: <b>{s['period_label']}</b>\n\n"
        f"рџ“¬ Р’СЃРµРіРѕ РїРѕСЃС‚РѕРІ: <b>{s['total']}</b>\n"
        f"вњ… РћРїСѓР±Р»РёРєРѕРІР°РЅРѕ: <b>{s['published']}</b>\n"
        f"вќЊ РћС€РёР±РѕРє: <b>{s['errors']}</b>\n"
        f"рџ•ђ РџРѕСЃР»РµРґРЅРёР№: <b>{s['last_published_at']}</b>\n\n"
        f"рџЏЄ <b>РџРѕ РјР°РіР°Р·РёРЅР°Рј:</b>\n"
    )
    if s['by_store']:
        for store, count in s['by_store'].items():
            text += f"  {store}: {count}\n"
    else:
        text += "  РќРµС‚ РґР°РЅРЅС‹С…\n"

    nav_row = []
    if channel_idx > 0:
        nav_row.append(InlineKeyboardButton(text="в—ЂпёЏ РљР°РЅР°Р»", callback_data=f"saas_stats:{channel_idx - 1}:{period}"))
    if channel_idx < total_ch - 1:
        nav_row.append(InlineKeyboardButton(text="РљР°РЅР°Р» в–¶пёЏ", callback_data=f"saas_stats:{channel_idx + 1}:{period}"))

    period_row = []
    for p_key, p_cfg in STAT_PERIODS.items():
        label = f"В· {p_cfg['label']} В·" if p_key == period else p_cfg["label"]
        period_row.append(InlineKeyboardButton(text=label, callback_data=f"saas_stats:{channel_idx}:{p_key}"))

    kb = []
    if nav_row:
        kb.append(nav_row)
    kb.append(period_row)
    kb.append([InlineKeyboardButton(text="рџ”™ РќР°Р·Р°Рґ", callback_data="menu:main")])

    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode=ParseMode.HTML)

@router.callback_query(F.data.startswith("saas_stats:"))
async def cb_saas_stats_nav(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    try:
        channel_idx = int(parts[1])
        period = parts[2]
    except (IndexError, ValueError):
        await callback.answer("вќЊ РћС€РёР±РєР° РЅР°РІРёРіР°С†РёРё", show_alert=True)
        return
    if period not in STAT_PERIODS:
        period = "30d"
    await _show_saas_stats(callback, callback.from_user.id, channel_idx, period)
    await callback.answer()


@router.message(Command("test_cpc"))
async def cmd_test_cpc(message: Message):
    from services.admitad_subnetwork import get_website_campaigns, get_all_websites
    websites = await get_all_websites()
    
    # РќР° СЃР»СѓС‡Р°Р№, РµСЃР»Рё API РЅРµ СЃСЂР°Р±РѕС‚Р°Р» вЂ” fallback РЅР° Р‘Р”
    if not websites:
        conn = get_db()
        try:
            channels = conn.execute("SELECT channel_id, channel_title, admitad_website_id FROM channels WHERE admitad_website_id IS NOT NULL").fetchall()
        finally:
            conn.close()
        if not channels:
            await message.answer("вќЊ РќРµС‚ РїР»РѕС‰Р°РґРѕРє. Р’РѕР·РјРѕР¶РЅРѕ, scope `websites` РЅРµ РІРєР»СЋС‡С‘РЅ РІ РЅР°СЃС‚СЂРѕР№РєР°С… РїСЂРёР»РѕР¶РµРЅРёСЏ Admitad.")
            return
        website_list = [(ch["channel_title"] or ch["channel_id"], ch["admitad_website_id"]) for ch in channels]
    else:
        website_list = [(w.get("name", f"ID {w['id']}"), w["id"]) for w in websites]

    parts = []
    for w_name, w_id in website_list:
        campaigns = await get_website_campaigns(w_id)
        if not campaigns:
            parts.append(f"рџ“є {w_name} (ID {w_id}): РЅРµС‚ РєР°РјРїР°РЅРёР№")
            continue
        lines = [f"рџ“є {w_name} (ID {w_id}):"]
        for c in campaigns:
            name = c.get("name", "?")
            status = c.get("connection_status", "?")
            gotolink = c.get("gotolink", "")
            actions = c.get("actions", [])
            rates = []
            for a in actions[:3]:
                a_name = a.get("name", "?")
                a_rate = a.get("rate", "?")
                a_currency = a.get("currency", "в‚Ѕ")
                rates.append(f"      {a_name}: {a_rate} {a_currency}")
            lines.append(f"  вЂў {name} вЂ” {status}")
            if rates:
                lines.extend(rates)
            if gotolink:
                cpclink = gotolink.replace("/g/", "/c/")
                lines.append(f"    CPA: {gotolink[:70]}...")
                lines.append(f"    CPC: {cpclink[:70]}...")
        parts.append("\n".join(lines))

    text = "рџ“Љ РџРѕРґРєР»СЋС‡РµРЅРЅС‹Рµ СЂРµРєР»Р°РјРѕРґР°С‚РµР»Рё:\n\n" + "\n\n".join(parts)
    if len(text) > 4000:
        text = text[:4000] + "\n\n..."
    await message.answer(text)


@router.message(Command("test_all_cpc"))
async def cmd_test_all_cpc(message: Message):
    from services.admitad_subnetwork import search_all_cpc_campaigns
    await message.answer("рџ”Ќ РС‰Сѓ CPC-СЂРµРєР»Р°РјРѕРґР°С‚РµР»РµР№...")
    campaigns = await search_all_cpc_campaigns(limit=100)
    if not campaigns:
        await message.answer("вќЊ РќРµ РЅР°Р№РґРµРЅРѕ CPC-СЂРµРєР»Р°РјРѕРґР°С‚РµР»РµР№. Р’РѕР·РјРѕР¶РЅРѕ, scope `advcampaigns` РЅРµ РІРєР»СЋС‡С‘РЅ РІ РЅР°СЃС‚СЂРѕР№РєР°С… РїСЂРёР»РѕР¶РµРЅРёСЏ Admitad.")
        return
    lines = [f"рџ“Љ РќР°Р№РґРµРЅРѕ CPC-СЂРµРєР»Р°РјРѕРґР°С‚РµР»РµР№: {len(campaigns)}"]
    for c in campaigns[:15]:
        name = c.get("name", "?")
        site_url = c.get("site_url", "")
        actions = c.get("actions", [])
        cpc_actions = [a for a in actions if "РєР»РёРє" in (a.get("name", "") or "").lower()]
        rates_str = "; ".join(f"{a['name']}: {a['rate']} {a.get('currency', 'в‚Ѕ')}" for a in cpc_actions)
        lines.append(f"\nвЂў {name}")
        if rates_str:
            lines.append(f"  {rates_str}")
        if site_url:
            lines.append(f"  {site_url}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n\n..."
    await message.answer(text)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    token = generate_admin_token(message.from_user.id)
    base = WEBAPP_ADMIN_URL.rstrip('/')
    login_url = f"{base}/login?token={token}"
    await message.answer(
        f"рџ”‘ <a href='{login_url}'>РћС‚РєСЂС‹С‚СЊ Р°РґРјРёРЅРєСѓ</a>\n\n"
        f"РР»Рё СЃРєРѕРїРёСЂСѓР№С‚Рµ СЃСЃС‹Р»РєСѓ:\n{login_url}",
        disable_web_page_preview=True
    )

@router.callback_query(F.data == "menu:webstats")
async def cb_webstats(callback: CallbackQuery):
    user_id = callback.from_user.id
    token = generate_user_token(user_id)
    link = f"{WEBAPP_BASE_URL}/my-stats?token={token}"
    await safe_edit(callback.message,
        f"рџ“Љ <a href='{link}'>РћС‚РєСЂС‹С‚СЊ СЃС‚Р°С‚РёСЃС‚РёРєСѓ</a>\n\n"
        "РЎСЃС‹Р»РєР° РґРµР№СЃС‚РІРёС‚РµР»СЊРЅР° 24 С‡Р°СЃР°.\n"
        "Р•СЃР»Рё РІС‹ РЅРµ РјРѕР¶РµС‚Рµ РїРµСЂРµР№С‚Рё, СЃРєРѕРїРёСЂСѓР№С‚Рµ Р°РґСЂРµСЃ:\n"
        f"<code>{link}</code>",
        disable_web_page_preview=True,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()

@router.callback_query(F.data == "menu:privacy")
async def cb_menu_privacy(callback: CallbackQuery):
    await safe_edit(callback.message,
        "рџ“„ РџРѕР»РёС‚РёРєР° РєРѕРЅС„РёРґРµРЅС†РёР°Р»СЊРЅРѕСЃС‚Рё:\nhttps://teletype.in/@miliron/yYN0SEGfm5l",
        disable_web_page_preview=True
    )
    await callback.answer()
# ---------------------------------------------------------------------------
# РЈСЃРїРµС€РЅР°СЏ РѕРїР»Р°С‚Р° (Р·РІС‘Р·РґС‹)
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
            await message.answer("вќЊ РўР°СЂРёС„ РЅРµ РЅР°Р№РґРµРЅ.")
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
        f"вњ… <b>РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРёСЂРѕРІР°РЅР°!</b>\n\n"
        f"Р”РµР№СЃС‚РІСѓРµС‚ РґРѕ: {new_until.strftime('%d.%m.%Y %H:%M')} (UTC)",
        parse_mode=ParseMode.HTML
    )

# ---------------------------------------------------------------------------
# РћРќР‘РћР Р”РРќР“: SAAS вЂ“ Р”РћР‘РђР’Р›Р•РќРР• РљРђРќРђР›Рђ (РєР»СЋС‡РµРІРѕР№ РѕР±СЂР°Р±РѕС‚С‡РёРє)
# ---------------------------------------------------------------------------
@router.message(OnboardingStates.waiting_saas_tg_channel)
async def handle_saas_channel_addition(message: Message, state: FSMContext) -> None:
    """РћР±СЂР°Р±РѕС‚С‡РёРє РїСЂРёРЅРёРјР°РµС‚ @username РёР»Рё РїРµСЂРµСЃР»Р°РЅРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ РёР· РєР°РЅР°Р»Р°."""
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
                logger.info(f"РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ {user_id} РїРµСЂРµСЃР»Р°Р» СЃРѕРѕР±С‰РµРЅРёРµ РёР· РєР°РЅР°Р»Р° {tg_chat_id}")
        else:
            channel_username = message.text.strip()
            if channel_username.startswith("/"):
                await message.answer("РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РѕС‚РїСЂР°РІСЊС‚Рµ @username РєР°РЅР°Р»Р° РёР»Рё РїРµСЂРµС€Р»РёС‚Рµ СЃРѕРѕР±С‰РµРЅРёРµ РёР· РЅРµРіРѕ.")
                return
            if not channel_username.startswith("@"):
                await message.answer(
                    "вљ пёЏ РћС‚РїСЂР°РІСЊС‚Рµ РєРѕСЂСЂРµРєС‚РЅС‹Р№ @username (РЅР°РїСЂРёРјРµСЂ, @mychannel) РёР»Рё РїРµСЂРµС€Р»РёС‚Рµ Р»СЋР±РѕРµ СЃРѕРѕР±С‰РµРЅРёРµ РёР· РІР°С€РµРіРѕ РєР°РЅР°Р»Р°."
                )
                return

            logger.info(f"РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ {user_id} РїС‹С‚Р°РµС‚СЃСЏ РґРѕР±Р°РІРёС‚СЊ РєР°РЅР°Р» {channel_username}")
            try:
                chat_info = await message.bot.get_chat(channel_username)
                tg_chat_id = str(chat_info.id)
                tg_title = chat_info.title or channel_username
            except Exception as e:
                logger.error(f"РћС€РёР±РєР° РїРѕР»СѓС‡РµРЅРёСЏ РёРЅС„РѕСЂРјР°С†РёРё Рѕ РєР°РЅР°Р»Рµ {channel_username}: {e}")
                await message.answer("вќЊ РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ РёРЅС„РѕСЂРјР°С†РёСЋ Рѕ РєР°РЅР°Р»Рµ. РџСЂРѕРІРµСЂСЊС‚Рµ РїСЂР°РІРёР»СЊРЅРѕСЃС‚СЊ @username.")
                return

        chat_identifier = channel_username if channel_username else tg_chat_id
        is_admin_ok = await check_bot_admin(message.bot, tg_chat_id if tg_chat_id else chat_identifier)
        if not is_admin_ok:
            logger.warning(f"Р‘РѕС‚ РЅРµ Р°РґРјРёРЅ РІ РєР°РЅР°Р»Рµ {chat_identifier}")
            await message.answer(
                "вќЊ Р‘РѕС‚ РЅРµ СЏРІР»СЏРµС‚СЃСЏ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂРѕРј РІ СЌС‚РѕРј РєР°РЅР°Р»Рµ. "
                "Р”РѕР±Р°РІСЊС‚Рµ Р±РѕС‚Р° РІ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂС‹ РєР°РЅР°Р»Р° СЃ РїСЂР°РІРѕРј РїСѓР±Р»РёРєР°С†РёРё СЃРѕРѕР±С‰РµРЅРёР№ Рё РїРѕРїСЂРѕР±СѓР№С‚Рµ СЃРЅРѕРІР°."
            )
            return

        conn = get_db()
        try:
            # РџСЂРѕРІРµСЂРєР° Р»РёРјРёС‚Р° РєР°РЅР°Р»РѕРІ
            user = conn.execute("SELECT role, tariff_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            conn.execute(
                """INSERT INTO channels (user_id, channel_id, channel_title, sub_id)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, channel_id) DO UPDATE SET channel_title = excluded.channel_title""",
                (user_id, channel_username if channel_username else tg_chat_id, tg_title, tg_chat_id)
            )
            conn.commit()
            logger.info(f"РљР°РЅР°Р» {chat_identifier} СѓСЃРїРµС€РЅРѕ РґРѕР±Р°РІР»РµРЅ РґР»СЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ {user_id}")
        except sqlite3.Error as e:
            logger.error(f"РћС€РёР±РєР° Р‘Р” РїСЂРё РґРѕР±Р°РІР»РµРЅРёРё РєР°РЅР°Р»Р°: {e}")
            await message.answer("вќЊ РћС€РёР±РєР° РїСЂРё РґРѕР±Р°РІР»РµРЅРёРё РєР°РЅР°Р»Р° РІ Р±Р°Р·Сѓ РґР°РЅРЅС‹С…. РџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР·Р¶Рµ.")
            return
        finally:
            conn.close()

        # Р РµРіРёСЃС‚СЂР°С†РёСЏ РїРѕРґРїР»РѕС‰Р°РґРєРё РІ Admitad (subnetwork)
        try:
            from services.admitad_subnetwork import register_channel_as_website
            channel_id_str = channel_username if channel_username else str(tg_chat_id)
            website_id = await register_channel_as_website(
                channel_id=channel_id_str,
                channel_name=tg_title or channel_username or str(tg_chat_id)
            )
            if website_id:
                logger.info(f"вњ… РџРѕРґРїР»РѕС‰Р°РґРєР° Admitad СЃРѕР·РґР°РЅР°: website_id={website_id} РґР»СЏ РєР°РЅР°Р»Р° {channel_id_str}")
            else:
                logger.warning(f"вљ пёЏ РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ РїРѕРґРїР»РѕС‰Р°РґРєСѓ РґР»СЏ РєР°РЅР°Р»Р° {channel_id_str}")
        except Exception as e:
            logger.warning(f"вљ пёЏ РћС€РёР±РєР° СЃРѕР·РґР°РЅРёСЏ РїРѕРґРїР»РѕС‰Р°РґРєРё: {e}")

        display_name = channel_username if channel_username else tg_title
        await message.answer(
            f"вњ… РљР°РЅР°Р» <b>{html.escape(display_name)}</b> СѓСЃРїРµС€РЅРѕ РґРѕР±Р°РІР»РµРЅ!",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_cabinet_menu("saas")
        )
        await state.clear()
        await show_user_cabinet(message, user_id=user_id)

    except Exception as e:
        logger.exception(f"РљСЂРёС‚РёС‡РµСЃРєР°СЏ РѕС€РёР±РєР° РїСЂРё РѕР±СЂР°Р±РѕС‚РєРµ РґРѕР±Р°РІР»РµРЅРёСЏ РєР°РЅР°Р»Р°: {e}")
        await message.answer(
            "вќЊ РџСЂРѕРёР·РѕС€Р»Р° РІРЅСѓС‚СЂРµРЅРЅСЏСЏ РѕС€РёР±РєР°. РђРґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ СѓР¶Рµ СѓРІРµРґРѕРјР»С‘РЅ. РџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР·Р¶Рµ РёР»Рё СЃРІСЏР¶РёС‚РµСЃСЊ СЃ РїРѕРґРґРµСЂР¶РєРѕР№."
        )
        await state.clear()

@router.callback_query(OnboardingStates.waiting_role)
async def process_role_selection(callback: CallbackQuery, state: FSMContext):
    role = callback.data.split(":")[1]  # "saas" РёР»Рё "blogger"
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
        conn.execute("UPDATE users SET commission_rate = 0.70 WHERE user_id = ?", (user_id,))
        # Р РµС„РµСЂР°Р»СЊРЅР°СЏ СЃРІСЏР·СЊ
        if referrer_id:
            conn.execute("""
                INSERT OR IGNORE INTO referrals (referrer_id, referral_id, total_brought_profit)
                VALUES (?, ?, 0)
            """, (referrer_id, user_id))
        conn.commit()
    finally:
        conn.close()

    # РЈРІРµРґРѕРјР»РµРЅРёРµ СЂРµС„РµСЂРµСЂСѓ
    if referrer_id:
        try:
            await callback.bot.send_message(
                referrer_id,
                f"рџЋ‰ РџРѕ РІР°С€РµР№ СЂРµС„РµСЂР°Р»СЊРЅРѕР№ СЃСЃС‹Р»РєРµ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°Р»СЃСЏ РЅРѕРІС‹Р№ Р±Р»РѕРіРµСЂ (ID {user_id})!\n"
                "Р’С‹ Р±СѓРґРµС‚Рµ РїРѕР»СѓС‡Р°С‚СЊ 10% РѕС‚ РµРіРѕ Р·Р°СЂР°Р±РѕС‚РєР°."
            )
        except Exception as e:
            logger.error(f"РќРµ СѓРґР°Р»РѕСЃСЊ СѓРІРµРґРѕРјРёС‚СЊ СЂРµС„РµСЂРµСЂР° {referrer_id}: {e}")

    if role == "saas":
        await safe_edit(callback.message,
            "рџ‘‹ Р”РѕР±СЂРѕ РїРѕР¶Р°Р»РѕРІР°С‚СЊ! Р”Р»СЏ РЅР°С‡Р°Р»Р° СЂР°Р±РѕС‚С‹ РѕС‚РїСЂР°РІСЊС‚Рµ @username РІР°С€РµРіРѕ Telegram-РєР°РЅР°Р»Р°."
        )
        await state.set_state(OnboardingStates.waiting_saas_tg_channel)
    else:  # blogger
        await safe_edit(callback.message,
            "рџ‘‹ Р”РѕР±СЂРѕ РїРѕР¶Р°Р»РѕРІР°С‚СЊ, Р±Р»РѕРіРµСЂ! Р”Р»СЏ РЅР°С‡Р°Р»Р° РѕС‚РїСЂР°РІСЊС‚Рµ @username РІР°С€РµРіРѕ Telegram-РєР°РЅР°Р»Р°."
        )
        await state.set_state(OnboardingStates.waiting_saas_tg_channel)  # С‚Рѕ Р¶Рµ СЃРѕСЃС‚РѕСЏРЅРёРµ, РЅРѕ Р±РµР· Р»РёРјРёС‚РѕРІ

    await callback.answer()
# ---------------------------------------------------------------------------
# РћР±СЂР°Р±РѕС‚С‡РёРєРё РёРЅСЃС‚СЂСѓРєС†РёР№ Рё РїРѕРґРґРµСЂР¶РєРё
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "support:contact")
async def cb_support_contact(callback: CallbackQuery):
    text = (
        "рџ“ћ <b>РЎРІСЏР·СЊ СЃ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂРѕРј</b>\n\n"
        "РџРѕ Р»СЋР±С‹Рј РІРѕРїСЂРѕСЃР°Рј РїРёС€РёС‚Рµ:\n"
        "рџ‘‰ <a href='https://t.me/Zigih90'>@Zigih90</a>\n\n"
        "в”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓв”Ѓ\n"
        "вќ“ <b>Р§Р°СЃС‚С‹Рµ РІРѕРїСЂРѕСЃС‹:</b>\n\n"
        "<b>Р‘РѕС‚ РЅРµ РїСѓР±Р»РёРєСѓРµС‚ РїРѕСЃС‚С‹?</b>\n"
        "РЈР±РµРґРёС‚РµСЃСЊ, С‡С‚Рѕ Р±РѕС‚ вЂ” Р°РґРјРёРЅ РєР°РЅР°Р»Р° СЃ РїСЂР°РІР°РјРё РЅР° РїСѓР±Р»РёРєР°С†РёСЋ.\n\n"
        "<b>РќРµС‚ РґРѕС…РѕРґР°?</b>\n"
        "Р”РѕС…РѕРґ РїРѕСЏРІР»СЏРµС‚СЃСЏ РїРѕСЃР»Рµ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ РїРѕРєСѓРїРѕРє СЂРµРєР»Р°РјРѕРґР°С‚РµР»РµРј (30вЂ“90 РґРЅРµР№).\n\n"
        "<b>РќРµ РјРѕРіСѓ РІС‹РІРµСЃС‚Рё РґРµРЅСЊРіРё?</b>\n"
        "РќСѓР¶РµРЅ СЃС‚Р°С‚СѓСЃ СЃР°РјРѕР·Р°РЅСЏС‚РѕРіРѕ Рё Р±Р°Р»Р°РЅСЃ РѕС‚ 3000 в‚Ѕ.\n\n"
        "<b>РљР°РєРёРµ РјР°РіР°Р·РёРЅС‹ РґРѕСЃС‚СѓРїРЅС‹?</b>\n"
         "РќР°Р¶РјРёС‚Рµ В«рџЏЄ РњР°РіР°Р·РёРЅС‹В» в†’ РІС‹Р±РµСЂРёС‚Рµ В«рџ›’ РџРѕРєСѓРїРєР°В» (CPA) РёР»Рё В«рџ‘† РљР»РёРєРёВ» (CPC).\n\n"
        "<i>РЎС‚Р°СЋСЃСЊ РѕС‚РІРµС‡Р°С‚СЊ Р±С‹СЃС‚СЂРѕ</i>"
    )
    await safe_edit(callback.message, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="рџ”™ РќР°Р·Р°Рґ", callback_data="menu:main")]
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
        "рџ“– <b>РРЅСЃС‚СЂСѓРєС†РёСЏ РґР»СЏ SaaS-РєР»РёРµРЅС‚РѕРІ</b>\n\n"
        "<b>1. РџРѕРґРіРѕС‚РѕРІРєР°</b>\n"
        "в”Ђ Р‘РѕС‚ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё РїРѕР»СѓС‡Р°РµС‚ С‚РѕРІР°СЂС‹ РёР· РїСЂРѕРІРµСЂРµРЅРЅС‹С… РјР°РіР°Р·РёРЅРѕРІ (Admitad).\n"
        "в”Ђ Р’Р°Рј РЅРµ РЅСѓР¶РЅРѕ РІРІРѕРґРёС‚СЊ API-РєР»СЋС‡Рё РёР»Рё РѕРїР»Р°С‡РёРІР°С‚СЊ РїРѕРґРїРёСЃРєСѓ вЂ” РґРѕСЃС‚СѓРї Р±РµСЃСЃСЂРѕС‡РЅС‹Р№ Рё Р±РµСЃРїР»Р°С‚РЅС‹Р№.\n\n"
        "<b>2. РџРѕРґРєР»СЋС‡РµРЅРёРµ РєР°РЅР°Р»РѕРІ</b>\n"
        "в”Ђ РџРµСЂРµР№РґРёС‚Рµ РІ В«рџ“ў РњРѕРё РєР°РЅР°Р»С‹В» Рё РѕС‚РїСЂР°РІСЊС‚Рµ @username РІР°С€РµРіРѕ РєР°РЅР°Р»Р°.\n"
        "в”Ђ Р”Р»СЏ РєР°Р¶РґРѕРіРѕ РєР°РЅР°Р»Р° Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃРѕР·РґР°С‘С‚СЃСЏ СѓРЅРёРєР°Р»СЊРЅС‹Р№ РёРґРµРЅС‚РёС„РёРєР°С‚РѕСЂ, РєРѕС‚РѕСЂС‹Р№ РїРѕР·РІРѕР»СЏРµС‚ РѕС‚СЃР»РµР¶РёРІР°С‚СЊ РїСЂРѕРґР°Р¶Рё.\n\n"
        "<b>3. Р’С‹Р±РѕСЂ РјР°РіР°Р·РёРЅРѕРІ</b>\n"
         "в”Ђ РќР°Р¶РјРёС‚Рµ В«рџЏЄ РњР°РіР°Р·РёРЅС‹В» Рё РІС‹Р±РµСЂРёС‚Рµ С‚РёРї РјРѕРЅРµС‚РёР·Р°С†РёРё:\n"
         "   вЂў В«рџ›’ РџРѕРєСѓРїРєР° (CPA)В» вЂ” РґРѕС…РѕРґ Р·Р° РїРѕРґС‚РІРµСЂР¶РґС‘РЅРЅС‹Рµ Р·Р°РєР°Р·С‹.\n"
         "   вЂў В«рџ‘† РљР»РёРєРё (CPC)В» вЂ” РґРѕС…РѕРґ Р·Р° РєР»РёРєРё РїРѕ СЃСЃС‹Р»РєРµ.\n"
         "в”Ђ Р’ РєР°Р¶РґРѕРј СЂР°Р·РґРµР»Рµ РѕС‚РјРµС‚СЊС‚Рµ РёРЅС‚РµСЂРµСЃСѓСЋС‰РёРµ РјР°РіР°Р·РёРЅС‹ РёР»Рё СЂРµРєР»Р°РјРѕРґР°С‚РµР»РµР№.\n"
         "в”Ђ РћС‚ РІС‹Р±СЂР°РЅРЅС‹С… РјР°РіР°Р·РёРЅРѕРІ Р·Р°РІРёСЃРёС‚, РєР°РєРёРµ С‚РѕРІР°СЂС‹ Р±СѓРґСѓС‚ РїСѓР±Р»РёРєРѕРІР°С‚СЊСЃСЏ.\n\n"
         "<b>4. РђРІС‚РѕРјР°С‚РёС‡РµСЃРєРёР№ РїРѕСЃС‚РёРЅРі Рё РґРѕС…РѕРґ</b>\n"
        "в”Ђ Р‘РѕС‚ СЃР°РјРѕСЃС‚РѕСЏС‚РµР»СЊРЅРѕ РЅР°РїРѕР»РЅСЏРµС‚ РєР°С‚Р°Р»РѕРі С‚РѕРІР°СЂР°РјРё СЃ РјР°СЂРєРёСЂРѕРІРєРѕР№ ERID.\n"
        "в”Ђ РџРѕСЃС‚С‹ РІС‹С…РѕРґСЏС‚ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СЃ РїР°СЂС‚РЅС‘СЂСЃРєРёРјРё СЃСЃС‹Р»РєР°РјРё, РІ РєРѕС‚РѕСЂС‹Рµ РІСЃС‚СЂРѕРµРЅ РёРґРµРЅС‚РёС„РёРєР°С‚РѕСЂ РІР°С€РµРіРѕ РєР°РЅР°Р»Р°.\n"
        "в”Ђ Р”РѕС…РѕРґ РѕС‚ РїСЂРѕРґР°Р¶ СЂР°СЃРїСЂРµРґРµР»СЏРµС‚СЃСЏ РІ РїСЂРѕРїРѕСЂС†РёРё: 70% вЂ“ РІР°Рј, 30% вЂ“ СЃРµСЂРІРёСЃСѓ.\n\n"
        "<b>5. РРЅС‚РµСЂРІР°Р» РїРѕСЃС‚РѕРІ</b>\n"
        "в”Ђ Р’С‹ РјРѕР¶РµС‚Рµ РЅР°СЃС‚СЂРѕРёС‚СЊ С‡Р°СЃС‚РѕС‚Сѓ РїСѓР±Р»РёРєР°С†РёР№ РІ СЂР°Р·РґРµР»Рµ В«вљ™пёЏ РџРµСЂРёРѕРґРёС‡РЅРѕСЃС‚СЊ РїРѕСЃС‚РѕРІВ».\n\n"
        "<b>6. Р¦РёРєР»РёС‡РµСЃРєРёР№ РїРѕСЃС‚РёРЅРі</b>\n"
        "в”Ђ Р’ РЅР°СЃС‚СЂРѕР№РєР°С… SaaS РЅР°Р¶РјРёС‚Рµ В«вЏ° Р¦РёРєР»РёС‡РµСЃРєРёР№ РїРѕСЃС‚РёРЅРіВ» Рё Р·Р°РґР°Р№С‚Рµ РїРµСЂРёРѕРґРёС‡РЅРѕСЃС‚СЊ РґР»СЏ РєР°Р¶РґРѕРіРѕ РјР°РіР°Р·РёРЅР°.\n"
        "в”Ђ Р‘РѕС‚ Р±СѓРґРµС‚ РїСѓР±Р»РёРєРѕРІР°С‚СЊ С‚РѕРІР°СЂС‹ РёР· РЅСѓР¶РЅРѕРіРѕ РјР°РіР°Р·РёРЅР° С‡РµСЂРµР· Р·Р°РґР°РЅРЅС‹Рµ РёРЅС‚РµСЂРІР°Р»С‹ (РѕС‚ 1 РґРЅСЏ РґРѕ 1 РјРµСЃСЏС†Р°).\n"
        "в”Ђ Р•СЃР»Рё СЂР°СЃРїРёСЃР°РЅРёРµ РЅРµ РЅР°СЃС‚СЂРѕРµРЅРѕ вЂ” РјР°РіР°Р·РёРЅС‹ С‡РµСЂРµРґСѓСЋС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.\n\n"
        "<b>7. РђРІС‚РѕСѓРґР°Р»РµРЅРёРµ РїРѕСЃС‚РѕРІ</b>\n"
        "в”Ђ Р’ РЅР°СЃС‚СЂРѕР№РєР°С… SaaS РЅР°Р¶РјРёС‚Рµ В«рџ—‘ РђРІС‚РѕСѓРґР°Р»РµРЅРёРµ РїРѕСЃС‚РѕРІВ» Рё РІС‹Р±РµСЂРёС‚Рµ РІСЂРµРјСЏ Р¶РёР·РЅРё РїРѕСЃС‚Р°.\n"
        "в”Ђ РџРѕ СѓРјРѕР»С‡Р°РЅРёСЋ РїРѕСЃС‚С‹ СѓРґР°Р»СЏСЋС‚СЃСЏ С‡РµСЂРµР· 7 РґРЅРµР№. РњРѕР¶РЅРѕ РІС‹РєР»СЋС‡РёС‚СЊ РёР»Рё СѓСЃС‚Р°РЅРѕРІРёС‚СЊ РѕС‚ 1 С‡Р°СЃР° РґРѕ 30 РґРЅРµР№.\n"
        "в”Ђ РџРµСЂРµС…РѕРґС‹ Р·Р°СЃС‡РёС‚С‹РІР°СЋС‚СЃСЏ РІ С‚РµС‡РµРЅРёРµ 30 РґРЅРµР№ (РєСѓРєР° Admitad), РґР°Р¶Рµ РµСЃР»Рё РїРѕСЃС‚ СѓР¶Рµ СѓРґР°Р»С‘РЅ.\n\n"
         "<b>8. РЁР°Р±Р»РѕРЅС‹ Рё С„РёРЅР°РЅСЃС‹</b>\n"
         "в”Ђ Р’ РІРµР±-СЃС‚Р°С‚РёСЃС‚РёРєРµ (РєРЅРѕРїРєР° В«рџ“Љ Р’РµР±-СЃС‚Р°С‚РёСЃС‚РёРєР°В») РґРѕСЃС‚СѓРїРЅС‹ РѕС‚РґРµР»СЊРЅС‹Рµ С€Р°Р±Р»РѕРЅС‹ РґР»СЏ CPA-РїРѕСЃС‚РѕРІ Рё CPC-РїРѕСЃС‚РѕРІ.\n"
         "в”Ђ РўР°Рј Р¶Рµ РјРѕР¶РЅРѕ Р·Р°РїСЂРѕСЃРёС‚СЊ РІС‹РїР»Р°С‚Сѓ.\n\n"
        "<b>9. Р РµС„РµСЂР°Р»СЊРЅР°СЏ РїСЂРѕРіСЂР°РјРјР°</b>\n"
        "в”Ђ Р’С‹ РјРѕР¶РµС‚Рµ РїСЂРёРіР»Р°С€Р°С‚СЊ РґСЂСѓРіРёС… РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ РїРѕ СЂРµС„РµСЂР°Р»СЊРЅРѕР№ СЃСЃС‹Р»РєРµ Рё РїРѕР»СѓС‡Р°С‚СЊ 10% РѕС‚ РёС… РґРѕС…РѕРґР°.\n\n"
        "<i>РџРѕ РІСЃРµРј РІРѕРїСЂРѕСЃР°Рј РѕР±СЂР°С‰Р°Р№С‚РµСЃСЊ Рє Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂСѓ.</i>"
    )
    await safe_edit(callback.message, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="рџ”™ РќР°Р·Р°Рґ", callback_data="cabinet:open")]
        ]),
        parse_mode=ParseMode.HTML
    )
async def show_blogger_instruction(callback: CallbackQuery):
    text = (
        "рџ“– <b>РРЅСЃС‚СЂСѓРєС†РёСЏ: РљР°Рє Р·Р°СЂР°Р±Р°С‚С‹РІР°С‚СЊ СЃ Р±РѕС‚РѕРј</b>\n\n"
        "Р‘РѕС‚ СЃР°Рј РїСѓР±Р»РёРєСѓРµС‚ С‚РѕРІР°СЂС‹ РѕС‚ Р±СЂРµРЅРґРѕРІ РІ РІР°С€ TelegramвЂ‘РєР°РЅР°Р», Р° РІС‹ РїРѕР»СѓС‡Р°РµС‚Рµ <b>70%</b> "
        "РѕС‚ РєРѕРјРёСЃСЃРёРё Р·Р° РєР°Р¶РґСѓСЋ РїРѕРєСѓРїРєСѓ. Р§С‚РѕР±С‹ СЂР°Р±РѕС‚Р° Р±С‹Р»Р° СЃС‚Р°Р±РёР»СЊРЅРѕР№ Рё Р»РµРіР°Р»СЊРЅРѕР№, СЃР»РµРґСѓР№С‚Рµ С‚СЂС‘Рј С€Р°РіР°Рј.\n\n"
        "<b>вЏі РЁР°Рі 1. РљР°Рє СѓСЃС‚СЂРѕРµРЅ Р±Р°Р»Р°РЅСЃ</b>\n"
        "РљРѕРіРґР° РїРѕРґРїРёСЃС‡РёРє РїРµСЂРµС…РѕРґРёС‚ РїРѕ СЃСЃС‹Р»РєРµ Рё РїРѕРєСѓРїР°РµС‚ С‚РѕРІР°СЂ, РІ РІРµР±-СЃС‚Р°С‚РёСЃС‚РёРєРµ (РєРЅРѕРїРєР° В«рџ“Љ Р’РµР±-СЃС‚Р°С‚РёСЃС‚РёРєР°В») РѕР±РЅРѕРІР»СЏРµС‚СЃСЏ Р±Р°Р»Р°РЅСЃ:\n"
        "вЂў <b>В«Р’ РѕР¶РёРґР°РЅРёРёВ»</b> вЂ” РјР°РіР°Р·РёРЅ РїСЂРѕРІРµСЂСЏРµС‚ Р·Р°РєР°Р· (30вЂ“90 РґРЅРµР№).\n"
        "вЂў <b>В«Р”РѕСЃС‚СѓРїРЅРѕ Рє РІС‹РІРѕРґСѓВ»</b> вЂ” РґРµРЅСЊРіРё РїРѕРґС‚РІРµСЂР¶РґРµРЅС‹, РјРѕР¶РЅРѕ Р·Р°Р±РёСЂР°С‚СЊ.\n\n"
        "<b>рџ’і РЁР°Рі 2. Р’С‹РІРѕРґ СЃСЂРµРґСЃС‚РІ Рё РЅР°Р»РѕРіРё</b>\n"
        "РњРёРЅРёРјР°Р»СЊРЅР°СЏ СЃСѓРјРјР° РґР»СЏ РІС‹РІРѕРґР° вЂ” <b>3000 в‚Ѕ</b>. РЎРµСЂРІРёСЃ СЂР°Р±РѕС‚Р°РµС‚ РѕС„РёС†РёР°Р»СЊРЅРѕ, РїРѕСЌС‚РѕРјСѓ РІС‹ РѕР±СЏР·Р°РЅС‹ "
        "РёРјРµС‚СЊ СЃС‚Р°С‚СѓСЃ <b>РЎР°РјРѕР·Р°РЅСЏС‚РѕРіРѕ</b> (РѕС„РѕСЂРјР»СЏРµС‚СЃСЏ Р±РµСЃРїР»Р°С‚РЅРѕ РІ РїСЂРёР»РѕР¶РµРЅРёРё В«РњРѕР№ РќР°Р»РѕРіВ») РёР»Рё <b>РРџ</b>.\n"
        "РљРѕРіРґР° РЅР°РєРѕРїРёС‚СЃСЏ 3000 в‚Ѕ, РѕС‚РєСЂРѕР№С‚Рµ РІРµР±-СЃС‚Р°С‚РёСЃС‚РёРєСѓ Рё РЅР°Р¶РјРёС‚Рµ В«рџ’ё Р—Р°РїСЂРѕСЃРёС‚СЊ РІС‹РїР»Р°С‚СѓВ», СѓРєР°Р¶РёС‚Рµ СЂРµРєРІРёР·РёС‚С‹.\n\n"
        "<b>рџ›ЎпёЏ РЁР°Рі 3. Р§РµРє Рё Р·Р°С‰РёС‚Р° РІС‹РїР»Р°С‚С‹</b>\n"
        "вЂў РђРґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ РѕС‚РїСЂР°РІР»СЏРµС‚ РґРµРЅСЊРіРё.\n"
        "вЂў Р’ РІРµР±-СЃС‚Р°С‚РёСЃС‚РёРєРµ РїРѕСЏРІРёС‚СЃСЏ С‡Р°С‚ СЃ РєРЅРѕРїРєРѕР№ В«рџ“¤ РћС‚РїСЂР°РІРёС‚СЊ С‡РµРєВ». <b>Р’С‹ РѕР±СЏР·Р°РЅС‹ РІ С‚РµС‡РµРЅРёРµ 24 С‡Р°СЃРѕРІ</b> "
        "СЃС„РѕСЂРјРёСЂРѕРІР°С‚СЊ С‡РµРє РІ РїСЂРёР»РѕР¶РµРЅРёРё В«РњРѕР№ РќР°Р»РѕРіВ» (С‚РёРї: РџСЂРѕРґР°Р¶Р° С„РёР·.Р»РёС†Сѓ, СѓСЃР»СѓРіР°: Р РµРєР»Р°РјРЅС‹Рµ СѓСЃР»СѓРіРё) "
        "Рё Р·Р°РіСЂСѓР·РёС‚СЊ РµРіРѕ.\n"
        "вЂў РџРѕСЃР»Рµ РїСЂРѕРІРµСЂРєРё Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂРѕРј Р·Р°СЏРІРєР° Р·Р°РєСЂС‹РІР°РµС‚СЃСЏ.\n\n"
        "<b>вљ пёЏ Р’РђР–РќРћ:</b> Р•СЃР»Рё РІС‹ РЅРµ РїСЂРёС€Р»С‘С‚Рµ С‡РµРє Р·Р° 24 С‡Р°СЃР°, Р°РєРєР°СѓРЅС‚ Р±СѓРґРµС‚ <b>Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅ РЅР°РІСЃРµРіРґР°</b>, "
        "Р° РЅРµРІС‹РїР»Р°С‡РµРЅРЅС‹Рµ СЃСЂРµРґСЃС‚РІР° Р°РЅРЅСѓР»РёСЂРѕРІР°РЅС‹.\n\n"
        "<b>рџљ« Р—Р°РїСЂРµС‰РµРЅРѕ (Р±Р°РЅ Р±РµР· РІС‹РїР»Р°С‚):</b>\n"
        "вЂў РЎРїР°Рј СЃСЃС‹Р»РєР°РјРё РІ С‡СѓР¶РёС… РєР°РЅР°Р»Р°С…, РєРѕРјРјРµРЅС‚Р°СЂРёСЏС…, Р»РёС‡РЅС‹С… СЃРѕРѕР±С‰РµРЅРёСЏС….\n"
        "вЂў РњРѕС‚РёРІРёСЂРѕРІР°РЅРЅС‹Р№ С‚СЂР°С„РёРє (РїСЂРѕСЃСЊР±С‹ В«РєСѓРїРё РїРѕ СЃСЃС‹Р»РєРµ, СЏ РІРµСЂРЅСѓ РґРµРЅСЊРіРёВ»).\n"
        "вЂў РЎР°РјРѕРІС‹РєСѓРїС‹ Рё РЅР°РєСЂСѓС‚РєР°.\n"
        "вЂў Р Р°Р·РјРµС‰РµРЅРёРµ СЃСЃС‹Р»РѕРє РІ РєР°РЅР°Р»Р°С… СЃ Р·Р°РїСЂРµС‰С‘РЅРЅС‹Рј РєРѕРЅС‚РµРЅС‚РѕРј (РєР°Р·РёРЅРѕ, РїРёСЂР°С‚СЃС‚РІРѕ, С‚СЂРµС€).\n\n"
        "<b>рџљЂ РЎ С‡РµРіРѕ РЅР°С‡Р°С‚СЊ:</b>\n"
         "1. Р”РѕР±Р°РІСЊС‚Рµ РєР°РЅР°Р» С‡РµСЂРµР· В«рџ“ў РњРѕРё TelegramвЂ‘РєР°РЅР°Р»С‹В».\n"
         "2. РќР°Р·РЅР°С‡СЊС‚Рµ Р±РѕС‚Р° Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂРѕРј СЃ РїСЂР°РІРѕРј РїСѓР±Р»РёРєР°С†РёРё.\n"
         "3. Р’С‹Р±РµСЂРёС‚Рµ РјР°РіР°Р·РёРЅС‹ РІ В«рџЏЄ РњР°РіР°Р·РёРЅС‹В» (CPA РґР»СЏ РґРѕС…РѕРґР° СЃ РїСЂРѕРґР°Р¶, CPC РґР»СЏ РґРѕС…РѕРґР° СЃ РєР»РёРєРѕРІ).\n"
         "4. РќР°СЃС‚СЂРѕР№С‚Рµ РёРЅС‚РµСЂРІР°Р» РїРѕСЃС‚РѕРІ.\n"
         "5. РќР°СЃС‚СЂРѕР№С‚Рµ С€Р°Р±Р»РѕРЅС‹ Рё СЃР»РµРґРёС‚Рµ Р·Р° РґРѕС…РѕРґРѕРј РІ В«рџ“Љ Р’РµР±вЂ‘СЃС‚Р°С‚РёСЃС‚РёРєР°В».\n\n"
        "<b>вЏ° Р¦РёРєР»РёС‡РµСЃРєРёР№ РїРѕСЃС‚РёРЅРі (РІ РЅР°СЃС‚СЂРѕР№РєР°С… SaaS):</b>\n"
        "в”Ђ Р—Р°РґР°Р№С‚Рµ РїРµСЂРёРѕРґРёС‡РЅРѕСЃС‚СЊ РґР»СЏ РєР°Р¶РґРѕРіРѕ РјР°РіР°Р·РёРЅР° (1 РґРµРЅСЊ вЂ“ 1 РјРµСЃСЏС†).\n"
        "в”Ђ Р‘РѕС‚ Р±СѓРґРµС‚ РїСѓР±Р»РёРєРѕРІР°С‚СЊ С‚РѕРІР°СЂС‹ РёР· РЅСѓР¶РЅРѕРіРѕ РјР°РіР°Р·РёРЅР° РїРѕ СЂР°СЃРїРёСЃР°РЅРёСЋ.\n\n"
        "<b>рџ—‘ РђРІС‚РѕСѓРґР°Р»РµРЅРёРµ РїРѕСЃС‚РѕРІ:</b>\n"
        "в”Ђ РџРѕ СѓРјРѕР»С‡Р°РЅРёСЋ РїРѕСЃС‚С‹ СѓРґР°Р»СЏСЋС‚СЃСЏ С‡РµСЂРµР· 7 РґРЅРµР№. РњРѕР¶РЅРѕ РёР·РјРµРЅРёС‚СЊ (РѕС‚ 1 С‡Р°СЃР° РґРѕ 30 РґРЅРµР№) РёР»Рё РІС‹РєР»СЋС‡РёС‚СЊ.\n"
        "в”Ђ РџРµСЂРµС…РѕРґС‹ Р·Р°СЃС‡РёС‚С‹РІР°СЋС‚СЃСЏ 30 РґРЅРµР№ (РєСѓРєР° Admitad), РґР°Р¶Рµ РїРѕСЃР»Рµ СѓРґР°Р»РµРЅРёСЏ РїРѕСЃС‚Р°.\n\n"
        "РџРѕ РІРѕРїСЂРѕСЃР°Рј РїРёС€РёС‚Рµ: рџ‘‰ <a href='https://t.me/Zigih90'>@Zigih90</a>"
    )
    await safe_edit(callback.message, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="рџ”™ РќР°Р·Р°Рґ", callback_data="cabinet:open")]
        ]),
        parse_mode=ParseMode.HTML
    )

# ---------------------------------------------------------------------------
# РђРґРјРёРЅРёСЃС‚СЂР°С‚РёРІРЅС‹Рµ РєРѕРјР°РЅРґС‹
# ---------------------------------------------------------------------------


@router.message(Command("debug_sub"))
async def debug_subscription(message: Message):
    if not is_admin(message.from_user.id):
        return
    conn = get_db()
    user = conn.execute("SELECT role, subscription_until FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()
    if user:
        await message.answer(f"DEBUG:\nР РѕР»СЊ: {user['role']}\nРџРѕРґРїРёСЃРєР° РґРѕ: {user['subscription_until']}")
    else:
        await message.answer("РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РЅР°Р№РґРµРЅ РІ Р‘Р”!")

@router.message(Command("fix_channels"))
async def fix_duplicate_channels(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    conn = get_db()
    conn.execute("DELETE FROM channels WHERE id NOT IN (SELECT MIN(id) FROM channels GROUP BY user_id, channel_id)")
    conn.commit()
    conn.close()
    await message.answer("вњ… Р”СѓР±Р»РёРєР°С‚С‹ РєР°РЅР°Р»РѕРІ СѓРґР°Р»РµРЅС‹.")

@router.callback_query(F.data.startswith("admin:"))
async def handle_admin_callbacks(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("в›” РќРµС‚ РґРѕСЃС‚СѓРїР°", show_alert=True)
        return
    action = call.data.split(":")[1]
    if action == "broadcast":
        await call.answer()
        await state.set_state(AdminStates.broadcast_text)
        await call.message.answer("вњЏпёЏ Р’РІРµРґРё С‚РµРєСЃС‚ СЂР°СЃСЃС‹Р»РєРё:")
    elif action == "extend_sub":
        await call.answer()
        await state.set_state(AdminStates.extend_user_id)
        await call.message.answer("рџ‘¤ Р’РІРµРґРё user_id РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ:")
    else:
        await call.answer("РќРµРёР·РІРµСЃС‚РЅР°СЏ РєРѕРјР°РЅРґР°", show_alert=True)


@router.callback_query(F.data == "payout:request")
async def cb_payout_request(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT balance_available, tax_status FROM users WHERE user_id=?", (user_id,)).fetchone()
        available = user["balance_available"]
        tax_status = user["tax_status"]
        # РџСЂРѕРІРµСЂРєР° РЅР°Р»РѕРіРѕРІРѕРіРѕ СЃС‚Р°С‚СѓСЃР°
        if tax_status != "business":
            await callback.answer("вќЊ Р’С‹РІРѕРґ СЃСЂРµРґСЃС‚РІ РґРѕСЃС‚СѓРїРµРЅ С‚РѕР»СЊРєРѕ СЃР°РјРѕР·Р°РЅСЏС‚С‹Рј/РРџ.", show_alert=True)
            return
        # РџСЂРѕРІРµСЂРєР° Р°РєС‚РёРІРЅС‹С… Р·Р°СЏРІРѕРє
        active = conn.execute(
            "SELECT id FROM payout_requests WHERE user_id=? AND status IN ('processing','awaiting_receipt','receipt_uploaded')",
            (user_id,)
        ).fetchone()
        if active:
            await callback.answer("вќЊ РЈ РІР°СЃ СѓР¶Рµ РµСЃС‚СЊ Р°РєС‚РёРІРЅР°СЏ Р·Р°СЏРІРєР° РЅР° РІС‹РїР»Р°С‚Сѓ.", show_alert=True)
            return
        if available < MIN_PAYOUT:
            await callback.answer(f"вќЊ РњРёРЅРёРјР°Р»СЊРЅР°СЏ СЃСѓРјРјР° РІС‹РІРѕРґР°: {MIN_PAYOUT} в‚Ѕ", show_alert=True)
            return
    finally:
        conn.close()

    await safe_edit(callback.message,
        f"рџ’ё РЈРєР°Р¶РёС‚Рµ СЂРµРєРІРёР·РёС‚С‹ РґР»СЏ РІС‹РїР»Р°С‚С‹ (РЅРѕРјРµСЂ РєР°СЂС‚С‹, Р±Р°РЅРє, TON-РєРѕС€РµР»С‘Рє РёР»Рё РґСЂСѓРіРёРµ РґР°РЅРЅС‹Рµ):\n"
        f"Р”РѕСЃС‚СѓРїРЅРѕ: <b>{available:.2f} в‚Ѕ</b>\n\n"
        f"РџСЂРёРјРµСЂ: <i>РЎР±РµСЂР±Р°РЅРє 2202 2081 0829 0025</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="рџ”™ РћС‚РјРµРЅР°", callback_data="menu:finance")]
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
            "вќЊ Р РµРєРІРёР·РёС‚С‹ СЃР»РёС€РєРѕРј РєРѕСЂРѕС‚РєРёРµ РёР»Рё РґР»РёРЅРЅС‹Рµ (3вЂ“100 СЃРёРјРІРѕР»РѕРІ).\n"
            "РџСЂРёРјРµСЂ: <i>РЎР±РµСЂР±Р°РЅРє 2202 2081 0829 0025</i> РёР»Рё <i>UQAbc123...</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    conn = get_db()
    try:
        user = conn.execute("SELECT balance_available, tax_status FROM users WHERE user_id=?", (user_id,)).fetchone()
        available = user["balance_available"]
        if user["tax_status"] != "business":
            await message.answer("вќЊ Р’С‹РІРѕРґ СЃСЂРµРґСЃС‚РІ РЅРµРґРѕСЃС‚СѓРїРµРЅ РґР»СЏ РІР°С€РµРіРѕ РЅР°Р»РѕРіРѕРІРѕРіРѕ СЃС‚Р°С‚СѓСЃР°.")
            await state.clear()
            return
        if available < MIN_PAYOUT:
            await message.answer("вќЊ РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ СЃСЂРµРґСЃС‚РІ.")
            await state.clear()
            return
        # РЎРїРёСЃР°РЅРёРµ Р±Р°Р»Р°РЅСЃР° СЃСЂР°Р·Сѓ
        conn.execute("UPDATE users SET balance_available = balance_available - ? WHERE user_id=?", (available, user_id))
        # РЎРѕР·РґР°РЅРёРµ Р·Р°СЏРІРєРё СЃРѕ СЃС‚Р°С‚СѓСЃРѕРј processing
        conn.execute(
            "INSERT INTO payout_requests (user_id, amount, message, status) VALUES (?, ?, ?, 'processing')",
            (user_id, available, text)
        )
        conn.commit()
        request_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()

    await message.answer(
        f"вњ… Р—Р°СЏРІРєР° РЅР° РІС‹РїР»Р°С‚Сѓ <b>{available:.2f} в‚Ѕ</b> СЃРѕР·РґР°РЅР° Рё РїРµСЂРµРґР°РЅР° Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂСѓ. "
        f"РќРѕРјРµСЂ Р·Р°СЏРІРєРё: <b>#{request_id}</b>.\nРћР¶РёРґР°Р№С‚Рµ СѓРІРµРґРѕРјР»РµРЅРёСЏ Рѕ РїРµСЂРµРІРѕРґРµ.",
        parse_mode=ParseMode.HTML
    )

    # РЈРІРµРґРѕРјР»РµРЅРёРµ Р°РґРјРёРЅР°Рј
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"рџ”” РќРѕРІС‹Р№ Р·Р°РїСЂРѕСЃ РЅР° РІС‹РїР»Р°С‚Сѓ!\n"
                f"РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ: {user_id}\n"
                f"РЎСѓРјРјР°: {available:.2f} в‚Ѕ\n"
                f"Р—Р°СЏРІРєР° #{request_id}\n"
                f"Р РµРєРІРёР·РёС‚С‹: {text[:200]}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="рџЊђ РћС‚РєСЂС‹С‚СЊ Р°РґРјРёРЅРєСѓ", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))]
                ])
            )
        except Exception as e:
            logger.error(f"РќРµ СѓРґР°Р»РѕСЃСЊ СѓРІРµРґРѕРјРёС‚СЊ Р°РґРјРёРЅР° {admin_id}: {e}")

    await state.clear()
# ---------------------------------------------------------------------------
# РљРѕР»Р±СЌРє "cabinet:open" (РёР· РёРЅС‚РµСЂС„РµР№СЃР°)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "cabinet:open")
async def cb_open_cabinet(callback: CallbackQuery):
    await show_user_cabinet(callback.message, user_id=callback.from_user.id, edit_message=callback.message)
    await callback.answer()

# ---------------------------------------------------------------------------
# РџР»Р°РЅРёСЂРѕРІС‰РёРє Рё РїРµСЂРёРѕРґРёС‡РµСЃРєРёРµ Р·Р°РґР°С‡Рё
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
        logger.info(f"РћС‡РёСЃС‚РєР°: {draft_count} С‡РµСЂРЅРѕРІРёРєРѕРІ, {pub_count} РѕРїСѓР±Р»РёРєРѕРІР°РЅРЅС‹С…, {orphan_count} orphan subid_stats")
    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РѕС‡РёСЃС‚РєРё: {e}")
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
        logger.info(f"РћС‡РёСЃС‚РєР° РѕС‚С‡С‘С‚РѕРІ: СѓРґР°Р»РµРЅРѕ {removed} С„Р°Р№Р»РѕРІ СЃС‚Р°СЂС€Рµ 90 РґРЅРµР№")

async def auto_delete_posts(bot: Bot):
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT p.id, p.channel_id, p.direct_link, p.user_id, p.auto_delete_hours, p.published_at
            FROM posts p
            WHERE p.status = 'published'
              AND p.auto_delete_hours IS NOT NULL
              AND p.auto_delete_hours > 0
              AND p.published_at IS NOT NULL
              AND datetime(p.published_at, '+' || p.auto_delete_hours || ' hours') <= datetime('now')
        """).fetchall()
        deleted_count = 0
        for row in rows:
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
            logger.info(f"РђРІС‚РѕСѓРґР°Р»РµРЅРёРµ: СѓРґР°Р»РµРЅРѕ {deleted_count} РїРѕСЃС‚РѕРІ РёР· РєР°РЅР°Р»РѕРІ")
    except Exception as e:
        logger.error(f"РћС€РёР±РєР° Р°РІС‚РѕСѓРґР°Р»РµРЅРёСЏ: {e}")
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
        writer.writerow(["РљР°РЅР°Р» (ID)", "SubID", "РџСЂСЏРјР°СЏ СЃСЃС‹Р»РєР° РЅР° РїРѕСЃС‚", "Р’СЂРµРјСЏ (UTC)", "РќР°Р·РІР°РЅРёРµ РєР°РЅР°Р»Р°"])
        for ch_id, subid, link, ts, title in rows:
            writer.writerow([ch_id, subid or "", link or "", ts or "", title or ""])

    caption = (
        f"рџ“Љ <b>Р•Р¶РµРґРЅРµРІРЅС‹Р№ РѕС‚С‡С‘С‚</b>\n"
        f"рџ“… {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC\n\n"
        f"рџџў РђРєС‚РёРІРЅС‹С… РєР°РЅР°Р»РѕРІ: <b>{active_channels}</b>\n"
        f"рџ“¬ Р’СЃРµРіРѕ РїРѕСЃС‚РѕРІ: <b>{total_posts}</b>\n"
        f"рџ’° РќРѕРІС‹С… С‚СЂР°РЅР·Р°РєС†РёР№: <b>{new_tx}</b>\n\n"
        f"рџ“Ћ Р¤Р°Р№Р» СЃРѕС…СЂР°РЅС‘РЅ РЅР° СЃРµСЂРІРµСЂРµ: <code>{filepath}</code>"
    )

    admin_id = ADMIN_IDS[0] if ADMIN_IDS else None
    if admin_id:
        try:
            from aiogram.types import FSInputFile
            doc = FSInputFile(filepath, filename=filename)
            await bot.send_document(admin_id, document=doc, caption=caption, parse_mode="HTML")
            logger.info(f"Р•Р¶РµРґРЅРµРІРЅС‹Р№ РѕС‚С‡С‘С‚ РѕС‚РїСЂР°РІР»РµРЅ Рё СЃРѕС…СЂР°РЅС‘РЅ РєР°Рє {filepath}")
        except Exception as e:
            logger.error(f"РћС€РёР±РєР° РѕС‚РїСЂР°РІРєРё РµР¶РµРґРЅРµРІРЅРѕРіРѕ РѕС‚С‡С‘С‚Р°: {e}")


async def check_receipt_reminders(bot: Bot):
    """РќР°РїРѕРјРёРЅР°РµС‚ Р±Р»РѕРіРµСЂР°Рј Рѕ РЅРµРѕР±С…РѕРґРёРјРѕСЃС‚Рё Р·Р°РіСЂСѓР·РёС‚СЊ С‡РµРє С‡РµСЂРµР· 12 С‡Р°СЃРѕРІ РїРѕСЃР»Рµ РѕС‚РїСЂР°РІРєРё РґРµРЅРµРі."""
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
                    f"вЏ° <b>РќР°РїРѕРјРёРЅР°РЅРёРµ Рѕ С‡РµРєРµ</b>\n\n"
                    f"Р’Р°Рј Р±С‹Р» РѕС‚РїСЂР°РІР»РµРЅ РїРµСЂРµРІРѕРґ РЅР° СЃСѓРјРјСѓ <b>{row['amount']} в‚Ѕ</b>.\n"
                    "РЎРѕРіР»Р°СЃРЅРѕ РѕС„РµСЂС‚Рµ, РІС‹ РѕР±СЏР·Р°РЅС‹ Р·Р°РіСЂСѓР·РёС‚СЊ С‡РµРє РёР· РїСЂРёР»РѕР¶РµРЅРёСЏ В«РњРѕР№ РЅР°Р»РѕРіВ» РІ С‚РµС‡РµРЅРёРµ 24 С‡Р°СЃРѕРІ.\n"
                    "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РїРµСЂРµР№РґРёС‚Рµ РІ РІРµР±-СЃС‚Р°С‚РёСЃС‚РёРєСѓ Рё РЅР°Р¶РјРёС‚Рµ В«рџ“¤ РћС‚РїСЂР°РІРёС‚СЊ С‡РµРєВ».",
                    parse_mode=ParseMode.HTML
                )
                conn.execute("UPDATE payout_requests SET receipt_reminded = 1 WHERE id = ?", (row["id"],))
                conn.commit()
                logger.info(f"РћС‚РїСЂР°РІР»РµРЅРѕ РЅР°РїРѕРјРёРЅР°РЅРёРµ Рѕ С‡РµРєРµ РїРѕ Р·Р°СЏРІРєРµ #{row['id']}")
            except Exception as e:
                logger.error(f"РћС€РёР±РєР° РѕС‚РїСЂР°РІРєРё РЅР°РїРѕРјРёРЅР°РЅРёСЏ РґР»СЏ Р·Р°СЏРІРєРё #{row['id']}: {e}")
    finally:
        conn.close()

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    logger.info("рџ”„ РќР°СЃС‚СЂРѕР№РєР° РїР»Р°РЅРёСЂРѕРІС‰РёРєР°...")
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    
    scheduler.add_job(unpin_old_messages, trigger="interval", minutes=30, kwargs={"bot": bot}, id="unpin_vip_posts", replace_existing=True)
    scheduler.add_job(cleanup_old_posts, trigger="cron", hour=3, minute=0, id="cleanup_old_posts", replace_existing=True)
    scheduler.add_job(cleanup_old_report_files, trigger="cron", hour=3, minute=5, id="cleanup_report_files", replace_existing=True)
    scheduler.add_job(backup_database_to_telegram, trigger="cron", hour=3, minute=10, kwargs={"bot": bot}, id="backup_database", replace_existing=True)
    scheduler.add_job(publish_from_catalog, trigger="interval", minutes=10, jitter=30, kwargs={"bot": bot}, id="publish_catalog", replace_existing=True)
    scheduler.add_job(publish_cpc_campaigns, trigger="interval", minutes=15, jitter=30, kwargs={"bot": bot}, id="publish_cpc", replace_existing=True)
    scheduler.add_job(refill_admitad_catalogs, trigger="interval", minutes=15, id="refill_admitad", replace_existing=True)
    scheduler.add_job(daily_report, trigger="cron", hour=9, minute=0, kwargs={"bot": bot}, id="daily_report", replace_existing=True)
    scheduler.add_job(update_all_store_data_from_feed, trigger="cron", hour=4, minute=0, id="update_coupons_feed", replace_existing=True)
    scheduler.add_job(check_rss_and_publish, trigger="interval", minutes=15, kwargs={"bot": bot}, id="check_rss", replace_existing=True)
    scheduler.add_job(check_receipt_reminders, trigger="interval", minutes=30, kwargs={"bot": bot}, id="receipt_reminders", replace_existing=True)
    scheduler.add_job(update_post_views, 'cron', hour=3, minute=30, kwargs={"bot": bot}, id="update_views", replace_existing=True)
    scheduler.add_job(generate_monthly_ord_reports, trigger="cron", day=1, hour=0, minute=5, kwargs={"bot": bot}, id="monthly_ord_reports", replace_existing=True)
    scheduler.add_job(auto_delete_posts, trigger="interval", minutes=15, kwargs={"bot": bot}, id="auto_delete_posts", replace_existing=True)
    
    logger.info("вњ… Р’СЃРµ Р·Р°РґР°С‡Рё РґРѕР±Р°РІР»РµРЅС‹ РІ РїР»Р°РЅРёСЂРѕРІС‰РёРє")
    return scheduler
# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
async def main() -> None:
    logger.info("=== AutoPost Bot + Web Admin Panel Р·Р°РїСѓСЃРєР°РµС‚СЃСЏ ===")
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

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("РџР»Р°РЅРёСЂРѕРІС‰РёРє (APScheduler) Р·Р°РїСѓС‰РµРЅ")

    # Р‘СЌРєС‚РµР№Р» СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёС… РєР°РЅР°Р»РѕРІ РІ Admitad subnetwork
    try:
        from services.admitad_subnetwork import backfill_existing_channels
        asyncio.create_task(backfill_existing_channels())
    except Exception as e:
        logger.warning(f"вљ пёЏ Р—Р°РїСѓСЃРє Р±СЌРєС‚РµР№Р»Р° subnetwork РѕС‚Р»РѕР¶РµРЅ: {e}")

    # ===== РљРћРњРђРќР”Р« Р”Р›РЇ Р’РЎР•РҐ РџРћР›Р¬Р—РћР’РђРўР•Р›Р•Р™ =====
    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ"),
            BotCommand(command="cabinet", description="Р›РёС‡РЅС‹Р№ РєР°Р±РёРЅРµС‚"),
            BotCommand(command="help", description="РЎРїСЂР°РІРєР° Рё РєРѕРЅС‚Р°РєС‚С‹"),
        ],
        scope=BotCommandScopeDefault(),
    )

    # ===== РљРћРњРђРќР”Р« Р”Р›РЇ РђР”РњРРќРћР’ =====
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(
                commands=[
                    BotCommand(command="start", description="РџР°РЅРµР»СЊ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР°"),
                    BotCommand(command="cabinet", description="РџР°РЅРµР»СЊ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР°"),
                    BotCommand(command="debug_sub", description="РџСЂРѕРІРµСЂРёС‚СЊ РїРѕРґРїРёСЃРєСѓ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ"),
                    BotCommand(command="fix_channels", description="РЈРґР°Р»РёС‚СЊ РґСѓР±Р»РёРєР°С‚С‹ РєР°РЅР°Р»РѕРІ"),
                    BotCommand(command="beta", description="РЈРїСЂР°РІР»РµРЅРёРµ Р±РµС‚Р°-С‚РµСЃС‚РµСЂР°РјРё"),
                    BotCommand(command="preview", description="РџСЂРµРґРїСЂРѕСЃРјРѕС‚СЂ РїРѕСЃС‚Р°"),
                ],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except TelegramBadRequest as e:
            logger.warning(f"РќРµ СѓРґР°Р»РѕСЃСЊ СѓСЃС‚Р°РЅРѕРІРёС‚СЊ РєРѕРјР°РЅРґС‹ РґР»СЏ Р°РґРјРёРЅР° {admin_id}: {e}")

    # ===== РљРћРњРђРќР”Р« Р”Р›РЇ Р‘Р•РўРђ-РўР•РЎРўР•Р РћР’ =====
    for tester in get_beta_testers():
        user_id = tester["user_id"]
        if user_id in ADMIN_IDS:
            continue
        try:
            await bot.set_my_commands(
                commands=[
                    BotCommand(command="start", description="Р“Р»Р°РІРЅРѕРµ РјРµРЅСЋ"),
                    BotCommand(command="cabinet", description="Р›РёС‡РЅС‹Р№ РєР°Р±РёРЅРµС‚"),
                    BotCommand(command="preview", description="РџСЂРµРґРїСЂРѕСЃРјРѕС‚СЂ РїРѕСЃС‚Р°"),
                ],
                scope=BotCommandScopeChat(chat_id=user_id),
            )
            logger.info(f"РљРѕРјР°РЅРґС‹ РґР»СЏ Р±РµС‚Р°-С‚РµСЃС‚РµСЂР° {user_id} СѓСЃС‚Р°РЅРѕРІР»РµРЅС‹")
        except Exception as e:
            logger.warning(f"РќРµ СѓРґР°Р»РѕСЃСЊ СѓСЃС‚Р°РЅРѕРІРёС‚СЊ РєРѕРјР°РЅРґС‹ РґР»СЏ {user_id}: {e}")

    # ===== Р—РђРџРЈРЎРљ FASTAPI =====
    fastapi_app = create_app(bot)
    config = uvicorn.Config(
        fastapi_app,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        log_level="warning"
    )
    server = uvicorn.Server(config)

    logger.info(f"рџЊђ Web Admin Panel РґРѕСЃС‚СѓРїРµРЅ РїРѕ Р°РґСЂРµСЃСѓ: http://{WEBAPP_HOST}:{WEBAPP_PORT}/admin")

    try:
        await asyncio.gather(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
            server.serve(),
            return_exceptions=True
        )
    finally:
        await bot.session.close()
        scheduler.shutdown()
        logger.info("Р‘РѕС‚ Рё РїР»Р°РЅРёСЂРѕРІС‰РёРє РѕСЃС‚Р°РЅРѕРІР»РµРЅС‹")

async def generate_monthly_ord_reports(bot: Bot):
    """Р“РµРЅРµСЂРёСЂСѓРµС‚ РѕС‚С‡С‘С‚ РћР Р” Р·Р° РїСЂРѕС€РµРґС€РёР№ РјРµСЃСЏС† Рё РѕС‚РїСЂР°РІР»СЏРµС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏРј РІ Telegram"""
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
                "ERID", "РџР»РѕС‰Р°РґРєР° (Telegram)", "РўРёРї РїР»РѕС‰Р°РґРєРё",
                "РљРѕР»РёС‡РµСЃС‚РІРѕ РїРѕРєР°Р·РѕРІ", "РљРѕР»РёС‡РµСЃС‚РІРѕ РїРµСЂРµС…РѕРґРѕРІ", "РЎСѓРјРјР° РїРѕС‚СЂР°С‡РµРЅРЅР°СЏ",
                "Р”Р°С‚Р° РЅР°С‡Р°Р»Р°", "Р”Р°С‚Р° РѕРєРѕРЅС‡Р°РЅРёСЏ", "РЎСЃС‹Р»РєР° РЅР° РїРѕСЃС‚", "РќР°Р·РІР°РЅРёРµ РєР°РЅР°Р»Р°"
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
                caption=f"рџ“Љ РћС‚С‡С‘С‚ РћР Р” Р·Р° {month_label}\n\nР’СЃРµРіРѕ РїРѕСЃС‚РѕРІ: {len(posts)}"
            )
            logger.info(f"РћС‚С‡С‘С‚ РћР Р” Р·Р° {month_label} РѕС‚РїСЂР°РІР»РµРЅ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ {user_id}")
        except Exception as e:
            logger.error(f"РћС€РёР±РєР° РіРµРЅРµСЂР°С†РёРё РѕС‚С‡С‘С‚Р° РґР»СЏ user_id={user_id}: {e}")
async def backup_database_to_telegram(bot: Bot):
    db_path = DB_PATH
    if not os.path.exists(db_path):
        logger.error("Р‘СЌРєР°Рї: С„Р°Р№Р» Р±Р°Р·С‹ РґР°РЅРЅС‹С… РЅРµ РЅР°Р№РґРµРЅ")
        return

    admin_id = ADMIN_IDS[0] if ADMIN_IDS else None
    if not admin_id:
        logger.error("Р‘СЌРєР°Рї: РЅРµ СѓРєР°Р·Р°РЅ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂ")
        return

    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"autopost_backup_{timestamp}.db"
        db_file = FSInputFile(db_path, filename=filename)
        await bot.send_document(
            chat_id=admin_id,
            document=db_file,
            caption=f"рџ“¦ Р•Р¶РµРґРЅРµРІРЅС‹Р№ Р±СЌРєР°Рї Р±Р°Р·С‹ РґР°РЅРЅС‹С… ({timestamp})"
        )
        logger.info("Р‘СЌРєР°Рї Р±Р°Р·С‹ РґР°РЅРЅС‹С… РѕС‚РїСЂР°РІР»РµРЅ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂСѓ")
    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РїСЂРё РѕС‚РїСЂР°РІРєРµ Р±СЌРєР°РїР°: {e}")

@router.message(Command("beta"))
async def cmd_beta(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "рџ“‹ РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ:\n"
            "/beta add USER_ID вЂ” РґРѕР±Р°РІРёС‚СЊ С‚РµСЃС‚РµСЂР°\n"
            "/beta remove USER_ID вЂ” СѓР±СЂР°С‚СЊ С‚РµСЃС‚РµСЂР°\n"
            "/beta list вЂ” СЃРїРёСЃРѕРє С‚РµСЃС‚РµСЂРѕРІ"
        )
        return
    
    action = args[1]
    try:
        if action == "add":
            if len(args) < 3:
                await message.answer("вќЊ РЈРєР°Р¶РёС‚Рµ USER_ID")
                return
            user_id = int(args[2])
            if add_beta_tester(user_id):
                await message.answer(f"вњ… РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ {user_id} РґРѕР±Р°РІР»РµРЅ РІ Р±РµС‚Р°-С‚РµСЃС‚РµСЂС‹")
            else:
                await message.answer(f"вќЊ РќРµ СѓРґР°Р»РѕСЃСЊ РґРѕР±Р°РІРёС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ {user_id}")
        elif action == "remove":
            if len(args) < 3:
                await message.answer("вќЊ РЈРєР°Р¶РёС‚Рµ USER_ID")
                return
            user_id = int(args[2])
            if remove_beta_tester(user_id):
                await message.answer(f"вњ… РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ {user_id} СѓРґР°Р»С‘РЅ РёР· Р±РµС‚Р°-С‚РµСЃС‚РµСЂРѕРІ")
            else:
                await message.answer(f"вќЊ РќРµ СѓРґР°Р»РѕСЃСЊ СѓРґР°Р»РёС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ {user_id}")
        elif action == "list":
            testers = get_beta_testers()
            if testers:
                text = "рџ‘Ґ Р‘РµС‚Р°-С‚РµСЃС‚РµСЂС‹:\n"
                for t in testers:
                    text += f"- {t['user_id']} ({t['username'] or 'Р±РµР· username'})\n"
                await message.answer(text)
            else:
                await message.answer("вќЊ РќРµС‚ Р±РµС‚Р°-С‚РµСЃС‚РµСЂРѕРІ")
        else:
            await message.answer("вќЊ РќРµРёР·РІРµСЃС‚РЅРѕРµ РґРµР№СЃС‚РІРёРµ")
    except ValueError:
        await message.answer("вќЊ USER_ID РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ С‡РёСЃР»РѕРј")
    except Exception as e:
        await message.answer(f"вќЊ РћС€РёР±РєР°: {e}")

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logger.critical(f"РљСЂРёС‚РёС‡РµСЃРєР°СЏ РѕС€РёР±РєР°: {e}. РџРµСЂРµР·Р°РїСѓСЃРє С‡РµСЂРµР· 5 СЃРµРєСѓРЅРґ...")
            import time as _time
            _time.sleep(5)
            continue
        break
