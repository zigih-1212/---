import asyncio
import logging
import httpx
import json
import re
import urllib.parse
import random
import os
from bs4 import BeautifulSoup

# --- НАСТРОЙКИ ---
def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()
TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = config["active_channel"]
DONOR = config["settings"]["donor_username"]
TAKPRODAM_ID = config["settings"]["partner_id"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

# --- ФУНКЦИЯ КОМАНД ---
async def check_commands(client, last_update_id):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={last_update_id}&limit=1"
        resp = await client.get(url)
        data = resp.json()
        if data.get("result"):
            update = data["result"][0]
            msg = update.get("message", {})
            text = msg.get("text", "")
            if text == "/status":
                await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={
                    "chat_id": msg["chat"]["id"],
                    "text": f"🤖 Бот в сети!\nТекущий канал: {CHANNEL}\nСтатус: Работает"
                })
            return update["update_id"] + 1
    except Exception as e:
        log.error(f"Ошибка проверки команд: {e}")
    return last_update_id

# --- ОСНОВНОЙ ЦИКЛ ---
async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        log.info("Бот запущен в режиме DEV-TEST!")
        last_update_id = 0
        last_id = 0
        
        while True:
            try:
                # 1. Проверяем команды
                last_update_id = await check_commands(client, last_update_id)
                
                # 2. Парсим донора
                resp = await client.get(f"https://t.me/s/{DONOR}")
                soup = BeautifulSoup(resp.text, 'html.parser')
                posts = soup.find_all('div', class_='tgme_widget_message')
                
                for post in reversed(posts):
                    pid = int(post.get('data-post').split('/')[-1])
                    if pid <= last_id: continue
                    
                    # Логика обработки товаров (здесь твой стандартный код)
                    link_tag = post.find('a', href=lambda x: x and ('wildberries' in x or 'ozon' in x))
                    if link_tag:
                        log.info(f"Найден новый пост: {pid}")
                        # (тут твоя логика отправки...)
                        
                    last_id = pid
            except Exception as e:
                log.error(f"Критическая ошибка цикла: {e}")
            
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
