# services/admitad.py
import asyncio
import hashlib
import logging
import urllib.request
from urllib.parse import urlparse, parse_qs
from xml.etree.ElementTree import XMLPullParser, ElementTree
import httpx
from services.db import get_db
from config import ADMITAD_CLIENT_ID, ADMITAD_CLIENT_SECRET

logger = logging.getLogger("autopost_bot.admitad")

# ---------------------------------------------------------------------------
# Магазины и маппинг
# ---------------------------------------------------------------------------

STORES = {
    "Читай-город": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=24883&last_import=",
        "adult": False,
        "website_id": 15460,   # из XML-фида купонов
    },
    "Аквафор": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=18482&last_import=",
        "adult": False,
        "website_id": 0,  # Аквафор отключён, ставим 0 или убираем
    },
    "Розовый кролик": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=26654&last_import=",
        "adult": True,
        "website_id": 181544,
    },
    "Hi Store RU": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=25803&last_import=",
        "adult": False,
        "website_id": 109641,
    },
    "KANZLER": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=25851&last_import=",
        "adult": False,
        "website_id": 14625,
    },
    "KIKO MILANO": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=15202&last_import=",
        "adult": False,
        "website_id": 15735,
    },
    "Moulinex": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=25773&last_import=",
        "adult": False,
        "website_id": 15488,
    },
    "Playtoday": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=26222&last_import=",
        "adult": False,
        "website_id": 17006,
    },
    "SELA": {
        "feed_url": "https://export.admitad.com/ru/webmaster/websites/2956090/products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy&format=xml&currency=&feed_id=24700&last_import=",
        "adult": False,
        "website_id": 6476,
    },
    # Galaxy Store добавлен позже, но без фида товаров (только купоны)
    "Galaxystore": {
        "feed_url": "",  # фида нет, только купоны
        "adult": False,
        "website_id": 13423,
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
    12: "Galaxystore",
}

# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

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
        selected_rows = conn.execute(
            "SELECT category_id FROM user_category_preferences WHERE user_id = ?",
            (user_id,)
        ).fetchall()
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
        feed_url = store_cfg.get("feed_url", "")
        if not feed_url:
            continue

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

                                conn_local = get_db()
                                try:
                                    conn_local.execute(
                                        """INSERT OR IGNORE INTO gdeslon_catalog
                                        (sku, user_id, title, price, old_price, discount_percent, currency,
                                         partner_url, erid, advertiser, image_url, category_keyword, used, source)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                                        (sku, user_id, name, price, old_price, discount_percent, currency,
                                         url, erid, store_name, picture, store_name, store_name)
                                    )
                                    conn_local.commit()
                                finally:
                                    conn_local.close()

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


# ---------------------------------------------------------------------------
# Работа с купонами через XML-фид (НЕ через API)
# ---------------------------------------------------------------------------

XML_COUPONS_URL = (
    "https://export.admitad.com/ru/webmaster/websites/2956090/coupons/export/"
    "?website=2956090&region=00&language=&only_my=on&keyword="
    "&code=emrdliwjzy&user=zigi_oh-by2ec9e&format=xml&v=1"
)


async def update_all_store_data_from_feed():
    """Загружает XML-фид купонов, обновляет таблицы store_promocodes и store_delivery."""
    import xml.etree.ElementTree as ET
    logger.info("🔄 Обновление промокодов и доставки из XML-фида...")
    conn = get_db()
    try:
        # Убедимся, что таблицы существуют
        conn.execute("""
            CREATE TABLE IF NOT EXISTS store_promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store TEXT NOT NULL,
                promocode TEXT NOT NULL,
                description TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS store_delivery (
                store TEXT PRIMARY KEY,
                delivery_text TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Очищаем старые данные
        conn.execute("DELETE FROM store_promocodes")
        conn.execute("DELETE FROM store_delivery")
        conn.commit()

        with urllib.request.urlopen(XML_COUPONS_URL) as response:
            tree = ET.parse(response)
        root = tree.getroot()

        # Сопоставление campaign_id → название магазина
        campaigns = {}
        for adv in root.findall('.//advcampaigns/advcampaign'):
            cid = adv.get('id')
            name = adv.findtext('name')
            if cid and name:
                campaigns[cid] = name

        # Обработка купонов
        for coupon in root.findall('coupon'):
            promo = (coupon.findtext('promocode') or '').strip()
            desc = (coupon.findtext('description') or '').strip()
            short_name = (coupon.findtext('name') or '').strip() or desc
            campaign_id = (coupon.findtext('advcampaign_id') or coupon.findtext('advcampaign') or '').strip()
            if not campaign_id:
                continue

            store_name = campaigns.get(campaign_id)
            if not store_name:
                continue

            # Сохраняем промокод
            if promo:
                conn.execute(
                    "INSERT INTO store_promocodes (store, promocode, description) VALUES (?, ?, ?)",
                    (store_name, promo, short_name or desc)
                )

            # Тип "Free delivery" (id=1) → в доставку
            type_id = (coupon.findtext('type_id') or '').strip()
            if type_id == '1':
                conn.execute(
                    "INSERT OR REPLACE INTO store_delivery (store, delivery_text) VALUES (?, ?)",
                    (store_name, desc or short_name)
                )

        conn.commit()
        logger.info("✅ Данные из XML-фида обновлены")
    except Exception as e:
        logger.error(f"Ошибка обновления из фида: {e}")
    finally:
        conn.close()


def get_delivery_for_store(store_name: str) -> str:
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT delivery_text FROM store_delivery WHERE store = ?",
            (store_name,)
        ).fetchone()
        return row["delivery_text"] if row else ""
    except Exception:
        return ""
    finally:
        try:
            conn.close()
        except:
            pass


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
