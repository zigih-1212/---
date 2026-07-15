# services/saas_core.py
import asyncio
import hashlib
import logging
import re
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, Message

from services.db import get_db
from config import is_night_time
from services.text_rewriter import generate_post_text
from services.admitad import get_delivery_for_store, get_random_promocode, STORE_ID_MAP, ADULT_STORES
from utils import get_block_reason

def generate_subid2(user_id: int, channel_id: str) -> str:
    clean_channel = channel_id.lstrip("@").replace(" ", "_")
    return f"u{user_id}_ch_{clean_channel[:20]}"


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
    has_spoiler: bool = False,
) -> Optional[Message]:
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
                    has_spoiler=has_spoiler,
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
                has_spoiler=has_spoiler,
            )
        except TelegramAPIError as e:
            logger.warning(f"Ошибка отправки: {e}")
            reason = get_block_reason(e)
            if reason:
                # Деактивируем канал
                conn_deact = get_db()
                try:
                    conn_deact.execute("UPDATE channels SET is_active = 0 WHERE channel_id = ?", (channel_id,))
                    conn_deact.commit()
                    # Уведомление владельцу канала (найдём user_id по channel_id)
                    user_row = conn_deact.execute("SELECT user_id FROM channels WHERE channel_id = ?", (channel_id,)).fetchone()
                    if user_row:
                        try:
                            await bot.send_message(
                                user_row["user_id"],
                                f"⚠️ Бот не может публиковать посты в канал <b>{channel_id}</b>.\n"
                                f"Причина: {reason}. Канал деактивирован. Вы можете повторно добавить его после исправления проблемы."
                            )
                        except: pass
                finally:
                    conn_deact.close()
                return None  # Прерываем текущую попытку
            # Если не критично, пробуем фолбэк дальше

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
async def publish_from_catalog(bot: Bot):
    if is_night_time():
        logger.info("🌙 Ночной режим активен, автоматическая публикация приостановлена")
        return

    conn = get_db()
    try:
        users = conn.execute("""
            SELECT u.user_id, u.tariff_id, u.role, u.post_interval_minutes, u.commission_rate
            FROM users u
            WHERE u.role IN ('saas', 'blogger') AND u.is_active = 1
            AND (u.subscription_until > datetime('now') OR u.role = 'blogger')
        """).fetchall()
    finally:
        conn.close()

    logger.info(f"[DEBUG] Найдено активных пользователей: {len(users)}")

    for user in users:
        user_id = user["user_id"]
        role = user["role"]
        tariff_id = user["tariff_id"]
        post_interval = user["post_interval_minutes"] or 60
        commission_rate = user["commission_rate"] or 0.95

        # Проверка интервала для блогеров
        if role == "blogger":
            conn = get_db()
            try:
                last_post = conn.execute(
                    "SELECT MAX(published_at) FROM posts WHERE user_id=? AND status='published' AND donor_post_id LIKE 'admitad_%'",
                    (user_id,)
                ).fetchone()[0]
                if last_post:
                    last_dt = datetime.fromisoformat(last_post.replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - last_dt).total_seconds() < post_interval * 60:
                        logger.info(f"[DEBUG] User {user_id}: интервал не вышел, пропускаем")
                        continue
            finally:
                conn.close()

        # Лимит постов для SaaS
        max_posts_per_hour = 1
        if role == "saas" and tariff_id:
            pass   # полностью игнорируем ограничения

        # Загружаем выбранные пользователем магазины
        conn = get_db()
        try:
            user_stores = conn.execute("SELECT category_id FROM user_category_preferences WHERE user_id=?", (user_id,)).fetchall()
            store_ids = [r["category_id"] for r in user_stores]
        finally:
            conn.close()

        from services.admitad import STORE_ID_MAP, ADULT_STORES, STORES
        allowed_sources = [STORE_ID_MAP[sid] for sid in store_ids if sid in STORE_ID_MAP]

        if role == "blogger" and not allowed_sources:
            allowed_sources = list(STORES.keys())

        min_discount = 0
        if role == "saas":
            conn = get_db()
            try:
                min_disc = conn.execute("SELECT min_discount FROM users WHERE user_id=?", (user_id,)).fetchone()
                min_discount = min_disc["min_discount"] if min_disc else 0
            finally:
                conn.close()

        # Получаем пользовательский шаблон товара
        conn = get_db()
        try:
            user_tmpl = conn.execute("SELECT product_template FROM users WHERE user_id=?", (user_id,)).fetchone()
            custom_template = user_tmpl["product_template"] if user_tmpl and user_tmpl["product_template"] else None
        finally:
            conn.close()

        # Выбор товара
        conn = get_db()
        try:
            if allowed_sources:
                placeholders = ','.join('?' * len(allowed_sources))
                product = conn.execute(
                    f"SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL AND source IN ({placeholders}) AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                    (user_id, *allowed_sources, min_discount)
                ).fetchone()
            else:
                product = None

            if not product:
                if allowed_sources:
                    conn.execute(
                        f"UPDATE gdeslon_catalog SET used = 0 WHERE user_id = ? AND source IN ({placeholders})",
                        (user_id, *allowed_sources)
                    )
                else:
                    conn.execute("UPDATE gdeslon_catalog SET used = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
                if allowed_sources:
                    product = conn.execute(
                        f"SELECT * FROM gdeslon_catalog WHERE user_id = ? AND erid != '' AND erid IS NOT NULL AND source IN ({placeholders}) AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                        (user_id, *allowed_sources, min_discount)
                    ).fetchone()
                else:
                    product = conn.execute(
                        "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND erid != '' AND erid IS NOT NULL AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                        (user_id, min_discount)
                    ).fetchone()

            if product:
                conn.execute("UPDATE gdeslon_catalog SET used = 1 WHERE id = ?", (product["id"],))
                conn.commit()
        finally:
            conn.close()

        if not product:
            logger.info(f"[DEBUG] User {user_id}: нет доступных товаров")
            if role == "blogger":
                # Пополняем каталог, если он пуст
                logger.info(f"[DEBUG] User {user_id}: запускаем экстренное пополнение каталога")
                from services.admitad import fetch_admitad_catalog_for_user
                await fetch_admitad_catalog_for_user(user_id, max_items_per_store=100)
            continue

        if role == "blogger":
            conn = get_db()
            try:
                remaining = conn.execute("SELECT COUNT(*) FROM gdeslon_catalog WHERE user_id = ? AND used = 0", (user_id,)).fetchone()[0]
                if remaining < 20:
                    logger.info(f"[DEBUG] User {user_id}: мало товаров, запускаем пополнение")
                    from services.admitad import fetch_admitad_catalog_for_user
                    await fetch_admitad_catalog_for_user(user_id, max_items_per_store=100)
            finally:
                conn.close()

        logger.info(f"[DEBUG] User {user_id}: выбран товар id={product['id']}, source={product['source']}")

        partner_url = product['partner_url'] or ''
        title = product['title'] or ''
        price = product['price'] or 0
        currency = product['currency'] or '₽'
        advertiser = product['advertiser'] or 'Рекламодатель'
        erid = product['erid'] or ''

        if not partner_url or not erid:
            logger.info(f"[DEBUG] User {user_id}: товар пропущен (нет partner_url или erid)")
            continue

        photo_url = product["image_url"]
        source = product["source"] if "source" in product.keys() else ""

        conn = get_db()
        try:
            channels = conn.execute(
                "SELECT channel_id, sub_id FROM channels WHERE user_id = ? AND is_active = 1",
                (user_id,)
            ).fetchall()
        finally:
            conn.close()

        if not channels:
            logger.info(f"[DEBUG] User {user_id}: нет активных каналов")
            continue

        logger.info(f"[DEBUG] User {user_id}: публикуем в {len(channels)} каналов")
        for ch in channels:
            final_url = partner_url
            if ch["sub_id"]:
                if '?' in final_url:
                    final_url += '&subid=' + ch["sub_id"]
                else:
                    final_url += '?subid=' + ch["sub_id"]
            # Добавляем subid2 для детализации трафика
            subid2 = generate_subid2(user_id, ch["channel_id"])
            if '?' in final_url:
                final_url += '&subid2=' + subid2
            else:
                final_url += '?subid2=' + subid2

            adult = source in ADULT_STORES
            delivery_info = get_delivery_for_store(source)
            promocode = get_random_promocode(source)

            caption = generate_post_text(
                title=title,
                price=price,
                currency=currency,
                advertiser=advertiser,
                erid=erid,
                partner_url=final_url,
                adult=adult,
                old_price=product["old_price"] if "old_price" in product.keys() else None,
                discount_percent=product["discount_percent"] if "discount_percent" in product.keys() else None,
                delivery_info=delivery_info,
                promocode=promocode,
                custom_template=custom_template
            )

            try:
                msg = await publish_post_with_fallback(
                    bot=bot,
                    channel_id=ch["channel_id"],
                    caption=caption,
                    photo_url=photo_url,
                    has_spoiler=adult
                )
                if msg:
                    direct_link = f"https://t.me/{ch['channel_id'].lstrip('@')}/{msg.message_id}" if ch['channel_id'] else ""
                    donor_post_id = f"admitad_{product['id']}_{user_id}_{int(datetime.now(timezone.utc).timestamp())}"
                    conn_rec = get_db()
                    try:
                        conn_rec.execute(
                            """INSERT INTO posts 
                            (user_id, donor_post_id, channel_id, target_channel_id, subid1, direct_link, status, published_at, caption)
                            VALUES (?, ?, ?, ?, ?, ?, 'published', ?, ?)""",
                            (user_id, donor_post_id, ch['channel_id'], ch['channel_id'], ch['sub_id'], direct_link,
                             datetime.now(timezone.utc).isoformat(), caption)
                        )
                        conn_rec.commit()
                    finally:
                        conn_rec.close()
                    logger.info(f"[DEBUG] Опубликовано в {ch['channel_id']}, post_id={msg.message_id}")
                else:
                    logger.warning(f"[DEBUG] Не удалось опубликовать в {ch['channel_id']}")
            except Exception as e:
                logger.error(f"[DEBUG] Ошибка публикации в {ch['channel_id']}: {e}")
                # Отправляем пост в карантин с причиной ошибки
                conn_q = get_db()
                try:
                    donor_post_id = f"admitad_{product['id']}_{user_id}_{int(datetime.now(timezone.utc).timestamp())}"
                    conn_q.execute(
                        """INSERT INTO posts 
                        (user_id, donor_post_id, channel_id, target_channel_id, subid1, status, quarantine_reason, created_at)
                        VALUES (?, ?, ?, ?, ?, 'quarantine', ?, ?)""",
                        (user_id, donor_post_id, ch['channel_id'], ch['channel_id'], ch['sub_id'],
                         f"Ошибка отправки: {str(e)[:200]}", datetime.now(timezone.utc).isoformat())
                    )
                    conn_q.commit()
                except Exception as db_err:
                    logger.error(f"Не удалось записать в карантин: {db_err}")
                finally:
                    conn_q.close()
