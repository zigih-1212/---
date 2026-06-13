import logging
import os
import sqlite3
import asyncio
import sys
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("OT_TOKEN")
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- СОСТОЯНИЯ (FSM) ---
class AdminStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_erid = State()

# --- ФУНКЦИИ ---
def is_admin(user_id):
    return str(user_id) in [aid.strip() for aid in ADMIN_IDS]

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS clients 
                      (id INTEGER PRIMARY KEY, channel_id TEXT, erid TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- ОБРАБОТЧИКИ ---
@dp.message(CommandStart())
async def start(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Доступ ограничен.")
        return
        
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="➕ Добавить клиента", callback_data="add_client"),
            types.InlineKeyboardButton(text="❌ Удалить клиента", callback_data="del_client")
        ],
        [
            types.InlineKeyboardButton(text="🏷 Установить ЕРИД", callback_data="set_erid"),
            types.InlineKeyboardButton(text="📊 Статистика", callback_data="stats")
        ],
        [
            types.InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast")
        ]
    ])
    await message.answer("🛠 Админ-панель SMM-бота:\nВыберите управление:", reply_markup=builder)

@dp.callback_query(F.data == "add_client")
async def add_client_step1(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID канала (например, @channel_name):")
    await state.set_state(AdminStates.waiting_for_channel)
    await callback.answer()

@dp.message(AdminStates.waiting_for_channel)
async def add_client_step2(message: types.Message, state: FSMContext):
    channel_id = message.text
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO clients (channel_id) VALUES (?)", (channel_id,))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Канал {channel_id} успешно добавлен!")
    await state.clear()

@dp.callback_query(F.data == "stats")
async def show_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM clients")
    count = cursor.fetchone()[0]
    conn.close()
    await callback.message.answer(f"📊 Всего клиентов в базе: {count}")
    await callback.answer()

# --- ПАРСИНГ ---
async def start_parsing():
    log.info("Парсер запущен.")
    while True:
        # Логика будет расширяться здесь
        await asyncio.sleep(60)

async def main():
    if not TOKEN:
        log.error("OT_TOKEN не найден!")
        return
    asyncio.create_task(start_parsing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот остановлен.")
