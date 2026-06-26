# services/admitad.py
import asyncio
import hashlib
import logging
from urllib.parse import urlparse, parse_qs
from xml.etree.ElementTree import XMLPullParser
import httpx
from services.db import get_db

logger = logging.getLogger("autopost_bot.admitad")

# Список магазинов с их фидами и признаком 18+
STORES = {
    "Читай-город": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=24883&last_import=",
        "adult": False
    },
    "Аквафор": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=18482&last_import=",
        "adult": False
    },
    "Розовый кролик": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=26654&last_import=",
        "adult": True
    },
    "Hi Store RU": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=25803&last_import=",
        "adult": False
    },
    "KANZLER": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=25851&last_import=",
        "adult": False
    },
    "KIKO MILANO": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=15202&last_import=",
        "adult": False
    },
    "Moulinex": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=25773&last_import=",
        "adult": False
    },
    "Playtoday": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=26222&last_import=",
        "adult": False
    },
    "SELA": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=24700&last_import=",
        "adult": False
    },
}
def extract_erid_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        return params.get('erid', [''])[0]
    except Exception:
        return ""

async def fetch_admitad_catalog(user_id: int, max_items_per_store: int = 50) -> int:
    saved = 0
    conn = get_db()

    for store_name, store_cfg in STORES.items():
        feed_url = store_cfg["feed_url"]
        store_saved = 0
        parser = XMLPullParser(['end'])   # новый парсер для каждого магазина
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("GET", feed_url) as resp:
                    if resp.status_code != 200:
                        logger.error(f"Admitad фид {store_name} недоступен: {resp.status_code}")
                        continue

                    async for chunk in resp.aiter_bytes():
                        try:
                            parser.feed(chunk)
                        except Exception as parse_error:
                            # Пропускаем битый кусок и продолжаем
                            logger.warning(f"Ошибка парсинга XML в {store_name}: {parse_error}")
                            continue

                        for event, elem in parser.read_events():
                            if elem.tag == 'offer':
                                name = elem.findtext('name', '')
                                price = float(elem.findtext('price', '0'))
                                currency = elem.findtext('currencyId', 'RUR')
                                picture = elem.findtext('picture', '')
                                url = elem.findtext('url', '')
                                if not url:
                                    elem.clear()
                                    continue

                                erid = extract_erid_from_url(url)
                                if not erid:
                                    elem.clear()
                                    continue

                                sku = hashlib.md5(url.encode()).hexdigest()[:12]
                                conn.execute(
                                    """INSERT OR IGNORE INTO gdeslon_catalog
                                    (sku, user_id, title, price, currency, partner_url, erid, advertiser, image_url, category_keyword, used, source)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                                    (sku, user_id, name, price, currency, url, erid, store_name, picture, store_name, store_name)
                                )
                                store_saved += 1
                                elem.clear()
                                if store_saved >= max_items_per_store:
                                    await resp.aclose()
                                    break
                        if store_saved >= max_items_per_store:
                            break
        except Exception as e:
            logger.error(f"Admitad stream error for {store_name}: {e}")

        saved += store_saved
        logger.info(f"  {store_name}: добавлено {store_saved} товаров")

    conn.commit()
    conn.close()
    logger.info(f"Admitad: всего добавлено {saved} товаров для user {user_id}")
    return saved


async def refill_admitad_catalogs(bot=None):
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
        await fetch_admitad_catalog(user["user_id"], max_items_per_store=50)
        await asyncio.sleep(1)

    logger.info("🔄 Пополнение каталогов Admitad завершено")
