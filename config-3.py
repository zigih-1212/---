"""
Конфигурация бота.
Токены можно также задавать через переменные окружения (для Railway/VPS).
"""
import os

# ─────────────────────────────────────────────
# ТОКЕНЫ (можно переопределить через ENV)
# ─────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "@wb_skidochniki")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ─────────────────────────────────────────────
# КАНАЛЫ-ДОНОРЫ
# ─────────────────────────────────────────────
DONOR_CHANNELS = [
    "wb_skidkamam",
    "ozon_valberis_odezhda",
]

# ─────────────────────────────────────────────
# НАСТРОЙКИ РАБОТЫ
# ─────────────────────────────────────────────

# Интервал между полными проходами (в секундах)
# 900 = 15 минут
RUN_INTERVAL_SECONDS = int(os.getenv("RUN_INTERVAL_SECONDS", "900"))

# Сколько постов обработать при первом запуске (на каждый канал)
FIRST_RUN_POSTS_COUNT = int(os.getenv("FIRST_RUN_POSTS_COUNT", "5"))

# Файл для хранения курсоров (LAST_ID)
CURSORS_FILE = os.getenv("CURSORS_FILE", "cursors.json")
