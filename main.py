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
GROQ_API = os.getenv("GROQ_API_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

async def get_rewrite(client, text):
    """Генерация красивого описания товара"""
    if not GROQ_API: 
        return "🔥 <b>Находка дня!</b>\n\nСмотри, какой крутой товар я нашел. Успей забрать по отличной цене! 👇"
    
    payload = {
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{"role": "user", "content": f"Напиши короткий, эмоциональный продающий текст (до 300 символов) для этого товара в Telegram. Используй эмодзи: {text}"}],
        "temperature": 0.7
    }
    try:
        resp = await client.post("https://api.groq.com/openai/v1/chat/completions", 
            json=payload, headers={"Authorization": f"Bearer {GROQ_API}"}, timeout=5)
        return resp.json()["choices"][0]["message"]["content"]
    except: 
        return "🔥 <b>Находка дня!</b>\n\nСмотри, какой крутой товар я нашел. Успей забрать по отличной цене! 👇"

def generate_partner_link(original_url: str) -> str:
    base = f"https://takprdm.ru/{TAKPRODAM_ID}/?redirectTo="
    encoded_url = urllib.parse.quote(original_url, safe='')
    return f"{base}{encoded_url}"

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
                    
                    # Получаем текст
                    text = await get_rewrite(client, post.get_text())
                    partner_url = generate_partner_link(link_tag['href'])
                    
                    # Пытаемся взять фото
                    photo_tag = post.find('a', class_='tgme_widget_message_photo_wrap')
                    img_url = None
                    if photo_tag and 'style' in photo_tag.attrs:
                        m = re.search(r"url\('(.+?)'\)", photo_tag['style'])
                        if m: img_url = m.group(1).replace("_a.jpg", "_w.jpg")

                    payload = {
                        "chat_id": CHANNEL, "caption": text, "parse_mode": "HTML", 
                        "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ СО СКИДКОЙ", "url": partner_url}]]})
                    }

                    if img_url:
                        payload["photo"] = img_url
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=payload)
                    else:
                        payload["text"] = text
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload)
                    
                    last_id = pid
                    await asyncio.sleep(20)
            except Exception as e: log.error(f"Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
