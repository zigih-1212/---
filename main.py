import asyncio
import logging
import os
import httpx
import json
from bs4 import BeautifulSoup
import re

TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

async def main():
    async with httpx.AsyncClient() as client:
        log.info("Бот запущен!")
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
                    
                    # ОТПРАВЛЯЕМ ТОЛЬКО ТЕКСТ (БЕЗ ФОТО)
                    caption = "🔥 Отличная находка! Жми кнопку ниже 👇"
                    payload = {
                        "chat_id": CHANNEL,
                        "text": caption,
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 КУПИТЬ", "url": link_tag['href']}]]})
                    }

                    r = await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload)
                    
                    if r.status_code == 200:
                        log.info(f"✅ Успешно отправил пост #{pid}")
                    else:
                        log.error(f"❌ Ошибка Telegram: {r.text}")
                    
                    last_id = pid
                    await asyncio.sleep(10)
            except Exception as e: log.error(f"Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
