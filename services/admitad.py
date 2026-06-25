# services/admitad.py
import asyncio
import hashlib
import logging
from datetime import datetime
from xml.etree import ElementTree as ET

import httpx

from services.db import get_db

logger = logging.getLogger("autopost_bot.admitad")

FEED_URL = "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=14107&last_import="


async def fetch_admitad_catalog(user_id: int, max_items: int = 10) -> int:
    """Потоково скачивает фид Admitad, парсит первые max_items товаров с ERID и сохраняет."""
    try:
        last_import = ""
        try:
            with open("/tmp/admitad_last_import.txt", "r") as f:
                last_import = f.read().strip()
        except FileNotFoundError:
            last_import = "2025-01-01T00:00:00"

        full_url = FEED_URL + last_import
        logger.info(f"Admitad: начинаю загрузку фида с {last_import}")

        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            # stream=True для потоковой загрузки
            async with client.stream("GET", full_url) as resp:
                if resp.status_code != 200:
                    logger.error(f"Admitad фид недоступен: {resp.status_code}")
                    return 0

                # Потоково читаем XML
                saved = 0
                conn = get_db()
                # iterparse для потокового парсинга
                context = ET.iterparse(resp.aiter_bytes(), events=("end",))
                for event, elem in context:
                    if elem.tag == "offer":
                        # Извлекаем данные из offer
                        name = elem.findtext("name", "")
                        price = float(elem.findtext("price", "0"))
                        currency = elem.findtext("currencyId", "RUB")
                        picture = elem.findtext("picture", "")
                        url = elem.findtext("url", "")
                        if url:
                            erid = ""
                            for param in elem.findall("param"):
                                if param.get("name") == "erid":
                                    erid = param.text or ""
                                    break
                            if erid:
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
                        # Очищаем элемент, чтобы не засорять память
                        elem.clear()
                        if saved >= max_items:
                            break  # Достигли лимита, прерываем парсинг
                conn.commit()
                conn.close()

        # Сохраняем время последнего импорта
        with open("/tmp/admitad_last_import.txt", "w") as f:
            f.write(datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"))

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
        await fetch_admitad_catalog(user["user_id"], max_items=10)
        await asyncio.sleep(1)

    logger.info("🔄 Пополнение каталогов Admitad завершено")
