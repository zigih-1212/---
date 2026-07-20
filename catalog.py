import asyncio
import httpx
import re
import logging

logger = logging.getLogger(__name__)
from xml.etree.ElementTree import XMLPullParser
from urllib.parse import urlparse, parse_qs

# ---------- Настройки ----------
BASE_FEED_URL = ("https://export.admitad.com/ru/webmaster/websites/2956090/"
                 "products/export_adv_products/?user=zigi_oh-by2ec9e&code=emrdliwjzy"
                 "&format=xml&currency=&feed_id={feed_id}&last_import=")

# Ключ: латиница, значение: русское название города и ID фида
CITY_DATA = {
    'moscow': ('Москва', '24825'),
    'spb': ('Санкт-Петербург', '24826'),
    'astrakhan': ('Астрахань', '24827'),
    'barnaul': ('Барнаул', '24828'),
    'belgorod': ('Белгород', '24829'),
    'volgograd': ('Волгоград', '24830'),
    'voronezh': ('Воронеж', '24832'),
    'ekaterinburg': ('Екатеринбург', '24833'),
    'irkutsk': ('Иркутск', '24834'),
    'kazan': ('Казань', '24835'),
    'kaliningrad': ('Калининград', '24836'),
    'kemerovo': ('Кемерово', '24837'),
    'krasnodar': ('Краснодар', '24838'),
    'lipetsk': ('Липецк', '24839'),
    'nnovgorod': ('Нижний Новгород', '24840'),
    'novokuznetsk': ('Новокузнецк', '24843'),
    'novosibirsk': ('Новосибирск', '24846'),
    'omsk': ('Омск', '24847'),
    'perm': ('Пермь', '24848'),
    'rostov': ('Ростов-на-Дону', '24849'),
}

def get_city_name(key: str) -> str:
    return CITY_DATA[key][0]

def get_feed_url(key: str) -> str:
    if key == 'vk_zen':
        return "https://api.zen.yandex.ru/v1/feed"
    elif key in CITY_DATA:
        return BASE_FEED_URL.format(feed_id=CITY_DATA[key][1])
    raise ValueError(f"Unknown city key: {key}")

def extract_erid(url: str) -> str | None:
    parsed = parse_qs(urlparse(url).query)
    return parsed.get('erid', [None])[0]

async def fetch_products(city_key: str, limit: int = 5) -> list[dict]:
    """Fetch products from catalog with improved error handling and validation.
    
    Returns:
        List of product dicts with keys: name, price, url, erid, image (if available)
    """
    feed_url = get_feed_url(city_key)
    parser = XMLPullParser(['end'])
    products = []
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream('GET', feed_url) as resp:
                if resp.status_code != 200:
                    logger.error(f"Failed to fetch catalog {city_key}. Status: {resp.status_code}")
                    return []
                
                async for chunk in resp.aiter_bytes():
                    try:
                        parser.feed(chunk)
                        for event, elem in parser.read_events():
                            if elem.tag == 'offer' and len(products) < limit:
                                product = {
                                    'name': elem.findtext('name', '').strip(),
                                    'price': float(elem.findtext('price', '0')),
                                    'url': elem.findtext('url', '').strip(),
                                    'erid': extract_erid(elem.findtext('url', '')),
                                    'image': elem.findtext('picture', '').strip()
                                }
                                # Validate required fields
                                if product['name'] and product['url'] and product['erid']:
                                    products.append(product)
                                elem.clear()
                    except Exception as parse_error:
                        logger.warning(f"XML parse error: {parse_error}")
                        continue
                
                logger.info(f"Fetched {len(products)} products for {city_key}")
                return products
    except Exception as e:
        logger.error(f"Catalog fetch failed for {city_key}: {str(e)}")
        return []
