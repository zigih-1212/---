# services/admitad.py
import asyncio
import hashlib
import logging
from urllib.parse import urlparse, parse_qs
from xml.etree.ElementTree import XMLPullParser
import httpx
from services.db import get_db
from config import ADMITAD_CLIENT_ID, ADMITAD_CLIENT_SECRET

logger = logging.getLogger("autopost_bot.admitad")

STORES = {
    "Читай-город": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=24883&last_import=",
        "adult": False,
        "admitad_advertiser_id": 12345  # нужно уточнить ID рекламодателя, можно оставить 0, но для API купонов потребуется
    },
    "Аквафор": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=18482&last_import=",
        "adult": False,
    },
    "Розовый кролик": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=26654&last_import=",
        "adult": True,
    },
    "Hi Store RU": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=25803&last_import=",
        "adult": False,
    },
    "KANZLER": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=25851&last_import=",
        "adult": False,
    },
    "KIKO MILANO": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=15202&last_import=",
        "adult": False,
    },
    "Moulinex": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=25773&last_import=",
        "adult": False,
    },
    "Playtoday": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=26222&last_import=",
        "adult": False,
    },
    "SELA": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=24700&last_import=",
        "adult": False,
    },
}
ADULT_STORES = {"Розовый кролик"}
STORE_ID_MAP = {
    2: "Читай-город",
    3: "Аквафор",
    4: "Розовый кролик",
    6: "Hi Store RU",
    7: "KANZLER",
    8: "KIKO MILANO",
    9: "Moulinex",
    10: "Playtoday",
    11: "SELA",
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

async def fetch_admitad_catalog_for_user(user_id: int, max_items_per_store: int = 50) -> int:
    # ... без изменений (тот же код, который был) ...
    # (оставьте текущую реализацию, она не требует изменений)

async def refill_admitad_catalogs(bot=None):
    # ... без изменений (тот же код) ...

async def get_admitad_token() -> str:
    """Получение access_token по client_credentials."""
    url = "https://api.admitad.com/token/"
    auth = httpx.BasicAuth(ADMITAD_CLIENT_ID, ADMITAD_CLIENT_SECRET)
    data = {"grant_type": "client_credentials", "scope": "coupons"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, auth=auth, data=data)
        resp.raise_for_status()
        token_data = resp.json()
        return token_data["access_token"]

async def update_store_delivery_info():
    """Обновляет информацию о доставке из API купонов Admitad."""
    logger.info("🔄 Обновление информации о доставке из Admitad API...")
    try:
        token = await get_admitad_token()
    except Exception as e:
        logger.error(f"Не удалось получить токен Admitad: {e}")
        return

    headers = {"Authorization": f"Bearer {token}"}
    conn = get_db()
    try:
        # Создаём таблицу, если её нет
        conn.execute("""
            CREATE TABLE IF NOT EXISTS store_delivery (
                store TEXT PRIMARY KEY,
                delivery_text TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        for store_name, cfg in STORES.items():
            # Для поиска купонов используем название магазина как ключевое слово
            params = {
                "limit": 50,
                "language": "ru",
                "query": store_name,
            }
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api.admitad.com/coupons/", headers=headers, params=params)
                resp.raise_for_status()
                coupons_data = resp.json()
                results = coupons_data.get("results", [])

                delivery_phrases = []
                for coup in results:
                    description = coup.get("description", "")
                    if not description:
                        continue
                    # Ищем ключевые слова, связанные с доставкой
                    lower_desc = description.lower()
                    if any(w in lower_desc for w in ["доставк", "delivery", "бесплатн"]):
                        delivery_phrases.append(description.strip())

                if delivery_phrases:
                    # Берём самую первую подходящую фразу (можно все через ;)
                    delivery_text = delivery_phrases[0]
                    conn.execute(
                        "INSERT OR REPLACE INTO store_delivery (store, delivery_text) VALUES (?, ?)",
                        (store_name, delivery_text)
                    )
                else:
                    # Если нет, можно удалить запись (чтобы не показывать устаревшую)
                    conn.execute("DELETE FROM store_delivery WHERE store = ?", (store_name,))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка обновления доставки: {e}")
    finally:
        conn.close()
    logger.info("✅ Информация о доставке обновлена")

async def update_store_promocodes():
    """Обновляет промокоды из API купонов Admitad."""
    logger.info("🔄 Обновление промокодов из Admitad API...")
    try:
        token = await get_admitad_token()
    except Exception as e:
        logger.error(f"Не удалось получить токен Admitad: {e}")
        return

    headers = {"Authorization": f"Bearer {token}"}
    conn = get_db()
    try:
        # Очищаем старые промокоды (или можно добавлять новые с проверкой уникальности)
        conn.execute("DELETE FROM store_promocodes")
        conn.commit()

        for store_name, cfg in STORES.items():
            params = {
                "limit": 100,
                "language": "ru",
                "query": store_name,
                "type": "promocode",  # или "coupon", зависит от API
            }
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://api.admitad.com/coupons/", headers=headers, params=params)
                if resp.status_code != 200:
                    logger.warning(f"Не удалось получить купоны для {store_name}: {resp.status_code}")
                    continue
                data = resp.json()
                results = data.get("results", [])

                for coup in results:
                    promo = coup.get("promocode")
                    if not promo:
                        continue
                    description = coup.get("description", "")
                    conn.execute(
                        "INSERT INTO store_promocodes (store, promocode, description) VALUES (?, ?, ?)",
                        (store_name, promo, description)
                    )
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка обновления промокодов: {e}")
    finally:
        conn.close()
    logger.info("✅ Промокоды обновлены")

def get_random_promocode(store_name: str) -> str:
    """Возвращает случайный промокод для магазина или пустую строку."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT promocode FROM store_promocodes WHERE store = ? ORDER BY RANDOM() LIMIT 1",
            (store_name,)
        ).fetchone()
        return row["promocode"] if row else ""
    finally:
        conn.close()

def get_delivery_for_store(store_name: str) -> str:
    """Возвращает сохранённую информацию о доставке для магазина."""
    conn = get_db()
    try:
        row = conn.execute("SELECT delivery_text FROM store_delivery WHERE store = ?", (store_name,)).fetchone()
        return row["delivery_text"] if row else ""
    finally:
        conn.close()
