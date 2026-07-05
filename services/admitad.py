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
    conn = get_db()
    try:
        selected_rows = conn.execute("SELECT category_id FROM user_category_preferences WHERE user_id = ?", (user_id,)).fetchall()
        selected_ids = {r["category_id"] for r in selected_rows}
    finally:
        conn.close()

    saved = 0
    for store_id, store_name in STORE_ID_MAP.items():
        if store_id not in selected_ids:
            continue
        if store_name not in STORES:
            continue

        store_cfg = STORES[store_name]
        feed_url = store_cfg["feed_url"]
        store_saved = 0
        parser = XMLPullParser(['end'])

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                async with client.stream("GET", feed_url) as resp:
                    if resp.status_code != 200:
                        logger.error(f"Admitad фид {store_name} недоступен: {resp.status_code}")
                        continue

                    async for chunk in resp.aiter_bytes(chunk_size=128*1024):
                        try:
                            parser.feed(chunk)
                        except Exception as e:
                            logger.warning(f"Ошибка парсинга чанка в {store_name}: {e}")
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

                                # --- парсинг старой цены ---
                                old_price = None
                                discount_percent = None
                                old_price_elem = elem.find('oldprice')
                                if old_price_elem is not None and old_price_elem.text:
                                    try:
                                        old_price = float(old_price_elem.text)
                                        if old_price > 0 and price < old_price:
                                            discount_percent = int(round((old_price - price) / old_price * 100))
                                    except ValueError:
                                        old_price = None

                                sku = hashlib.md5(url.encode()).hexdigest()[:12]

                                conn = get_db()
                                try:
                                    conn.execute(
                                        """INSERT OR IGNORE INTO gdeslon_catalog
                                        (sku, user_id, title, price, old_price, discount_percent, currency, partner_url, erid, advertiser, image_url, category_keyword, used, source)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                                        (sku, user_id, name, price, old_price, discount_percent, currency, url, erid, store_name, picture, store_name, store_name)
                                    )
                                    conn.commit()
                                finally:
                                    conn.close()

                                store_saved += 1
                                elem.clear()

                                if store_saved >= max_items_per_store:
                                    break
                        if store_saved >= max_items_per_store:
                            break
        except Exception as e:
            logger.error(f"Admitad stream error for {store_name}: {e}")
        finally:
            try:
                parser.close()
            except Exception as e:
                logger.warning(f"Parser close warning for {store_name}: {e}")

        saved += store_saved
        logger.info(f"  {store_name}: добавлено {store_saved} товаров")

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
        await fetch_admitad_catalog_for_user(user["user_id"], max_items_per_store=50)
        await asyncio.sleep(1)

    logger.info("🔄 Пополнение каталогов Admitad завершено")


async def get_admitad_token() -> str:
    url = "https://api.admitad.com/token/"
    data = {
        "grant_type": "client_credentials",
        "scope": "coupons",
        "client_id": ADMITAD_CLIENT_ID,
        "client_secret": ADMITAD_CLIENT_SECRET,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=data)
        resp.raise_for_status()
        token_data = resp.json()
        return token_data["access_token"]


async def update_store_delivery_info():
    logger.info("🔄 Обновление информации о доставке из Admitad API...")
    try:
        token = await get_admitad_token()
    except Exception as e:
        logger.error(f"Не удалось получить токен Admitad: {e}")
        return

    headers = {"Authorization": f"Bearer {token}"}
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS store_delivery (
                store TEXT PRIMARY KEY,
                delivery_text TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        for store_name, cfg in STORES.items():
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
                    lower_desc = description.lower()
                    if any(w in lower_desc for w in ["доставк", "delivery", "бесплатн"]):
                        delivery_phrases.append(description.strip())

                if delivery_phrases:
                    delivery_text = delivery_phrases[0]
                    conn.execute(
                        "INSERT OR REPLACE INTO store_delivery (store, delivery_text) VALUES (?, ?)",
                        (store_name, delivery_text)
                    )
                else:
                    conn.execute("DELETE FROM store_delivery WHERE store = ?", (store_name,))
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка обновления доставки: {e}")
    finally:
        conn.close()
    logger.info("✅ Информация о доставке обновлена")


def get_delivery_for_store(store_name: str) -> str:
    try:
        conn = get_db()
        row = conn.execute("SELECT delivery_text FROM store_delivery WHERE store = ?", (store_name,)).fetchone()
        return row["delivery_text"] if row else ""
    except Exception:
        return ""
    finally:
        try:
            conn.close()
        except:
            pass


async def update_store_promocodes():
    logger.info("🔄 Обновление промокодов из Admitad API...")
    try:
        token = await get_admitad_token()
    except Exception as e:
        logger.error(f"Не удалось получить токен Admitad: {e}")
        return

    headers = {"Authorization": f"Bearer {token}"}
    conn = get_db()
    try:
        conn.execute("DELETE FROM store_promocodes")
        conn.commit()

        for store_name, cfg in STORES.items():
            params = {
                "limit": 100,
                "language": "ru",
                "query": store_name,
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
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT promocode FROM store_promocodes WHERE store = ? ORDER BY RANDOM() LIMIT 1",
            (store_name,)
        ).fetchone()
        return row["promocode"] if row else ""
    except Exception:
        return ""
    finally:
        try:
            conn.close()
        except:
            pass
