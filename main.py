import asyncio
import logging
import os
import httpx
import json
from bs4 import BeautifulSoup
import re
import urllib.parse

TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"
TAKPRODAM_ID = "36498e27-9209-4b9a-b85b-f4750ef56904"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        log.info("Бот запущен! Пытаюсь отправить фото через прокси-ссылки...")
        last_id = 0
        while True:
            try:
                resp = await client.get(f"https://t.me/s/{DONOR}")
                soup = BeautifulSoup(resp.text, 'html.parser')
                posts = soup.find_all('div', class_='tgme_widget_message')
                
                for post in reversed(posts):
                    pid = int(post.get('data-post').split('/')[-1])
                    if pid <= last_id: continue
                    
                    link_tag = post.find('a', href=lambda x: x and ('wildberries' in x or 'ozon' in x))
                    if not link_tag: continue
                    
                    # Пытаемся найти фото и конвертируем в прямую ссылку cdn
                    img_tag = post.find('a', class_='tgme_widget_message_photo_wrap')
                    img_url = None
                    if img_tag and 'style' in img_tag.attrs:
                        m = re.search(r"background-image:url\('(.+?)'\)", img_tag['style'])
                        if m:
                            # Telegram лучше ест ссылки на cdn-телеграмма, чем на preview
                            img_url = m.group(1).replace("_a.jpg", "_w.jpg")

                    partner_url = f"https://takprdm.ru/{TAKPRODAM_ID}/?redirectTo={urllib.parse.quote(link_tag['href'], safe='')}"
                    caption = "🔥 <b>Находка дня!</b>\n\nСмотри, какой крутой товар! Успей забрать по отличной цене! 👇"

                    if img_url:
                        payload = {"chat_id": CHANNEL, "photo": img_url, "caption": caption, "parse_mode": "HTML",
                                   "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ СО СКИДКОЙ", "url": partner_url}]]})}
                        r = await client.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=payload)
                    else:
                        payload = {"chat_id": CHANNEL, "text": caption, "parse_mode": "HTML",
                                   "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ СО СКИДКОЙ", "url": partner_url}]]})}
                        r = await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload)
                    
                    if r.status_code == 200:
                        log.info(f"✅ Успешно отправил пост #{pid}")
                    else:
                        log.error(f"❌ Ошибка Telegram: {r.text}")
                    
                    last_id = pid
                    await asyncio.sleep(20)
            except Exception as e: log.error(f"Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
