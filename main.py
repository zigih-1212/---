import asyncio
import logging
import os
import httpx
from bs4 import BeautifulSoup
import json

TOKEN = "8800001861:AAGW0Qlgk3NRh5ruzrlI7OxZ4-LPmUT18ms"
CHANNEL = "@wb_skidochniki"
DONOR = "wb_skidkamam"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

async def main():
    async with httpx.AsyncClient() as client:
        log.info("--- ТЕСТОВЫЙ ЗАПУСК ---")
        try:
            # 1. Проверяем парсинг
            resp = await client.get(f"https://t.me/s/{DONOR}")
            soup = BeautifulSoup(resp.text, 'html.parser')
            post = soup.find('div', class_='tgme_widget_message')
            
            if post:
                text = "Тестовое сообщение от бота: парсинг работает!"
                log.info("Парсинг успешен, шлю тест...")
                
                # 2. Проверяем отправку в Telegram (без фото, просто текст)
                url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                data = {"chat_id": CHANNEL, "text": text}
                r = await client.post(url, data=data)
                
                if r.status_code == 200:
                    log.info("✅ УСПЕХ! Telegram принял сообщение.")
                else:
                    log.error(f"❌ Telegram вернул ошибку: {r.text}")
            else:
                log.error("❌ Не удалось найти посты на странице!")
                
        except Exception as e:
            log.error(f"Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())
