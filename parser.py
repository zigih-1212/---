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
ADMIN_VIP_CHANNEL_ID = int(os.getenv("ADMIN_VIP_CHANNEL_ID", "0"))
SAAS_DONOR_CHANNELS: list[str] = [
    x.strip() for x in os.getenv("SAAS_DONOR_CHANNELS", "").split(",") if x.strip()
]
MASTER_TOKEN_EVERY_N: int = int(os.getenv("MASTER_TOKEN_EVERY_N", "70"))
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


async def process_new_video(
    bot: Bot, 
    user_id: int, 
    video_id: str, 
    description: str, 
    sku: Optional[str], 
    photo_url: Optional[str], 
    marketplace: str = 'wb'
):
    """Формирует пост с учётом ночного режима и авто-закрепления"""
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
        blogger_mode = user.get("blogger_mode", "direct")
        auto_pin = bool(user.get("auto_pin", 1))
        
        # Определяем целевой канал
        target_channel = str(ADMIN_VIP_CHANNEL_ID) if blogger_mode == "vip_pin" else user["channel_id"]
        
        if not target_channel:
            return

        # === НОЧНОЙ РЕЖИМ (00:00 - 08:00 по Москве = UTC+3) ===
        now_msk = datetime.now(timezone(timedelta(hours=3)))
        if now_msk.hour < 8:
            logger.info(f"🌙 Ночной режим: пост {video_id} отложен до 08:01 МСК")
            # Можно записать в night_queue (рекомендуется) или пропустить
            # Для простоты — пропускаем, следующий скан в 08:xx его подхватит
            return

        # 1. Получаем данные товара
        product_info = await get_product_data(sku, sub_id) if sku else None
        
        video_title = "🔥 Новое видео!"
        
        # 2. Формируем текст
        if product_info:
            caption = (
                f"🎬 <b>{video_title}</b>\n\n"
                f"💰 Цена: {product_info['price']} (Скидка: {product_info.get('discount', '')})\n\n"
                f'<a href="{product_info["link"]}">👉 Купить товар из видео</a>\n\n'
                f"<i>Реклама. {product_info['advertiser']}. Erid: {product_info['erid']}</i>"
            )
            erid_to_save = product_info['erid']
        else:
            caption = f"🎬 <b>{video_title}</b>\n\nСмотри новое видео на канале!"
            erid_to_save = "none"
        
        # 3. Публикуем
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
            
            # === АВТО-ЗАКРЕПЛЕНИЕ ===
            if auto_pin or blogger_mode == "vip_pin":
                try:
                    await bot.pin_chat_message(
                        chat_id=target_channel, 
                        message_id=msg.message_id
                    )
                    
                    # Запись для автоматического открепления через 24ч
                    unpin_time = datetime.now(timezone.utc) + timedelta(hours=24)
                    conn.execute(
                        "INSERT INTO pinned_posts (chat_id, message_id, unpin_at) "
                        "VALUES (?, ?, ?)",
                        (target_channel, msg.message_id, unpin_time.isoformat())
                    )
                except Exception as pin_e:
                    logger.warning(f"Не удалось закрепить пост: {pin_e}")
            
            # Запись в статистику
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
            
            logger.info(f"✅ Пост опубликован для пользователя {user_id} (закреплён: {auto_pin})")
            
        except Exception as e:
            logger.error(f"Ошибка публикации для юзера {user_id}: {e}")
            
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
