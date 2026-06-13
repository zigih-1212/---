import logging
import os
import sqlite3
import asyncio
import sys
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage

# 1. КОНФИГУРАЦИЯ
TOKEN = os.getenv("OT_TOKEN")
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL")

if not TOKEN:
    print("КРИТИЧЕСКАЯ ОШИБКА: OT_TOKEN не найден!")
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
                      (id INTEGER PRIMARY KEY, channel_id TEXT, erid TEXT, status TEXT)''')
    conn.commit()
    conn.close()

init_db()

# 3. АДМИН-ПАНЕЛЬ (Меню)
@dp.message(CommandStart())
async def start(message: types.Message):
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить клиента", callback_data="add_client"),
         types.InlineKeyboardButton(text="❌ Удалить клиента", callback_data="del_client")],
        [types.InlineKeyboardButton(text="🏷 Установить ЕРИД", callback_data="set_erid"),
         types.InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [types.InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast")]
    ])
    await message.answer("🛠 Админ-панель SMM-бота:\nВыберите управление:", reply_markup=builder)

# 4. ОБРАБОТКА НАЖАТИЙ (Callback)
@dp.callback_query(F.data == "stats")
async def show_stats(callback: types.CallbackQuery):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM clients")
    count = cursor.fetchone()[0]
    conn.close()
    await callback.message.answer(f"📊 Всего клиентов в базе: {count}")
    await callback.answer()

@dp.callback_query(F.data == "add_client")
async def add_client(callback: types.CallbackQuery):
    await callback.message.answer("Введите ID канала клиента:")
    await callback.answer()

# 5. ПАРСИНГ (Фоновый процесс)
async def start_parsing():
    log.info("Парсинг запущен и готов к работе.")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Логика будет расширяться здесь
                await asyncio.sleep(60)
            except Exception as e:
                log.error(f"Ошибка в цикле парсинга: {e}")
                await asyncio.sleep(60)

# 6. ЗАПУСК
async def main():
    log.info("Бот запускается...")
    asyncio.create_task(start_parsing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот остановлен.")
