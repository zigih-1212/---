import asyncio
import logging
import httpx
import json
import re
import urllib.parse
import random
import os
from bs4 import BeautifulSoup

# Функция загрузки конфигурации
def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

# Загружаем настройки один раз при запуске
config = load_config()

# Теперь все переменные берутся из твоего JSON
TOKEN = "8800001861:AAGW0Qlgk3NRf5ruzrlI7OxZ4-LPmUT18ms" # Токен лучше оставить тут или тоже вынести в защищенный конфиг
CHANNEL = config["active_channel"]
DONOR = config["settings"]["donor_username"]
TAKPRODAM_ID = config["settings"]["partner_id"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

# ... (остальной код остается прежним)
# --- ШАБЛОНЫ ТЕКСТА ---
TEMPLATES = [
    "🔥 <b>Находка дня!</b>\n\nСмотри, какой крутой товар я нашел. Идеальное сочетание цены и качества, которое точно тебе понравится. Успей забрать, пока всё не разобрали! 👇",
    "✨ <b>Твой идеальный выбор!</b>\n\nДавно искал что-то подобное? Этот товар — настоящий топ по отзывам. Очень рекомендую присмотреться, пока действует скидка. 😉",
    "🚀 <b>Хит продаж!</b>\n\nНе упусти возможность обновить свои покупки. Качественная вещь по приятной цене уже ждет тебя. Переходи по ссылке и оформляй заказ! 👇",
    "💎 <b>Топ-находка с маркетплейса!</b>\n\nСобрал для тебя всё самое лучшее. Отличный товар, который сделает твою жизнь чуточку комфортнее. Скорее переходи и забирай свой экземпляр!"
]

async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        log.info("Бот запущен и работает в режиме отправки файлов!")
        last_id = 0
        while True:
            try:
                resp = await client.get(f"https://t.me/s/{DONOR}")
                soup = BeautifulSoup(resp.text, 'html.parser')
                posts = soup.find_all('div', class_='tgme_widget_message')
                
                for post in reversed(posts):
                    pid = int(post.get('data-post').split('/')[-1])
                    if pid <= last_id: continue
                    
                    # 1. Поиск ссылки на товар
                    link_tag = post.find('a', href=lambda x: x and ('wildberries' in x or 'ozon' in x))
                    if not link_tag: continue
                    
                    # 2. Обработка текста
                    text_tag = post.find('div', class_='tgme_widget_message_text')
                    raw_text = text_tag.get_text(separator="\n") if text_tag else ""
                    clean_text = re.sub(r'https?://\S+|www\.\S+|t\.me/\S+', '', raw_text).strip()
                    final_caption = f"{random.choice(TEMPLATES)}\n\n{clean_text[:150]}"
                    
                    # 3. Партнерская ссылка
                    partner_url = f"https://takprdm.ru/{TAKPRODAM_ID}/?redirectTo={urllib.parse.quote(link_tag['href'], safe='')}"
                    
                    # 4. Поиск фото
                    img_tag = post.find('a', class_='tgme_widget_message_photo_wrap')
                    img_url = None
                    if img_tag and 'style' in img_tag.attrs:
                        m = re.search(r"url\('(.+?)'\)", img_tag['style'])
                        if m: img_url = m.group(1).replace("_a.jpg", "_w.jpg")

                    # 5. Отправка (сначала пробуем как файл, если нет — текстом)
                    sent = False
                    if img_url:
                        try:
                            img_resp = await client.get(img_url)
                            if img_resp.status_code == 200:
                                files = {'photo': img_resp.content}
                                data = {
                                    "chat_id": CHANNEL, "caption": final_caption, "parse_mode": "HTML",
                                    "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ СО СКИДКОЙ", "url": partner_url}]]})
                                }
                                r = await client.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto", data=data, files=files)
                                if r.status_code == 200: sent = True
                        except Exception as e:
                            log.error(f"Ошибка отправки фото: {e}")

                    if not sent:
                        payload = {
                            "chat_id": CHANNEL, "text": final_caption, "parse_mode": "HTML",
                            "reply_markup": json.dumps({"inline_keyboard": [[{"text": "🛒 ЗАБРАТЬ СО СКИДКОЙ", "url": partner_url}]]})
                        }
                        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=payload)
                    
                    last_id = pid
                    await asyncio.sleep(20)
            except Exception as e:
                log.error(f"Общая ошибка: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
