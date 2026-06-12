import asyncio
import logging
import os
import httpx
import json
from bs4 import BeautifulSoup

TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

async def main():
    async with httpx.AsyncClient() as client:
        log.info("Бот запущен и готов к работе!")
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
                    
                    # Пытаемся найти фото
                    photo_tag = post.find('a', class_='tgme_widget_message_photo_wrap')
                    img_url = None
                    if photo_tag and 'style' in photo_tag.attrs:
                        m = re.search(r"url\('(.+?)'\)", photo_tag['style'])
                        if m: img_url = m.group(1)

                    # ОТПРАВКА БЕЗ GROQ (ЧИСТЫЙ ТЕКСТ + ССЫЛКА)
                    caption = "🔥 Новинка! Переходи по ссылке ниже 👇"
                    payload = {
                        "chat_id": CHANNEL,
                        "caption": caption,
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 КУПИТЬ", "url": link_tag['href']}]]})
                    }

                    if img_url:
                        payload["photo"] = img_url
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=payload)
                    else:
                        payload["text"] = caption
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload)
                    
                    log.info(f"✅ Успешно отправил пост #{pid}")
                    last_id = pid
                    await asyncio.sleep(10)
            except Exception as e: log.error(f"Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    import re
    asyncio.run(main())
