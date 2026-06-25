# services/admitad.py
import asyncio
import hashlib
import logging
from xml.etree import ElementTree as ET

import httpx

from services.db import get_db

logger = logging.getLogger("autopost_bot.admitad")

# Прямая ссылка на фид (AliExpress)
FEED_URL = "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=14107&last_import="


async def fetch_admitad_catalog(user_id: int) -> int:
    try:
        # Берём дату последнего импорта из файла (потом перенесём в БД)
        last_import = ""
        try:
            with open("/tmp/admitad_last_import.txt", "r") as f:
                last_import = f.read().strip()
        except FileNotFoundError:
            last_import = "2025-01-01T00:00:00"  # если файла нет, начинаем с этой даты

        url = f"https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=14107&last_import={last_import}"

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            logger.error(f"Admitad фид недоступен: {resp.status_code}")
            return 0

        root = ET.fromstring(resp.text)
        offers = root.findall('.//offer')
        # Ограничиваем первыми 200 товарами
        offers = offers[:200]
        saved = 0
        conn = get_db()

        for offer in offers:
            # ... парсинг и вставка (как было, но с проверкой ERID)

        conn.commit()
        conn.close()

        # Сохраняем текущее время как дату последнего импорта
        from datetime import datetime
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
        await fetch_admitad_catalog(user["user_id"])
        await asyncio.sleep(1)

    logger.info("🔄 Пополнение каталогов Admitad завершено")
