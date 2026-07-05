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
MAX_ACTIVE_PAYOUTS: int = 2

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

# --- Тарифы ---
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
                "max_stores": r["max_stores"] if "max_stores" in r.keys() else 3,  # ← добавлено
            }
            for r in rows
        ]
    finally:
        conn.close()

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
STARS_PROVIDER_TOKEN: str = os.getenv("STARS_PROVIDER_TOKEN", "")
WEBAPP_HOST: str = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT: int = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8000")))
CARD_SBER: str = os.getenv("PAY_SBER", "2202 2081 0829 0025")
CARD_TBANK: str = os.getenv("PAY_TBANK", "2200 7013 7009 3863")
CARD_TON: str = os.getenv("PAY_CRYPTO_TON", "UQCua97IuHkQy5F5NPHBray_FJRJoWZa1OOLnq-geGIbGT")
CARD_VISA_KG: str = os.getenv("PAY_VISA_KG", "4196720087839790")
DB_PATH: str = "/app/data/autopost.db"
