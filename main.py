import asyncio
import logging
import os
import httpx
import json
import re
import urllib.parse
import random
from bs4 import BeautifulSoup

# КОНФИГ
TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"
TAKPRODAM_ID = "36498e27-9209-4b9a-b85b-f4750ef56904"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

# Шаблоны для текста
TEMPLATES = [
    "🔥 <b>Находка дня!</b>\n\nСмотри, какой крутой товар я нашел. Идеальное сочетание цены и качества, которое точно тебе понравится. Успей забрать, пока всё не разобрали! 👇",
    "✨ <b>Твой идеальный выбор!</b>\n\nДавно искал что-то подобное? Этот товар — настоящий топ по отзывам. Очень рекомендую присмотреться, пока действует скидка. 😉",
    "🚀 <b>Хит продаж!</b>\n\nНе упусти возможность обновить свои покупки. Качественная вещь по приятной цене уже ждет тебя. Переходи по ссылке и оформляй заказ! 👇",
    "💎 <b>Топ-находка с маркетплейса!</b>\n\nСобрал для тебя всё самое лучшее. Отличный товар, который сделает твою жизнь чуточку комфортнее. Скорее переходи и забирай свой экземпляр!"
]

async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        log.info("Бот запущен и работает!")
        last_id = 0
        while True:
            try:
                resp = await client.get(f"https://t.me/s/{DONOR}")
                soup = BeautifulSoup(resp.text, 'html.parser')
                # ИСПРАВЛЕНО: используем class_=
                posts = soup.find_all('div', class_='tgme_widget_message')
                
                for post in reversed(posts):
                    pid = int(post.get('data-post').split('/')[-1])
                    if pid <= last_id: continue
                    
                    link_tag = post.find('a', href=lambda x: x and ('wildberries' in x or 'ozon' in x))
                    if not link_tag: continue
                    
                    text_tag = post.find('div', class_='tgme_widget_message_text')
                    raw_text = text_tag.get_text(separator="\n") if text_tag else ""
                    clean_text = re.sub(r'https?://\S+|www\.\S+|t\.me/\S+', '', raw_text).strip()
                    
                    final_caption = f"{random.choice(TEMPLATES)}\n\n{clean_text[:150]}"
                    partner_url = f"https://takprdm.ru/{TAKPRODAM_ID}/?redirectTo={urllib.parse.quote(link_tag['href'], safe='')}"
                    
                   # ПОИСК ФОТО (НАДЕЖНЫЙ МЕТОД)
                    img_tag = post.find('a', class_='tgme_widget_message_photo_wrap')
                    img_url = None
                    if img_tag and 'style' in img_tag.attrs:
                        m = re.search(r"url\('(.+?)'\)", img_tag['style'])
                        if m:
                            # Берем ссылку и чистим её
                            raw_url = m.group(1)
                            img_url = raw_url.replace("_a.jpg", "_w.jpg")

                    # ПОИСК ССЫЛКИ НА ТОВАР И ФОТО
                    link_tag = post.find('a', href=lambda x: x and ('wildberries' in x or 'ozon' in x))
                    if not link_tag: continue
                    
                    product_url = link_tag['href']
                    img_url = None
                    
                    # Пытаемся вытянуть фото Wildberries через ID товара
                    if "wildberries.ru" in product_url:
                        prod_id = re.search(r'/(\d+)/', product_url)
                        if prod_id:
                            # Официальный CDN WB для картинок
                            img_url = f"https://images.wbstatic.net/big/new/{prod_id.group(1)}-1.jpg"
                    
                    # Если фото не нашли, пытаемся взять старым методом (из поста)
                    if not img_url:
                        img_tag = post.find('a', class_='tgme_widget_message_photo_wrap')
                        if img_tag and 'style' in img_tag.attrs:
                            m = re.search(r"url\('(.+?)'\)", img_tag['style'])
                            if m: img_url = m.group(1)

                    # ОТПРАВКА
                    payload = {
                        "chat_id": CHANNEL,
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ СО СКИДКОЙ", "url": partner_url}]]})
                    }

                    if img_url:
                        payload["photo"] = img_url
                        payload["caption"] = final_caption
                        r = await client.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=payload)
                    else:
                        payload["text"] = final_caption
                        r = await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload)
                        }
                        r = await client.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=payload)
                        if r.status_code != 200:
                            payload_text = {"chat_id": CHANNEL, "text": final_caption, "parse_mode": "HTML",
                                            "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ СО СКИДКОЙ", "url": partner_url}]]})}
                            await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload_text)
                    else:
                        payload = {"chat_id": CHANNEL, "text": final_caption, "parse_mode": "HTML",
                                   "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ СО СКИДКОЙ", "url": partner_url}]]})}
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload)
                    
                    last_id = pid
                    await asyncio.sleep(20)
            except Exception as e: log.error(f"Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
