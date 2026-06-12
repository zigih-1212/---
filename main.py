import asyncio
import logging
import os
import re
import httpx
from bs4 import BeautifulSoup

# КОНФИГ
TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"
GROQ_API = os.getenv("GROQ_API_KEY", "") 

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

async def get_rewrite(client, text):
    payload = {
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{"role": "user", "content": f"Напиши уникальное описание для товара: {text}. Без цен, только эмодзи и текст."}],
        "temperature": 0.7
    }
    try:
        resp = await client.post("https://api.groq.com/openai/v1/chat/completions", 
            json=payload, headers={"Authorization": f"Bearer {GROQ_API}"})
        if resp.status_code != 200:
            log.error(f"Groq Error {resp.status_code}: {resp.text}")
            return None
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.error(f"Groq Exception: {e}")
        return None

async def main():
    async with httpx.AsyncClient() as client:
        log.info("Бот запущен!")
        last_id = 0
        while True:
            try:
                resp = await client.get(f"https://t.me/s/{DONOR}")
                soup = BeautifulSoup(resp.text, 'html.parser')
                posts = soup.find_all('div', class_='tgme_widget_message')
                
                for post in posts:
                    pid = int(post.get('data-post').split('/')[-1])
                    if pid <= last_id: continue
                    
                    # Поиск фото (надежный способ)
                    img_url = None
                    photo_tag = post.find('a', class_='tgme_widget_message_photo_wrap')
                    if photo_tag and 'style' in photo_tag.attrs:
                        m = re.search(r"url\('(.+?)'\)", photo_tag['style'])
                        if m: img_url = m.group(1)

                    text = await get_rewrite(client, post.get_text())
                    if not text: text = "✨ Новинка! Переходи по ссылке 👇"

                    # Ссылка
                    link_tag = post.find('a', href=re.compile(r'wildberries|ozon', re.I))
                    if not link_tag: continue
                    url = link_tag['href']

                    # Отправка
                    data = {"chat_id": CHANNEL, "caption": text, "parse_mode": "HTML", 
                            "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 КУПИТЬ", "url": url}]]})}
                    
                    if img_url:
                        data["photo"] = img_url
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=data)
                    else:
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data)
                    
                    last_id = max(last_id, pid)
                    await asyncio.sleep(10)
            except Exception as e: log.error(f"Main loop error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    import json
    asyncio.run(main())
