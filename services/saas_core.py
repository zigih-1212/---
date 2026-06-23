# services/saas_core.py
import asyncio
import hashlib
import logging
import os
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, Message

from services.db import get_db
from parser import rewrite_text_with_ai, find_product_links, process_new_video

logger = logging.getLogger("autopost_bot")

# ---------------------------------------------------------------------------
# Вспомогательные (общие)
# ---------------------------------------------------------------------------
def get_wb_image_url(sku: int) -> str:
    """Вычисляет прямую ссылку на фото Wildberries по артикулу (SKU)."""
    try:
        sku = int(sku)
    except (ValueError, TypeError):
        return ""

    vol = sku // 100000
    part = sku // 1000

    if 0 <= vol <= 143:
        host = "basket-01.wbbasket.ru"
    elif 144 <= vol <= 287:
        host = "basket-02.wbbasket.ru"
    elif 288 <= vol <= 431:
        host = "basket-03.wbbasket.ru"
    elif 432 <= vol <= 719:
        host = "basket-04.wbbasket.ru"
    elif 720 <= vol <= 1007:
        host = "basket-05.wbbasket.ru"
    elif 1008 <= vol <= 1061:
        host = "basket-06.wbbasket.ru"
    elif 1062 <= vol <= 1115:
        host = "basket-07.wbbasket.ru"
    elif 1116 <= vol <= 1169:
        host = "basket-08.wbbasket.ru"
    elif 1170 <= vol <= 1313:
        host = "basket-09.wbbasket.ru"
    elif 1314 <= vol <= 1601:
        host = "basket-10.wbbasket.ru"
    elif 1602 <= vol <= 1655:
        host = "basket-11.wbbasket.ru"
    elif 1656 <= vol <= 1919:
        host = "basket-12.wbbasket.ru"
    elif 1920 <= vol <= 2045:
        host = "basket-13.wbbasket.ru"
    elif 2046 <= vol <= 2189:
        host = "basket-14.wbbasket.ru"
    elif 2190 <= vol <= 2405:
        host = "basket-15.wbbasket.ru"
    elif 2406 <= vol <= 2621:
        host = "basket-16.wbbasket.ru"
    elif 2622 <= vol <= 2837:
        host = "basket-17.wbbasket.ru"
    elif 2838 <= vol <= 3053:
        host = "basket-18.wbbasket.ru"
    elif 3054 <= vol <= 3269:
        host = "basket-19.wbbasket.ru"
    else:
        host = "basket-20.wbbasket.ru"

    return f"https://{host}/vol{vol}/part{part}/{sku}/images/big/1.webp"


async def download_image(url: str) -> Optional[bytes]:
    if not url or not url.startswith("http"):
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
# GdeSlon / ТакПродам API
# ---------------------------------------------------------------------------
async def fetch_gdeslon_catalog(user_id: int, keyword: str, limit: int = 50) -> int:
    token = os.getenv("GDESLON_API_KEY", "")
    if not token:
        return 0
    page = random.randint(1, 5)
    url = f"https://www.gdeslon.ru/api/search.xml?q={keyword}&l={limit}&p={page}&order=newest&_gs_at={token}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return 0
        root = ET.fromstring(resp.text)
        offers = root.findall('.//offer')
        saved = 0
        conn = get_db()
        for offer in offers:
            partner_url = (offer.findtext('url') or '').strip()
            if not partner_url:
                continue
            # Извлекаем erid, гарантируем, что переменная существует
            erid = ''
            if 'erid=' in partner_url:
                erid = partner_url.split('erid=')[-1].split('&')[0]
            # Пропускаем товары без ERID (чтобы не засорять каталог)
            if not erid:
                continue
            sku = hashlib.md5(partner_url.encode()).hexdigest()[:12]
            name = offer.findtext('name', 'Товар')
            price = float(offer.findtext('price', '0'))
            currency = offer.findtext('currencyId', 'RUR')
            picture = offer.findtext('picture', '')
            vendor = offer.findtext('vendor', '') or 'Рекламодатель'
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO gdeslon_catalog (sku, user_id, title, price, currency, partner_url, erid, advertiser, image_url, category_keyword) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (sku, user_id, name, price, currency, partner_url, erid, vendor, picture or '', keyword)
                )
                saved += 1
            except Exception as e:
                logger.warning(f"Gdeslon insert error: {e}")
        conn.commit()
        conn.close()
        logger.info(f"Gdeslon: добавлено {saved} товаров для user {user_id} по ключу '{keyword}'")
        return saved
    except Exception as e:
        logger.error(f"fetch_gdeslon_catalog error: {e}")
        return 0


async def fetch_gdeslon_by_sku(sku: str) -> Optional[Dict[str, str]]:
    token = os.getenv("GDESLON_API_KEY", "")
    if not token:
        return None
    url = f"https://www.gdeslon.ru/api/search.xml?articles={sku}&l=1&_gs_at={token}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        root = ET.fromstring(resp.text)
        offers = root.findall('.//offer')
        if not offers:
            return None
        offer = offers[0]
        name = offer.findtext('name', '')
        price = offer.findtext('price', '')
        currency = offer.findtext('currencyId', 'RUB')
        picture = offer.findtext('picture', '')
        url_elem = offer.find('url')
        partner_url = url_elem.text if url_elem is not None else ''
        erid = ''
        if 'erid=' in partner_url:
            erid = partner_url.split('erid=')[-1].split('&')[0]
        shop_name = offer.findtext('shop_name', '') or offer.findtext('merchant', '') or 'Рекламодатель'
        if partner_url:
            return {
                "link": partner_url,
                "erid": erid,
                "advertiser": shop_name,
                "image_url": picture or "",
                "title": name,
                "price": price,
                "currency": currency,
            }
    except Exception as e:
        logger.error(f"GdeSlon API error for SKU {sku}: {e}")
    return None


async def fetch_takprodam_by_sku(token: str, sku: str) -> Optional[Dict[str, str]]:
    if not token:
        return None
    url = "https://api.takprodam.ru/v1/products/info"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params={"sku": sku})
        if resp.status_code != 200:
            logger.warning(f"ТакПродам API: статус {resp.status_code} для SKU {sku}")
            return None
        data = resp.json()
        link = data.get("link", "")
        erid = data.get("erid", "").strip()
        advertiser = data.get("advertiser", "").strip()
        image_url = data.get("image") or data.get("photo") or ""
        if not erid or not advertiser:
            logger.warning(f"ТакПродам: неполные данные для SKU {sku}: {data}")
            return None
        return {"link": link, "erid": erid, "advertiser": advertiser, "image_url": image_url}
    except Exception as e:
        logger.error(f"Ошибка при запросе к ТакПродам для SKU {sku}: {e}")
        return None


async def get_source_id(token: str) -> Optional[int]:
    conn = get_db()
    try:
        cached = conn.execute("SELECT source_id FROM takprodam_sources WHERE token = ?", (token,)).fetchone()
        if cached:
            return cached["source_id"]
    finally:
        conn.close()

    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.takprodam.ru/v2/publisher/source/", headers=headers)
        if resp.status_code == 200:
            sources = resp.json().get("items", [])
            if sources:
                source_id = sources[0]["id"]
                conn = get_db()
                conn.execute("INSERT OR REPLACE INTO takprodam_sources (token, source_id) VALUES (?, ?)", (token, source_id))
                conn.commit()
                conn.close()
                return source_id
    except Exception as e:
        logger.error(f"get_source_id error: {e}")
    return None


async def resolve_erid(
    bot: Bot, user_id: int, url: str,
    donor_post_id: str = "unknown", channel_id: str = "unknown"
) -> Optional[Dict[str, str]]:
    db = get_db()
    try:
        row = db.execute("SELECT api_key, client_erid_override FROM users WHERE user_id = ?", (user_id,)).fetchone()
    finally:
        db.close()

    if not row:
        return None

    api_key = row["api_key"] or ""
    override_erid = (row["client_erid_override"] or "").strip()

    erid = None
    advertiser = None
    partner_link = None
    image_url = None

    async def try_deeplink(token: str):
        nonlocal erid, advertiser, partner_link, image_url
        source_id = await get_source_id(token)
        if not source_id:
            return
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"source_id": source_id, "target_url": url}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.takprodam.ru/v2/publisher/deeplink/",
                    headers=headers,
                    json=payload
                )
            if resp.status_code == 200:
                data = resp.json()
                partner_link = data.get("tracking_link") or data.get("link") or partner_link
                erid = (data.get("erid") or "").strip() or erid
                advertiser = (data.get("advertiser") or "").strip() or advertiser
                image_url = data.get("image_url") or data.get("image") or image_url
            else:
                logger.warning(f"Deeplink API error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Deeplink API exception: {e}")

    if api_key:
        await try_deeplink(api_key)
    if not erid and os.getenv("TAKPRODAM_MASTER_TOKEN", "") and os.getenv("TAKPRODAM_MASTER_TOKEN") != api_key:
        await try_deeplink(os.getenv("TAKPRODAM_MASTER_TOKEN"))
    if not erid and override_erid:
        erid = override_erid

    if erid:
        return {
            "link": partner_link or url,
            "erid": erid,
            "advertiser": advertiser or "Рекламодатель",
            "image_url": image_url or ""
        }
    return None

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
    from config import is_night_time  # временно, позже вынесем

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

    erid_data = None
    if sku:
        erid_data = await fetch_gdeslon_by_sku(sku)

    if erid_data and erid_data.get("erid"):
        final_link = erid_data["link"]
        advertiser = erid_data["advertiser"]
        erid = erid_data["erid"]
        legal_block = f"<i>Реклама. {advertiser}. Erid: {erid}</i>"
    else:
        if url:
            final_link = url
        elif sku:
            if marketplace == "WB":
                final_link = f"https://www.wildberries.ru/catalog/{sku}/detail.aspx"
            else:
                final_link = f"https://www.ozon.ru/product/{sku}/"
        else:
            final_link = None
        legal_block = ""

    if final_link:
        link_block = f"👉 <a href='{final_link}'>Посмотреть и заказать</a>"
    else:
        link_block = "👉 <i>Ссылка временно недоступна</i>"

    post_html = (
        f"{clean_rewritten}\n\n"
        f"🛒 <b>Артикул:</b> <code>{sku or 'не указан'}</code>\n\n"
        f"{link_block}\n\n"
        f"{legal_block}"
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
        # donor_post_id используется только для вызова process_saas_core
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
    from config import is_night_time
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
                "SELECT COUNT(*) as cnt FROM posts WHERE user_id = ? AND status = 'published' AND published_at >= ? AND donor_post_id LIKE 'gdeslon_%'",
                (user_id, hour_ago)
            ).fetchone()["cnt"]
        finally:
            conn.close()

        if posts_last_hour >= max_posts_per_hour:
            continue

        conn = get_db()
        try:
            # Сначала пробуем товар с ERID
            product = conn.execute(
                "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL ORDER BY RANDOM() LIMIT 1",
                (user_id,)
            ).fetchone()
            # Если нет ни одного товара с ERID, берём любой неиспользованный
            if not product:
                product = conn.execute(
                    "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 ORDER BY RANDOM() LIMIT 1",
                    (user_id,)
                ).fetchone()
            # Если и таких нет (все использованы), сбрасываем used и пробуем снова (сначала с ERID)
            if not product:
                conn.execute("UPDATE gdeslon_catalog SET used = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
                # После сброса опять приоритет ERID
                product = conn.execute(
                    "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND erid != '' AND erid IS NOT NULL ORDER BY RANDOM() LIMIT 1",
                    (user_id,)
                ).fetchone()
                if not product:
                    product = conn.execute(
                        "SELECT * FROM gdeslon_catalog WHERE user_id = ? ORDER BY RANDOM() LIMIT 1",
                        (user_id,)
                    ).fetchone()
            if product:
                conn.execute("UPDATE gdeslon_catalog SET used = 1 WHERE id = ?", (product["id"],))
                conn.commit()
        finally:
            conn.close()

        if not product:
            continue

        # Проверяем обязательные поля
        partner_url = (product['partner_url'] or '').strip()
        title = (product['title'] or '').strip()
        price = product['price'] or 0
        currency = product['currency'] or '₽'
        advertiser = product['advertiser'] or 'Рекламодатель'
        erid = (product['erid'] or '').strip()

        # Если нет ссылки – удаляем товар из каталога и пропускаем
        if not partner_url:
            conn = get_db()
            try:
                conn.execute("DELETE FROM gdeslon_catalog WHERE id = ?", (product["id"],))
                conn.commit()
            finally:
                conn.close()
            continue

        # Пропускаем товары без ERID
        if not erid:
            continue

        # Формируем пост
        caption = f"{title}\n\n"
        if price > 0:
            caption += f"💰 Цена: {price} {currency}\n\n"
        caption += f"👉 <a href='{partner_url}'>Посмотреть и заказать</a>\n\n"
        if erid:
            caption += f"Реклама. {advertiser}. Erid: {erid}"
        else:
            caption += f"Реклама. {advertiser}"

        photo_url = product["image_url"]

        # Публикуем в каналы пользователя
        conn = get_db()
        try:
            channels = conn.execute(
                "SELECT channel_id FROM channels WHERE user_id = ? AND is_active = 1",
                (user_id,)
            ).fetchall()
        finally:
            conn.close()

        for ch in channels:
            await publish_post_with_fallback(
                bot=bot,
                channel_id=ch["channel_id"],
                caption=caption,
                photo_url=photo_url
            )
            await asyncio.sleep(1)


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
                    photo_url = get_wb_image_url(prepared["sku"])
                if not photo_url and post.get("image_url"):
                    photo_url = post["image_url"]
                if not photo_url and prepared and prepared.get("sku") and os.getenv("TAKPRODAM_MASTER_TOKEN"):
                    try:
                        product_data = await fetch_takprodam_by_sku(os.getenv("TAKPRODAM_MASTER_TOKEN"), prepared["sku"])
                        if product_data and product_data.get("image_url"):
                            photo_url = product_data["image_url"]
                    except Exception:
                        pass
                if not photo_url and prepared and prepared.get("sku") and prepared.get("marketplace") == "WB":
                    sku = prepared["sku"]
                    vol = int(sku) // 100000
                    part = int(sku) // 1000
                    photo_url = f"https://basket-01.wbbasket.ru/vol{vol}/part{part}/{sku}/images/big/1.webp"

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
async def refill_all_catalogs(bot: Bot):
    """Раз в 30 минут пополняет каталог GdeSlon для всех активных SaaS-клиентов."""
    conn = get_db()
    try:
        users = conn.execute("""
            SELECT u.user_id
            FROM users u
            WHERE u.role = 'saas' AND u.is_active = 1
            AND u.subscription_until > datetime('now')
        """).fetchall()
    finally:
        conn.close()

    for user in users:
        user_id = user["user_id"]
        conn = get_db()
        try:
            cats = conn.execute("""
                SELECT pc.keyword FROM product_categories pc
                JOIN user_category_preferences ucp ON pc.id = ucp.category_id
                WHERE ucp.user_id = ?
            """, (user_id,)).fetchall()
        finally:
            conn.close()

        if not cats:
            continue

        for cat in cats:
            await fetch_gdeslon_catalog(user_id, cat["keyword"], limit=5)
            await asyncio.sleep(1)

async def fetch_takprodam_catalog(user_id: int, limit: int = 20) -> int:
    """Пополняет каталог товарами из ТакПродам через v2/publisher/product."""
    token = os.getenv("TAKPRODAM_MASTER_TOKEN", "")
    if not token:
        return 0

    headers = {"Authorization": f"Bearer {token}"}
    source_id = None
    conn = get_db()
    try:
        row = conn.execute("SELECT source_id FROM takprodam_sources WHERE token = ?", (token,)).fetchone()
        if row:
            source_id = row["source_id"]
    finally:
        conn.close()

    if not source_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://api.takprodam.ru/v2/publisher/source/", headers=headers)
            if resp.status_code == 200:
                sources = resp.json().get("items", [])
                if sources:
                    source_id = sources[0]["id"]
                    conn = get_db()
                    conn.execute("INSERT OR REPLACE INTO takprodam_sources (token, source_id) VALUES (?, ?)", (token, source_id))
                    conn.commit()
                    conn.close()
        except Exception as e:
            logger.error(f"get_source_id error: {e}")
            return 0

    if not source_id:
        return 0

    saved = 0
    # Запрашиваем по одному запросу для WB и Ozon с page=1 и лимитом = limit/2
    for marketplace in ("Wildberries", "Ozon"):
        params = {
            "source_id": source_id,
            "marketplace": marketplace,
            "limit": max(5, limit // 2),
            "page": 1
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get("https://api.takprodam.ru/v2/publisher/product/", headers=headers, params=params)
            if resp.status_code != 200:
                logger.warning(f"ТакПродам v2 product {marketplace}: статус {resp.status_code}, ответ: {resp.text[:200]}")
                continue
            data = resp.json()
            products = data.get("results", [])
            conn = get_db()
            for p in products:
                erid = (p.get("erid") or "").strip()
                if not erid:
                    continue
                advertiser = (p.get("advertiser") or "").strip()
                title = p.get("title") or "Товар"
                price = float(p.get("price", 0))
                tracking_link = p.get("tracking_link") or ""
                image_url = p.get("image_url") or ""
                sku = p.get("sku") or hashlib.md5(tracking_link.encode()).hexdigest()[:12]
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO gdeslon_catalog
                        (sku, user_id, title, price, currency, partner_url, erid, advertiser, image_url, category_keyword, used, source)
                        VALUES (?, ?, ?, ?, 'RUB', ?, ?, ?, ?, 'takprodam_general', 0, 'takprodam')""",
                        (sku, user_id, title, price, tracking_link, erid, advertiser, image_url)
                    )
                    saved += 1
                except Exception as e:
                    logger.warning(f"ТакПродам insert error: {e}")
            conn.commit()
            conn.close()
            # Задержка, чтобы избежать 429
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"ТакПродам v2 request error: {e}")

    logger.info(f"ТакПродам: добавлено {saved} товаров для user {user_id}")
    return saved
async def refill_takprodam_catalogs(bot: Bot):
    """Периодически пополняет каталог ТакПродам для всех активных SaaS-клиентов (без привязки к категориям)."""
    conn = get_db()
    try:
        users = conn.execute("""
            SELECT u.user_id
            FROM users u
            WHERE u.role = 'saas' AND u.is_active = 1
            AND u.subscription_until > datetime('now')
        """).fetchall()
    finally:
        conn.close()

    for user in users:
        user_id = user["user_id"]
        await fetch_takprodam_catalog(user_id, limit=30)
        await asyncio.sleep(1)

    logger.info("🔄 Пополнение каталогов ТакПродам завершено")

    
    logger.info("🔄 Пополнение каталогов GdeSlon завершено")
