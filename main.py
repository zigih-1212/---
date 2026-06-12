import asyncio
import base64
import json
import logging
import os
import re
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup

# Подтягиваем твои настройки из config.py
from config import (
    BOT_TOKEN, TARGET_CHANNEL, GROQ_API_KEY, 
    DONOR_CHANNELS, RUN_INTERVAL_SECONDS, 
    FIRST_RUN_POSTS_COUNT, CURSORS_FILE
)

# Настройка логов, чтобы все писалось в Railway моментально
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
    parts.append({"type": "text", "text": full_prompt})

    payload = {
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{"role": "user", "content": parts}],
        "temperature": 0.8,
        "max_tokens": 1024,
    }

    try:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error(f"Ошибка ответа Groq API: {e}")
        return clean_text # В случае ошибки отправляем исходный текст

# --- ОТПРАВКА В TELEGRAM ---
async def send_to_telegram(client: httpx.AsyncClient, text: str, img_url: str | None, btn_label: str, target_url: str) -> bool:
    keyboard = {"inline_keyboard": [[{"text": btn_label, "url": target_url}]]}
    
    if img_url:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        data = {"chat_id": TARGET_CHANNEL, "caption": text, "parse_mode": "HTML", "reply_markup": json.dumps(keyboard), "photo": img_url}
    else:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": TARGET_CHANNEL, "text": text, "parse_mode": "HTML", "reply_markup": json.dumps(keyboard)}

    try:
        r = await client.post(url, data=data, timeout=30)
        r.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Ошибка отправки в TG: {e}")
        return False

# --- ПАРСЕР ДОНОРОВ ---
async def process_donor(client: httpx.AsyncClient, channel: str, cursors: dict):
    log.info(f"🔎 Проверяю канал-донор: {channel}")
    try:
        resp = await client.get(f"https://t.me/s/{channel}", headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"Сбой загрузки канала {channel}: {e}")
        return

    soup = BeautifulSoup(resp.text, 'lxml')
    posts = soup.find_all('div', class_='tgme_widget_message', attrs={'data-post': True})
    
    if not posts:
        return

    parsed = []
    for p in posts:
        pid = p['data-post'].split('/')[-1]
        if pid.isdigit():
            parsed.append((int(pid), p))
    parsed.sort(key=lambda x: x[0], reverse=True) # Новые сверху
    
    last_id = cursors.get(channel)
    if not last_id:
        log.info(f"🚀 Первый старт для {channel}. Ищу 5 постов.")
        queue = parsed[:FIRST_RUN_POSTS_COUNT]
        queue.reverse()
    else:
        queue = [p for p in parsed if p[0] > last_id]
        queue.reverse()
        if not queue:
            log.info(f"💤 В {channel} пока нет новых постов.")
            return

    max_id = last_id or 0
    for pid, html in queue:
        links = []
        for a in html.find_all('a', href=True):
            href = unquote(a['href'].split('redirectTo=')[1].split('&')[0]) if 'redirectTo=' in a['href'] else a['href']
            links.append(href.lower())

        mp_link, link_type = None, None
        for link in links:
            if any(x in link for x in ["wildberries", "wb.ru", "wb.link"]):
                mp_link, link_type = link, "wildberries"
                break
            if any(x in link for x in ["ozon.ru", "ozon.link", "ozon.by"]):
                mp_link, link_type = link, "ozon"
                break

        if not mp_link:
            max_id = max(max_id, pid)
            continue

        text_div = html.find('div', class_='tgme_widget_message_text')
        clean_text = re.sub(r'http\S+', '', text_div.get_text(separator="\n")) if text_div else ""

        img_url = None
        photo_div = html.find('a', class_='tgme_widget_message_photo_wrap')
        if photo_div
