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

import os
import html
import logging
import re
import sqlite3
import time
import asyncio
import yt_dlp
import logging
from parser import check_all_bloggers
from collections import deque
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional

import httpx
import uvicorn
from aiogram.client.default import DefaultBotProperties
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, Message  # <--- ВОТ ЭТОТ ИМПОРТ
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from aiogram.types import InlineKeyboardMarkup, Message, InlineKeyboardButton, LabeledPrice, SuccessfulPayment, CallbackQuery, PreCheckoutQuery

class PaymentFSM(StatesGroup):
    choosing_tariff = State()        
    choosing_method = State()        
    waiting_for_receipt = State() 

def get_latest_video(channel_url: str):
    """Возвращает данные о последнем видео на канале."""
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': True,
        'playlist_items': '1', # Берем только последнее
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if 'entries' in info and info['entries']:
                return info['entries'][0]
    except Exception as e:
        logger.error(f"Ошибка парсинга {channel_url}: {e}")
    return None

# --- Логирование ---
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
file_handler = RotatingFileHandler("bot.log", maxBytes=5 * 1024 * 1024, backupCount=3)
file_handler.setFormatter(log_formatter)
logging.basicConfig(level=logging.INFO, handlers=[file_handler, logging.StreamHandler()])
logger = logging.getLogger("autopost_bot")

# --- Конфигурация ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
QUARANTINE_CHAT_ID = int(os.getenv("QUARANTINE_CHAT_ID", "-1001234567890"))
ADMIN_VIP_CHANNEL_ID = int(os.getenv("ADMIN_VIP_CHANNEL_ID", "-1009876543210"))
TAKPRODAM_MASTER_TOKEN = os.getenv("TAKPRODAM_MASTER_TOKEN")
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", 8000))
STARS_PROVIDER_TOKEN = os.getenv("STARS_PROVIDER_TOKEN", "")
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
# ---------- Тарифная сетка (Цены в рублях и эквивалент в Telegram Stars) --------
# Курс: 1 рубль ≈ 1.5 Stars
TARIFF_PLANS: dict[str, dict] = {
    "15d":  {"days": 15,  "stars": 900,  "rub": 600,  "label": "15 дней — 600₽ / 900 ⭐"},
    "30d":  {"days": 30,  "stars": 1500, "rub": 1000, "label": "30 дней — 1000₽ / 1500 ⭐ (−17%)"},
    "90d":  {"days": 90,  "stars": 3800, "rub": 2550, "label": "90 дней — 2550₽ / 3800 ⭐ (−25%)"},
    "180d": {"days": 180, "stars": 6800, "rub": 4500, "label": "180 дней — 4500₽ / 6800 ⭐ (−33%)"},
    "360d": {"days": 360, "stars": 10500, "rub": 7000, "label": "360 дней — 7000₽ / 10500 ⭐ (−42%)"},
}

# Реквизиты для органического трафика (карты РФ/KG)
CARD_DETAILS_RU: str = "Сбербанк: 4276 XXXX XXXX XXXX | Получатель: ИП Иванов И.И."
CARD_DETAILS_KG: str = "Mbank: +996 XXX XXX XXX | Получатель: ..."

# =============================================================================
# === DATABASE (SQLite WAL-Mode) ===============================================
# =============================================================================

DB_PATH = "autopost.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        
        # 1. Создаем основные таблицы (как у вас было)
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                role TEXT DEFAULT 'blogger',
                channel_id TEXT,
                channel_title TEXT,
                sub_id TEXT UNIQUE,
                sub_end TEXT,
                is_active INTEGER DEFAULT 0,
                traffic_source TEXT DEFAULT 'organic',
                api_key TEXT,
                client_erid_override TEXT,
                filter_wb INTEGER DEFAULT 1,
                filter_ozon INTEGER DEFAULT 1,
                blogger_mode TEXT DEFAULT 'direct'
            );
            CREATE TABLE IF NOT EXISTS promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                days INTEGER,
                used BOOLEAN DEFAULT 0,
                used_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                donor_post_id TEXT,
                status TEXT,
                erid TEXT
            );
            -- НОВАЯ ТАБЛИЦА ДЛЯ ФИНАНСОВ БЛОГЕРОВ
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sub_id TEXT,
                order_id TEXT UNIQUE,
                status TEXT,
                payout REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 2. БЕЗОПАСНО добавляем колонку referrer_id, если её нет
        try:
            cur.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
            logger.info("Колонка referrer_id добавлена")
        except sqlite3.OperationalError:
            # Если колонка уже существует, sqlite3 выдаст ошибку - мы её просто игнорируем
            pass
            
        conn.commit()
        logger.info("БД инициализирована (структура проверена)")
    finally:
        conn.close()

# =============================================================================
# === CIRCUIT BREAKER (защита от бесконечного цикла запросов к API) ===========
# =============================================================================

class CircuitBreaker:
    """
    Если API 5 раз подряд вернуло 500-ошибку — делаем паузу 15 минут.
    Защита от бесконечного цикла и исчерпания лимитов API.
    """
    MAX_FAILURES: int = 5
    PAUSE_SECONDS: int = 15 * 60  # 15 минут

    def __init__(self) -> None:
        self._failures: int = 0
        self._open_until: Optional[float] = None

    def is_open(self) -> bool:
        """True = схема разомкнута, запросы запрещены."""
        if self._open_until is None:
            return False
        if time.monotonic() >= self._open_until:
            # Таймаут истёк — сбрасываем и пробуем снова
            self._failures = 0
            self._open_until = None
            logger.info("Circuit Breaker: схема замкнута, запросы к API возобновлены")
            return False
        return True

    def record_failure(self) -> None:
        self._failures += 1
        logger.warning(f"Circuit Breaker: ошибка API #{self._failures}/{self.MAX_FAILURES}")
        if self._failures >= self.MAX_FAILURES:
            self._open_until = time.monotonic() + self.PAUSE_SECONDS
            logger.error(
                f"Circuit Breaker: СХЕМА РАЗОМКНУТА на {self.PAUSE_SECONDS // 60} мин "
                f"(5 последовательных 500-ошибок)"
            )

    def record_success(self) -> None:
        if self._failures > 0:
            logger.info("Circuit Breaker: успешный запрос, счётчик ошибок сброшен")
        self._failures = 0
        self._open_until = None


circuit_breaker = CircuitBreaker()

# =============================================================================
# === API INTEGRATION (ТакПродам) =============================================
# =============================================================================

async def get_takprodam_data(sku: str, api_key: str) -> Optional[dict]:
    # Логика обращения к API TakProdam
    url = "https://api.takprodam.ru/v1/products/info"
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params={"sku": sku}, headers=headers)
            if resp.status_code == 200:
                return resp.json() # Возвращает link, erid, advertiser
        except:
            return None
    return None

async def resolve_erid(bot: Bot, user_id: int, sku: str, donor_post_id: str, channel_id: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT api_key, client_erid_override FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()

    if not row: return None
    
    api_key, override = row
    
    # 1. Пробуем API (если ключ есть)
    if api_key:
        data = await get_takprodam_data(sku, api_key)
        if data and data.get("erid"):
            return data

    # 2. Пробуем override (если в API пусто или ключа нет)
    if override:
        return {"erid": override, "link": "https://ваша_ссылка", "advertiser": "Рекламодатель"}

    # 3. Карантин (если ничего не нашли)
    await bot.send_message(QUARANTINE_CHAT_ID, f"🚨 Требуется ручная маркировка для поста {donor_post_id}")
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
    Иерархия получения ERID:
      1. API ТакПродам (api_key пользователя)
      2. client_erid_override из настроек пользователя
      3. Карантин (пост блокируется, уходит на ручную проверку)

    ⚠️  Фейковые ERID ЗАПРЕЩЕНЫ. Только реальные данные или блокировка.

    Возвращает dict с ключами link, erid, advertiser или None (= карантин).
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT api_key, client_erid_override FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        await _send_to_quarantine(bot, user_id, donor_post_id, channel_id,
                                  reason="Пользователь не найден в БД")
        return None

    api_key: str = row["api_key"] or ""
    override_erid: str = (row["client_erid_override"] or "").strip()

    # --- Шаг 1: Запрос к API -------------------------------------------------
    api_data: Optional[dict] = None
    if api_key:
        api_data = await get_takprodam_data(sku, api_key)

    if api_data and api_data.get("erid"):
        logger.info(f"ERID получен из API для SKU={sku}, user={user_id}")
        return api_data

    # --- Шаг 2: Клиентский override ------------------------------------------
    if override_erid:
        logger.info(f"ERID взят из client_erid_override для user={user_id}")
        link = api_data["link"] if api_data else ""
        advertiser = api_data["advertiser"] if api_data else "Не определён"
        return {"link": link, "erid": override_erid, "advertiser": advertiser}

    # --- Шаг 3: Карантин (публикация запрещена) ------------------------------
    reason = "API не вернул ERID, client_erid_override не задан"
    if not api_key:
        reason = "api_key не настроен, client_erid_override не задан"
    elif circuit_breaker.is_open():
        reason = "Circuit Breaker активен (API недоступен), client_erid_override не задан"

    await _send_to_quarantine(bot, user_id, donor_post_id, channel_id, reason=reason)
    return None


async def _send_to_quarantine(
    bot: Bot,
    user_id: int,
    donor_post_id: str,
    channel_id: str,
    reason: str,
) -> None:
    """
    Отправляет уведомление в карантинный чат администратора.
    Пост НЕ публикуется до ручного одобрения.
    """
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO posts (user_id, donor_post_id, channel_id, status, quarantine_reason)
               VALUES (?, ?, ?, 'quarantine', ?)""",
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
        logger.warning(f"Пост {donor_post_id} отправлен в карантин. Причина: {reason}")
    except TelegramAPIError as e:
        logger.error(f"Не удалось отправить пост в карантин: {e}")

async def rewrite_text_with_ai(text: str) -> str:
    """Уникализирует текст поста через API DeepInfra."""
    if not DEEPINFRA_API_KEY:
        return text  # Если ключ не задан, возвращаем оригинал

    url = "https://api.deepinfra.com/v1/openai/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPINFRA_API_KEY}"}
    payload = {
        "model": "meta-llama/Meta-Llama-3-8B-Instruct",
        "messages": [{"role": "user", "content": f"Перепиши этот текст для рекламного поста в Telegram, сохранив суть и призыв к действию: {text}"}]
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Ошибка рерайта: {e}")
    return text


# =============================================================================
# === HTML SANITIZER ==========================================================
# =============================================================================

# Разрешённые Telegram HTML-теги (избегаем Can't find end of entity)
_ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre", "a"}
_OPEN_TAG_RE = re.compile(r"<([a-zA-Z]+)(?:\s[^>]*)?>")
_CLOSE_TAG_RE = re.compile(r"</([a-zA-Z]+)>")


def sanitize_html(text: str) -> str:
    """
    Очищает HTML для Telegram:
    1. Удаляет теги не из белого списка.
    2. Закрывает все незакрытые допустимые теги (висячие теги → ошибка Telegram).
    3. Усекает текст до лимита Telegram (4096 символов для caption).
    """
    if not text:
        return ""

    # Удаляем запрещённые теги (оставляем содержимое)
    def strip_disallowed(m: re.Match) -> str:
        tag = m.group(1).lower()
        return m.group(0) if tag in _ALLOWED_TAGS else ""

    text = re.sub(r"</?([a-zA-Z]+)(?:\s[^>]*)?>", lambda m: (
        m.group(0) if m.group(1).lower() in _ALLOWED_TAGS else ""
    ), text)

    # Закрываем висячие теги (стек открытых тегов)
    open_tags: deque[str] = deque()
    for m in _OPEN_TAG_RE.finditer(text):
        tag = m.group(1).lower()
        if tag in _ALLOWED_TAGS and tag not in {"br", "hr"}:
            open_tags.append(tag)
    for m in _CLOSE_TAG_RE.finditer(text):
        tag = m.group(1).lower()
        if open_tags and open_tags[-1] == tag:
            open_tags.pop()

    # Закрываем в обратном порядке
    closing = "".join(f"</{t}>" for t in reversed(open_tags))
    text = text + closing

    # Лимит Telegram: 1024 для caption, 4096 для message
    return text[:4096]


def build_post_caption(
    product_title: str,
    price: str,
    affiliate_url: str,
    erid: str,
    advertiser: str,
) -> str:
    """
    Формирует финальный текст поста с обязательной маркировкой.
    Формат маркировки: «Реклама. {advertiser}. Erid: {erid}»
    """
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
    """Проверяет расширение URL изображения."""
    if not url:
        return False
    path = url.split("?")[0].lower()
    return any(path.endswith(ext) for ext in _VALID_IMAGE_EXTENSIONS)


async def publish_post_with_fallback(
    bot: Bot,
    channel_id: str,
    caption: str,
    photo_url: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """
    Публикует пост с фото. При ошибке «wrong type of web page content»
    мгновенно делает fallback → публикует текстом (send_message).
    Возвращает True при успехе, False при полном провале.
    """
    # Попытка с фото (если URL валиден)
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
            err_msg = str(e).lower()
            if _WRONG_CONTENT_RE.search(err_msg) or "wrong file identifier" in err_msg:
                logger.warning(
                    f"Фото не принято Telegram ({e}), fallback → текстовый пост"
                )
                # Fallback: публикуем без фото
            else:
                logger.error(f"Ошибка публикации с фото: {e}")
                return False

    # Текстовый fallback
    try:
        await bot.send_message(
            chat_id=channel_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=False,
        )
        return True
    except TelegramAPIError as e:
        logger.error(f"Ошибка публикации текстового поста: {e}")
        return False


# =============================================================================
# === NIGHT QUEUE (очередь постов 23:00 – 08:00) ==============================
# =============================================================================

def is_night_time() -> bool:
    """True с 23:00 до 08:00 по UTC+3 (Москва)."""
    now = datetime.now(tz=timezone(timedelta(hours=3)))
    return now.hour >= 23 or now.hour < 8


async def add_to_night_queue(
    user_id: int,
    channel_id: str,
    text: str,
    photo_url: Optional[str],
    erid: str,
    advertiser: str,
    affiliate_url: str,
) -> None:
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO night_queue
               (user_id, channel_id, text, photo_url, erid, advertiser, affiliate_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, channel_id, text, photo_url, erid, advertiser, affiliate_url)
        )
        conn.commit()
        logger.info(f"Пост добавлен в ночную очередь (user={user_id}, канал={channel_id})")
    finally:
        conn.close()


async def flush_night_queue(bot: Bot) -> None:
    """
    Запускается по крону в 08:00. Последовательно публикует посты из очереди
    с задержкой 90 секунд между публикациями (защита от флуда).
    """
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM night_queue ORDER BY created_at ASC"
        ).fetchall()
        if not rows:
            return
        logger.info(f"Ночная очередь: {len(rows)} постов к публикации")
        for row in rows:
            success = await publish_post_with_fallback(
                bot=bot,
                channel_id=row["channel_id"],
                caption=row["text"],
                photo_url=row["photo_url"],
            )
            if success:
                conn.execute("DELETE FROM night_queue WHERE id=?", (row["id"],))
                conn.commit()
            await asyncio.sleep(90)
    finally:
        conn.close()


# =============================================================================
# === TRANSLITERATION (генерация sub_id из username) ==========================
# =============================================================================

_TRANSLIT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def generate_sub_id(username: str, user_id: int) -> str:
    """
    Генерирует уникальный sub_id через транслитерацию username.
    Пример: @МойКанал_123 → moikanal_123_uid7890
    """
    username = (username or "").lstrip("@").lower()
    result = ""
    for ch in username:
        result += _TRANSLIT_MAP.get(ch, ch if ch.isalnum() or ch == "_" else "")
    # Убираем повторяющиеся символы, нечитаемые символы
    result = re.sub(r"[^a-z0-9_]", "", result)
    result = re.sub(r"_+", "_", result).strip("_")
    if not result:
        result = f"user{user_id}"
    return f"{result}_uid{user_id}"


# =============================================================================
# === KEYBOARD HELPERS (безопасные callback_data через словари) ================
# =============================================================================

def kb_main_menu(role: str) -> InlineKeyboardMarkup:
    """Главное меню. Кнопки только через dict callback_data (без пробелов/спецсимволов)."""
    buttons = []
    if role == "blogger":
        buttons = [
            [InlineKeyboardButton(text="📢 Мой канал", callback_data="menu:channel")],
            [InlineKeyboardButton(text="💎 Тарифы и подписка", callback_data="menu:tariffs")],
            [InlineKeyboardButton(text="📊 Статистика постов", callback_data="menu:stats")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
        ]
    elif role == "saas":
        buttons = [
            [InlineKeyboardButton(text="🔑 API-ключ ТакПродам", callback_data="menu:apikey")],
            [InlineKeyboardButton(text="🏷 Корпоративный ERID", callback_data="menu:erid_override")],
            [InlineKeyboardButton(text="🛒 Фильтры маркетплейсов", callback_data="menu:filters")],
            [InlineKeyboardButton(text="💎 Тарифы и подписка", callback_data="menu:tariffs")],
            [InlineKeyboardButton(text="📊 Аналитика", callback_data="menu:stats")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_tariffs(traffic_source: str) -> InlineKeyboardMarkup:
    """
    Умное разделение платёжных методов:
    - organic: Stars + карты РФ/KG
    - affiliate: только Stars
    """
    rows = []
    for plan_id, plan in TARIFF_PLANS.items():
        rows.append([
            InlineKeyboardButton(
                text=f"⭐ {plan['label']}",
                callback_data=f"buy:stars:{plan_id}"
            )
        ])
    if traffic_source == "organic":
        rows.append([
            InlineKeyboardButton(text="💳 Карта РФ (перевод)", callback_data="buy:card:ru"),
            InlineKeyboardButton(text="💳 Карта KG", callback_data="buy:card:kg"),
        ])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_filter_settings(wb: int, ozon: int) -> InlineKeyboardMarkup:
    wb_label = f"{'✅' if wb else '❌'} Wildberries"
    ozon_label = f"{'✅' if ozon else '❌'} Ozon"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=wb_label, callback_data="filter:toggle:wb")],
        [InlineKeyboardButton(text=ozon_label, callback_data="filter:toggle:ozon")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:settings")],
    ])


def kb_blogger_mode(mode: str) -> InlineKeyboardMarkup:
    direct_label = f"{'✅' if mode == 'direct' else '☐'} Напрямую в мой канал"
    vip_label = f"{'✅' if mode == 'vip_pin' else '☐'} VIP-закреп в главном канале (24ч)"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=direct_label, callback_data="blogger_mode:direct")],
        [InlineKeyboardButton(text=vip_label, callback_data="blogger_mode:vip_pin")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:settings")],
    ])


def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Рассылка всем", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="💰 Запустить биллинг-чек", callback_data="admin:billing_check")],
        [InlineKeyboardButton(text="🔧 Продлить подписку", callback_data="admin:extend_sub")],
        [InlineKeyboardButton(text="🌐 Открыть WebApp", callback_data="admin:webapp_link")],
    ])


# =============================================================================
# === FSM STATES ==============================================================
# =============================================================================

class OnboardingStates(StatesGroup):
    waiting_channel = State()
    waiting_role = State()
    waiting_role_confirm = State()


class AdminStates(StatesGroup):
    broadcast_text = State()
    extend_user_id = State()
    extend_days = State()


class SaasStates(StatesGroup):
    waiting_apikey = State()
    waiting_erid_override = State()


# =============================================================================
# === ROUTER & HANDLERS =======================================================
# =============================================================================

router = Router()


# -----------------------------------------------------------------------------
# /start
# -----------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    username = message.from_user.username or ""
    args = message.text.split(maxsplit=1)[1] if " " in (message.text or "") else ""

    # Определяем источник трафика
    traffic_source = "organic"
    referrer_id: Optional[int] = None
    if args.startswith("aff_"):
        # Аффилиатный трафик: ищем реферера по sub_id
        aff_sub_id = args[4:]  # убираем "aff_"
        conn = get_db()
        try:
            ref_row = conn.execute(
                "SELECT user_id FROM users WHERE sub_id=?", (aff_sub_id,)
            ).fetchone()
            if ref_row:
                referrer_id = ref_row["user_id"]
                traffic_source = "affiliate"
        finally:
            conn.close()

    # Регистрируем или обновляем пользователя
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT user_id, role FROM users WHERE user_id=?", (user_id,)
        ).fetchone()

        # ... внутри cmd_start ...
        if not existing:
            sub_id = generate_sub_id(username, user_id)
            # Временно ставим 'pending', пока пользователь не выберет роль
            conn.execute(
                "INSERT INTO users (user_id, username, sub_id, traffic_source, referrer_id, role) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, sub_id, traffic_source, referrer_id, 'pending')
            )
            conn.commit()
            
            # Отправляем меню выбора роли
            await message.answer(
                "👋 Привет! Выбери свой режим работы:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👤 Блогер", callback_data="role:blogger")],
                    [InlineKeyboardButton(text="🏢 SaaS / Бизнес", callback_data="role:saas")]
                ])
            )
            await state.set_state(OnboardingStates.waiting_role)
            return
# ... остальной код (если existing есть, то оставляем как было) ...

    # Приветствие для блогера/SaaS (язык профессионала рынка)
    welcome_text = (
        f"👋 <b>Добро пожаловать в AutoPost</b>\n\n"
        f"Инструмент для <b>легального автопостинга</b> товаров с маркетплейсов "
        f"в твои Telegram-каналы.\n\n"
        f"🔒 <b>Каждый пост автоматически маркируется</b> согласно требованиям ФАС "
        f"(ERID + ссылка на рекламодателя). Никаких штрафов.\n\n"
        f"📢 Подключи канал, настрой фильтры и запусти монетизацию трафика за 2 минуты."
    )
    await message.answer(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(role),
    )


# -----------------------------------------------------------------------------
# Онбординг: привязка канала
# -----------------------------------------------------------------------------
# --- Регистрация блогера ---

@router.callback_query(OnboardingStates.waiting_role, F.data == "role:blogger")
async def cb_blogger_reg(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "👤 <b>Регистрация блогера</b>\n\n"
        "Отправь ссылку на свою основную площадку (YouTube, TikTok или Instagram), "
        "чтобы я мог начать мониторинг.",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(OnboardingStates.waiting_channel) # Используем существующее состояние

@router.message(OnboardingStates.waiting_channel)
async def handle_blogger_channel(message: Message, state: FSMContext) -> None:
    link = message.text.strip()
    user_id = message.from_user.id
    username = message.from_user.username or "user"
    
    # Определяем площадку из ссылки (простая логика)
    platform = "yt" if "youtube" in link.lower() else "tt" if "tiktok" in link.lower() else "inst"
    
    # Генерация хвостика: имя_платформа (пример: nastyayt)
    sub_id = f"{username.lower()}{platform}"
    
    conn = get_db()
    conn.execute(
        "UPDATE users SET role='blogger', channel_id=?, traffic_source=?, sub_id=? WHERE user_id=?",
        (link, 'affiliate', sub_id, user_id)
    )
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(
        f"✅ <b>Готово!</b>\n"
        f"Твой личный хвост для партнёрки: <code>{sub_id}</code>\n"
        f"Теперь я буду мониторить этот канал.",
        parse_mode=ParseMode.HTML
    )
# -----------------------------------------------------------------------------
# Починка: Умное меню управления каналом
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:channel")
async def cb_menu_channel(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    row = conn.execute("SELECT channel_title, channel_id FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()

    # Если канал уже привязан — показываем панель управления
    if row and row["channel_id"]:
        await callback.message.edit_text(
            f"📢 <b>Управление каналом</b>\n\n"
            f"Привязанный канал: <b>{html.escape(row['channel_title'] or 'Без названия')}</b>\n"
            f"ID: <code>{row['channel_id']}</code>\n\n"
            "Что хочешь сделать?",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Изменить канал", callback_data="channel:change")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")]
            ])
        )
    else:
        # Если канала нет — запускаем онбординг
        await callback.message.edit_text(
            "📢 <b>Привязка канала</b>\n\n"
            "Перешли сюда любое сообщение из твоего канала, либо отправь <code>@username</code>.",
            parse_mode=ParseMode.HTML,
        )
        await state.set_state(OnboardingStates.waiting_channel)
    
    await callback.answer()

# Добавляем обработчик для смены канала
@router.callback_query(F.data == "channel:change")
async def cb_change_channel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "📢 Введи <code>@username</code> нового канала или перешли сообщение из него:",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(OnboardingStates.waiting_channel)
    await callback.answer()

@router.callback_query(OnboardingStates.waiting_role, F.data.startswith("role:"))
async def cb_set_role(callback: CallbackQuery, state: FSMContext) -> None:
    role = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    conn = get_db()
    conn.execute("UPDATE users SET role=? WHERE user_id=?", (role, user_id))
    conn.commit()
    conn.close()
    
    await state.clear()
    await callback.message.edit_text(
        f"✅ Выбрана роль: <b>{'Блогер' if role == 'blogger' else 'SaaS'}</b>\n\n"
        "Теперь привяжи канал, чтобы начать.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(role)
    )
  
@router.message(OnboardingStates.waiting_channel)
async def handle_channel_input(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    channel_id: Optional[str] = None
    channel_title: Optional[str] = None

    # Принимаем: форвард из канала или @username
    if message.forward_origin:
        try:
            chat = message.forward_origin.chat
            channel_id = str(chat.id)
            channel_title = chat.title
        except AttributeError:
            pass
    elif message.text and message.text.startswith("@"):
        channel_id = message.text.strip()
        channel_title = channel_id

    if not channel_id:
        await message.answer(
            "⚠️ Не распознал канал. Перешли сообщение из канала или введи <code>@username</code>.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Сохраняем в БД
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET channel_id=?, channel_title=? WHERE user_id=?",
            (channel_id, channel_title, user_id)
        )
        conn.commit()
        row = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
        role = row["role"] if row else "blogger"
    finally:
        conn.close()

    await state.clear()
    await message.answer(
        f"✅ <b>Канал привязан:</b> {html.escape(channel_title or channel_id)}\n\n"
        f"Теперь настрой тариф и запускай автопостинг.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(role),
    )


# -----------------------------------------------------------------------------
# Тарифы
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:tariffs")
async def cb_menu_tariffs(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT traffic_source, sub_end, is_active FROM users WHERE user_id=?",
            (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()

    traffic_source = row["traffic_source"] if row else "organic"
    sub_info = ""
    if row and row["sub_end"]:
        status = "✅ Активна" if row["is_active"] else "❌ Истекла"
        sub_info = f"\n\n<b>Текущая подписка:</b> {status} до {row['sub_end']}"

    text = (
        f"💎 <b>Тарифы AutoPost</b>{sub_info}\n\n"
        f"Выбери период — стоимость списывается в Telegram Stars "
        f"{'(единственный доступный способ оплаты для партнёрского трафика)' if traffic_source == 'affiliate' else 'или банковским переводом'}.\n\n"
        f"{'💳 Для органического трафика доступны карты РФ и KG.' if traffic_source == 'organic' else ''}"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=kb_tariffs(traffic_source),
    )
    await callback.answer()

# --- Шаг 2: Обработка выбранного тарифа (Ожидает состояние choosing_tariff) ---
@router.callback_query(PaymentFSM.choosing_tariff, F.data.startswith("tariff_"))
async def process_tariff_selection(callback_query: CallbackQuery, state: FSMContext):
    # Извлекаем ID тарифа (например, '30d')
    plan_id = callback_query.data.split("_")[1]
    
    if plan_id not in TARIFF_PLANS:
        await callback_query.answer("⚠️ Тариф не найден", show_alert=True)
        return
        
    # Сохраняем тариф в FSM
    await state.update_data(selected_plan=plan_id)
    
    # Создаем клавиатуру выбора метода оплаты
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Карта РФ (Сбер, Т-Банк)", callback_data="pay:ru")],
        [InlineKeyboardButton(text="💳 Карта КГ (Visa)", callback_data="pay:kg")],
        [InlineKeyboardButton(text="💎 Криптовалюта (TON)", callback_data="pay:ton")],
        [InlineKeyboardButton(text="⭐️ Telegram Stars", callback_data=f"buy:stars:{plan_id}")],
        [InlineKeyboardButton(text="◀️ Назад к тарифам", callback_data="menu:tariffs")]
    ])
    
    plan = TARIFF_PLANS[plan_id]
    await callback_query.message.edit_text(
        f"Выбран тариф: <b>{plan['label']}</b>\n\n"
        "Выберите способ оплаты.\n"
        "Если оплачиваете картой или TON — после перевода отправьте чек в этот чат.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )
    # Переводим в состояние выбора метода
    await state.set_state(PaymentFSM.choosing_method)
    await callback_query.answer()

# --- Шаг 3: Выдача реквизитов и ожидание чека ---
@router.callback_query(PaymentFSM.choosing_method, F.data.startswith("pay:"))
async def process_payment_method(callback_query: CallbackQuery, state: FSMContext):
    method = callback_query.data.split(":")[1]
    
    # Достаем выбранный тариф из состояния
    data = await state.get_data()
    plan_id = data.get("selected_plan")
    plan = TARIFF_PLANS.get(plan_id)
    
    if not plan:
        await callback_query.answer("⚠️ Ошибка данных, начните сначала", show_alert=True)
        return

    # Подготовка текста реквизитов
    if method == "ru":
        text = (f"💳 <b>Оплата картой РФ</b>\n\n"
                f"К оплате: <b>{plan['rub']} ₽</b>\n\n"
                f"Сбербанк: <code>2202 2081 0829 0025</code> (Выборных Д.П)\n"
                f"Т-Банк: <code>2200 7013 7009 3863</code> (Выборных Д.П)\n\n"
                f"После перевода пришлите фото чека в этот чат.")
    elif method == "kg":
        text = (f"🇰🇬 <b>Оплата Visa KG</b>\n\n"
                f"К оплате: <b>{plan['rub']} ₽</b> (по курсу банка)\n\n"
                f"Visa: <code>4196720087839790</code>\n\n"
                f"После перевода пришлите фото чека в этот чат.")
    elif method == "ton":
        text = (f"💎 <b>Оплата TON</b>\n\n"
                f"К оплате: <b>{plan['rub']} ₽</b> (эквивалент в TON)\n\n"
                f"Адрес: <code>UQCua97IuHkQy5F5NPHBrDpay_FJRJoWZa1OOLnq-geGIbGT</code>\n"
                f"После перевода пришлите скриншот транзакции в этот чат.")
    
    await callback_query.message.edit_text(
        text, 
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к выбору метода", callback_data=f"tariff_{plan_id}")]
        ])
    )
    
    # Переводим бота в состояние ожидания фотографии
    await state.set_state(PaymentFSM.waiting_receipt)
    await callback_query.answer()

# --- Шаг 4: Прием чека и пересылка админу ---
@router.message(PaymentFSM.waiting_receipt, F.photo)
async def process_receipt_photo(message: Message, state: FSMContext):
    # Берем ID самого качественного фото
    photo_id = message.photo[-1].file_id
    user = message.from_user
    data = await state.get_data()
    plan_id = data.get("selected_plan")
    plan = TARIFF_PLANS.get(plan_id)

    # Сообщение пользователю
    await message.answer("✅ Чек получен! Администратор проверит его в течение 30 минут и активирует подписку.")

    # Формируем сообщение для админа
    admin_text = (
        f"💰 <b>Новая заявка на оплату!</b>\n\n"
        f"👤 Пользователь: @{user.username or 'без юзернейма'}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"💎 Тариф: {plan['label']}\n\n"
        f"Ожидает подтверждения."
    )

    # Клавиатура для админа
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Активировать", callback_data=f"adm_pay:ok:{user.id}:{plan_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_pay:no:{user.id}")]
    ])

    # Рассылаем всем админам (в списке ADMIN_IDS)
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_photo(
                chat_id=admin_id,
                photo=photo_id,
                caption=admin_text,
                parse_mode=ParseMode.HTML,
                reply_markup=admin_kb
            )
        except Exception as e:
            logger.error(f"Не удалось отправить чек админу {admin_id}: {e}")

    # Сбрасываем состояние
    await state.clear()

# Если пользователь прислал не фото, а текст
@router.message(PaymentFSM.waiting_receipt)
async def process_receipt_wrong_type(message: Message):
    await message.answer("⚠️ Пожалуйста, пришлите именно фотографию (скриншот) чека.")

# --- Шаг 5: Обработка решения админа (нажатие кнопок под чеком) ---
@router.callback_query(F.data.startswith("adm_pay:"))
async def admin_payment_decision(callback_query: CallbackQuery):
    # Разбираем данные: [тип_действия, id_юзера, id_тарифа(если есть)]
    parts = callback_query.data.split(":")
    action = parts[1]
    user_id = int(parts[2])
    
    if action == "ok":
        plan_id = parts[3]
        plan = TARIFF_PLANS.get(plan_id)
        
        # Обновляем БД (продлеваем подписку)
        conn = get_db()
        try:
            row = conn.execute("SELECT sub_end FROM users WHERE user_id=?", (user_id,)).fetchone()
            now = datetime.now(tz=timezone.utc)
            
            # Логика продления (аналогично автоматическому продлению)
            if row and row["sub_end"]:
                try:
                    current_end = datetime.fromisoformat(row["sub_end"])
                    base = max(current_end, now)
                except ValueError:
                    base = now
            else:
                base = now
            new_end = base + timedelta(days=plan["days"])
            
            conn.execute(
                "UPDATE users SET sub_end=?, is_active=1 WHERE user_id=?",
                (new_end.isoformat(), user_id)
            )
            conn.commit()
        finally:
            conn.close()
        
        # Уведомляем пользователя
        try:
            await callback_query.bot.send_message(
                user_id, 
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"Ваш тариф <b>{plan['label']}</b> активирован до {new_end.strftime('%d.%m.%Y')}."
            )
        except Exception:
            pass
            
        await callback_query.message.edit_caption(caption=f"✅ Подписка активирована для {user_id}")
        await callback_query.answer("Подписка активирована")
        
    elif action == "no":
        # Просто отклоняем
        try:
            await callback_query.bot.send_message(
                user_id, 
                "❌ <b>Оплата отклонена.</b>\n\n"
                "Администратор не смог подтвердить ваш перевод. Пожалуйста, обратитесь в поддержку."
            )
        except Exception:
            pass
            
        await callback_query.message.edit_caption(caption=f"❌ Оплата отклонена для {user_id}")
        await callback_query.answer("Заявка отклонена")

# -----------------------------------------------------------------------------
# Оплата Stars
# -----------------------------------------------------------------------------

@router.callback_query(F.data.startswith("buy:stars:"))
async def cb_buy_stars(callback: CallbackQuery) -> None:
    plan_id = callback.data.split(":")[2]
    plan = TARIFF_PLANS.get(plan_id)
    if not plan:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"AutoPost — {plan['label']}",
        description=(
            f"Подписка на автопостинг с маркировкой ERID на {plan['days']} дней. "
            f"Каждый пост соответствует требованиям ФАС."
        ),
        payload=f"autopost:{plan_id}:{callback.from_user.id}",
        provider_token=STARS_PROVIDER_TOKEN,
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice(label=plan["label"], amount=plan["stars"])],
    )
    await callback.answer()


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout: PreCheckoutQuery) -> None:
    """Обязательная обработка pre_checkout_query для Stars."""
    payload = pre_checkout.invoice_payload
    if not payload.startswith("autopost:"):
        await pre_checkout.answer(ok=False, error_message="Неверный платёж")
        return
    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    """Автоматическое продление подписки после успешного платежа Stars."""
    payment: SuccessfulPayment = message.successful_payment
    payload = payment.invoice_payload
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != "autopost":
        logger.error(f"Неверный payload платежа: {payload}")
        return

    plan_id = parts[1]
    user_id = int(parts[2])
    plan = TARIFF_PLANS.get(plan_id)
    if not plan:
        logger.error(f"Неизвестный тариф в payload: {plan_id}")
        return

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT sub_end FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        now = datetime.now(tz=timezone.utc)
        if row and row["sub_end"]:
            try:
                current_end = datetime.fromisoformat(row["sub_end"])
                if current_end > now:
                    new_end = current_end + timedelta(days=plan["days"])
                else:
                    new_end = now + timedelta(days=plan["days"])
            except ValueError:
                new_end = now + timedelta(days=plan["days"])
        else:
            new_end = now + timedelta(days=plan["days"])

        conn.execute(
            "UPDATE users SET sub_end=?, is_active=1 WHERE user_id=?",
            (new_end.isoformat(), user_id)
        )
        conn.execute(
            """INSERT INTO billing_log (user_id, plan, stars_paid, payment_method, payment_id)
               VALUES (?, ?, ?, 'stars', ?)""",
            (user_id, plan_id, plan["stars"], payment.telegram_payment_charge_id)
        )
        conn.commit()
    finally:
        conn.close()

    await message.answer(
        f"✅ <b>Подписка активирована</b>\n\n"
        f"Тариф: {plan['label']}\n"
        f"Активна до: {new_end.strftime('%d.%m.%Y')}\n\n"
        f"Автопостинг с маркировкой ERID запущен.",
        parse_mode=ParseMode.HTML,
    )
    logger.info(f"Подписка продлена: user={user_id}, план={plan_id}, до={new_end.date()}")


# -----------------------------------------------------------------------------
# Оплата картой (только organic)
# -----------------------------------------------------------------------------

@router.callback_query(F.data.startswith("buy:card:"))
async def cb_buy_card(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT traffic_source FROM users WHERE user_id=?",
            (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()

    if row and row["traffic_source"] == "affiliate":
        await callback.answer(
            "❌ Для партнёрского трафика доступна только оплата Telegram Stars.",
            show_alert=True
        )
        return

    card_type = callback.data.split(":")[2]
    details = CARD_DETAILS_RU if card_type == "ru" else CARD_DETAILS_KG

    await callback.message.edit_text(
        f"💳 <b>Оплата переводом ({card_type.upper()})</b>\n\n"
        f"<code>{details}</code>\n\n"
        f"После оплаты отправь скриншот чека сюда — администратор проверит "
        f"и активирует подписку вручную в течение 30 минут.\n\n"
        f"<i>Укажи в комментарии к переводу свой Telegram ID: "
        f"<code>{callback.from_user.id}</code></i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tariffs")]
        ])
    )
    await callback.answer()


# -----------------------------------------------------------------------------
# Настройки
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:settings")
async def cb_menu_settings(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT role, filter_wb, filter_ozon, blogger_mode, api_key, client_erid_override "
            "FROM users WHERE user_id=?",
            (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return

    role = row["role"]
    buttons = [
        [InlineKeyboardButton(text="📢 Режим публикации", callback_data="settings:blogger_mode")],
        [InlineKeyboardButton(text="🛒 Фильтры маркетплейсов", callback_data="settings:filters")],
    ]
    if role == "saas":
        buttons.insert(0, [
            InlineKeyboardButton(text="🔑 API-ключ ТакПродам", callback_data="menu:apikey")
        ])
        buttons.insert(1, [
            InlineKeyboardButton(text="🏷 Корпоративный ERID", callback_data="menu:erid_override")
        ])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")])

    api_status = f"{'✅ задан' if row['api_key'] else '❌ не задан'}"
    erid_status = f"{'✅ ' + row['client_erid_override'][:20] if row['client_erid_override'] else '—'}"

    text = (
        f"⚙️ <b>Настройки</b>\n\n"
        f"API-ключ: {api_status}\n"
        f"Корп. ERID: {erid_status}\n"
        f"WB: {'✅' if row['filter_wb'] else '❌'}  |  Ozon: {'✅' if row['filter_ozon'] else '❌'}\n"
        f"Режим: {'Напрямую' if row['blogger_mode'] == 'direct' else 'VIP-закреп'}"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@router.callback_query(F.data == "settings:filters")
async def cb_settings_filters(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT filter_wb, filter_ozon FROM users WHERE user_id=?",
            (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()
    await callback.message.edit_text(
        "🛒 <b>Фильтры маркетплейсов</b>\n\nВыбери, какие площадки включить в автопостинг:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_filter_settings(row["filter_wb"], row["filter_ozon"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("filter:toggle:"))
async def cb_filter_toggle(callback: CallbackQuery) -> None:
    field = callback.data.split(":")[2]  # "wb" или "ozon"
    db_field = f"filter_{field}"
    conn = get_db()
    try:
        row = conn.execute(
            f"SELECT {db_field} FROM users WHERE user_id=?",
            (callback.from_user.id,)
        ).fetchone()
        current = row[db_field] if row else 1
        new_val = 0 if current else 1
        conn.execute(
            f"UPDATE users SET {db_field}=? WHERE user_id=?",
            (new_val, callback.from_user.id)
        )
        conn.commit()
        row2 = conn.execute(
            "SELECT filter_wb, filter_ozon FROM users WHERE user_id=?",
            (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()
    await callback.message.edit_reply_markup(
        reply_markup=kb_filter_settings(row2["filter_wb"], row2["filter_ozon"])
    )
    await callback.answer(f"{'✅ Включено' if new_val else '❌ Отключено'}: {field.upper()}")


@router.callback_query(F.data == "settings:blogger_mode")
async def cb_blogger_mode_menu(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT blogger_mode FROM users WHERE user_id=?",
            (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()
    mode = row["blogger_mode"] if row else "direct"
    await callback.message.edit_text(
        "📢 <b>Режим публикации</b>\n\n"
        "<b>Напрямую</b> — посты выходят в твой канал с твоим sub_id.\n"
        "<b>VIP-закреп</b> — твой пост публикуется и закрепляется на 24ч "
        "в главном канале администратора (аудитория платформы).",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_blogger_mode(mode),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("blogger_mode:"))
async def cb_blogger_mode_set(callback: CallbackQuery) -> None:
    mode = callback.data.split(":")[1]
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET blogger_mode=? WHERE user_id=?",
            (mode, callback.from_user.id)
        )
        conn.commit()
    finally:
        conn.close()
    label = "Напрямую в канал" if mode == "direct" else "VIP-закреп"
    await callback.answer(f"✅ Режим: {label}", show_alert=False)
    await cb_blogger_mode_menu(callback)


# -----------------------------------------------------------------------------
# SaaS: ввод API-ключа
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:apikey")
async def cb_menu_apikey(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "🔑 <b>API-ключ ТакПродам</b>\n\n"
        "Введи api_key от личного кабинета ТакПродам. "
        "Ключ используется для получения ERID и партнёрских ссылок.",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(SaasStates.waiting_apikey)
    await callback.answer()


@router.message(SaasStates.waiting_apikey)
async def handle_apikey_input(message: Message, state: FSMContext) -> None:
    api_key = message.text.strip() if message.text else ""
    if len(api_key) < 10:
        await message.answer("⚠️ Ключ слишком короткий. Проверь и попробуй снова.")
        return
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET api_key=?, role='saas' WHERE user_id=?",
            (api_key, message.from_user.id)
        )
        conn.commit()
    finally:
        conn.close()
    await state.clear()
    await message.answer(
        "✅ <b>API-ключ сохранён.</b>\n\n"
        "Теперь ERID будет получаться автоматически для каждого поста.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu("saas"),
    )


# -----------------------------------------------------------------------------
# SaaS: корпоративный ERID override
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:erid_override")
async def cb_menu_erid_override(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "🏷 <b>Корпоративный ERID</b>\n\n"
        "Если твой бренд работает с рекламодателем напрямую и у тебя есть "
        "собственный ERID — введи его здесь. Он будет применяться вместо API-данных.\n\n"
        "⚠️ <b>Используй только реальный ERID, полученный от ОРД.</b>",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(SaasStates.waiting_erid_override)
    await callback.answer()


@router.message(SaasStates.waiting_erid_override)
async def handle_erid_override_input(message: Message, state: FSMContext) -> None:
    erid = message.text.strip() if message.text else ""
    # Базовая проверка формата ERID (не генерируем — только принимаем реальный)
    if len(erid) < 5 or not re.match(r"^[A-Za-z0-9\-_]+$", erid):
        await message.answer(
            "⚠️ Неверный формат ERID. Допустимы только латинские буквы, цифры, дефис и подчёркивание.\n"
            "Убедись, что вводишь <b>реальный ERID от ОРД</b>, а не генерируешь его самостоятельно.",
            parse_mode=ParseMode.HTML,
        )
        return
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET client_erid_override=? WHERE user_id=?",
            (erid, message.from_user.id)
        )
        conn.commit()
    finally:
        conn.close()
    await state.clear()
    await message.answer(
        f"✅ <b>Корпоративный ERID сохранён:</b> <code>{html.escape(erid)}</code>\n\n"
        f"Будет применяться при публикации, если API не вернёт ERID.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu("saas"),
    )


# -----------------------------------------------------------------------------
# Статистика
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:stats")
async def cb_menu_stats(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    
    # 1. Сразу отвечаем Telegram, чтобы убрать "зависание" кнопки
    await callback.answer() 
    
    conn = get_db()
    try:
        # Получаем общие цифры
        total = conn.execute("SELECT COUNT(*) FROM posts WHERE user_id=?", (user_id,)).fetchone()[0]
        published = conn.execute("SELECT COUNT(*) FROM posts WHERE user_id=? AND status='published'", (user_id,)).fetchone()[0]
        quarantine = conn.execute("SELECT COUNT(*) FROM posts WHERE user_id=? AND status='quarantine'", (user_id,)).fetchone()[0]
        
        # Получаем список последних постов
        last_posts = conn.execute(
            "SELECT donor_post_id, status, created_at FROM posts "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    # 2. Безопасная сборка текста (если постов нет)
    if not last_posts:
        last_str = "  <i>Постов ещё не было</i>"
    else:
        last_str = "\n".join(
            f"  • <code>{p['donor_post_id']}</code> — {p['status']} ({p['created_at'][:10]})"
            for p in last_posts
        )

    # 3. Вывод данных
    await callback.message.edit_text(
        f"📊 <b>Статистика постов</b>\n\n"
        f"Всего: {total}\n"
        f"Опубликовано: {published}\n"
        f"Карантин: {quarantine}\n\n"
        f"<b>Последние 5 постов:</b>\n{last_str}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")]
        ])
    )
    await callback.answer()


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
# === ADMIN HANDLERS ==========================================================
# =============================================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "📣 <b>Рассылка</b>\n\nВведи текст сообщения для отправки всем пользователям платформы.\n"
        "Поддерживается HTML-разметка.",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(AdminStates.broadcast_text)
    await callback.answer()


@router.message(AdminStates.broadcast_text)
async def handle_broadcast_text(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    clean_text = sanitize_html(text)

    conn = get_db()
    try:
        users = conn.execute("SELECT user_id FROM users").fetchall()
    finally:
        conn.close()

    sent, failed = 0, 0
    for user in users:
        try:
            await message.bot.send_message(
                user["user_id"], clean_text, parse_mode=ParseMode.HTML
            )
            sent += 1
            await asyncio.sleep(0.05)  # ~20 msg/sec — в рамках лимитов Telegram
        except TelegramAPIError:
            failed += 1

    await state.clear()
    await message.answer(
        f"✅ Рассылка завершена.\n✉️ Доставлено: {sent}  |  ❌ Ошибок: {failed}",
        reply_markup=kb_admin_panel(),
    )
    logger.info(f"Рассылка: отправлено {sent}, ошибок {failed}")


@router.callback_query(F.data == "admin:billing_check")
async def cb_admin_billing_check(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    count = await run_billing_check(callback.bot)
    await callback.answer(f"✅ Биллинг выполнен. Отключено: {count}", show_alert=True)


@router.callback_query(F.data == "admin:extend_sub")
async def cb_admin_extend_sub(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "🔧 <b>Ручное продление подписки</b>\n\nВведи Telegram ID пользователя:",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(AdminStates.extend_user_id)
    await callback.answer()


@router.message(AdminStates.extend_user_id)
async def handle_extend_user_id(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        uid = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("⚠️ Введи числовой Telegram ID.")
        return
    await state.update_data(extend_uid=uid)
    await state.set_state(AdminStates.extend_days)
    await message.answer(f"Пользователь: <code>{uid}</code>\nСколько дней добавить?",
                         parse_mode=ParseMode.HTML)


@router.message(AdminStates.extend_days)
async def handle_extend_days(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    try:
        days = int(message.text.strip())
        if days <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("⚠️ Введи положительное число дней.")
        return

    data = await state.get_data()
    uid = data.get("extend_uid")
    conn = get_db()
    try:
        row = conn.execute("SELECT sub_end FROM users WHERE user_id=?", (uid,)).fetchone()
        if not row:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return
        now = datetime.now(tz=timezone.utc)
        if row["sub_end"]:
            try:
                current_end = datetime.fromisoformat(row["sub_end"])
                base = max(current_end, now)
            except ValueError:
                base = now
        else:
            base = now
        new_end = base + timedelta(days=days)
        conn.execute(
            "UPDATE users SET sub_end=?, is_active=1 WHERE user_id=?",
            (new_end.isoformat(), uid)
        )
        conn.commit()
    finally:
        conn.close()

    await state.clear()
    await message.answer(
        f"✅ Подписка продлена.\nUser: <code>{uid}</code> | Новый конец: {new_end.strftime('%d.%m.%Y')}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_admin_panel(),
    )
    logger.info(f"Админ продлил подписку: user={uid} до {new_end.date()}")


@router.callback_query(F.data == "admin:webapp_link")
async def cb_admin_webapp_link(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await callback.answer(
        f"🌐 WebApp доступен по адресу:\nhttp://{WEBAPP_HOST}:{WEBAPP_PORT}/admin",
        show_alert=True
    )


# =============================================================================
# === CRON BILLING CHECK (ежечасная проверка подписок) ========================
# =============================================================================

async def run_billing_check(bot: Bot) -> int:
    """
    Ежечасно деактивирует пользователей с истёкшей подпиской.
    Возвращает количество деактивированных аккаунтов.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    conn = get_db()
    try:
        expired = conn.execute(
            """SELECT user_id FROM users
               WHERE is_active=1 AND sub_end IS NOT NULL AND sub_end < ?""",
            (now,)
        ).fetchall()

        if not expired:
            return 0

        for row in expired:
            conn.execute(
                "UPDATE users SET is_active=0 WHERE user_id=?", (row["user_id"],)
            )
            try:
                await bot.send_message(
                    row["user_id"],
                    "⏰ <b>Подписка истекла.</b>\n\n"
                    "Автопостинг приостановлен. Для продления выбери тариф в главном меню.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💎 Продлить", callback_data="menu:tariffs")]
                    ])
                )
            except TelegramAPIError:
                pass

        conn.commit()
        count = len(expired)
        logger.info(f"Биллинг: деактивировано {count} аккаунтов")
        return count
    finally:
        conn.close()


# =============================================================================
# === CORE AUTOPOST ENGINE ====================================================
# =============================================================================

async def process_donor_post(
    bot: Bot,
    user_id: int,
    donor_post_id: str,
    sku: str,
    marketplace: str,   # 'wb' | 'ozon'
    product_title: str,
    price: str,
    photo_url: Optional[str],
) -> None:
    """
    Главная функция обработки поста донора:
    1. Проверяет активность подписки.
    2. Проверяет фильтры маркетплейсов.
    3. Получает ERID через resolve_erid() (карантин при отсутствии).
    4. Формирует caption с маркировкой.
    5. Кладёт в ночную очередь или публикует немедленно.
    6. Записывает результат в БД.
    """
    conn = get_db()
    try:
        user = conn.execute(
            """SELECT channel_id, is_active, filter_wb, filter_ozon, blogger_mode
               FROM users WHERE user_id=?""",
            (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not user:
        logger.warning(f"process_donor_post: user {user_id} не найден")
        return

    # Проверка подписки
    if not user["is_active"]:
        logger.info(f"User {user_id}: автопостинг пропущен (нет активной подписки)")
        return

    # Проверка фильтров маркетплейсов
    if marketplace == "wb" and not user["filter_wb"]:
        logger.info(f"User {user_id}: WB пост пропущен по фильтру")
        return
    if marketplace == "ozon" and not user["filter_ozon"]:
        logger.info(f"User {user_id}: Ozon пост пропущен по фильтру")
        return

    channel_id = user["channel_id"]
    if not channel_id:
        logger.warning(f"User {user_id}: канал не привязан")
        return

    # Получение ERID (блокировка без реального ERID)
    erid_data = await resolve_erid(bot, user_id, sku, donor_post_id, channel_id)
    if not erid_data:
        # Пост ушёл в карантин внутри resolve_erid — ничего не делаем
        return

    erid = erid_data["erid"]
    advertiser = erid_data["advertiser"]
    affiliate_url = erid_data["link"]

    caption = build_post_caption(product_title, price, affiliate_url, erid, advertiser)

    blogger_mode = user["blogger_mode"]

    # Ночная очередь
    if is_night_time():
        await add_to_night_queue(
            user_id, channel_id, caption, photo_url, erid, advertiser, affiliate_url
        )
        _record_post(user_id, donor_post_id, channel_id, marketplace, sku, erid, advertiser,
                     status="pending")
        return

    # Публикация
    if blogger_mode == "vip_pin":
        # VIP-закреп в главном канале администратора
        success = await publish_post_with_fallback(
            bot=bot,
            channel_id=str(ADMIN_VIP_CHANNEL_ID),
            caption=caption,
            photo_url=photo_url,
        )
        if success:
            try:
                # Закрепляем пост на 24 часа (снятие через крон)
                msg = await bot.send_message(
                    chat_id=ADMIN_VIP_CHANNEL_ID, text=caption,
                    parse_mode=ParseMode.HTML
                )
                await bot.pin_chat_message(
                    chat_id=ADMIN_VIP_CHANNEL_ID, message_id=msg.message_id
                )
                # Планируем открепление через 24ч (добавляем в отдельную таблицу при необходимости)
            except TelegramAPIError as e:
                logger.warning(f"VIP-закреп: не удалось закрепить — {e}")
    else:
        success = await publish_post_with_fallback(
            bot=bot,
            channel_id=channel_id,
            caption=caption,
            photo_url=photo_url,
        )

    status = "published" if success else "failed"
    _record_post(user_id, donor_post_id, channel_id, marketplace, sku, erid, advertiser,
                 status=status)


def _record_post(
    user_id: int, donor_post_id: str, channel_id: str,
    marketplace: str, sku: str, erid: str, advertiser: str, status: str
) -> None:
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO posts
               (user_id, donor_post_id, channel_id, marketplace, sku, erid, advertiser, status, published_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, donor_post_id, channel_id, marketplace, sku, erid, advertiser, status,
             datetime.now(tz=timezone.utc).isoformat() if status == "published" else None)
        )
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# === FASTAPI WEBAPP (Admin Panel) ============================================
# =============================================================================

def create_fastapi_app(bot: Bot) -> FastAPI:
    app = FastAPI(title="AutoPost Admin", docs_url=None, redoc_url=None)

    @app.get("/admin", response_class=HTMLResponse)
    async def admin_panel(request: Request):
        conn = get_db()
        try:
            users = conn.execute(
                """SELECT user_id, username, channel_title, role, is_active, sub_end
                   FROM users ORDER BY created_at DESC"""
            ).fetchall()

            rows_html = ""
            for u in users:
                # Последние 5 постов для аудит-контроля
                posts = conn.execute(
                    """SELECT donor_post_id, status, created_at FROM posts
                       WHERE user_id=? ORDER BY created_at DESC LIMIT 5""",
                    (u["user_id"],)
                ).fetchall()
                posts_str = ", ".join(
                    f'<span class="post-{p["status"]}">{html.escape(p["donor_post_id"])} '
                    f'({p["status"]})</span>'
                    for p in posts
                ) or "<em>нет постов</em>"
                status_badge = (
                    '<span class="badge active">Active</span>'
                    if u["is_active"]
                    else '<span class="badge inactive">Inactive</span>'
                )
                rows_html += f"""
                <tr>
                    <td><code>{u['user_id']}</code></td>
                    <td>@{html.escape(u['username'] or '—')}</td>
                    <td>{html.escape(u['channel_title'] or '—')}</td>
                    <td><span class="role">{u['role']}</span></td>
                    <td>{status_badge}</td>
                    <td>{(u['sub_end'] or '—')[:10]}</td>
                    <td class="posts-cell">{posts_str}</td>
                </tr>"""
        finally:
            conn.close()

        total_users = len(users) if users else 0
        return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AutoPost — Admin Panel</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3e;
    --accent: #7c6aff; --green: #2ecc71; --red: #e74c3c;
    --text: #e0e0e8; --muted: #6b7280; --code: #a78bfa;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Inter', system-ui, sans-serif; background: var(--bg);
          color: var(--text); padding: 2rem; }}
  h1 {{ color: var(--accent); font-size: 1.5rem; margin-bottom: 0.25rem; }}
  .meta {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 2rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ background: var(--surface); color: var(--muted); text-transform: uppercase;
        font-size: 0.7rem; letter-spacing: 0.08em; padding: 0.75rem 1rem;
        text-align: left; border-bottom: 1px solid var(--border); }}
  td {{ padding: 0.7rem 1rem; border-bottom: 1px solid var(--border);
        vertical-align: top; }}
  tr:hover td {{ background: var(--surface); }}
  code {{ color: var(--code); font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; }}
  .badge {{ display: inline-block; padding: 0.2rem 0.55rem; border-radius: 9999px;
             font-size: 0.72rem; font-weight: 600; }}
  .badge.active {{ background: #1a3a2a; color: var(--green); }}
  .badge.inactive {{ background: #3a1a1a; color: var(--red); }}
  .role {{ color: var(--accent); font-size: 0.78rem; }}
  .posts-cell {{ font-size: 0.75rem; color: var(--muted); max-width: 280px; }}
  .post-published {{ color: var(--green); }}
  .post-quarantine {{ color: var(--red); }}
  .post-failed {{ color: #f39c12; }}
  .post-pending {{ color: var(--muted); }}
</style>
</head>
<body>
<h1>⚡ AutoPost Admin Panel</h1>
<p class="meta">Всего пользователей: <strong>{total_users}</strong> &nbsp;|&nbsp;
Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</p>
<table>
  <thead>
    <tr>
      <th>User ID</th><th>Username</th><th>Канал</th><th>Роль</th>
      <th>Статус</th><th>Подписка до</th><th>Последние 5 постов (аудит)</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
</body>
</html>""")

  # ... (здесь ваш код админ-панели @app.get("/admin")) ...

    # --- НОВЫЙ БЛОК: ВЕБХУК ДЛЯ ТАКПРОДАМ ---
    @app.post("/webhook/takprodam")
    async def takprodam_webhook(request: Request):
        try:
            data = await request.json()
            
            order_id = str(data.get("order_id", ""))
            sub_id = data.get("sub_id", "")
            status = data.get("status", "pending") # pending, approved, rejected
            
            # 1. Получаем грязную выплату от партнерки
            original_payout = float(data.get("payout", 0.0))
            
            # 2. Вычитаем комиссию ТакПродам на вывод (10%)
            net_payout = original_payout * 0.90
            
            # 3. Вычисляем долю блогера (50% от ЧИСТОЙ прибыли)
            blogger_payout = net_payout * 0.5
            
            if not order_id or not sub_id:
                return {"status": "error", "message": "Missing order_id or sub_id"}
                
            conn = get_db()
            
            # 3. Сохраняем в базу ИМЕННО долю блогера (blogger_payout)
            conn.execute(
                """INSERT INTO transactions (order_id, sub_id, status, payout, updated_at) 
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(order_id) DO UPDATE SET 
                   status=excluded.status, 
                   payout=excluded.payout,
                   updated_at=CURRENT_TIMESTAMP""",
                (order_id, sub_id, status, blogger_payout)
            )
            conn.commit()
            conn.close()
            
            logger.info(f"Вебхук: заказ {order_id} для {sub_id} обновлен -> {status}. Доля блогера: {blogger_payout} руб.")
            return {"status": "success"}
            
        except Exception as e:
            logger.error(f"Ошибка обработки вебхука ТакПродам: {e}")
            return {"status": "error", "message": str(e)}

    return app # Эта строка уже была, она завершает функцию create_fastapi_app

# =============================================================================
# === SCHEDULER ===============================================================
# =============================================================================

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    # Ежечасный биллинг-чек
    scheduler.add_job(
        run_billing_check,
        trigger="interval",
        hours=1,
        kwargs={"bot": bot},
        id="billing_check",
    )

    # Утренняя публикация ночной очереди (08:00 МСК)
    scheduler.add_job(
        flush_night_queue,
        trigger="cron",
        hour=8,
        minute=0,
        kwargs={"bot": bot},
        id="flush_night_queue",
    )

    return scheduler
async def check_all_bloggers(bot: Bot):
    conn = get_db()
    bloggers = conn.execute("SELECT user_id, channel_id FROM users WHERE role='blogger'").fetchall()
    conn.close()

    for b in bloggers:
        # 1. Сначала "легкий" запрос, чтобы понять, есть ли новое видео
        latest = get_latest_video(b['channel_id'])
        if not latest or is_video_processed(latest['id']):
            continue

        # 2. Ролик новый! Запрашиваем полное описание
        full_info = get_video_full_details(latest['url'])
        if not full_info:
            continue
            
        description = full_info.get('description', '')
        video_id = full_info.get('id')
        
        logger.info(f"Получено описание для видео {video_id}")
        
        # 3. Здесь ищем артикул в описании
        sku_match = re.search(r'\d{6,12}', description)
        sku = sku_match.group(0) if sku_match else None
        
        # 4. Вызываем публикацию
        await process_new_video(
            bot=bot,
            user_id=b['user_id'],
            video_id=video_id,
            description=description,
            sku=sku,
            photo_url=full_info.get('thumbnail')
        )
# =============================================================================
# === MAIN ENTRYPOINT =========================================================
# =============================================================================
async def scheduler_job(bot: Bot):
    """Задача, которая будет выполняться каждые N минут."""
    logger.info("Запуск цикла парсинга...")
    # Вот здесь нужно правильно вызвать функцию, а не определять её внутри!
    await scan_donor_channels(bot)

# А функцию get_donor_channels_list нужно вынести ВНЕ этой функции
def get_donor_channels_list() -> list:
    """Извлекает список каналов из переменных окружения."""
    channels = os.getenv("DONOR_CHANNELS", "")
    return [ch.strip() for ch in channels.split(",") if ch.strip()]

async def scan_donor_channels(bot: Bot):
    """Основной цикл парсинга каналов."""
    channels = get_donor_channels_list()
    for channel in channels:
        try:
            # Получаем последние сообщения
            history = await bot.get_chat_history(channel, limit=5)
            for message in history:
                text = message.caption or message.text or ""
                photo_url = None
                if message.photo:
                    file = await bot.get_file(message.photo[-1].file_id)
                    photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
                
                # Поиск SKU (артикула) для ТакПродам
                sku_match = re.search(r'\d{6,12}', text)
                if sku_match:
                    sku = sku_match.group(0)
                    # Вызываем обработку (упрощенно: берем всех активных пользователей)
                    await process_donor_post(bot, ADMIN_IDS[0], f"donor_{message.message_id}", sku, "wb", "Товар", "0", photo_url)
        except Exception as e:
            logger.error(f"Ошибка при парсинге {channel}: {e}")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
  
async def main() -> None:
    logger.info("=== AutoPost Bot запускается ===")
    init_db()

    bot = Bot(
        token=BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планировщик задач запущен")

    # === ИСПРАВЛЕННЫЕ ОТСТУПЫ ЗДЕСЬ ===
    scheduler.add_job(
        check_all_bloggers,
        trigger="interval",
        hours=1,
        kwargs={"bot": bot},
        id="blogger_monitor"
    )

    # 1. Создаем веб-приложение
    fastapi_app = create_fastapi_app(bot)
    
    # 2. Создаем сервер
    config = uvicorn.Config(
        fastapi_app,
        host=os.getenv("WEBAPP_HOST", "0.0.0.0"),
        port=int(os.getenv("WEBAPP_PORT", 8000)),
        log_level="info"
    )
    server = uvicorn.Server(config)
    
    # Запускаем всё вместе
    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()
    )

if __name__ == "__main__":
    asyncio.run(main())
