# services/saas_core.py
import asyncio
import hashlib
import logging
import re
import os
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

from services.db import get_db
from config import is_night_time
from services.text_rewriter import generate_post_text
from services.admitad import get_delivery_for_store, get_random_promocode, STORE_ID_MAP, ADULT_STORES
from helpers import get_block_reason

def generate_subid2(user_id: int, channel_id: str) -> str:
    """Генерирует уникальный subid2 в формате: u{user_id}_ch_{channel}"""
    clean_channel = channel_id.lstrip("@").replace(" ", "_").replace("-", "_")
    return f"u{user_id}_ch_{clean_channel[:20]}"


class _OGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.og_image = ""
        self.og_description = ""
        self._title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "meta":
            prop = d.get("property", "").lower()
            if prop == "og:image":
                self.og_image = d.get("content", "")
            elif prop == "og:description":
                self.og_description = d.get("content", "")
        if tag == "title":
            self._in_title = True

    def handle_data(self, data):
        if self._in_title:
            self._title += data

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False


async def scrape_og_data(url: str) -> dict:
    """Скрейпит og:image, og:description и title со страницы."""
    if not url or not url.startswith("http"):
        return {"og_image": "", "og_description": "", "og_title": ""}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return {"og_image": "", "og_description": "", "og_title": ""}
            html = resp.text[:50000]
            parser = _OGParser()
            parser.feed(html)
            return {
                "og_image": parser.og_image,
                "og_description": parser.og_description,
                "og_title": parser._title.strip(),
            }
    except Exception as e:
        logger.warning(f"OG scrape failed for {url}: {e}")
        return {"og_image": "", "og_description": "", "og_title": ""}

def generate_partner_url(base_url: str, subid1: str = None, subid2: str = None) -> str:
    """
    Генерирует партнёрскую ссылку с subid параметрами.
    
    Args:
        base_url: Базовая URL-ссылка
        subid1: Основной идентификатор (обычно sub_id канала)
        subid2: Дополнительный идентификатор (обычно комбинация user_id + channel_id)
    
    Returns:
        Сформированная партнёрская ссылка с параметрами
    """
    if not base_url:
        return ""
    
    # Очищаем URL от существующих subid параметров
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(base_url)
    query_params = {}
    
    # Парсим существующие параметры (исключая subid)
    if parsed.query:
        query_params = {k: v[0] for k, v in parse_qs(parsed.query).items() 
                       if k.lower() not in ['subid', 'subid1', 'subid2']}
    
    # Добавляем наши subid параметры
    if subid1:
        query_params['subid'] = subid1  # Для обратной совместимости
        query_params['subid1'] = subid1
    if subid2:
        query_params['subid2'] = subid2
    
    # Собираем URL обратно
    new_query = urlencode(query_params)
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)


logger = logging.getLogger("autopost_bot")

# ---------------------------------------------------------------------------
# Вспомогательные (общие)
# ---------------------------------------------------------------------------

async def download_image(url: str) -> Optional[bytes]:
    if not url or not url.startswith("http"):
        return None

    cache_dir = "/app/data/cache"
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_path = os.path.join(cache_dir, url_hash + ".png")
    os.makedirs(cache_dir, exist_ok=True)

    if os.path.isfile(cache_path):
        age = datetime.now(timezone.utc).timestamp() - os.path.getmtime(cache_path)
        if age < 86400:
            with open(cache_path, "rb") as f:
                cached = f.read()
            if cached:
                logger.info(f"download_image: cache hit ({url})")
                return cached
            logger.info(f"download_image: cache empty, re-download")

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "image/webp,image/jpeg,image/png,*/*;q=0.8",
        "Referer": "https://www.wildberries.ru/"
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"download_image: статус {resp.status_code}")
                return None
            content = resp.content
            if len(content) < 1024:
                logger.warning(f"download_image: слишком мало данных {len(content)}")
                return None
            if url.lower().endswith(".svg") or content[:500].lstrip().startswith(b"<svg") or content[:500].lstrip().startswith(b"<?xml"):
                logger.info(f"download_image: SVG detected, converting to PNG ({url})")
                try:
                    import cairosvg
                    png_bytes = cairosvg.svg2png(bytestring=content, output_width=400)
                    logger.info(f"download_image: SVG→PNG success {len(content)}→{len(png_bytes)} bytes")
                    with open(cache_path, "wb") as f:
                        f.write(png_bytes)
                    return png_bytes
                except Exception as e:
                    logger.warning(f"download_image: SVG→PNG failed: {e}")
                return None
            with open(cache_path, "wb") as f:
                f.write(content)
            return content
    except Exception as e:
        logger.warning(f"download_image error: {e}")
    return None


async def publish_post_with_fallback(
    bot: Bot, 
    channel_id: str,
    caption: str,
    user_id: int = None,
    photo_url: Optional[str] = None,
    video_url: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    has_spoiler: bool = False,
    parse_mode: str = "HTML",
) -> Optional[Message]:
    from aiogram.types import BufferedInputFile
    logger.info(f"publish_post_with_fallback: channel={channel_id}, photo_url={photo_url!r}, caption_len={len(caption)}, parse_mode={parse_mode!r}")

    if photo_url:
        image_bytes = await download_image(photo_url)
        logger.info(f"publish_post_with_fallback: image_bytes={'yes' if image_bytes else 'no'}")
        if image_bytes:
            try:
                logger.info(f"publish_post_with_fallback: sending photo to {channel_id}, caption={caption[:80]!r}")
                return await bot.send_photo(
                    chat_id=channel_id,
                    photo=BufferedInputFile(image_bytes, filename="product.jpg"),
                    caption=caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    has_spoiler=has_spoiler,
                )
            except TelegramAPIError as e:
                logger.warning(f"Ошибка отправки фото: {e}")
        else:
            try:
                logger.info(f"publish_post_with_fallback: trying URL directly for {channel_id}")
                return await bot.send_photo(
                    chat_id=channel_id,
                    photo=photo_url,
                    caption=caption,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    has_spoiler=has_spoiler,
                )
            except TelegramAPIError as e:
                logger.warning(f"Ошибка отправки фото по URL: {e}")

    if video_url:
        try:
            return await bot.send_video(
                chat_id=channel_id,
                video=video_url,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                has_spoiler=has_spoiler,
            )
        except TelegramAPIError as e:
            logger.warning(f"Ошибка отправки: {e}")
            reason = get_block_reason(e)
            if reason:
                conn_deact = get_db()
                try:
                    conn_deact.execute("UPDATE channels SET is_active = 0 WHERE channel_id = ?", (channel_id,))
                    conn_deact.commit()
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
                return None
    try:
        logger.info(f"publish_post_with_fallback: sending text fallback to {channel_id}, text={caption[:80]!r}")
        return await bot.send_message(
            chat_id=channel_id,
            text=caption,
            parse_mode=parse_mode,
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
            WHERE u.role IN ('saas', 'blogger') AND u.is_active = 1 AND u.cpa_enabled = 1
        """).fetchall()
    finally:
        conn.close()

    logger.info(f"[DEBUG] Найдено активных пользователей: {len(users)}")
    for u in users:
        logger.info(f"[DEBUG] Пользователь {u['user_id']}, роль {u['role']}")

    for user in users:
        user_id = user["user_id"]
        role = user["role"]
        post_interval = user["post_interval_minutes"] or 60
        commission_rate = user["commission_rate"] or 0.70

        logger.info(f"[DEBUG] Обработка пользователя {user_id}, роль {role}")

        # Загружаем выбранные пользователем магазины
        conn = get_db()
        try:
            user_stores = conn.execute("SELECT category_id FROM user_category_preferences WHERE user_id=?", (user_id,)).fetchall()
            store_ids = [r["category_id"] for r in user_stores]
            logger.info(f"[DEBUG] User {user_id}: store_ids = {store_ids}")
        finally:
            conn.close()

        from services.admitad import STORE_ID_MAP, ADULT_STORES, STORES
        allowed_sources = [STORE_ID_MAP[sid] for sid in store_ids if sid in STORE_ID_MAP]
        logger.info(f"[DEBUG] User {user_id}: allowed_sources = {allowed_sources}")

        if not allowed_sources:
            logger.info(f"[DEBUG] User {user_id}: нет выбранных магазинов, пропускаем")
            continue

        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")

        scheduled_stores = []
        conn = get_db()
        try:
            sched_rows = conn.execute(
                "SELECT target_id, post_time FROM post_schedules WHERE user_id=? AND target_type='store' AND post_date=? AND is_posted=0",
                (user_id, today_str)
            ).fetchall()
            for sr in sched_rows:
                stid = sr["target_id"]
                if stid in STORE_ID_MAP and STORE_ID_MAP[stid] in allowed_sources:
                    scheduled_stores.append((STORE_ID_MAP[stid], sr["post_time"]))
        finally:
            conn.close()

        has_timer = False
        if scheduled_stores:
            scheduled_stores.sort(key=lambda x: x[1])
            for src, ptime in scheduled_stores:
                if ptime <= current_time:
                    has_timer = True
                    break

        if not has_timer:
            conn = get_db()
            try:
                last_post = conn.execute(
                    "SELECT MAX(published_at) FROM posts WHERE user_id=? AND status='published' AND donor_post_id LIKE 'admitad_%'",
                    (user_id,)
                ).fetchone()[0]
                if last_post:
                    last_dt = datetime.fromisoformat(last_post.replace("Z", "+00:00"))
                    seconds_since_last = (datetime.now(timezone.utc) - last_dt).total_seconds()
                    if seconds_since_last < post_interval * 60:
                        logger.info(f"[DEBUG] User {user_id}: нет таймеров, интервал {post_interval} мин, прошло {seconds_since_last:.0f} сек, пропускаем")
                        continue
                    else:
                        logger.info(f"[DEBUG] User {user_id}: нет таймеров, интервал прошёл, публикуем по расписанию магазинов")
            finally:
                conn.close()
            if not scheduled_stores:
                logger.info(f"[DEBUG] User {user_id}: нет запланированных магазинов на сегодня")
                continue

        if scheduled_stores:
            best = None
            for src, ptime in scheduled_stores:
                if ptime <= current_time:
                    best = src
            if not best:
                logger.info(f"[DEBUG] User {user_id}: время публикации для магазинов ещё не наступило")
                continue
            logger.info(f"[DEBUG] User {user_id}: таймер — публикуем магазин {best} (без проверки интервала)")
            allowed_sources = [best]

            scheduled_store_id = None
            for src, ptime in scheduled_stores:
                if ptime <= current_time:
                    for sid_candidate in store_ids:
                        if sid_candidate in STORE_ID_MAP and STORE_ID_MAP[sid_candidate] == src:
                            scheduled_store_id = sid_candidate
                            break
                    break

        min_discount = 0
        if role == "saas":
            conn = get_db()
            try:
                min_disc = conn.execute("SELECT min_discount FROM users WHERE user_id=?", (user_id,)).fetchone()
                min_discount = min_disc["min_discount"] if min_disc else 0
            finally:
                conn.close()

        # Получаем пользовательский шаблон товара и настройки автоудаления
        conn = get_db()
        try:
            user_tmpl = conn.execute("SELECT product_template, default_auto_delete_hours FROM users WHERE user_id=?", (user_id,)).fetchone()
            custom_template = user_tmpl["product_template"] if user_tmpl and user_tmpl["product_template"] else None
            auto_delete_hours = user_tmpl["default_auto_delete_hours"] if user_tmpl and user_tmpl["default_auto_delete_hours"] is not None else 168
        finally:
            conn.close()

        # Выбор товара
        conn = get_db()
        try:
            # Сначала проверим, сколько всего товаров в каталоге для пользователя
            total_count = conn.execute("SELECT COUNT(*) FROM gdeslon_catalog WHERE user_id = ?", (user_id,)).fetchone()[0]
            unused_count = conn.execute("SELECT COUNT(*) FROM gdeslon_catalog WHERE user_id = ? AND used = 0", (user_id,)).fetchone()[0]
            logger.info(f"[DEBUG] User {user_id}: всего товаров={total_count}, неиспользованных={unused_count}")

            if allowed_sources:
                placeholders = ','.join('?' * len(allowed_sources))
                query = f"""
                    SELECT * FROM gdeslon_catalog 
                    WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL 
                    AND source IN ({placeholders}) 
                    AND (discount_percent IS NULL OR discount_percent >= ?) 
                    ORDER BY RANDOM() LIMIT 1
                """
                logger.info(f"[DEBUG] User {user_id}: запрос с source IN ({placeholders})")
                product = conn.execute(query, (user_id, *allowed_sources, min_discount)).fetchone()
            else:
                product = None

            if not product:
                if allowed_sources:
                    # Сбрасываем used для всех товаров выбранных магазинов
                    conn.execute(
                        f"UPDATE gdeslon_catalog SET used = 0 WHERE user_id = ? AND source IN ({placeholders})",
                        (user_id, *allowed_sources)
                    )
                else:
                    conn.execute("UPDATE gdeslon_catalog SET used = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
                logger.info(f"[DEBUG] User {user_id}: сбросили used для всех товаров")

                if allowed_sources:
                    product = conn.execute(query, (user_id, *allowed_sources, min_discount)).fetchone()
                else:
                    product = conn.execute(
                        "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND erid != '' AND erid IS NOT NULL AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                        (user_id, min_discount)
                    ).fetchone()

            if product:
                conn.execute("UPDATE gdeslon_catalog SET used = 1 WHERE id = ?", (product["id"],))
                conn.commit()
                logger.info(f"[DEBUG] User {user_id}: выбран товар id={product['id']}, source={product['source']}")
            else:
                logger.info(f"[DEBUG] User {user_id}: товар не найден после сброса used")
        finally:
            conn.close()

        if not product:
            logger.info(f"[DEBUG] User {user_id}: нет доступных товаров")
            if role == "blogger":
                logger.info(f"[DEBUG] User {user_id}: запускаем экстренное пополнение каталога")
                from services.admitad import fetch_admitad_catalog_for_user
                await fetch_admitad_catalog_for_user(user_id, max_items_per_store=100)
            continue

        if role == "blogger":
            conn = get_db()
            try:
                remaining = conn.execute("SELECT COUNT(*) FROM gdeslon_catalog WHERE user_id = ? AND used = 0", (user_id,)).fetchone()[0]
                if remaining < 20:
                    logger.info(f"[DEBUG] User {user_id}: мало товаров ({remaining}), запускаем пополнение")
                    from services.admitad import fetch_admitad_catalog_for_user
                    await fetch_admitad_catalog_for_user(user_id, max_items_per_store=100)
            finally:
                conn.close()

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
            subid2 = generate_subid2(user_id, ch["channel_id"])
            if '?' in final_url:
                final_url += '&subid2=' + subid2
            else:
                final_url += '?subid2=' + subid2

            adult = source in ADULT_STORES
            delivery_info = get_delivery_for_store(source)
            promocode = get_random_promocode(source)
            
            # Особые условия для Moulinex
            if source == "Moulinex":
                delivery_info = "🚚 Бесплатная доставка от 3000₽ | 1-3 дня"
                if not (product["price"] or 0) >= 3000:
                    delivery_info += "\n⚠️ Для кэшбэка минимальный заказ 3000₽"

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
                            (user_id, donor_post_id, channel_id, target_channel_id, subid1, subid2, direct_link, erid, status, published_at, caption, auto_delete_hours)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?)""",
                            (user_id, donor_post_id, ch['channel_id'], ch['channel_id'], ch['sub_id'], subid2, direct_link,
                             erid, datetime.now(timezone.utc).isoformat(), caption, auto_delete_hours)
                        )
                        conn_rec.commit()
                        logger.info(f"[DEBUG] Опубликовано в {ch['channel_id']}, post_id={msg.message_id}")
                        # Помечаем расписание как опубликованное
                        try:
                            conn_sched = get_db()
                            conn_sched.execute(
                                "UPDATE post_schedules SET is_posted=1 WHERE user_id=? AND target_type='store' AND target_id=? AND post_date=? AND post_time<=? AND is_posted=0",
                                (user_id, scheduled_store_id, today_str, current_time)
                            )
                            conn_sched.commit()
                            conn_sched.close()
                        except Exception:
                            pass
                        await pin_post_if_enabled(bot, user_id, ch["channel_id"], msg.message_id)
                        try:
                            conn_chk = get_db()
                            try:
                                row = conn_chk.execute("SELECT notify_posts FROM users WHERE user_id=?", (user_id,)).fetchone()
                                do_notify = row["notify_posts"] if row else 1
                            finally:
                                conn_chk.close()
                            if do_notify:
                                channel_title = ch['channel_id'].lstrip('@')
                                await bot.send_message(
                                    user_id,
                                    f"✅ Пост опубликован в <b>{channel_title}</b>\n"
                                    f"📦 {title}\n"
                                    f"💰 {price} {currency}\n"
                                    f"<a href='{direct_link}'>Открыть пост</a>",
                                    parse_mode="HTML",
                                    disable_web_page_preview=True
                                )
                        except Exception:
                            pass
                    finally:
                        conn_rec.close()
                    if cyclic_store_id:
                        try:
                            conn_cyc = get_db()
                            conn_cyc.execute(
                                "UPDATE cyclic_schedules SET last_posted_at = ? WHERE user_id = ? AND store_id = ?",
                                (datetime.now(timezone.utc).isoformat(), user_id, cyclic_store_id)
                            )
                            conn_cyc.commit()
                            conn_cyc.close()
                        except Exception:
                            pass
                else:
                    logger.warning(f"[DEBUG] Не удалось опубликовать в {ch['channel_id']}")
            except Exception as e:
                logger.error(f"[DEBUG] Ошибка публикации в {ch['channel_id']}: {e}")
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

async def pin_post_if_enabled(bot: Bot, user_id: int, channel_id: str, message_id: int, pin_duration_hours: int = 24):
    """
    Закрепляет пост в канале, если у пользователя включён auto_pin.
    По умолчанию закрепляет на 24 часа (можно настроить).
    """
    conn = get_db()
    try:
        user = conn.execute("SELECT auto_pin FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user or not user["auto_pin"]:
            return
        
        # Закрепляем сообщение
        await bot.pin_chat_message(chat_id=channel_id, message_id=message_id)
        
        # Записываем время открепления
        unpin_at = datetime.now(timezone.utc) + timedelta(hours=pin_duration_hours)
        conn.execute(
            "INSERT INTO pinned_posts (chat_id, message_id, unpin_at) VALUES (?, ?, ?)",
            (channel_id, message_id, unpin_at.isoformat())
        )
        conn.commit()
        logger.info(f"Пост {message_id} закреплён в канале {channel_id} до {unpin_at}")
    except Exception as e:
        logger.error(f"Ошибка закрепления поста {message_id} в {channel_id}: {e}")
    finally:
        conn.close()


async def publish_cpc_campaigns(bot: Bot):
    if is_night_time():
        return

    import re as _re
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")

    conn = get_db()
    try:
        scheduled = conn.execute(
            "SELECT user_id, target_id, post_time FROM post_schedules WHERE target_type='campaign' AND post_date=? AND is_posted=0",
            (today_str,)
        ).fetchall()
    finally:
        conn.close()

    if not scheduled:
        return

    campaigns_to_post = []
    for sched in scheduled:
        if sched["post_time"] > current_time:
            continue
        user_id = sched["user_id"]
        campaign_id = sched["target_id"]
        conn = get_db()
        try:
            row = conn.execute("""
                SELECT cpc.id, cpc.user_id, cpc.campaign_id, cpc.name, cpc.cpc_link,
                       cpc.text, cpc.image_url, cpc.description,
                       u.cpc_banned,
                       ch.channel_id, ch.sub_id, ch.channel_title
                FROM cpc_campaigns cpc
                JOIN users u ON u.user_id = cpc.user_id
                JOIN channels ch ON ch.user_id = cpc.user_id
                WHERE cpc.is_active = 1
                  AND u.is_active = 1
                  AND u.cpc_banned = 0
                  AND cpc.user_id = ?
                  AND cpc.id = ?
            """, (user_id, campaign_id)).fetchone()
        finally:
            conn.close()
        if row:
            campaigns_to_post.append(row)

    if not campaigns_to_post:
        return

    posted_ids = set()
    for row in campaigns_to_post:
        user_id = row["user_id"]
        cpc_id = row["id"]
        channel_id = row["channel_id"]
        sub_id = row["sub_id"] or ""
        cpc_link = row["cpc_link"]
        text_template = row["text"] or ""
        description = row["description"] or ""
        name = row["name"]
        image_url = row["image_url"] or ""
        ch_title = row["channel_title"] or channel_id

        if not cpc_link or not channel_id:
            continue

        # Получаем CPC-шаблон пользователя
        cpc_template = None
        auto_delete_hours = 168
        try:
            c = get_db()
            try:
                u_row = c.execute(
                    "SELECT cpc_template, default_auto_delete_hours FROM users WHERE user_id=?", (user_id,)
                ).fetchone()
                if u_row:
                    cpc_template = u_row["cpc_template"]
                    if u_row["default_auto_delete_hours"] is not None:
                        auto_delete_hours = u_row["default_auto_delete_hours"]
            finally:
                c.close()
        except Exception:
            pass

        subid2 = generate_subid2(user_id, channel_id)
        separator = "&" if "?" in cpc_link else "?"
        final_url = f"{cpc_link}{separator}subid1={sub_id}&subid2={subid2}"

        erid_match = _re.search(r'erid=([^&]+)', final_url)
        erid_value = erid_match.group(1) if erid_match else ""

        if not erid_value:
            logger.warning(f"CPC авто-пост без ERID: campaign={campaign_id} name={name!r} user={user_id}")
            continue

        hidden_link = f"<a href='{final_url}'>Перейти</a>"

        if cpc_template:
            post_text = cpc_template
        elif text_template:
            post_text = text_template
        elif description:
            post_text = "👆 {name}\n\n{description}\n\n{link}"
        else:
            post_text = "👆 {name}\n\n{link}"

        post_text = post_text.replace("{name}", name)
        post_text = post_text.replace("{description}", description)

        if "{link}" in post_text:
            post_text = post_text.replace("{link}", hidden_link)
        else:
            post_text = post_text.rstrip() + f"\n\n{hidden_link}"

        reklama_line = f"Реклама. {name}. Erid: {erid_value}" if erid_value else ""
        post_text = f"{post_text}\n\n{reklama_line}"

        if len(post_text) > 1024:
            idx = post_text.rfind(hidden_link)
            if idx > 0:
                safe = post_text[idx:]
                head = post_text[:1024 - len(safe) - 3].rstrip()
                post_text = head + "...\n\n" + safe

        try:
            cpc_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Перейти", url=final_url)]
            ])
            msg = await publish_post_with_fallback(
                bot=bot, channel_id=channel_id,
                caption=post_text, photo_url=image_url,
                reply_markup=cpc_kb, parse_mode="HTML",
            )
            if not msg:
                logger.error(f"❌ CPC пост '{name}' → {ch_title}: publish_post_with_fallback вернул None")
                continue

            logger.info(f"✅ CPC пост '{name}' отправлен в {ch_title} (user {user_id})")

            direct_link = f"https://t.me/{channel_id.lstrip('@')}/{msg.message_id}"

            donor_post_id = f"cpc_{cpc_id}_{user_id}_{int(datetime.now(timezone.utc).timestamp())}"
            c = get_db()
            try:
                c.execute(
                    "INSERT INTO posts (user_id, donor_post_id, channel_id, status, published_at, auto_delete_hours, caption, direct_link) "
                    "VALUES (?, ?, ?, 'published', ?, ?, ?, ?)",
                    (user_id, donor_post_id, channel_id, datetime.now(timezone.utc).isoformat(),
                     auto_delete_hours, post_text, direct_link)
                )
                c.commit()
            finally:
                c.close()

            if cpc_id not in posted_ids:
                posted_ids.add(cpc_id)
                c = get_db()
                try:
                    c.execute("UPDATE cpc_campaigns SET last_posted_at=datetime('now'), times_posted=times_posted+1 WHERE id=?", (cpc_id,))
                    c.execute(
                        "UPDATE post_schedules SET is_posted=1 WHERE user_id=? AND target_type='campaign' AND target_id=? AND post_date=? AND post_time<=? AND is_posted=0",
                        (user_id, cpc_id, today_str, current_time)
                    )
                    c.commit()
                finally:
                    c.close()

        except Exception as e:
            logger.error(f"❌ CPC пост '{name}' → {ch_title}: {e}")
