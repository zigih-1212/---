import logging
import os
import sqlite3
import asyncio
import sys
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage

# 1. ПРОВЕРКА ПЕРЕМЕННЫХ (Защита от падения)
TOKEN = os.getenv("OT_TOKEN")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")

if not TOKEN or not TARGET_CHANNEL:
    print("КРИТИЧЕСКАЯ ОШИБКА: Проверь наличие OT_TOKEN и TARGET_CHANNEL в Railway!")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# 2. БАЗА ДАННЫХ
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS clients 
                      (id INTEGER PRIMARY KEY, erid TEXT, channel_id TEXT)''')
    conn.commit()
    conn.close()

init_db()

# 3. АДМИН-ПАНЕЛЬ
@dp.message(CommandStart())
async def start(message: types.Message):
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")],
        [types.InlineKeyboardButton(text="🏷 Установить ЕРИД", callback_data="set_erid")]
    ])
    await message.answer("🤖 Админ-панель бота:\nВыбери действие:", reply_markup=builder)

# 4. ЛОГИКА ПАРСИНГА (Фоновый процесс)
async def start_parsing():
    log.info("Парсинг запущен и готов к работе.")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Здесь будет твоя логика взятия постов
                # ... (код парсинга)
                pass 
            except Exception as e:
                log.error(f"Ошибка в цикле парсинга: {e}")
            await asyncio.sleep(60)

# 5. ЗАПУСК
async def main():
    log.info("Бот запускается...")
    # Запускаем парсинг в фоне
    asyncio.create_task(start_parsing())
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот остановлен.")
