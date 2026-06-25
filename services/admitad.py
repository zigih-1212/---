# services/admitad.py
import asyncio
import hashlib
import logging
from xml.etree import ElementTree as ET
import httpx
from services.db import get_db

logger = logging.getLogger("autopost_bot.admitad")

FEED_URL = "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=14107&last_import="

async def fetch_admitad_catalog(user_id: int) -> int:
    """Скачивает XML-фид Admitad и сохраняет товары с ERID."""
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(FEED_URL)
        if resp.status_code != 200:
            logger.error(f"Admitad фид недоступен: {resp.status_code}")
            return 0
        root = ET.fromstring(resp.text)
        offers = root.findall('.//offer')
        saved = 0
        conn = get_db()
        for offer in offers:
            name = offer.findtext('name', '')
            price = float(offer.findtext('price', '0'))
            currency = offer.findtext('currencyId', 'RUB')
            picture = offer.findtext('picture', '')
            url = offer.findtext('url', '')
            if not url:
                continue
            erid = ''
            for param in offer.findall('param'):
                if param.get('name') == 'erid':
                    erid = param.text or ''
                    break
            if not erid:
                continue
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
        await fetch_admitad_catalog(user["user_id"])
        await asyncio.sleep(1)
    logger.info("🔄 Пополнение каталогов Admitad завершено")
