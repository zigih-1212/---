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
    if not is_admin(message.from_user.id): return
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить клиента", callback_data="add_client")],
        [types.InlineKeyboardButton(text="🏷 Установить ЕРИД", callback_data="set_erid")],
        [types.InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ])
    await message.answer("🛠 Админ-панель SMM-бота:", reply_markup=builder)

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
        # Здесь в будущем будет цикл по базе данных:
        # 1. Получаем список всех channel_id из таблицы
        # 2. Идем в каждый донорский канал
        # 3. Парсим, подставляем ЕРИД и шлем в целевой канал
        await asyncio.sleep(60)

async def main():
    asyncio.create_task(start_parsing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
