import asyncio
import logging
import httpx
import json
import os
from bs4 import BeautifulSoup

# --- НАСТРОЙКИ ИЗ RAILWAY ---
# Если переменная не найдена, используем значение по умолчанию или None
TOKEN = os.getenv("OT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")

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
                    "text": f"🤖 Тестовый бот в сети!\nКанал: {TARGET_CHANNEL}\nСтатус: Работает"
                })
            return update["update_id"] + 1
    except Exception as e:
        log.error(f"Ошибка проверки команд: {e}")
    return last_update_id

# --- ОСНОВНОЙ ЦИКЛ ---
async def main():
    if not TOKEN or not TARGET_CHANNEL:
        log.error("ОШИБКА: TOKEN или TARGET_CHANNEL не заданы в переменных Railway!")
        return

    async with httpx.AsyncClient(timeout=30) as client:
        log.info("Бот запущен в режиме DEV-TEST!")
        last_update_id = 0
        last_id = 0
        
        while True:
            try:
                # 1. Проверяем команды
                last_update_id = await check_commands(client, last_update_id)
                
                # 2. Парсим донора (используй свой URL донора)
                # Пример: resp = await client.get("https://t.me/s/твоя_ссылка")
                
                # ... тут твой код парсинга ...

            except Exception as e:
                log.error(f"Критическая ошибка цикла: {e}")
            
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
