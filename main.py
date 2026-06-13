import logging
import os
import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import F
import httpx

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("OT_TOKEN")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS clients 
                      (user_id INTEGER PRIMARY KEY, erid TEXT, channel_id TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- КНОПКИ ---
@dp.message(CommandStart())
async def start(message: types.Message):
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")],
        [types.InlineKeyboardButton(text="🏷 Установить ЕРИД", callback_data="set_erid")]
    ])
    await message.answer("🤖 Админ-панель бота:\nВыбери действие:", reply_markup=builder)

# --- ПАРСИНГ ---
async def start_parsing():
    while True:
        logging.info("Парсинг запущен...")
        await asyncio.sleep(60)

async def main():
    # Запускаем парсинг в фоне
    asyncio.create_task(start_parsing())
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
