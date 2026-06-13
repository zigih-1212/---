import logging
import os
import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
import httpx
from bs4 import BeautifulSoup

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("OT_TOKEN")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

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
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Добавить канал", callback_data="add_channel"))
    markup.add(types.InlineKeyboardButton("🏷 Установить ЕРИД", callback_data="set_erid"))
    await message.answer("🤖 Админ-панель бота:\nВыбери действие:", reply_markup=markup)

# --- ПАРСИНГ (Фоновый процесс) ---
async def start_parsing():
    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Здесь твой код парсинга
                # Для примера: просто лог, чтобы бот не засыпал
                logging.info("Парсинг запущен...")
            except Exception as e:
                logging.error(f"Ошибка парсинга: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_parsing())
    executor.start_polling(dp, skip_updates=True)
