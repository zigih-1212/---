"""
ПАРСЕР КОНТЕНТА
Отдельный модуль для всей логики парсинга (yt-dlp + обработка описаний)
"""

import asyncio
import logging
import os
import re
import random
import sqlite3
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import httpx
import yt_dlp
from aiogram import Bot

logger = logging.getLogger("parser")

DB_PATH = os.getenv("DB_PATH", "/app/data/autopost.db")
TAKPRODAM_MASTER_TOKEN = os.getenv("TAKPRODAM_MASTER_TOKEN")
ADMIN_VIP_CHANNEL_ID = int(os.getenv("ADMIN_VIP_CHANNEL_ID", "0"))
SAAS_DONOR_CHANNELS: list[str] = [
    x.strip() for x in os.getenv("SAAS_DONOR_CHANNELS", "").split(",") if x.strip()
]
MASTER_TOKEN_EVERY_N: int = int(os.getenv("MASTER_TOKEN_EVERY_N", "70"))


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


# =============================================================================
# === ИЗВЛЕЧЕНИЕ ВИДЕО ========================================================
# =============================================================================

def extract_video_info(url: str) -> Optional[Dict[str, Any]]:
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
# === ПОИСК ТОВАРОВ ===========================================================
# =============================================================================

def find_product_links(description: str) -> list[Dict[str, str]]:
    if not description:
        return []
    links = []
    url_pattern = re.compile(r'https?://(?:www\.)?(wildberries\.ru|ozon\.ru)[^\s<>"]+')
    for match in url_pattern.finditer(description):
        links.append({"type": "url", "value": match.group(0)})
    sku_patterns = [
        r'(?:арт|артикул|wb|ozon|id)[:\s]*([A-Za-z0-9-]{6,12})',
        r'\b(\d{8,10})\b',
    ]
    for pattern in sku_patterns:
        for match in re.finditer(pattern, description, re.IGNORECASE):
            sku = match.group(1)
            marketplace = 'wb' if any(x in description.lower() for x in ['wb', 'wildberries']) else 'ozon'
            links.append({"type": "sku", "value": sku, "marketplace": marketplace})
    return links


# =============================================================================
# === API ТАКПРОДАМ ===========================================================
# =============================================================================

async def get_product_data(sku: str, sub_id: str) -> Optional[Dict]:
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


async def get_product_data_by_token(token: str, sub_id: str) -> Optional[Dict]:
    url = "https://api.takprodam.ru/v1/products/info"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                original_link = data.get("link", "")
                return {
                    "erid": data.get("erid"),
                    "advertiser": data.get("advertiser"),
                    "link": f"{original_link}?sub_id={sub_id}" if original_link else "",
                }
    except Exception as e:
        logger.error(f"get_product_data_by_token error: {e}")
    return None


# =============================================================================
# === ПУБЛИКАЦИЯ БЛОГЕР =======================================================
# =============================================================================

# --- ИСПРАВЛЕНИЕ: ХЕЛПЕРЫ ДЛЯ РАБОТЫ ---
def is_video_processed(post_id: str) -> bool:
    """Проверка, публиковали ли мы уже этот пост"""
    conn = get_db()
    try:
        exists = conn.execute("SELECT 1 FROM posts WHERE donor_post_id = ?", (post_id,)).fetchone()
        return exists is not None
    finally:
        conn.close()

async def rewrite_text_with_ai(text: str) -> str:
    """Заглушка рерайта, если нет API нейронки"""
    # Если используешь Gemini/GPT, вставь код вызова сюда
    return text

async def get_product_data_by_token(api_key: str, sub_id: str):
    """Логика получения данных о товаре через API"""
    # Это заглушка. Если есть API TakProdam, вставь код запроса сюда
    return {"erid": None, "advertiser": "Реклама"}


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
        blogger_mode = user["blogger_mode"] if user["blogger_mode"] else "direct"
        auto_pin = bool(user["auto_pin"] if user["auto_pin"] is not None else 1)

        target_channel = str(ADMIN_VIP_CHANNEL_ID) if blogger_mode == "vip_pin" else user["channel_id"]

        if not target_channel:
            return

        # === НОЧНОЙ РЕЖИМ (00:00 - 08:00 МСК) ===
        now_msk = datetime.now(timezone(timedelta(hours=3)))
        if now_msk.hour < 8:
            logger.info(f"🌙 Ночной режим: пост {video_id} → night_queue")
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
                f'<a href="{product_info["link"]}">👉 Купить товар из видео</a>\n\n'
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
# === ПУБЛИКАЦИЯ SAAS =========================================================
# =============================================================================

async def process_saas_post(bot: Bot, post_text: str, post_id: str, image_url: Optional[str] = None):
    """Полноценная обработка поста для SaaS с рерайтом, ERID и партнёрскими ссылками"""
    conn = get_db()
    try:
        saas_users = conn.execute("""
            SELECT u.user_id, u.api_key, u.sub_id, c.channel_id
            FROM users u
            JOIN channels c ON c.user_id = u.user_id 
            WHERE u.role = 'saas' AND u.is_active = 1 AND c.is_active = 1
        """).fetchall()
    finally:
        conn.close()

    if not saas_users:
        return

    for user in saas_users:
        try:
            user_id = user["user_id"]
            channel_id = user["channel_id"]
            db_post_id = f"saas_{post_id}_{channel_id}"

            # Защита от дублей
            if is_video_processed(db_post_id):
                continue

            # === AI Рерайт ===
            rewritten = await rewrite_text_with_ai(post_text or "Новое поступление!")

            # === Получаем данные товара через API ТакПродам ===
            product_info = None
            if user.get("api_key"):
                product_info = await get_product_data_by_token(user["api_key"], user["sub_id"])

            # === Формирование финального текста ===
            if product_info and product_info.get("erid"):
                caption = (
                    f"{rewritten}\n\n"
                    f'<a href="{product_info.get("link", "#")}">👉 Купить по партнёрской ссылке</a>\n\n'
                    f"<i>Реклама. {product_info.get('advertiser', 'Партнёр')}. Erid: {product_info['erid']}</i>"
                )
            else:
                caption = (
                    f"{rewritten}\n\n"
                    f"<i>Реклама</i>"
                )

            # === Публикация ===
            try:
                if image_url:
                    await bot.send_photo(
                        chat_id=channel_id,
                        photo=image_url,
                        caption=caption,
                        parse_mode="HTML"
                    )
                else:
                    await bot.send_message(
                        chat_id=channel_id,
                        text=caption,
                        parse_mode="HTML"
                    )

                # Сохранение в БД
                conn = get_db()
                conn.execute("""
                    INSERT INTO posts 
                    (user_id, donor_post_id, channel_id, target_channel_id, 
                     traffic_source, status, published_at)
                    VALUES (?, ?, ?, ?, 'saas_donor', 'published', ?)
                """, (
                    user_id, db_post_id, channel_id, channel_id, 
                    datetime.now(timezone.utc).isoformat()
                ))
                conn.commit()
                conn.close()

                logger.info(f"✅ SaaS пост успешно опубликован в {channel_id}")

            except Exception as e:
                logger.error(f"Ошибка отправки в канал {channel_id}: {e}")

            await asyncio.sleep(5)  # Увеличенная пауза между публикациями

        except Exception as e:
            logger.error(f"Ошибка process_saas_post для пользователя {user_id}: {e}")
            
# =============================================================================
# === RSS TELEGRAM =============================================================
# =============================================================================

async def fetch_telegram_channel_posts(channel: str):
    """Парсинг публичной веб-версии Telegram-канала (Web Scraping)."""
    username = channel.lstrip("@").strip()
    url = f"https://t.me/s/{username}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
