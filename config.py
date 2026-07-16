import os
import datetime                 # <-- модуль datetime
from datetime import timedelta, timezone
from typing import List, Optional, Dict, Any
from services.db import get_db

# --- Загрузка настроек ---
def load_settings():
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
        pass
    finally:
        conn.close()
    return defaults

settings = load_settings()

# --- Глобальные переменные ---
MIN_PAYOUT = float(settings["MIN_PAYOUT"])
PAYOUT_FIXED_FEE = float(settings["PAYOUT_FIXED_FEE"])
PAYOUT_BANK_PCT = float(settings["PAYOUT_BANK_PCT"])
ADMITAD_CLIENT_ID = os.getenv("ADMITAD_CLIENT_ID", "vQiCf6zVRa5E2MvG37HYWHHwb4uILL")
ADMITAD_CLIENT_SECRET = os.getenv("ADMITAD_CLIENT_SECRET", "AsA0jCS7zq2O5k4ZAoMGKv7AokyXOE")
WEBAPP_ADMIN_URL = os.getenv("WEBAPP_ADMIN_URL", "https://main-production-8221.up.railway.app/admin")
WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://main-production-8221.up.railway.app")
WEBAPP_PORT = int(os.getenv("PORT", "8000"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "my_wb_catcher_bot")
# --- Ночной режим ---
def is_night_time() -> bool:
    now = datetime.datetime.now(tz=timezone(timedelta(hours=3)))
    start_h, start_m = map(int, settings["NIGHT_START"].split(":"))
    end_h, end_m = map(int, settings["NIGHT_END"].split(":"))
    start = datetime.time(start_h, start_m)
    end = datetime.time(end_h, end_m)
    if start <= end:
        return start <= now.time() <= end
    else:
        return now.time() >= start or now.time() <= end



STORE_DELIVERY_INFO = {
    "Читай-город": "Бесплатная доставка от 3000 ₽",
    "Аквафор": "Доставка 0 ₽ при заказе фильтра",
    "Hi Store RU": "Доставка по всей России от 500 ₽",
    "KANZLER": "Бесплатно от 2500 ₽",
    "KIKO MILANO": "Доставка 300 ₽, бесплатно от 5000 ₽",
    "Moulinex": "Бесплатная доставка",
    "Playtoday": "Доставка от 400 ₽",
    "SELA": "Бесплатная доставка в пункты выдачи",
}
# --- Прочие константы ---
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
WEBAPP_ADMIN_URL: str = os.getenv("WEBAPP_ADMIN_URL", "")
QUARANTINE_CHAT_ID: int = int(os.getenv("QUARANTINE_CHAT_ID", "0"))
DEEPINFRA_API_KEY: str = os.getenv("DEEPINFRA_API_KEY", "")
WEBAPP_HOST: str = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT: int = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8000")))
DB_PATH: str = "/app/data/autopost.db"

CTA_PHRASES = [
    "🔥 Количество товара по акции ограничено!",
    "⚡️ Скидка актуальна на момент публикации.",
    "📦 Разбирают очень быстро, проверяйте наличие по ссылке!",
    "⏳ Акция действует ограниченное время.",
]
