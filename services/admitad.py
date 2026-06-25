# services/admitad.py
import asyncio
import hashlib
import logging
from datetime import datetime
from xml.etree.ElementTree import XMLPullParser

import httpx

from services.db import get_db

logger = logging.getLogger("autopost_bot.admitad")

# Прямая ссылка на фид (AliExpress)
FEED_URL = "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=14107&last_import="


async def fetch_admitad_catalog(user_id: int, max_items: int = 20) -> int:
    """
    Потоково скачивает XML-фид Admitad, извлекает товары с ERID,
    останавливается после max_items товаров. Не загружает весь фид в память.
    """
    saved = 0
    conn = get_db()

    try:
        parser = XMLPullParser(['end'])

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("GET", FEED_URL) as resp:
                if resp.status_code != 200:
                    logger.error(f"Admitad фид недоступен: {resp.status_code}")
                    return 0

                async for chunk in resp.aiter_bytes():
                    parser.feed(chunk)

                    for event, elem in parser.read_events():
                        if elem.tag == 'offer':
                            # Извлекаем данные
                            name = elem.findtext('name', '')
                            price = float(elem.findtext('price', '0'))
                            currency = elem.findtext('currencyId', 'RUB')
                            picture = elem.findtext('picture', '')
                            url = elem.findtext('url', '')
                            if not url:
                                elem.clear()
                                continue

                            # ERID
                            erid = ''
                            for param in elem.findall('param'):
                                if param.get('name') == 'erid':
                                    erid = param.text or ''
                                    break
                            if not erid:
                                elem.clear()
                                continue

                            # Сохраняем в БД
                            sku = hashlib.md5(url.encode()).hexdigest()[:12]
                            try:
                                conn.execute(
                                    """INSERT OR IGNORE INTO gdeslon_catalog
                                    (sku, user_id, title, price, currency, partner_url, erid, advertiser, image_url, category_keyword, used, source)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, 'Admitad', ?, 'admitad_general', 0, 'admitad')""",
                                    (sku, user_id, name, price, currency, url, erid, picture)
                                )
                                saved += 1
                            except Exception as e:
                                logger.warning(f"Admitad insert error: {e}")

                            # Очищаем элемент из памяти
                            elem.clear()

                            if saved >= max_items:
                                # Прерываем: закрываем поток досрочно
                                await resp.aclose()
                                break

        conn.commit()
        conn.close()
        logger.info(f"Admitad: добавлено {saved} товаров для user {user_id}")
        return saved

    except Exception as e:
        logger.error(f"Admitad error: {e}")
        return 0


async def refill_admitad_catalogs(bot=None):
    """Периодически пополняет каталог Admitad для всех активных SaaS-клиентов."""
    conn = get_db()
    try:
        users = conn.execute("""
            SELECT user_id FROM users
            WHERE role = 'saas' AND is_active = 1
            AND subscription_until > datetime('now')
        """).fetchall()
    finally:
        conn.close()

    for user in users:
        await fetch_admitad_catalog(user["user_id"], max_items=20)
        await asyncio.sleep(1)

    logger.info("🔄 Пополнение каталогов Admitad завершено")
