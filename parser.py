import yt_dlp
import logging
import re
import httpx
import sqlite3
import os
from typing import Optional
from aiogram import Bot
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("parser")
ADMIN_VIP_CHANNEL_ID = os.getenv("ADMIN_VIP_CHANNEL_ID", "-1009876543210") # Укажите ID вашего VIP-канала

# Настройки
DB_PATH = "autopost.db"
TAKPRODAM_MASTER_TOKEN = os.getenv("TAKPRODAM_MASTER_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ") 

def get_db():
    """Независимое подключение к БД для парсера"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def is_video_processed(video_id: str) -> bool:
    conn = get_db()
    row = conn.execute("SELECT 1 FROM posts WHERE donor_post_id=?", (video_id,)).fetchone()
    conn.close()
    return row is not None

def get_latest_video(channel_url: str):
    """Универсальный парсер для YouTube, TikTok, Instagram"""
    # yt-dlp сам понимает большинство площадок, нам нужно только сказать ему 'quiet'
    ydl_opts = {
        'quiet': True, 
        'extract_flat': True, 
        'playlist_items': '1',
        # Добавляем настройку для обхода простых ограничений
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(channel_url, download=False)
            
            # Если это плейлист или канал
            if 'entries' in info and info['entries']:
                video = info['entries'][0]
                # Добавляем информацию о площадке, если её нет
                if 'extractor' not in video:
                    video['extractor'] = info.get('extractor_key', 'generic')
                return video
            
            # Если это ссылка на конкретное видео/пост
            return info
            
        except Exception as e:
            logger.error(f"Ошибка парсинга {channel_url}: {e}")
            return None

def get_video_full_details(video_url: str):
    ydl_opts = {'quiet': True, 'no_warnings': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            return ydl.extract_info(video_url, download=False)
        except Exception as e:
            logger.error(f"Ошибка получения деталей видео: {e}")
            return None

async def get_product_data(sku: str, sub_id: str) -> dict:
    url = "https://api.takprodam.ru/v1/products/info"
    headers = {"Authorization": f"Bearer {TAKPRODAM_MASTER_TOKEN}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params={"sku": sku}, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                original_link = data.get("link", "")
                return {
                    "erid": data.get("erid"),
                    "advertiser": data.get("advertiser"),
                    "link": f"{original_link}?sub_id={sub_id}",
                    "price": data.get("price"),
                    "discount": data.get("discount")
                }
        except Exception as e:
            logger.error(f"Ошибка API ТакПродам: {e}")
    return None

async def process_new_video(bot: Bot, user_id: int, video_id: str, description: str, sku: Optional[str], photo_url: Optional[str]):
    """Формирует пост и отправляет его в канал блогера или в VIP-канал"""
    conn = get_db()
    # Теперь достаем еще и blogger_mode
    user = conn.execute("SELECT sub_id, channel_id, blogger_mode FROM users WHERE user_id=?", (user_id,)).fetchone()
    
    if not user:
        conn.close()
        return
        
    sub_id = user["sub_id"]
    blogger_mode = user["blogger_mode"]
    
    # Определяем, куда будем постить
    target_channel = ADMIN_VIP_CHANNEL_ID if blogger_mode == "vip_pin" else user["channel_id"]
    
    if not target_channel:
        conn.close()
        return

    # 1. Получаем данные товара
    product_info = await get_product_data(sku, sub_id) if sku else None
    
    video_title = "🔥 Новое видео!"
    
    # 2. Формируем текст
    if product_info:
        caption = (
            f"🎬 <b>{video_title}</b>\n\n"
            f"💰 Цена: {product_info['price']} (Скидка: {product_info['discount']})\n\n"
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
            msg = await bot.send_photo(chat_id=target_channel, photo=photo_url, caption=caption, parse_mode="HTML")
        else:
            msg = await bot.send_message(chat_id=target_channel, text=caption, parse_mode="HTML")
            
        # 4. Если это VIP-режим — закрепляем сообщение
        if blogger_mode == "vip_pin":
            await bot.pin_chat_message(chat_id=target_channel, message_id=msg.message_id)
            
            # Вычисляем время открепления (сейчас + 24 часа)
            unpin_time = datetime.now(timezone.utc) + timedelta(hours=24)
            conn.execute(
                "INSERT INTO pinned_posts (chat_id, message_id, unpin_at) VALUES (?, ?, ?)",
                (target_channel, msg.message_id, unpin_time.isoformat())
            )
            
        # Записываем пост в статистику
        conn.execute(
            "INSERT INTO posts (user_id, donor_post_id, target_channel_id, traffic_source, sku, erid, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, video_id, target_channel, "yt", sku or "no_sku", erid_to_save, "published")
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка публикации для юзера {user_id}: {e}")
    finally:
        conn.close()

async def check_all_bloggers(bot: Bot):
    """Главный цикл планировщика"""
    conn = get_db()
    bloggers = conn.execute("SELECT user_id, channel_id FROM users WHERE role='blogger'").fetchall()
    conn.close()

    for b in bloggers:
        if not b['channel_id'] or 'http' not in b['channel_id']:
            continue # Пропускаем, если канал не привязан

        latest = get_latest_video(b['channel_id'])
        if not latest or is_video_processed(latest['id']):
            continue

        full_info = get_video_full_details(latest['url'])
        if not full_info:
            continue
            
        description = full_info.get('description', '')
        video_id = full_info.get('id')
        thumbnail = full_info.get('thumbnail')
        
        logger.info(f"Найдено новое видео {video_id} у блогера {b['user_id']}")
        
        # Ищем артикул в описании (от 6 до 12 цифр)
        sku_match = re.search(r'\d{6,12}', description)
        sku = sku_match.group(0) if sku_match else None
        
        # Запускаем публикацию
        await process_new_video(bot, b['user_id'], video_id, description, sku, thumbnail)
