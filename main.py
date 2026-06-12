import asyncio
import logging
import os
import httpx
import json
import re
import urllib.parse
import random
from bs4 import BeautifulSoup

TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"
TAKPRODAM_ID = "36498e27-9209-4b9a-b85b-f4750ef56904"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

# Вариативность текстов
TEMPLATES = [
    "🔥 <b>Находка дня!</b>\n\nСмотри, какой крутой товар я нашел. Идеальное сочетание цены и качества, которое точно тебе понравится. Успей забрать, пока всё не разобрали! 👇",
    "✨ <b>Твой идеальный выбор!</b>\n\nДавно искал что-то подобное? Этот товар — настоящий топ по отзывам. Очень рекомендую присмотреться, пока действует скидка. 😉",
    "🚀 <b>Хит продаж!</b>\n\nНе упусти возможность обновить свои покупки. Качественная вещь по приятной цене уже ждет тебя. Переходи по ссылке и оформляй заказ! 👇",
    "💎 <b>Топ-находка с Wildberries!</b>\n\nСобрал для тебя всё самое лучшее. Отличный товар, который сделает твою жизнь чуточку комфортнее. Скорее переходи и забирай свой экземпляр!"
]

async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        log.info("Бот запущен в расширенном режиме!")
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
                    
                    # Получаем и очищаем текст
                    text_tag = post.find('div', class_='tgme_widget_message_text')
                    raw_text = text_tag.get_text(separator="\n") if text_tag else ""
                    clean_text = re.sub(r'https?://\S+|www\.\S+|t\.me/\S+', '', raw_text).strip()
                    
                    # Формируем пост (текст + вариативность)
                    final_caption = f"{random.choice(TEMPLATES)}\n\n{clean_text[:150]}"
                    partner_url = f"https://takprdm.ru/{TAKPRODAM_ID}/?redirectTo={urllib.parse.quote(link_tag['href'], safe='')}"
                    
                    # Пытаемся получить фото
                    img_tag = post.find('a', class_='tgme_widget_message_photo_wrap')
                    img_url = None
                    if img_tag and 'style' in img_tag.attrs:
                        m = re.search(r"url\('(.+?)'\)", img_tag['style'])
                        if m: img_url = m.group(1).replace("_a.jpg", "_w.jpg")

                    # ОТПРАВКА
                    payload = {
                        "chat_id": CHANNEL, "caption": final_caption, "parse_mode": "HTML",
                        "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ СО СКИДКОЙ", "url": partner_url}]]})
                    }
                    
                    if img_url:
                        payload["photo"] = img_url
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=payload)
                    else:
                        payload["text"] = final_caption
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload)
                    
                    last_id = pid
                    await asyncio.sleep(20)
            except Exception as e: log.error(f"Error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
