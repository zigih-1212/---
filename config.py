import os
import datetime                 # <-- модуль datetime
from datetime import timedelta, timezone

from services.db import get_db

# --- Загрузка настроек ---
def load_settings():
    defaults = {
        "night_start": os.getenv("NIGHT_START", "23:00"),
        "night_end": os.getenv("NIGHT_END", "08:00"),
        "run_interval": os.getenv("RUN_INTERVAL_SECONDS", "900"),

        "min_payout": os.getenv("PAYOUT_FIXED_FEE", "35"),
        "payout_bank_pct": os.getenv("PAYOUT_BANK_PCT", "0.043"),
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
MIN_PAYOUT = 3000
PAYOUT_FIXED_FEE = float(settings["min_payout"])
PAYOUT_BANK_PCT = float(settings["payout_bank_pct"])
ADMITAD_CLIENT_ID = os.getenv("ADMITAD_CLIENT_ID", "vQiCf6zVRa5E2MvG37HYWHHwb4uILL")
ADMITAD_CLIENT_SECRET = os.getenv("ADMITAD_CLIENT_SECRET", "AsA0jCS7zq2O5k4ZAoMGKv7AokyXOE")
WEBAPP_ADMIN_URL = os.getenv("WEBAPP_ADMIN_URL", "https://main-production-8221.up.railway.app/admin")
WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "https://main-production-8221.up.railway.app")
WEBAPP_PORT = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8000")))
BOT_USERNAME = os.getenv("BOT_USERNAME", "my_wb_catcher_bot")
# --- Ночной режим ---
def is_night_time() -> bool:
    now = datetime.datetime.now(tz=timezone(timedelta(hours=3)))
    start_h, start_m = map(int, settings["night_start"].split(":"))
    end_h, end_m = map(int, settings["night_end"].split(":"))
    start = datetime.time(start_h, start_m)
    end = datetime.time(end_h, end_m)
    if start <= end:
        return start <= now.time() <= end
    else:
        return now.time() >= start or now.time() <= end



# --- Прочие константы ---
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
QUARANTINE_CHAT_ID: int = int(os.getenv("QUARANTINE_CHAT_ID", "0"))
DEEPINFRA_API_KEY: str = os.getenv("DEEPINFRA_API_KEY", "")
WEBAPP_HOST: str = os.getenv("WEBAPP_HOST", "0.0.0.0")
DB_PATH: str = "/app/data/autopost.db"

CTA_PHRASES = [
    "🔥 Количество товара по акции ограничено!",
    "⚡️ Скидка актуальна на момент публикации.",
    "📦 Разбирают очень быстро, проверяйте наличие по ссылке!",
    "⏳ Акция действует ограниченное время.",
]
