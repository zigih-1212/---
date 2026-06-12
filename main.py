import asyncio
import base64
import json
import logging
import os
import re
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup

# Подтягиваем настройки из config.py
from config import (
    BOT_TOKEN, TARGET_CHANNEL, GROQ_API_KEY, 
    DONOR_CHANNELS, RUN_INTERVAL_SECONDS, 
    FIRST_RUN_POSTS_COUNT, CURSORS_FILE
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# --- ФУНКЦИИ ПАМЯТИ ---
def load_cursors() -> dict:
    if os.path.exists(CURSORS_FILE):
        try:
            with open(CURSORS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_cursors(cursors: dict) -> None:
    try:
        with open(CURSORS_FILE, "w", encoding="utf-8") as f:
            json.dump(cursors, f, indent=4)
    except Exception as e:
        log.error(f"Не удалось сохранить память: {e}")

# --- НЕЙРОСЕТЬ GROQ ---
async def groq_rewrite(client: httpx.AsyncClient, image_url: str | None, clean_text: str, marketplace: str) -> str:
    store_name = "Wildberries" if marketplace == "wildberries" else "Ozon"
    prompt = (
        f"Внимательно посмотри на это изображение товара с {store_name}. "
        "Твоя задача — написать абсолютно новое, уникальное, продающее описание для Telegram-канала, "
        "основываясь на том, ЧТО ТЫ ВИДИШЬ на фото. Сделай описание развернутым (минимум 3-4 предложения). "
        "Добавь классные эмодзи. СТРОЖАЙШЕ ЗАПРЕЩЕНО упоминать цены, скидки, артикулы или чужие ссылки. "
        "Ответь ТОЛЬКО готовым текстом нового описания на русском языке."
    )

    parts = []
    if image_url:
        try:
            img_resp = await client.get(image_url, headers=HEADERS, timeout=20, follow_redirects=True)
            img_resp.raise_for_status()
            img_b64 = base64.b64encode(img_resp.content).decode()
            ct = img_resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            parts.append({"type": "image_url", "image_url": {"url": f"data:{ct};base64,{img_b64}"}})
        except Exception as e:
            log.warning(f"Картинка не загрузилась в Groq: {e}")

    full_prompt = f"Контекст из источника:\n{clean_text}\n\n{prompt}" if clean_text else prompt
