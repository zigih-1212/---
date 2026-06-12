import asyncio
import logging
import os
import httpx
import json
from bs4 import BeautifulSoup

TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"
GROQ_API = os.getenv("GROQ_API_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

async def get_rewrite(client, text):
    if not GROQ_API: return "✨ Топ находка! Смотри подробности по ссылке 👇"
    payload = {
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{"role": "user", "content": f"Уникализируй описание: {text}. Эмодзи обязательны."}],
        "temperature": 0.7
    }
    try:
        resp = await client.post("https://api.groq.com/openai/v1/chat/completions", 
            json=payload, headers={"Authorization": f"Bearer {GROQ_API}"})
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        return "✨ Топ находка! Смотри подробности по ссылке 👇"
    except: return "✨ Топ находка! Смотри подробности по ссылке 👇"

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
                    
                    text = await get_rewrite(client, post.get_text())
                    data = {
                        "chat_id": CHANNEL, "caption": text, "parse_mode": "HTML", 
                        "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 КУПИТЬ", "url": link_tag['href']}]]})
                    }
                    
                    photo_tag = post.find('a', class_='tgme_widget_message_photo_wrap')
                    if photo_tag and 'style' in photo_tag.attrs:
                        img_url = photo_tag['style'].split("url('")[1].split("')")[0].replace("_a.jpg", "_w.jpg")
                        data["photo"] = img_url
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=data)
                    
                    last_id = pid
                    await asyncio.sleep(10)
            except Exception as e: log.error(f"Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
