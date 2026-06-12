import asyncio
import base64
import json
import logging
import os
import re
import httpx
from bs4 import BeautifulSoup

# КОНФИГ
TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"
GROQ_API = os.getenv("GROQ_API_KEY", "") # Укажи в Railway переменную GROQ_API_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

async def get_rewrite(client, img_url, text):
    # Промпт для уникализации
    prompt = f"Напиши уникальное продающее описание для товара на основе текста: {text}. Эмодзи обязательны. Без цен и артикулов."
    payload = {
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    try:
        resp = await client.post("https://api.groq.com/openai/v1/chat/completions", 
            json=payload, headers={"Authorization": f"Bearer {GROQ_API}"})
        return resp.json()["choices"][0]["message"]["content"]
    except: return "✨ Топ находка! Смотри подробности по ссылке ниже 👇"

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
                    
                    # Поиск ссылки
                    link_tag = post.find('a', href=True, text=re.compile(r'wildberries', re.I))
                    if not link_tag: continue
                    
                    raw_url = link_tag['href']
                    # МЕСТО ДЛЯ ТАКПРОДАМ: здесь будет функция замены на твой переходник
                    final_url = raw_url 
                    
                    # Поиск фото
                    photo_tag = post.find('a', class_='tgme_widget_message_photo_wrap')
                    img_url = None
                    if photo_tag and 'style' in photo_tag.attrs:
                        m = re.search(r"url\('(.+?)'\)", photo_tag['style'])
                        if m: img_url = m.group(1).replace("_a.jpg", "_w.jpg")

                    # Рерайт и отправка
                    text = await get_rewrite(client, img_url, post.get_text())
                    
                    keyboard = {"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ НА WB", "url": final_url}]]}
                    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
                    await client.post(url, data={"chat_id": CHANNEL, "photo": img_url, "caption": text, 
                                                "parse_mode": "HTML", "reply_markup": json.dumps(keyboard)})
                    
                    last_id = max(last_id, pid)
                    await asyncio.sleep(20) # Пауза чтобы не ловить бан
            except Exception as e: log.error(e)
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
