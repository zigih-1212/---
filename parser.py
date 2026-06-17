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

def is_video_processed(video_id: str) -> bool:
    conn = get_db()
    try:
        row = conn.execute("SELECT 1 FROM posts WHERE donor_post_id=?", (video_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


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

async def process_saas_post(bot: Bot, post_text: str, post_id: str):
    """Публикует пост из донора во все активные каналы SaaS с рерайтом"""
    from main import rewrite_text_with_ai

    conn = get_db()
    try:
        saas_users = conn.execute("""
            SELECT u.user_id, u.api_key, u.sub_id,
                   c.channel_id, c.channel_title
            FROM users u
            JOIN channels c ON c.user_id = u.user_id AND c.is_active = 1
            WHERE u.role = 'saas'
              AND u.is_active = 1
              AND u.subscription_until > datetime('now')
        """).fetchall()
        saas_users = list(saas_users)
    finally:
        conn.close()

    random.shuffle(saas_users)
    saas_post_counter = {}

    for user in saas_users:
        try:
            user_id = user["user_id"]
            channel_id = user["channel_id"]

            if is_video_processed(f"{post_id}_{channel_id}"):
                continue

            rewritten = await rewrite_text_with_ai(post_text)

            saas_post_counter[user_id] = saas_post_counter.get(user_id, 0) + 1
            use_master = (saas_post_counter[user_id] % MASTER_TOKEN_EVERY_N == 0)
            token = TAKPRODAM_MASTER_TOKEN if use_master else user["api_key"]

            if not token:
                logger.warning(f"SaaS user {user_id} не имеет api_key, пропускаем")
                continue

            product_info = await get_product_data_by_token(token, user["sub_id"])

            if product_info and product_info.get("erid"):
                caption = (
                    f"{rewritten}\n\n"
                    f"<i>Реклама. {product_info['advertiser']}. "
                    f"Erid: {product_info['erid']}</i>"
                )
            else:
                caption = rewritten

            msg = await bot.send_message(
                chat_id=channel_id,
                text=caption,
                parse_mode="HTML"
            )

            conn = get_db()
            try:
                conn.execute("""
                    INSERT INTO posts
                    (user_id, donor_post_id, channel_id, traffic_source, status, published_at)
                    VALUES (?, ?, ?, 'saas_donor', 'published', ?)
                """, (user_id, f"{post_id}_{channel_id}", channel_id,
                      datetime.now(timezone.utc).isoformat()))
                conn.commit()
            finally:
                conn.close()

            logger.info(f"✅ SaaS пост опубликован: user={user_id} канал={channel_id}")
            await asyncio.sleep(random.uniform(3, 7))

        except Exception as e:
            logger.error(f"process_saas_post ошибка user={user['user_id']}: {e}")


# =============================================================================
# === RSS TELEGRAM =============================================================
# =============================================================================

async def fetch_telegram_channel_posts(channel: str) -> list[Dict[str, str]]:
    """Читает RSS Telegram-канала через rsshub.app."""
    username = channel.lstrip("@").strip()
    url = f"https://rsshub.app/telegram/channel/{username}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            logger.warning(f"RSS {username}: статус {resp.status_code}")
            return []

        posts = []
        items = re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL)
        for item in items[:5]:
            guid = re.search(r"<guid[^>]*>(.*?)</guid>", item)
            title = re.search(r"<title>(.*?)</title>", item)
            desc = re.search(r"<description>(.*?)</description>", item, re.DOTALL)
            post_id = guid.group(1).strip() if guid else None
            text = ""
            if desc:
                text = re.sub(r"<[^>]+>", "", desc.group(1))
                text = re.sub(r"&amp;", "&", text)
                text = re.sub(r"&lt;", "<", text)
                text = re.sub(r"&gt;", ">", text)
                text = re.sub(r"&quot;", '"', text)
                text = text.strip()
            if post_id and text:
                posts.append({
                    "id": post_id,
                    "text": text,
                    "title": title.group(1).strip() if title else "",
                })
        return posts

    except Exception as e:
        logger.error(f"fetch_telegram_channel_posts error [{username}]: {e}")
        return []
