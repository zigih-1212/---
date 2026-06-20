"""
ПАРСЕР КОНТЕНТА
Отдельный модуль для всей логики парсинга (yt-dlp + обработка описаний)
Версия, согласованная с новым main.py (SaaS через process_saas_core, resolve_erid, scan_donor_channels)
"""

import asyncio
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

import httpx
import yt_dlp
from bs4 import BeautifulSoup

logger = logging.getLogger("parser")

DB_PATH = os.getenv("DB_PATH", "/app/data/autopost.db")
TAKPRODAM_MASTER_TOKEN = os.getenv("TAKPRODAM_MASTER_TOKEN")
ADMIN_VIP_CHANNEL_ID = int(os.getenv("ADMIN_VIP_CHANNEL_ID", "0"))


# =============================================================================
# === БАЗА ДАННЫХ (СИНХРОННАЯ) ================================================
# =============================================================================
def get_db():
    """Синхронное подключение к SQLite. Используется для быстрых операций."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


# =============================================================================
# === ИЗВЛЕЧЕНИЕ ВИДЕО (yt-dlp) ==============================================
# =============================================================================
def extract_video_info(url: str) -> Optional[Dict[str, Any]]:
    """Извлекает метаданные видео/поста из YouTube, TikTok и др."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'skip_download': True,
        'playlistend': 1,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info and info['entries']:
                video = info['entries'][0]
            else:
                video = info
            return {
                'id': video.get('id') or video.get('display_id'),
                'title': video.get('title'),
                'description': video.get('description') or video.get('title'),
                'thumbnail': video.get('thumbnail'),
                'url': video.get('url') or url,
                'extractor': video.get('extractor_key') or 'unknown',
                'duration': video.get('duration'),
            }
    except Exception as e:
        logger.error(f"extract_video_info error for {url}: {e}")
        return None


# =============================================================================
# === ПОИСК ТОВАРОВ (SKU / URL) ==============================================
# =============================================================================
def find_product_links(description: str) -> List[Dict[str, str]]:
    """
    Ищет в тексте артикулы (SKU) и прямые ссылки на Wildberries / Ozon.
    Возвращает список словарей с ключами:
      - type: 'sku' или 'url'
      - value: сам артикул или URL
      - marketplace: 'wb' или 'ozon' (если определён)
    """
    if not description:
        return []
    links = []

    # Прямые URL
    url_pattern = re.compile(r'https?://(?:www\.)?(wildberries\.ru|ozon\.ru)[^\s<>"]+')
    for match in url_pattern.finditer(description):
        links.append({"type": "url", "value": match.group(0)})

    # SKU: упоминания с префиксами или просто 8-10 цифр
        sku_patterns = [
        r'(?:арт|артикул|wb|ozon|id|арт\.|арт:|артикул:)[:\s]*([A-Za-z0-9-]{6,12})',  # ключевые слова
        r'(?:^|\s)-(\d{8,10})\b',  # дефис перед артикулом
        r'\b(\d{8,10})\b',  # просто число из 8-10 цифр
    ]
    for pattern in sku_patterns:
        for match in re.finditer(pattern, description, re.IGNORECASE):
            sku = match.group(1)
            # Определяем маркетплейс по контексту (грубо)
            marketplace = 'wb' if any(x in description.lower() for x in ['wb', 'wildberries']) else 'ozon'
            links.append({"type": "sku", "value": sku, "marketplace": marketplace})

    return links


# =============================================================================
# === API ТАКПРОДАМ (МАСТЕР-ТОКЕН) ===========================================
# =============================================================================
async def get_product_data(sku: str, sub_id: str) -> Optional[Dict]:
    """
    Получение партнёрской ссылки, ERID и рекламодателя через мастер-токен.
    Используется для БЛОГЕРОВ (твой мастер-аккаунт).
    """
    if not TAKPRODAM_MASTER_TOKEN:
        return None
    url = "https://api.takprodam.ru/v1/products/info"
    headers = {"Authorization": f"Bearer {TAKPRODAM_MASTER_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params={"sku": sku}, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                original_link = data.get("link", "")
                return {
                    "erid": data.get("erid"),
                    "advertiser": data.get("advertiser"),
                    "link": f"{original_link}?sub_id={sub_id}" if original_link else "",
                    "price": data.get("price"),
                    "title": data.get("title"),
                }
    except Exception as e:
        logger.error(f"TakProdam API error for SKU {sku}: {e}")
    return None


async def get_product_data_by_token(token: str, sku: str) -> Optional[Dict]:
    """
    Получение данных через КЛИЕНТСКИЙ токен по конкретному SKU.
    Возвращает {erid, advertiser, link, image_url} или None.
    """
    url = "https://api.takprodam.ru/v1/products/info"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params={"sku": sku})
            if resp.status_code == 200:
                data = resp.json()
                original_link = data.get("link", "")
                return {
                    "erid": data.get("erid"),
                    "advertiser": data.get("advertiser"),
                    "link": f"{original_link}?sub_id={token}" if original_link else "",
                    "image_url": data.get("image") or data.get("photo") or "",
                }
    except Exception as e:
        logger.error(f"get_product_data_by_token error: {e}")
    return None


# =============================================================================
# === AI REWRITE (DeepInfra / запасной) ======================================
# =============================================================================
async def rewrite_text_with_ai(text: str) -> str:
    """
    Создаёт рекламный пост из сырых характеристик товара через Groq.
    Если текст слишком короткий или API недоступен, возвращает исходный текст.
    """
    if not text or len(text) < 15:
        return text

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return text

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    system_prompt = (
    "Ты — профессиональный копирайтер для Telegram-канала с товарами Wildberries и Ozon. "
    "Твоя задача: из предоставленного текста (даже если он кажется неполным) составить короткий, привлекательный рекламный пост "
    "(2-3 предложения). Обязательно добавь 2-3 эмодзи. Сохрани цену и размеры, если они есть. "
    "НИКОГДА не говори «нет информации», «не могу», «не вижу текста». "
    "Если данных очень мало, просто напиши общее завлекающее описание товара по ссылке."
   )

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Опиши этот товар на основе данных:\n\n{text}"}
        ],
        "temperature": 0.5,
        "max_tokens": 500,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Ошибка Groq рерайта: {e}")

    return text  # fallback

# =============================================================================
# === ПРОВЕРКА ДУБЛИКАТОВ (БЛОГЕР) ===========================================
# =============================================================================
def is_video_processed(video_id: str) -> bool:
    """Проверяет, был ли пост уже опубликован (по donor_post_id)."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM posts WHERE donor_post_id = ? LIMIT 1",
            (video_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# =============================================================================
# === ПУБЛИКАЦИЯ ДЛЯ БЛОГЕРА =================================================
# =============================================================================
async def process_new_video(
    bot,        # aiogram.Bot
    user_id: int,
    video_id: str,
    description: str,
    sku: Optional[str] = None,
    photo_url: Optional[str] = None,
    marketplace: str = 'wb',
):
    """
    Публикует пост для блогера: проверяет ночной режим,
    получает партнёрские данные через мастер-токен, собирает подпись
    и отправляет в канал блогера (или VIP-канал).
    """
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT sub_id, channel_id, blogger_mode, auto_pin "
            "FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

        if not user or not user["channel_id"]:
            return

        sub_id = user["sub_id"]
        blogger_mode = user["blogger_mode"] if user["blogger_mode"] else "direct"
        auto_pin = bool(user["auto_pin"] if user["auto_pin"] is not None else 1)

        target_channel = str(ADMIN_VIP_CHANNEL_ID) if blogger_mode == "vip_pin" else user["channel_id"]
        if not target_channel:
            return

        # Ночной режим (00:00 – 08:00 МСК)
        now_msk = datetime.now(timezone(timedelta(hours=3)))
        if now_msk.hour < 8:
            logger.info(f"🌙 Ночной режим: пост {video_id} → night_queue")
            # Импортируем здесь, чтобы избежать цикла
            from main import add_to_night_queue
            await add_to_night_queue(
                user_id=user_id,
                video_id=video_id,
                description=description,
                sku=sku,
                photo_url=photo_url,
                marketplace=marketplace,
            )
            return

        product_info = await get_product_data(sku, sub_id) if sku else None
        video_title = "🔥 Новое видео!"

        if product_info:
            caption = (
                f"🎬 <b>{video_title}</b>\n\n"
                f"💰 Цена: {product_info['price']}\n\n"
                f"<a href=\"{product_info['link']}\">👉 Купить товар из видео</a>\n\n"
                f"<i>Реклама. {product_info['advertiser']}. Erid: {product_info['erid']}</i>"
            )
            erid_to_save = product_info['erid']
        else:
            caption = f"🎬 <b>{video_title}</b>\n\nСмотри новое видео на канале!"
            erid_to_save = "none"

        try:
            if photo_url:
                msg = await bot.send_photo(
                    chat_id=target_channel,
                    photo=photo_url,
                    caption=caption,
                    parse_mode="HTML"
                )
            else:
                msg = await bot.send_message(
                    chat_id=target_channel,
                    text=caption,
                    parse_mode="HTML"
                )

            if auto_pin or blogger_mode == "vip_pin":
                try:
                    await bot.pin_chat_message(
                        chat_id=target_channel,
                        message_id=msg.message_id
                    )
                    unpin_time = datetime.now(timezone.utc) + timedelta(hours=24)
                    conn.execute(
                        "INSERT INTO pinned_posts (chat_id, message_id, unpin_at) VALUES (?, ?, ?)",
                        (target_channel, msg.message_id, unpin_time.isoformat())
                    )
                    conn.commit()
                except Exception as pin_e:
                    logger.warning(f"Не удалось закрепить пост: {pin_e}")

            conn.execute(
                "INSERT INTO posts (user_id, donor_post_id, target_channel_id, "
                "traffic_source, sku, erid, status, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id, video_id, target_channel, "yt",
                    sku or "no_sku", erid_to_save, "published",
                    datetime.now(timezone.utc).isoformat()
                )
            )
            conn.commit()
            logger.info(f"✅ Пост опубликован для пользователя {user_id}")

        except Exception as e:
            logger.error(f"Ошибка публикации для юзера {user_id}: {e}")

    finally:
        conn.close()


# =============================================================================
# === ВЕБ-СКРАПИНГ TELEGRAM-КАНАЛОВ (SAAS) ===================================
# =============================================================================
async def fetch_telegram_channel_posts(channel: str) -> List[Dict[str, str]]:
    """
    Парсинг публичной веб-версии Telegram-канала (Web Scraping).
    Используется для получения постов из каналов-доноров.
    Возвращает список постов с полями id, text, image_url, channel.
    """
    username = channel.lstrip("@").strip()
    url = f"https://t.me/s/{username}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            logger.warning(f"Web Scraping {username}: статус {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, 'html.parser')
        posts = []
        messages = soup.find_all('div', class_='tgme_widget_message')

        for msg in messages:
            msg_id_attr = msg.get('data-post')
            if not msg_id_attr:
                continue
            post_id = msg_id_attr.split('/')[-1]

            text_div = msg.find('div', class_='tgme_widget_message_text')
            text = text_div.get_text(separator='\n') if text_div else ""

            image_url = None
            img_style = msg.find('a', class_='tgme_widget_message_photo_wrap')
            if img_style and 'background-image:url(' in img_style.get('style', ''):
                image_url = img_style['style'].split("background-image:url('")[1].split("')")[0]

            if post_id and text:
                posts.append({
                    "id": post_id,
                    "text": text.strip(),
                    "image_url": image_url,
                    "channel": channel
                })

        return posts

    except Exception as e:
        logger.error(f"Ошибка при парсинге {username}: {e}")
        return []
