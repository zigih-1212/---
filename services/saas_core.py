# services/saas_core.py
import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, Message

from services.db import get_db
from parser import rewrite_text_with_ai, find_product_links, process_new_video
from config import is_night_time

logger = logging.getLogger("autopost_bot")

# ---------------------------------------------------------------------------
# Вспомогательные (общие)
# ---------------------------------------------------------------------------

async def download_image(url: str) -> Optional[bytes]:
    if not url or not url.startswith("http"):
        return None
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "image/webp,image/jpeg,image/png,*/*;q=0.8",
        "Referer": "https://www.wildberries.ru/"
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200 and len(resp.content) > 1024:
                return resp.content
            logger.warning(f"download_image: статус {resp.status_code}, размер {len(resp.content)}")
    except Exception as e:
        logger.warning(f"download_image error: {e}")
    return None


async def publish_post_with_fallback(
    bot: Bot,
    channel_id: str,
    caption: str,
    photo_url: Optional[str] = None,
    video_url: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    """Публикует пост с фото. Если фото не скачалось – отправляет текст."""
    from aiogram.types import BufferedInputFile

    if photo_url:
        image_bytes = await download_image(photo_url)
        if image_bytes:
            try:
                return await bot.send_photo(
                    chat_id=channel_id,
                    photo=BufferedInputFile(image_bytes, filename="product.jpg"),
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            except TelegramAPIError as e:
                logger.warning(f"Ошибка отправки фото: {e}")

    if video_url:
        try:
            return await bot.send_video(
                chat_id=channel_id,
                video=video_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except TelegramAPIError as e:
            logger.warning(f"Ошибка отправки видео: {e}")

    try:
        return await bot.send_message(
            chat_id=channel_id,
            text=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=False
        )
    except TelegramAPIError as e:
        logger.error(f"Ошибка отправки текста: {e}")
        return None


# ---------------------------------------------------------------------------
# Очереди SaaS и публикация
# ---------------------------------------------------------------------------

async def add_to_saas_queue(
    user_id: int, channel_id: str, donor_post_id: str,
    original_text: str, photo_url: Optional[str],
    rewritten_text: Optional[str] = None,
    sku: Optional[str] = None,
    marketplace: str = "wb"
):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO saas_queue 
            (user_id, channel_id, donor_post_id, original_text, photo_url, rewritten_text, sku, marketplace)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, channel_id, donor_post_id, original_text, photo_url, rewritten_text, sku, marketplace)
        )
        conn.commit()
    finally:
        conn.close()


async def prepare_post_content(original_text: str) -> Optional[dict]:
    if not original_text:
        return None
    products = find_product_links(original_text)
    if not products:
        return None

    url = None
    sku = None
    marketplace = "WB"
    for p in products:
        if p.get("type") == "url":
            url = p["value"]
            marketplace = p.get("marketplace", "wb").upper()
            match = re.search(r'/catalog/(\d{6,12})', url)
            if match:
                sku = match.group(1)
            else:
                match = re.search(r'/product/.*?-(\d{6,12})/', url)
                if not match:
                    match = re.search(r'/context/detail/id/(\d{6,12})/', url)
                if match:
                    sku = match.group(1)
            break
    if not sku:
        for p in products:
            if p.get("type") == "sku":
                sku = p["value"]
                marketplace = p.get("marketplace", "wb").upper()
                break
    if not url and sku:
        if marketplace == "WB":
            url = f"https://www.wildberries.ru/catalog/{sku}/detail.aspx"
        else:
            url = f"https://www.ozon.ru/product/{sku}/"
    if not url and not sku:
        return None

    clean_text = re.sub(r'https?://\S+|www\.\S+', '', original_text)
    clean_text = re.sub(r'(?i)(купить|заказать|ссылка|артикул|тут|здесь|подробнее)[:\s👉👇⬇️]*$', '', clean_text)
    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
    if len(clean_text) < 15:
        lines = [l.strip() for l in original_text.split('\n') if l.strip() and not l.startswith('http')]
        clean_text = ' '.join(lines[:3])
    if len(clean_text) < 15:
        clean_text = original_text.split('http')[0].strip()
    if len(clean_text) < 15:
        clean_text = "Интересный товар по ссылке"
    rewritten = await rewrite_text_with_ai(clean_text)
    return {
        "rewritten": rewritten,
        "url": url,
        "sku": sku,
        "marketplace": marketplace
    }


async def process_saas_core(
    bot: Bot,
    user_id: int,
    original_text: str = "",
    donor_post_id: str = "unknown",
    channel_id: str = "unknown",
    force_post: bool = False,
    rewritten_text: Optional[str] = None,
    url: Optional[str] = None,
    sku: Optional[str] = None,
    marketplace: str = "WB"
) -> Optional[str]:
    if not force_post and is_night_time():
        if not rewritten_text:
            prepared = await prepare_post_content(original_text)
            if prepared:
                await add_to_saas_queue(
                    user_id, channel_id, donor_post_id,
                    original_text, None,
                    rewritten_text=prepared["rewritten"],
                    sku=prepared.get("sku"),
                    marketplace=prepared["marketplace"]
                )
        return None

    if not rewritten_text:
        prepared = await prepare_post_content(original_text)
        if not prepared:
            if force_post:
                clean_text = re.sub(r'https?://\S+', '', original_text).strip()
                if not clean_text:
                    clean_text = original_text.split('http')[0].strip()
                if not clean_text:
                    clean_text = "Интересный товар по ссылке"
                rewritten = await rewrite_text_with_ai(clean_text)
                return f"{rewritten}\n\n👉 <a href='{clean_text}'>Посмотреть и заказать</a>\n\n<i>Реклама</i>"
            return None
        rewritten_text = prepared["rewritten"]
        url = prepared.get("url")
        sku = prepared.get("sku")
        marketplace = prepared["marketplace"]

    clean_rewritten = re.sub(r'https?://\S+', '', rewritten_text).strip()
    clean_rewritten = re.sub(r'\bMAX\s*\(\s*клик\s*\)\b', '', clean_rewritten, flags=re.IGNORECASE)
    clean_rewritten = clean_rewritten.replace('<', '').replace('>', '')
    if len(clean_rewritten) < 10:
        fallback_text = original_text.split('http')[0].strip()
        if len(fallback_text) < 10:
            fallback_text = "Интересный товар по ссылке"
        clean_rewritten = await rewrite_text_with_ai(fallback_text)
    if len(clean_rewritten) < 10:
        clean_rewritten = "Отличный товар по ссылке – переходи и заказывай!"

    if url:
        final_link = url
    elif sku:
        if marketplace == "WB":
            final_link = f"https://www.wildberries.ru/catalog/{sku}/detail.aspx"
        else:
            final_link = f"https://www.ozon.ru/product/{sku}/"
    else:
        final_link = None

    if final_link:
        link_block = f"👉 <a href='{final_link}'>Посмотреть и заказать</a>"
    else:
        link_block = "👉 <i>Ссылка временно недоступна</i>"

    post_html = (
        f"{clean_rewritten}\n\n"
        f"🛒 <b>Артикул:</b> <code>{sku or 'не указан'}</code>\n\n"
        f"{link_block}\n\n"
        f"<i>Реклама</i>"
    ).strip()
    return post_html


async def flush_saas_queue_for_user(bot: Bot, user_id: int):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM saas_queue WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return 0

    published_count = 0
    for row in rows:
        original_text = row["original_text"]
        channel_id = row["channel_id"]
        donor_post_id = row["donor_post_id"]
        marketplace = row["marketplace"] or "wb"

        conn_limit = get_db()
        try:
            tariff_row = conn_limit.execute(
                "SELECT t.max_posts_per_day FROM users u JOIN tariffs t ON u.tariff_id = t.id WHERE u.user_id = ?",
                (row["user_id"],)
            ).fetchone()
            max_posts = tariff_row["max_posts_per_day"] if tariff_row else 25
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            posts_today = conn_limit.execute(
                "SELECT COUNT(*) as cnt FROM posts WHERE user_id = ? AND channel_id = ? AND status = 'published' AND published_at >= ?",
                (row["user_id"], channel_id, today_start)
            ).fetchone()["cnt"]
        finally:
            conn_limit.close()

        if posts_today >= max_posts:
            continue

        post_html = await process_saas_core(
            bot=bot,
            user_id=user_id,
            donor_post_id=donor_post_id,
            channel_id=channel_id,
            force_post=False,
            rewritten_text=row["rewritten_text"] if row["rewritten_text"] else None,
            url=None,
            sku=row["sku"],
            marketplace=marketplace
        )
        if not post_html:
            conn2 = get_db()
            conn2.execute("DELETE FROM saas_queue WHERE id = ?", (row["id"],))
            conn2.commit()
            conn2.close()
            continue

        photo_url = row["photo_url"]

        try:
            msg = await publish_post_with_fallback(
                bot=bot,
                channel_id=channel_id,
                caption=post_html,
                photo_url=photo_url
            )
            if not msg:
                continue

            conn_pin = get_db()
            try:
                pin_row = conn_pin.execute(
                    "SELECT auto_pin FROM users WHERE user_id = ?", (row["user_id"],)
                ).fetchone()
                auto_pin = bool(pin_row["auto_pin"]) if pin_row else False
            finally:
                conn_pin.close()

            if auto_pin:
                try:
                    await bot.pin_chat_message(chat_id=channel_id, message_id=msg.message_id)
                    unpin_time = datetime.now(timezone.utc) + timedelta(hours=24)
                    conn_pin2 = get_db()
                    conn_pin2.execute(
                        "INSERT INTO pinned_posts (chat_id, message_id, unpin_at) VALUES (?, ?, ?)",
                        (channel_id, msg.message_id, unpin_time.isoformat())
                    )
                    conn_pin2.commit()
                    conn_pin2.close()
                except Exception as e:
                    logger.warning(f"Не удалось закрепить пост: {e}")

            conn_del = get_db()
            conn_del.execute("DELETE FROM saas_queue WHERE id = ?", (row["id"],))
            conn_del.commit()
            conn_del.close()
            published_count += 1
            await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Ошибка при публикации из очереди SaaS: {e}")

    return published_count


async def flush_all_saas_queues(bot: Bot):
    conn = get_db()
    try:
        user_ids = conn.execute("SELECT DISTINCT user_id FROM saas_queue").fetchall()
    finally:
        conn.close()

    if not user_ids:
        logger.info("🅰️ SaaS-очередь пуста")
        return

    logger.info(f"🅰️ Обрабатываю SaaS-очередь для {len(user_ids)} пользователей")
    for row in user_ids:
        await flush_saas_queue_for_user(bot, row["user_id"])
        await asyncio.sleep(2)
    logger.info("🅰️ Обработка SaaS-очереди завершена")


async def publish_from_catalog(bot: Bot):
    if is_night_time():
        logger.info("🌙 Ночной режим активен, автоматическая публикация приостановлена")
        return

    conn = get_db()
    try:
        users = conn.execute("""
            SELECT u.user_id, u.tariff_id
            FROM users u
            WHERE u.role = 'saas' AND u.is_active = 1
            AND u.subscription_until > datetime('now')
        """).fetchall()
    finally:
        conn.close()

    for user in users:
        user_id = user["user_id"]
        tariff_id = user["tariff_id"]

        # Лимит постов в час
        max_posts_per_hour = 1
        if tariff_id:
            conn = get_db()
            try:
                tariff = conn.execute("SELECT max_posts_per_day FROM tariffs WHERE id = ?", (tariff_id,)).fetchone()
                if tariff and tariff["max_posts_per_day"]:
                    max_posts_per_hour = max(1, tariff["max_posts_per_day"] // 24)
            finally:
                conn.close()

        conn = get_db()
        try:
            hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            posts_last_hour = conn.execute(
                "SELECT COUNT(*) as cnt FROM posts WHERE user_id = ? AND status = 'published' AND published_at >= ? AND donor_post_id LIKE 'admitad_%'",
                (user_id, hour_ago)
            ).fetchone()["cnt"]
        finally:
            conn.close()

        if posts_last_hour >= max_posts_per_hour:
            continue

        # Выбор товара
        conn = get_db()
        try:
            product = conn.execute(
                "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL ORDER BY RANDOM() LIMIT 1",
                (user_id,)
            ).fetchone()
            if not product:
                # Сбрасываем used, если нет доступных
                conn.execute("UPDATE gdeslon_catalog SET used = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
                product = conn.execute(
                    "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND erid != '' AND erid IS NOT NULL ORDER BY RANDOM() LIMIT 1",
                    (user_id,)
                ).fetchone()
            if product:
                conn.execute("UPDATE gdeslon_catalog SET used = 1 WHERE id = ?", (product["id"],))
                conn.commit()
        finally:
            conn.close()

        if not product:
            continue

        partner_url = product['partner_url'] or ''
        title = product['title'] or ''
        price = product['price'] or 0
        currency = product['currency'] or '₽'
        advertiser = product['advertiser'] or 'Рекламодатель'
        erid = product['erid'] or ''

        if not partner_url or not erid:
            continue

        photo_url = product["image_url"]

        # Получаем каналы пользователя
        conn = get_db()
        try:
            channels = conn.execute(
                "SELECT channel_id, sub_id FROM channels WHERE user_id = ? AND is_active = 1",
                (user_id,)
            ).fetchall()
        finally:
            conn.close()

        # Публикуем в каждый канал с уникальным sub_id
        for ch in channels:
            final_url = partner_url
            if ch["sub_id"]:
                if '?' in final_url:
                    final_url += '&subid=' + ch["sub_id"]
                else:
                    final_url += '?subid=' + ch["sub_id"]
            
            adult_warning = ""
            if product.get("source") == "Розовый кролик":
                adult_warning = "🔞 18+\n"
            
            caption = adult_warning + f"{title}\n\n"
            
            caption = f"{title}\n\n"
            if price > 0:
                caption += f"💰 Цена: {price} {currency}\n\n"
            caption += f"👉 <a href='{final_url}'>Посмотреть и заказать</a>\n\n"
            caption += f"Реклама. {advertiser}. Erid: {erid}"

            await publish_post_with_fallback(
                bot=bot,
                channel_id=ch["channel_id"],
                caption=caption,
                photo_url=photo_url
            )
            await asyncio.sleep(1)

async def add_to_night_queue(
    user_id: int, video_id: str, description: str,
    sku: Optional[str], photo_url: Optional[str], marketplace: str = "wb"
) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO night_queue "
            "(user_id, video_id, description, sku, photo_url, marketplace) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, video_id, description, sku, photo_url, marketplace)
        )
        conn.commit()
    finally:
        conn.close()

async def scan_donor_channels(bot: Bot, force_post: bool = False) -> None:
    SAAS_DONOR_CHANNELS: list[str] = [
        x.strip() for x in os.getenv("SAAS_DONOR_CHANNELS", "").split(",") if x.strip()
    ]
    if not SAAS_DONOR_CHANNELS:
        return

    from parser import fetch_telegram_channel_posts

    for channel in SAAS_DONOR_CHANNELS:
        logger.info(f"🔍 Сканирую донора: {channel}")
        try:
            posts = await fetch_telegram_channel_posts(channel)
        except Exception as e:
            logger.error(f"Ошибка получения постов из {channel}: {e}")
            continue

        for post in posts:
            post_id = post.get("id")
            if not post_id:
                continue
            full_donor_id = f"saas_{channel}_{post_id}"
            text = post.get("text", "")
            if not text or len(text) < 20:
                continue
            text = re.sub(r'\bMAX\s*\(\s*клик\s*\)\b', '', text, flags=re.IGNORECASE)
            photo_url = post.get("image_url")

            if not force_post:
                db = get_db()
                try:
                    row = db.execute("SELECT 1 FROM posts WHERE donor_post_id = ? LIMIT 1", (full_donor_id,)).fetchone()
                    if row:
                        continue
                finally:
                    db.close()

            prepared = await prepare_post_content(text)
            if not prepared and not force_post:
                continue

            db = get_db()
            try:
                saas_rows = db.execute("""
                    SELECT u.user_id, c.channel_id
                    FROM users u
                    JOIN channels c ON c.user_id = u.user_id AND c.is_active = 1
                    WHERE u.role = 'saas'
                    AND u.is_active = 1
                    AND u.subscription_until IS NOT NULL
                    AND u.subscription_until > datetime('now')
                """).fetchall()
            finally:
                db.close()

            for row in saas_rows:
                user_id = row["user_id"]
                target_channel = row["channel_id"]

                if target_channel.lstrip("@").lower() == channel.lstrip("@").lower():
                    continue

                conn_pin = get_db()
                try:
                    pin_row = conn_pin.execute("SELECT auto_pin FROM users WHERE user_id = ?", (user_id,)).fetchone()
                    auto_pin = bool(pin_row["auto_pin"]) if pin_row else False
                finally:
                    conn_pin.close()

                post_html = await process_saas_core(
                    bot=bot,
                    user_id=user_id,
                    donor_post_id=full_donor_id,
                    channel_id=target_channel,
                    force_post=force_post,
                    rewritten_text=prepared["rewritten"] if prepared else None,
                    url=prepared["url"] if prepared else None,
                    marketplace=prepared["marketplace"] if prepared else "WB"
                )
                if not post_html:
                    continue

                if not photo_url and prepared and prepared.get("sku") and prepared.get("marketplace") == "WB":
                    from services.saas_core import get_wb_image_url  # заглушка, можно убрать
                    photo_url = get_wb_image_url(prepared["sku"]) if get_wb_image_url else None

                msg = await publish_post_with_fallback(
                    bot=bot,
                    channel_id=target_channel,
                    caption=post_html,
                    photo_url=photo_url
                )
                if not msg:
                    continue

                if auto_pin:
                    try:
                        await bot.pin_chat_message(chat_id=target_channel, message_id=msg.message_id)
                        unpin_time = datetime.now(timezone.utc) + timedelta(hours=24)
                        conn_pin2 = get_db()
                        conn_pin2.execute(
                            "INSERT INTO pinned_posts (chat_id, message_id, unpin_at) VALUES (?, ?, ?)",
                            (target_channel, msg.message_id, unpin_time.isoformat())
                        )
                        conn_pin2.commit()
                        conn_pin2.close()
                    except Exception as e:
                        logger.warning(f"Не удалось закрепить пост: {e}")

                conn_rec = get_db()
                conn_rec.execute(
                    "INSERT INTO posts (user_id, donor_post_id, channel_id, target_channel_id, status, published_at) "
                    "VALUES (?, ?, ?, ?, 'published', ?)",
                    (user_id, full_donor_id, target_channel, target_channel,
                     datetime.now(timezone.utc).isoformat())
                )
                conn_rec.commit()
                conn_rec.close()

                logger.info(f"✅ Пост {full_donor_id} опубликован в {target_channel}")
            await asyncio.sleep(1)
