"""
ПАРСЕР КОНТЕНТА — ФАЗА 3
Отдельный модуль для всей логики парсинга (yt-dlp + обработка описаний)
"""

import yt_dlp
import logging
import re
import httpx
import sqlite3
import os
from typing import Optional, Dict, Any
from aiogram import Bot
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("parser")

DB_PATH = os.getenv("DB_PATH", "autopost.db")
TAKPRODAM_MASTER_TOKEN = os.getenv("TAKPRODAM_MASTER_TOKEN")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def extract_video_info(url: str) -> Optional[Dict[str, Any]]:
    """
    Универсальная функция извлечения информации о видео/посте.
    Поддерживает YouTube, TikTok, Instagram и другие платформы через yt-dlp.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if 'entries' in info and info['entries']:  # плейлист / канал
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


def find_product_links(description: str) -> list[Dict[str, str]]:
    """
    Ищет ссылки на товары и артикулы в описании видео.
    Возвращает список найденных потенциальных товаров.
    """
    if not description:
        return []

    links = []

    # 1. Прямые ссылки на WB / Ozon
    url_pattern = re.compile(r'https?://(?:www\.)?(wildberries\.ru|ozon\.ru)[^\s<>"]+')
    for match in url_pattern.finditer(description):
        links.append({"type": "url", "value": match.group(0)})

    # 2. Артикулы (WB — цифры 8-10, Ozon — цифры/буквы)
    sku_patterns = [
        r'(?:арт|артикул|wb|ozon|id)[:\s]*([A-Za-z0-9-]{6,12})',
        r'\b(\d{8,10})\b',  # просто длинные цифры
    ]
    for pattern in sku_patterns:
        for match in re.finditer(pattern, description, re.IGNORECASE):
            sku = match.group(1)
            marketplace = 'wb' if any(x in description.lower() for x in ['wb', 'wildberries']) else 'ozon'
            links.append({"type": "sku", "value": sku, "marketplace": marketplace})

    return links


async def get_product_data(sku: str, sub_id: str) -> Optional[Dict]:
    """Получение данных товара через API ТакПродам"""
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


async def process_new_video(bot: Bot, user_id: int, video_info: Dict) -> None:
    """Основная функция публикации нового видео"""
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT sub_id, channel_id, blogger_mode FROM users WHERE user_id=?", 
            (user_id,)
        ).fetchone()

        if not user or not user["channel_id"]:
            return

        sub_id = user["sub_id"]
        blogger_mode = user.get("blogger_mode", "direct")
        target_channel = os.getenv("ADMIN_VIP_CHANNEL_ID") if blogger_mode == "vip_pin" else user["channel_id"]

        description = video_info.get("description", "")
        product_links = find_product_links(description)

        # Берём первый найденный SKU
        sku = None
        if product_links:
            for link in product_links:
                if link["type"] == "sku":
                    sku = link["value"]
                    break

        product_info = await get_product_data(sku, sub_id) if sku else None

        # Формируем текст поста
        if product_info and product_info.get("link"):
            caption = (
                f"🎬 <b>{video_info.get('title', 'Новое видео')}</b>\n\n"
                f"💰 {product_info.get('price', '')}\n\n"
                f'<a href="{product_info["link"]}">👉 Купить товар</a>\n\n'
                f"<i>Реклама. {product_info.get('advertiser', '')}. Erid: {product_info.get('erid', '')}</i>"
            )
        else:
            caption = f"🎬 <b>{video_info.get('title', 'Новое видео')}</b>\n\n{description[:500]}..."

        # Публикация
        thumbnail = video_info.get("thumbnail")
        if thumbnail:
            await bot.send_photo(chat_id=target_channel, photo=thumbnail, caption=caption, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=target_channel, text=caption, parse_mode="HTML")

        # Запись в БД
        conn.execute(
            "INSERT INTO posts (user_id, donor_post_id, target_channel_id, sku, status) "
            "VALUES (?, ?, ?, ?, 'published')",
            (user_id, video_info['id'], target_channel, sku)
        )
        conn.commit()

        logger.info(f"✅ Опубликовано новое видео для пользователя {user_id}")

    except Exception as e:
        logger.error(f"Ошибка process_new_video: {e}")
    finally:
        conn.close()


def is_video_processed(video_id: str) -> bool:
    """Проверка, был ли пост уже обработан"""
    conn = get_db()
    try:
        row = conn.execute("SELECT 1 FROM posts WHERE donor_post_id=?", (video_id,)).fetchone()
        return row is not None
    finally:
        conn.close()
