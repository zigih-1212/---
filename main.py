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
import sqlite3
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional

import httpx
import uvicorn
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
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
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

# ---------- Логирование (RotatingFileHandler — защита памяти контейнера) -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=5 * 1024 * 1024, backupCount=3),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("autopost_bot")

# ---------- Конфигурация из переменных окружения -----------------------------
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
# === DATABASE (SQLite WAL-Mode) ===============================================
# =============================================================================

DB_PATH: str = "/app/data/autopost.db"


def get_db():
    db = sqlite3.connect('/app/data/autopost.db') 
    db.row_factory = sqlite3.Row  # Это важно для доступа к данным по именам колонок
    return db


# =============================================================================
# === БЕЗОПАСНАЯ ИНИЦИАЛИЗАЦИЯ БД =============================================
# =============================================================================

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Создаем таблицу пользователей, если ее нет
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            role TEXT DEFAULT 'blogger',
            channel_id TEXT,
            channel_title TEXT,
            sub_id TEXT,
            source_link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Создаем таблицу каналов, если ее нет
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
    
    # 3. БЕЗОПАСНОЕ ОБНОВЛЕНИЕ: Проверяем наличие колонок, чтобы не стереть данные
    # Например, если вы добавили новые поля позже
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN source_link TEXT")
    except sqlite3.OperationalError:
        # Колонка уже существует, ничего не делаем
        pass
        
    conn.commit()
    conn.close()
    logger.info("База данных проверена и готова к работе.")


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


circuit_breaker = CircuitBreaker()


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
    user_id: int, channel_id: str, text: str,
    photo_url: Optional[str], erid: str, advertiser: str, affiliate_url: str,
) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO night_queue "
            "(user_id, channel_id, text, photo_url, erid, advertiser, affiliate_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, channel_id, text, photo_url, erid, advertiser, affiliate_url)
        )
        conn.commit()
    finally:
        conn.close()


async def flush_night_queue(bot: Bot) -> None:
    """Публикует посты из ночной очереди с паузой 90 сек между постами."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM night_queue ORDER BY created_at ASC"
        ).fetchall()
        if not rows:
            return
        logger.info(f"Ночная очередь: {len(rows)} постов")
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
        # Получаем ID бота из уже готового объекта bot
        bot_id = bot.id 
        member = await bot.get_chat_member(chat_id=channel_id, user_id=bot_id)
        
        # 1. Если создатель — сразу True
        if member.status == "creator":
            return True
            
        # 2. Если администратор — проверяем право на пост
        if member.status == "administrator":
            return getattr(member, "can_post_messages", False)
            
        # 3. Во всех остальных случаях (member, restricted, etc.) — False
        return False
    except TelegramAPIError as e:
        logger.error(f"Ошибка проверки админки в {channel_id}: {e}")
        return False


# =============================================================================
# === KEYBOARD HELPERS ========================================================
# =============================================================================

def kb_main_menu(role: str) -> InlineKeyboardMarkup:
    # Общие кнопки для всех пользователей
    buttons = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
        [InlineKeyboardButton(text="📖 Инструкции", callback_data="menu:instructions")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
    ]
    
    # Кнопки ТОЛЬКО ДЛЯ БЛОГЕРА
    if role == "blogger":
        buttons.insert(0, [InlineKeyboardButton(text="📢 Мой канал", callback_data="menu:channel")])
        buttons.insert(1, [InlineKeyboardButton(text="⚙️ Режим публикации", callback_data="menu:pub_mode")])
        buttons.insert(2, [InlineKeyboardButton(text="🤝 Партнёрская программа", callback_data="menu:partner")])
    
    # Кнопки ТОЛЬКО ДЛЯ SAAS
    elif role == "saas":
        # У SaaS нет кнопки "Режим публикации"
        buttons.insert(0, [InlineKeyboardButton(text="📢 Мои каналы", callback_data="menu:my_channels")])
        buttons.insert(1, [InlineKeyboardButton(text="🛒 Фильтры маркетплейсов", callback_data="menu:filters")])
        buttons.insert(2, [InlineKeyboardButton(text="💎 Тарифы и подписка", callback_data="menu:tariffs")])

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
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:settings")],
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


# =============================================================================
# === ROUTER & HANDLERS =======================================================
# =============================================================================

router = Router()

# =============================================================================
# === ОБРАБОТЧИК СТАРТА И РЕГИСТРАЦИИ =========================================
# =============================================================================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username
    
    if user_id in ADMIN_IDS:
        await message.answer("👋 Панель администратора.", reply_markup=kb_admin_panel())
        return

    conn = get_db()
    try:
        # Проверяем не просто наличие юзера, а заполненность полей
        user = conn.execute(
            "SELECT role, channel_id FROM users WHERE user_id=?", 
            (user_id,)
        ).fetchone()
        
        # 1. Если юзера нет — создаем и идем на выбор роли
        if not user:
            sub_id = generate_sub_id(username, user_id)
            conn.execute("INSERT INTO users (user_id, username, sub_id) VALUES (?, ?, ?)", 
                         (user_id, username, sub_id))
            conn.commit()
            
            await message.answer(
                "👋 Добро пожаловать! Кто вы?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👤 Я блогер", callback_data="role:blogger")],
                    [InlineKeyboardButton(text="🏢 Я SaaS-клиент", callback_data="role:saas")]
                ])
            )
            await state.set_state(OnboardingStates.waiting_role)
            return

        # 2. Если роль — дефолтная (blogger), но канала нет — идем привязывать канал
        # (ИЛИ добавьте в БД новое поле, например 'role_selected INTEGER DEFAULT 0')
        if not user["channel_id"]:
            await message.answer("⚠️ Вы еще не привязали канал. Пришлите @username или перешлите сообщение.")
            await state.set_state(OnboardingStates.waiting_channel)
            return

        # 3. Только если всё есть — показываем меню
        await message.answer("🏠 Главное меню", reply_markup=kb_main_menu(user["role"]))
        
    finally:
        conn.close()


# =============================================================================
# === ОБРАБОТЧИК ВЫБОРА РОЛИ ==================================================
# =============================================================================

@router.callback_query(OnboardingStates.waiting_role, F.data.startswith("role:"))
async def cb_set_role(callback: CallbackQuery, state: FSMContext) -> None:
    # Разбираем данные, полученные из нажатия кнопки (например, "role:blogger")
    role = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    # Записываем выбранную роль в базу данных
    conn = get_db()
    try:
        conn.execute("UPDATE users SET role=? WHERE user_id=?", (role, user_id))
        conn.commit()
    finally:
        conn.close()
    
    # ВЕТКА ДЛЯ БЛОГЕРОВ
    if role == "blogger":
        # Блогеру нужно привязать источник контента (YT/TT/Insta)
        await state.set_state(OnboardingStates.waiting_source_channel)
        await callback.message.edit_text(
            "✅ Выбрана роль: <b>БЛОГЕР</b>.\n\n"
            "Чтобы мы могли забирать видео для автопостинга, пожалуйста, пришлите ссылку "
            "на ваш основной канал (YouTube, TikTok или Instagram).",
            parse_mode=ParseMode.HTML
        )
        
    # ВЕТКА ДЛЯ SAAS-КЛИЕНТОВ
    else:
        # SaaS-клиенты не привязывают источник контента, они настраивают постинг
        await state.set_state(OnboardingStates.waiting_saas_tg_channel)
        await callback.message.edit_text(
            "✅ Выбрана роль: <b>SaaS-клиент</b>.\n\n"
            "Пришлите @username вашего Telegram-канала, куда наш бот должен делать "
            "автоматический постинг товаров из каналов-доноров.",
            parse_mode=ParseMode.HTML
        )
    
    await callback.answer()

# =============================================================================
# === ОБРАБОТЧИК ДЛЯ БЛОГЕРА: ПРИВЯЗКА ИСТОЧНИКА ВИДЕО ========================
# =============================================================================

@router.message(OnboardingStates.waiting_source_channel)
async def handle_blogger_source(message: Message, state: FSMContext) -> None:
    source_link = message.text
    user_id = message.from_user.id
    
    # Сохраняем ссылку на донора в базу данных
    conn = get_db()
    try:
        conn.execute("UPDATE users SET source_link=? WHERE user_id=?", (source_link, user_id))
        conn.commit()
    finally:
        conn.close()
        
    # Предлагаем выбор: свой канал или наш
    await message.answer(
        "✅ Источник успешно привязан!\n\n"
        "Теперь выберите, куда бот должен публиковать контент:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Общий", callback_data="target:own")],
            [InlineKeyboardButton(text="Мой канал", callback_data="target:ours")]
        ])
    )
    await state.set_state(OnboardingStates.waiting_target_choice)


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
        
    # Формируем список кнопок для каждого канала
    kb = []
    for ch in channels:
        kb.append([InlineKeyboardButton(text=f"📢 {ch['channel_title']}", callback_data=f"manage_ch:{ch['id']}")])
    
    kb.append([InlineKeyboardButton(text="➕ Добавить еще канал", callback_data="add_channel")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu:back")])
    
    await callback.message.edit_text("Выберите канал для управления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# Обработчик нажатия на кнопку "Добавить канал"
@router.callback_query(F.data == "add_channel")
async def cb_add_channel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Пришлите @username канала или перешлите сообщение из него:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu:my_channels")]
        ])
    )
    # Переводим бота в состояние ожидания ввода канала
    await state.set_state(OnboardingStates.waiting_saas_tg_channel)

@router.message(OnboardingStates.waiting_saas_tg_channel)
async def handle_saas_channel_addition(message: Message, state: FSMContext) -> None:
    channel_username = message.text.strip()
    user_id = message.from_user.id
    
    # Проверка прав бота в канале
    is_admin = await check_bot_admin(message.bot, channel_username)
    if not is_admin:
        await message.answer("❌ Бот не является администратором в этом канале. Добавьте его и попробуйте снова.")
        return
        
    # Добавляем новый канал в таблицу channels
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO channels (user_id, channel_id, channel_title) VALUES (?, ?, ?)",
            (user_id, channel_username, channel_username)
        )
        conn.commit()
    finally:
        conn.close()
        
    await message.answer(
        f"✅ Канал <b>{html.escape(channel_username)}</b> успешно добавлен к вашему списку!",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu("saas") # Возвращаем в меню
    )
    await state.clear()

@router.message(OnboardingStates.waiting_saas_tg_channel)
async def handle_saas_tg_channel(message: Message, state: FSMContext) -> None:
    channel_username = message.text
    user_id = message.from_user.id
    
    # Проверка, является ли бот администратором в указанном канале
    is_admin = await check_bot_admin(message.bot, channel_username)
    if not is_admin:
        await message.answer("❌ Бот не является администратором в этом канале. Добавьте бота.")
        return
        
    # Сохраняем канал в базу для SaaS
    conn = get_db()
    try:
        conn.execute("UPDATE users SET channel_id=? WHERE user_id=?", (channel_username, user_id))
        conn.commit()
    finally:
        conn.close()
        
    await state.clear()
    await message.answer("✅ Канал привязан! Теперь перейдите в настройки для добавления API и корпоративного ERID.")

  # =============================================================================
# === ОБРАБОТЧИК КНОПКИ "НАЗАД" ==============================================
# =============================================================================

@router.callback_query(F.data == "menu:back")
async def cb_back_to_main_menu(callback: CallbackQuery) -> None:
    # 1. Сначала отвечаем Telegram, чтобы убрать "вечную загрузку"
    await callback.answer()
    
    # 2. Получаем роль пользователя, чтобы показать правильное меню
    user_id = callback.from_user.id
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    
    role = user["role"] if user else "blogger"
    
    # 3. Обновляем сообщение, возвращая его в Главное меню
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

    # Подробный парсинг канала
    if message.forward_origin:
        try:
            chat = message.forward_origin.chat
            channel_id = str(chat.id)
            channel_title = chat.title
            logger.info(f"Получен ID канала из пересылки: {channel_id}")
        except AttributeError:
            pass
    elif message.text and message.text.startswith("@"):
        channel_id = message.text.strip()
        channel_title = channel_id
        logger.info(f"Получен username канала: {channel_id}")

    if not channel_id:
        await message.answer("⚠️ Не удалось распознать канал. Пожалуйста, пришлите пересланное сообщение или @username.")
        return

    # Проверка прав (Бот должен быть админом)
    is_admin_ok = await check_bot_admin(message.bot, channel_id)
    if not is_admin_ok:
        await message.answer(
            "❌ Бот не имеет прав администратора в этом канале.\n"
            "Добавьте бота в администраторы (с правом публикации) и попробуйте снова."
        )
        return

    # Запись канала в базу
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET channel_id=?, channel_title=? WHERE user_id=?", 
            (channel_id, channel_title, user_id)
        )
        conn.commit()
        
        # Получаем роль для возврата меню
        row = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
        role = row["role"] if row else "blogger"
        
        logger.info(f"Канал {channel_id} успешно привязан к пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка сохранения канала в БД: {e}")
        await message.answer("Ошибка при сохранении данных в базу.")
        return
    finally:
        conn.close()

    # Завершаем процесс регистрации
    await state.clear()
    
    await message.answer(
        f"✅ <b>Канал успешно привязан:</b> {html.escape(channel_title or channel_id)}\n\n"
        "Теперь вы можете полноценно пользоваться ботом.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(role)
    )

# -----------------------------------------------------------------------------
# Главное меню (единственное определение)
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


@router.callback_query(OnboardingStates.waiting_role, F.data.startswith("role:"))
async def cb_set_role(callback: CallbackQuery, state: FSMContext) -> None:
    role = callback.data.split(":")[1]
    user_id = callback.from_user.id
    username = callback.from_user.username
    
    conn = get_db()
    try:
        # 1. Проверяем, есть ли такой юзер
        cursor = conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if cursor.fetchone():
            # Если есть — обновляем
            conn.execute("UPDATE users SET role=? WHERE user_id=?", (role, user_id))
        else:
            # Если нет — создаем запись (защита от потери данных)
            conn.execute(
                "INSERT INTO users (user_id, username, role) VALUES (?, ?, ?)", 
                (user_id, username, role)
            )
        conn.commit()
    finally:
        conn.close()
    
    await state.clear()
    
    await callback.message.edit_text(
        f"✅ Роль <b>{role.upper()}</b> сохранена!\n\n"
        "Теперь привяжи канал: перешли сообщение из него или отправь <code>@username</code>.",
        parse_mode=ParseMode.HTML
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
# Статистика (единственное определение, с разделением blogger/saas)
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:stats")
async def cb_menu_stats(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT role, sub_id FROM users WHERE user_id=?", (user_id,)
        ).fetchone()

        if not user:
            await callback.message.edit_text("❌ Ошибка: пользователь не найден.")
            await callback.answer()
            return

        role = user["role"]
        keyboard: list = []

        if role == "blogger":
            sub_id = user["sub_id"] or ""
            approved_sum = conn.execute(
                "SELECT COALESCE(SUM(payout), 0.0) FROM transactions "
                "WHERE sub_id=? AND status='approved'", (sub_id,)
            ).fetchone()[0]
            approved_cnt = conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE sub_id=? AND status='approved'",
                (sub_id,)
            ).fetchone()[0]
            pending_cnt = conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE sub_id=? AND status='pending'",
                (sub_id,)
            ).fetchone()[0]

            text = (
                f"📊 <b>Твоя статистика партнёра</b>\n\n"
                f"🆔 sub_id: <code>{sub_id}</code>\n\n"
                f"📦 <b>Заказы:</b>\n"
                f" ├ Ожидают выкупа: <b>{pending_cnt} шт.</b>\n"
                f" └ Выкуплено: <b>{approved_cnt} шт.</b>\n\n"
                f"💸 <b>Твой заработок:</b>\n"
                f" └ <b>{approved_sum:.2f} руб.</b>\n\n"
                f"<i>* Баланс обновляется при выкупе товара клиентом.</i>"
            )
            if approved_sum >= MIN_PAYOUT:
                keyboard.append([
                    InlineKeyboardButton(
                        text="💳 Запросить выплату", callback_data="payout:request"
                    )
                ])
            elif approved_sum > 0:
                text += f"\n\n<i>⚠️ Вывод доступен от {MIN_PAYOUT:.0f} руб.</i>"
        else:
            total = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            published = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE user_id=? AND status='published'", (user_id,)
            ).fetchone()[0]
            quarantine = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE user_id=? AND status='quarantine'", (user_id,)
            ).fetchone()[0]
            last_posts = conn.execute(
                "SELECT donor_post_id, status, created_at FROM posts "
                "WHERE user_id=? ORDER BY id DESC LIMIT 5", (user_id,)
            ).fetchall()
            last_str = "\n".join(
                f"  • <code>{p['donor_post_id']}</code> — {p['status']} ({p['created_at'][:10]})"
                for p in last_posts
            ) or "  <i>Постов ещё не было</i>"
            text = (
                f"📊 <b>Статистика постов (SaaS)</b>\n\n"
                f"Всего: {total}  |  Опубликовано: {published}  |  Карантин: {quarantine}\n\n"
                f"<b>Последние 5 постов:</b>\n{last_str}"
            )

        keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")])
        await callback.message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        )
    except Exception as e:
        logger.error(f"Ошибка в menu:stats: {e}")
        await callback.message.edit_text("⚠️ Ошибка при загрузке статистики.")
    finally:
        conn.close()

    await callback.answer()


# -----------------------------------------------------------------------------
# Выплаты
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "payout:request")
async def cb_request_payout(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "💳 <b>Запрос на вывод средств</b>\n\n"
        "Введи номер карты или реквизиты СБП (номер телефона + банк):",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="menu:stats")]
        ]),
    )
    await state.set_state(PayoutStates.waiting_for_card)
    await callback.answer()


@router.message(PayoutStates.waiting_for_card)
async def handle_payout_card(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    card_details = message.text.strip() if message.text else ""
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT sub_id, username FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        if not user:
            await state.clear()
            return
        sub_id = user["sub_id"]
        approved_sum = conn.execute(
            "SELECT COALESCE(SUM(payout), 0.0) FROM transactions "
            "WHERE sub_id=? AND status='approved'", (sub_id,)
        ).fetchone()[0]
        if approved_sum < MIN_PAYOUT:
            await message.answer("❌ Недостаточно средств для вывода.")
            await state.clear()
            return
        await state.clear()
        await message.answer(
            "✅ <b>Заявка отправлена!</b>\n\nАдминистратор переведёт средства в ближайшее время.",
            parse_mode=ParseMode.HTML,
        )
        admin_text = (
            f"🚨 <b>Новая заявка на выплату!</b>\n\n"
            f"👤 @{user['username']} (ID: <code>{user_id}</code>, sub_id: {sub_id})\n"
            f"💰 Сумма: <b>{approved_sum:.2f} руб.</b>\n\n"
            f"💳 Реквизиты:\n<code>{card_details}</code>"
        )
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Выплачено",
                callback_data=f"adm_payout:done:{sub_id}:{user_id}",
            )]
        ])
        for admin_id in ADMIN_IDS:
            try:
                await message.bot.send_message(
                    chat_id=admin_id, text=admin_text,
                    parse_mode=ParseMode.HTML, reply_markup=admin_kb,
                )
            except Exception:
                pass
    finally:
        conn.close()


@router.callback_query(F.data.startswith("adm_payout:done:"))
async def cb_admin_payout_done(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    sub_id = parts[2]
    blogger_id = int(parts[3])
    conn = get_db()
    try:
        conn.execute(
            "UPDATE transactions SET status='paid' WHERE sub_id=? AND status='approved'",
            (sub_id,)
        )
        conn.commit()
    finally:
        conn.close()
    await callback.message.edit_text(
        callback.message.html_text + "\n\n<b>✅ ВЫПЛАЧЕНО</b>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer("Баланс блогера обнулён")
    try:
        await callback.bot.send_message(
            chat_id=blogger_id,
            text="💸 <b>Выплата отправлена!</b> Проверь баланс карты.",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


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
        sub_info = f"\n\n<b>Текущая подписка:</b> {status} до {row['sub_end'][:10]}"

    text = (
        f"💎 <b>Тарифы AutoPost</b>{sub_info}\n\n"
        + (
            "Оплата только через Telegram Stars (аффилиатный трафик)."
            if traffic_source == "affiliate"
            else "Доступны Stars, карты РФ, Visa KG и TON."
        )
    )
    await callback.message.edit_text(
        text, parse_mode=ParseMode.HTML, reply_markup=kb_tariffs(traffic_source),
    )
    await callback.answer()


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
            f"Подписка на {plan['days']} дней. "
            "Каждый пост маркируется ERID согласно требованиям ФАС."
        ),
        payload=f"autopost:{plan_id}:{callback.from_user.id}",
        provider_token=STARS_PROVIDER_TOKEN,
        currency="XTR",
        prices=[LabeledPrice(label=plan["label"], amount=plan["stars"])],
    )
    await callback.answer()


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout: PreCheckoutQuery) -> None:
    if not pre_checkout.invoice_payload.startswith("autopost:"):
        await pre_checkout.answer(ok=False, error_message="Неверный платёж")
        return
    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    payment: SuccessfulPayment = message.successful_payment
    parts = payment.invoice_payload.split(":")
    if len(parts) != 3 or parts[0] != "autopost":
        return
    plan_id = parts[1]
    user_id = int(parts[2])
    plan = TARIFF_PLANS.get(plan_id)
    if not plan:
        return

    conn = get_db()
    try:
        row = conn.execute("SELECT sub_end FROM users WHERE user_id=?", (user_id,)).fetchone()
        now = datetime.now(tz=timezone.utc)
        if row and row["sub_end"]:
            try:
                base = max(datetime.fromisoformat(row["sub_end"]), now)
            except ValueError:
                base = now
        else:
            base = now
        new_end = base + timedelta(days=plan["days"])
        conn.execute(
            "UPDATE users SET sub_end=?, is_active=1 WHERE user_id=?",
            (new_end.isoformat(), user_id)
        )
        conn.execute(
            "INSERT INTO billing_log (user_id, plan, stars_paid, payment_method, payment_id) "
            "VALUES (?, ?, ?, 'stars', ?)",
            (user_id, plan_id, plan["stars"], payment.telegram_payment_charge_id)
        )
        conn.commit()
    finally:
        conn.close()

    await message.answer(
        f"✅ <b>Подписка активирована</b>\n\n"
        f"Тариф: {plan['label']}\n"
        f"Активна до: {new_end.strftime('%d.%m.%Y')}\n\n"
        "Автопостинг с маркировкой ERID запущен.",
        parse_mode=ParseMode.HTML,
    )
    logger.info(f"Подписка: user={user_id}, план={plan_id}, до={new_end.date()}")


# -----------------------------------------------------------------------------
# Оплата картой / TON
# -----------------------------------------------------------------------------

@router.callback_query(F.data.startswith("buy:card:"))
async def cb_buy_card(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT traffic_source FROM users WHERE user_id=?", (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()

    if row and row["traffic_source"] == "affiliate":
        await callback.answer(
            "❌ Для аффилиатного трафика — только Telegram Stars.",
            show_alert=True,
        )
        return

    card_type = callback.data.split(":")[2]
    if card_type == "ru":
        details = (
            f"Сбербанк: <code>{CARD_SBER}</code>\n"
            f"Т-Банк: <code>{CARD_TBANK}</code>\n"
            "Получатель: Выборных Д.П."
        )
    elif card_type == "kg":
        details = f"Visa KG: <code>{CARD_VISA_KG}</code>"
    else:
        details = f"TON: <code>{CARD_TON}</code>"

    await callback.message.edit_text(
        f"💳 <b>Оплата ({card_type.upper()})</b>\n\n"
        f"{details}\n\n"
        "После перевода отправь скриншот чека. Активация в течение 30 минут.\n\n"
        f"<i>Укажи в комментарии ID: <code>{callback.from_user.id}</code></i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tariffs")]
        ]),
    )
    await callback.answer()


@router.message(PaymentFSM.waiting_for_receipt)
async def process_receipt_photo(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("⚠️ Пришли именно фото (скриншот) чека.")
        return
    photo_id = message.photo[-1].file_id
    user = message.from_user
    data = await state.get_data()
    plan_id = data.get("selected_plan", "—")
    plan = TARIFF_PLANS.get(plan_id, {})
    await message.answer(
        "✅ Чек получен! Администратор активирует подписку в течение 30 минут."
    )
    admin_text = (
        f"💰 <b>Новая заявка на оплату!</b>\n\n"
        f"👤 @{user.username or 'без юзернейма'} (ID: <code>{user.id}</code>)\n"
        f"💎 Тариф: {plan.get('label', plan_id)}"
    )
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Активировать", callback_data=f"adm_pay:ok:{user.id}:{plan_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_pay:no:{user.id}")],
    ])
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_photo(
                chat_id=admin_id, photo=photo_id,
                caption=admin_text, parse_mode=ParseMode.HTML, reply_markup=admin_kb,
            )
        except Exception as e:
            logger.error(f"Не удалось отправить чек админу {admin_id}: {e}")
    await state.clear()


@router.callback_query(F.data.startswith("adm_pay:"))
async def admin_payment_decision(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    action = parts[1]
    user_id = int(parts[2])

    if action == "ok":
        plan_id = parts[3] if len(parts) > 3 else ""
        plan = TARIFF_PLANS.get(plan_id)
        if not plan:
            await callback.answer("Тариф не найден", show_alert=True)
            return
        conn = get_db()
        try:
            row = conn.execute("SELECT sub_end FROM users WHERE user_id=?", (user_id,)).fetchone()
            now = datetime.now(tz=timezone.utc)
            if row and row["sub_end"]:
                try:
                    base = max(datetime.fromisoformat(row["sub_end"]), now)
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
        try:
            await callback.bot.send_message(
                user_id,
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"Тариф <b>{plan['label']}</b> активирован до {new_end.strftime('%d.%m.%Y')}.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        await callback.message.edit_caption(caption=f"✅ Подписка активирована для {user_id}")
        await callback.answer("Подписка активирована")
    else:
        try:
            await callback.bot.send_message(
                user_id,
                "❌ <b>Оплата отклонена.</b>\n\nОбратитесь в поддержку.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        await callback.message.edit_caption(caption=f"❌ Оплата отклонена для {user_id}")
        await callback.answer("Заявка отклонена")


# -----------------------------------------------------------------------------
# Настройки
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:settings")
async def cb_menu_settings(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT role, filter_wb, filter_ozon, blogger_mode, api_key, client_erid_override "
            "FROM users WHERE user_id=?", (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return

    role = row["role"]
    buttons = [
        [InlineKeyboardButton(text="🛒 Фильтры маркетплейсов", callback_data="settings:filters")],
    ]
    if role == "saas":
        buttons.insert(0, [InlineKeyboardButton(text="🔑 API-ключ", callback_data="menu:apikey")])
        buttons.insert(1, [InlineKeyboardButton(text="🏷 Корп. ERID", callback_data="menu:erid_override")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")])

    erid_val = row["client_erid_override"] or ""
    text = (
        f"⚙️ <b>Настройки</b>\n\n"
        f"API-ключ: {'✅ задан' if row['api_key'] else '❌ не задан'}\n"
        f"Корп. ERID: {'✅ ' + erid_val[:20] if erid_val else '—'}\n"
        f"WB: {'✅' if row['filter_wb'] else '❌'}  |  Ozon: {'✅' if row['filter_ozon'] else '❌'}\n"
        f"Режим: {'Напрямую' if row['blogger_mode'] == 'direct' else 'VIP-закреп'}"
    )
    await callback.message.edit_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"menu:filters", "settings:filters"}))
async def cb_settings_filters(callback: CallbackQuery) -> None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT filter_wb, filter_ozon FROM users WHERE user_id=?", (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()
    await callback.message.edit_text(
        "🛒 <b>Фильтры маркетплейсов</b>\n\nВыбери площадки для автопостинга:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_filter_settings(row["filter_wb"], row["filter_ozon"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("filter:toggle:"))
async def cb_filter_toggle(callback: CallbackQuery) -> None:
    field = callback.data.split(":")[2]
    db_field = f"filter_{field}"
    conn = get_db()
    try:
        row = conn.execute(
            f"SELECT {db_field} FROM users WHERE user_id=?", (callback.from_user.id,)
        ).fetchone()
        new_val = 0 if (row[db_field] if row else 1) else 1
        conn.execute(
            f"UPDATE users SET {db_field}=? WHERE user_id=?", (new_val, callback.from_user.id)
        )
        conn.commit()
        row2 = conn.execute(
            "SELECT filter_wb, filter_ozon FROM users WHERE user_id=?", (callback.from_user.id,)
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
            "SELECT blogger_mode FROM users WHERE user_id=?", (callback.from_user.id,)
        ).fetchone()
    finally:
        conn.close()
    mode = row["blogger_mode"] if row else "direct"
    await callback.message.edit_text(
        "📢 <b>Режим публикации</b>\n\n"
        "<b>Напрямую</b> — посты выходят в твой канал.\n"
        "<b>VIP-закреп</b> — пост закрепляется на 24ч в главном канале платформы.",
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
            "UPDATE users SET blogger_mode=? WHERE user_id=?", (mode, callback.from_user.id)
        )
        conn.commit()
    finally:
        conn.close()
    await callback.answer(
        f"✅ {'Напрямую' if mode == 'direct' else 'VIP-закреп'}", show_alert=False
    )
    await cb_blogger_mode_menu(callback)


# -----------------------------------------------------------------------------
# SaaS: API-ключ
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:apikey")
async def cb_menu_apikey(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "🔑 <b>API-ключ ТакПродам</b>\n\n"
        "Введи api_key из личного кабинета ТакПродам.",
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
        "✅ <b>API-ключ сохранён.</b>\n\nERID будет получаться автоматически для каждого поста.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu("saas"),
    )


# -----------------------------------------------------------------------------
# SaaS: ERID override
# -----------------------------------------------------------------------------

@router.callback_query(F.data == "menu:erid_override")
async def cb_menu_erid_override(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "🏷 <b>Корпоративный ERID</b>\n\n"
        "Введи реальный ERID, полученный от ОРД.\n\n"
        "⚠️ <b>Фейковые ERID запрещены — только реальные данные от ОРД.</b>",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(SaasStates.waiting_erid_override)
    await callback.answer()


@router.message(SaasStates.waiting_erid_override)
async def handle_erid_override_input(message: Message, state: FSMContext) -> None:
    erid = message.text.strip() if message.text else ""
    if len(erid) < 5 or not re.match(r"^[A-Za-z0-9\-_]+$", erid):
        await message.answer(
            "⚠️ Неверный формат. Допустимы латинские буквы, цифры, дефис, подчёркивание.\n"
            "Вводи только <b>реальный ERID от ОРД</b>.",
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
        f"✅ <b>ERID сохранён:</b> <code>{html.escape(erid)}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu("saas"),
    )


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
        "📣 <b>Рассылка</b>\n\nВведи текст (HTML поддерживается):",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(AdminStates.broadcast_text)
    await callback.answer()


@router.message(AdminStates.broadcast_text)
async def handle_broadcast_text(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    clean_text = sanitize_html(message.html_text or message.text or "")
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
            await asyncio.sleep(0.05)
        except TelegramAPIError:
            failed += 1
    await state.clear()
    await message.answer(
        f"✅ Рассылка завершена. Доставлено: {sent} | Ошибок: {failed}",
        reply_markup=kb_admin_panel(),
    )


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
        "🔧 <b>Ручное продление</b>\n\nВведи Telegram ID пользователя:",
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
    await message.answer(
        f"Пользователь: <code>{uid}</code>\nСколько дней добавить?",
        parse_mode=ParseMode.HTML,
    )


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
                base = max(datetime.fromisoformat(row["sub_end"]), now)
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
        f"✅ Подписка продлена.\n"
        f"User: <code>{uid}</code> | До: {new_end.strftime('%d.%m.%Y')}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_admin_panel(),
    )
    logger.info(f"Админ продлил подписку: user={uid} до {new_end.date()}")


@router.callback_query(F.data == "admin:webapp_link")
async def cb_admin_webapp_link(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    
    # Используем ваш реальный домен Railway
    public_url = "https://main-production-8221.up.railway.app"
    await callback.answer(f"🌐 WebApp: {public_url}/admin", show_alert=True)
    ()


# =============================================================================
# === BILLING CHECK ===========================================================
# =============================================================================

async def run_billing_check(bot: Bot) -> int:
    now = datetime.now(tz=timezone.utc).isoformat()
    conn = get_db()
    try:
        expired = conn.execute(
            "SELECT user_id FROM users "
            "WHERE is_active=1 AND sub_end IS NOT NULL AND sub_end < ?", (now,)
        ).fetchall()
        if not expired:
            return 0
        for row in expired:
            conn.execute("UPDATE users SET is_active=0 WHERE user_id=?", (row["user_id"],))
            try:
                await bot.send_message(
                    row["user_id"],
                    "⏰ <b>Подписка истекла.</b>\n\nАвтопостинг приостановлен.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💎 Продлить", callback_data="menu:tariffs")]
                    ]),
                )
            except TelegramAPIError:
                pass
        conn.commit()
        logger.info(f"Биллинг: деактивировано {len(expired)} аккаунтов")
        return len(expired)
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
    marketplace: str,
    product_title: str,
    price: str,
    photo_url: Optional[str],
) -> None:
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT channel_id, is_active, filter_wb, filter_ozon, blogger_mode, role "
            "FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not user:
        return
    if user["role"] == "saas" and not user["is_active"]:
        return
    if marketplace == "wb" and not user["filter_wb"]:
        return
    if marketplace == "ozon" and not user["filter_ozon"]:
        return

    channel_id = user["channel_id"]
    if not channel_id:
        return

    erid_data = await resolve_erid(bot, user_id, sku, donor_post_id, channel_id)
    if not erid_data:
        return

    caption = build_post_caption(
        product_title, price,
        erid_data["link"], erid_data["erid"], erid_data["advertiser"],
    )

    if is_night_time():
        await add_to_night_queue(
            user_id, channel_id, caption, photo_url,
            erid_data["erid"], erid_data["advertiser"], erid_data["link"],
        )
        _record_post(
            user_id, donor_post_id, channel_id, marketplace, sku,
            erid_data["erid"], erid_data["advertiser"], "pending",
        )
        return

    success = False
    if user["blogger_mode"] == "vip_pin":
        success = await publish_post_with_fallback(
            bot=bot, channel_id=str(ADMIN_VIP_CHANNEL_ID),
            caption=caption, photo_url=photo_url,
        )
        if success:
            try:
                msg = await bot.send_message(
                    ADMIN_VIP_CHANNEL_ID, caption, parse_mode=ParseMode.HTML
                )
                await bot.pin_chat_message(ADMIN_VIP_CHANNEL_ID, msg.message_id)
                unpin_at = (datetime.now(tz=timezone.utc) + timedelta(hours=24)).isoformat()
                conn2 = get_db()
                try:
                    conn2.execute(
                        "INSERT INTO pinned_posts (chat_id, message_id, unpin_at) "
                        "VALUES (?, ?, ?)",
                        (str(ADMIN_VIP_CHANNEL_ID), msg.message_id, unpin_at)
                    )
                    conn2.commit()
                finally:
                    conn2.close()
            except TelegramAPIError as e:
                logger.warning(f"VIP-закреп: {e}")
    else:
        success = await publish_post_with_fallback(
            bot=bot, channel_id=channel_id, caption=caption, photo_url=photo_url,
        )

    _record_post(
        user_id, donor_post_id, channel_id, marketplace, sku,
        erid_data["erid"], erid_data["advertiser"],
        "published" if success else "failed",
    )


def _record_post(
    user_id: int, donor_post_id: str, channel_id: str,
    marketplace: str, sku: str, erid: str, advertiser: str, status: str,
) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO posts (user_id, donor_post_id, channel_id, marketplace, sku, "
            "erid, advertiser, status, published_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                user_id, donor_post_id, channel_id, marketplace, sku,
                erid, advertiser, status,
                datetime.now(tz=timezone.utc).isoformat() if status == "published" else None,
            )
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
                "SELECT user_id, username, channel_title, role, is_active, sub_end "
                "FROM users ORDER BY created_at DESC"
            ).fetchall()
            rows_html = ""
            for u in users:
                posts = conn.execute(
                    "SELECT donor_post_id, status FROM posts "
                    "WHERE user_id=? ORDER BY id DESC LIMIT 5", (u["user_id"],)
                ).fetchall()
                posts_str = ", ".join(
                    f'<span class="post-{p["status"]}">'
                    f'{html.escape(p["donor_post_id"])} ({p["status"]})</span>'
                    for p in posts
                ) or "<em>нет постов</em>"
                badge = (
                    '<span class="badge active">Active</span>'
                    if u["is_active"] else
                    '<span class="badge inactive">Inactive</span>'
                )
                rows_html += (
                    f"<tr>"
                    f"<td><code>{u['user_id']}</code></td>"
                    f"<td>@{html.escape(u['username'] or '—')}</td>"
                    f"<td>{html.escape(u['channel_title'] or '—')}</td>"
                    f"<td>{u['role']}</td>"
                    f"<td>{badge}</td>"
                    f"<td>{(u['sub_end'] or '—')[:10]}</td>"
                    f"<td>{posts_str}</td>"
                    f"</tr>"
                )
            total_users = len(users)
        finally:
            conn.close()

        page = (
            "<!DOCTYPE html><html lang='ru'><head><meta charset='UTF-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>AutoPost Admin</title><style>"
            ":root{--bg:#0f1117;--surface:#1a1d27;--border:#2a2d3e;"
            "--accent:#7c6aff;--green:#2ecc71;--red:#e74c3c;--text:#e0e0e8;}"
            "*{box-sizing:border-box;margin:0;padding:0;}"
            "body{font-family:system-ui,sans-serif;background:var(--bg);"
            "color:var(--text);padding:2rem;}"
            "h1{color:var(--accent);margin-bottom:1rem;font-size:1.4rem;}"
            "p{color:#6b7280;margin-bottom:1.5rem;font-size:.85rem;}"
            "table{width:100%;border-collapse:collapse;font-size:.82rem;}"
            "th{background:var(--surface);padding:.75rem 1rem;text-align:left;"
            "border-bottom:1px solid var(--border);color:#6b7280;"
            "text-transform:uppercase;font-size:.7rem;letter-spacing:.08em;}"
            "td{padding:.7rem 1rem;border-bottom:1px solid var(--border);vertical-align:top;}"
            "tr:hover td{background:var(--surface);}"
            "code{color:var(--accent);}"
            ".badge{display:inline-block;padding:.2rem .55rem;border-radius:9999px;"
            "font-size:.72rem;font-weight:600;}"
            ".badge.active{background:#1a3a2a;color:var(--green);}"
            ".badge.inactive{background:#3a1a1a;color:var(--red);}"
            ".post-published{color:var(--green);}"
            ".post-quarantine{color:var(--red);}"
            ".post-failed{color:#f39c12;}"
            "</style></head><body>"
            f"<h1>AutoPost Admin Panel</h1>"
            f"<p>Пользователей: <b>{total_users}</b> | "
            f"Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>"
            "<table><thead><tr>"
            "<th>User ID</th><th>Username</th><th>Канал</th>"
            "<th>Роль</th><th>Статус</th><th>До</th><th>Последние 5 постов</th>"
            f"</tr></thead><tbody>{rows_html}</tbody></table>"
            "</body></html>"
        )
        return HTMLResponse(content=page)

    @app.post("/webhook/takprodam")
    async def takprodam_webhook(request: Request):
        try:
            data = await request.json()
            order_id = str(data.get("order_id", ""))
            sub_id = data.get("sub_id", "")
            status = data.get("status", "pending")
            original_payout = float(data.get("payout", 0.0))
            blogger_payout = original_payout * 0.90 * 0.5

            if not order_id or not sub_id:
                return {"status": "error", "message": "Missing order_id or sub_id"}

            conn = get_db()
            try:
                conn.execute(
                    "INSERT INTO transactions (order_id, sub_id, status, payout, updated_at) "
                    "VALUES (?, ?, ?, ?, datetime('now')) "
                    "ON CONFLICT(order_id) DO UPDATE SET "
                    "status=excluded.status, payout=excluded.payout, "
                    "updated_at=datetime('now')",
                    (order_id, sub_id, status, blogger_payout)
                )
                conn.commit()
            finally:
                conn.close()
            return {"status": "success"}
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return {"status": "error", "message": str(e)}

    return app


# =============================================================================
# === SCHEDULER ===============================================================
# =============================================================================

async def unpin_old_messages(bot: Bot) -> None:
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        rows = conn.execute(
            "SELECT id, chat_id, message_id FROM pinned_posts WHERE unpin_at <= ?", (now,)
        ).fetchall()
        for p in rows:
            try:
                await bot.unpin_chat_message(
                    chat_id=p["chat_id"], message_id=p["message_id"]
                )
            except Exception as e:
                logger.warning(f"Не удалось открепить {p['message_id']}: {e}")
            conn.execute("DELETE FROM pinned_posts WHERE id=?", (p["id"],))
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


def get_donor_channels_list() -> list[str]:
    channels = os.getenv("DONOR_CHANNELS", "")
    return [ch.strip() for ch in channels.split(",") if ch.strip()]


async def scan_donor_channels(bot: Bot) -> None:
    """Сканирует каналы-доноры. Расширяй под свою логику парсинга."""
    channels = get_donor_channels_list()
    for channel in channels:
        try:
            chat = await bot.get_chat(channel)
            logger.info(f"Донор: {chat.title or channel} — проверка выполнена")
        except Exception as e:
            logger.error(f"Ошибка при сканировании {channel}: {e}")


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
    logger.info("=== AutoPost Bot запускается ===")
    init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.update.middleware(ErrorLoggingMiddleware())
    dp.include_router(router)

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планировщик запущен")

    fastapi_app = create_fastapi_app(bot)
    config = uvicorn.Config(
        fastapi_app,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    logger.info(f"WebApp: http://{WEBAPP_HOST}:{WEBAPP_PORT}/admin")

    await asyncio.gather(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
