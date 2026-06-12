import asyncio
import logging
import os
import httpx
import json
import re  # <-- ЭТОТ ИМПОРТ РЕШАЕТ ПРОБЛЕМУ
import urllib.parse
from bs4 import BeautifulSoup

TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"
TAKPRODAM_ID = "36498e27-9209-4b9a-b85b-f4750ef56904"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        log.info("Бот запущен и работает идеально!")
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
                    
                    text_tag = post.find('div', class_='tgme_widget_message_text')
                    text = text_tag.get_text(separator="\n") if text_tag else "🔥 Топ товар!"
                    
                    # Очистка текста
                    text = re.sub(r'https?://\S+|www\.\S+|t\.me/\S+', '', text).strip()
                    if len(text) < 5:
                        text = "🔥 <b>Находка дня!</b>\n\nСмотри, какой крутой товар! Успей забрать по отличной цене! 👇"

                    partner_url = f"https://takprdm.ru/{TAKPRODAM_ID}/?redirectTo={urllib.parse.quote(link_tag['href'], safe='')}"
                    
                    payload = {
                        "chat_id": CHANNEL,
                        "text": f"{text}\n\n👇 Успей забрать по скидке:",
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ СО СКИДКОЙ", "url": partner_url}]]})
                    }
                    
                    r = await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload)
                    
                    if r.status_code == 200:
                        log.info(f"✅ Пост #{pid} успешно опубликован!")
                    
                    last_id = pid
                    await asyncio.sleep(20)
            except Exception as e: log.error(f"Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
