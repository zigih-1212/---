import asyncio
import logging
import httpx
import os
import sys

# --- НАСТРОЙКИ ИЗ RAILWAY ---
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
    # Проверка настроек
    if not TOKEN or not TARGET_CHANNEL:
        log.error("КРИТИЧЕСКАЯ ОШИБКА: Переменные OT_TOKEN или TARGET_CHANNEL не найдены в Railway!")
        return

    async with httpx.AsyncClient(timeout=30) as client:
        log.info(f"Бот запущен! Целевой канал: {TARGET_CHANNEL}")
        last_update_id = 0

        # ТЕСТОВАЯ ОТПРАВКА (проверка связи)
        await client.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={
            "chat_id": TARGET_CHANNEL,
            "text": "🤖 Бот успешно подключился к каналу! Проверка связи."
        })
        log.info("Тестовое сообщение отправлено!")
        
        while True:
            try:
                # 1. Проверяем команды
                last_update_id = await check_commands(client, last_update_id)
                
            # 2. Парсим донора
                donor_url = "https://t.me/s/wb_skidkamam" # Твой канал-донор
                resp = await client.get(donor_url)
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Ищем последний пост (пример логики)
                posts = soup.find_all("div", class_="tgme_widget_message_wrap")
                if posts:
                    last_post = posts[-1]
                    post_id = last_post.find("div", class_="tgme_widget_message")["data-post"]
                    
                    # Здесь должна быть проверка, видели ли мы этот пост (через last_id)
                    # Если пост новый:
                    # 1. Берем текст и картинку
                    # 2. Вызываем функцию обработки текста (с твоей рефералкой и ЕРИД)
                    # 3. Отправляем через client.post(...)
                # Бот работает, используя TARGET_CHANNEL вместо файла config.json
                
            except Exception as e:
                log.error(f"Ошибка в цикле: {e}")
            
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
