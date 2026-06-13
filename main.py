import logging
import os
import sqlite3
import asyncio
import sys
from datetime import datetime
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

# --- СОСТОЯНИЯ ---
class AdminStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_erid = State()

# --- ФУНКЦИИ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    # Добавили поля для полноценного SaaS
    cursor.execute('''CREATE TABLE IF NOT EXISTS clients 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                       channel_id TEXT, 
                       erid TEXT, 
                       sub_type TEXT DEFAULT 'test', 
                       sub_end DATE, 
                       posts_sent INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

def is_admin(user_id):
    return str(user_id) in [aid.strip() for aid in ADMIN_IDS]

# --- ОБРАБОТЧИКИ ---
@dp.message(CommandStart())
async def start(message: types.Message):
    if not is_admin(message.from_user.id): return
    builder = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить", callback_data="add_client"),
         types.InlineKeyboardButton(text="❌ Удалить", callback_data="list_delete")],
        [types.InlineKeyboardButton(text="📊 Статистика/Клиенты", callback_data="stats")],
        [types.InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast")]
    ])
    await message.answer("🛠 Админ-панель SMM-бота:", reply_markup=builder)

# --- УПРАВЛЕНИЕ КЛИЕНТАМИ ---
@dp.callback_query(F.data == "stats")
async def show_list(callback: types.CallbackQuery):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, channel_id FROM clients")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await callback.message.answer("База пуста.")
    else:
        builder = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"Клиент {r[1]}", callback_data=f"client_{r[0]}")] for r in rows
        ])
        await callback.message.answer("Выберите клиента для просмотра:", reply_markup=builder)
    await callback.answer()

@dp.callback_query(F.data.startswith("client_"))
async def show_client_details(callback: types.CallbackQuery):
    client_id = callback.data.split("_")[1]
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients WHERE id=?", (client_id,))
    c = cursor.fetchone()
    conn.close()
    
    text = f"👤 Клиент: {c[1]}\n🏷 ЕРИД: {c[2]}\n📦 Подписка: {c[3]} (до {c[4]})\n📈 Постов отправлено: {c[5]}"
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "add_client")
async def add_client_step1(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID канала:")
    await state.set_state(AdminStates.waiting_for_channel)
    await callback.answer()

@dp.message(AdminStates.waiting_for_channel)
async def add_client_step2(message: types.Message, state: FSMContext):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO clients (channel_id, sub_end) VALUES (?, ?)", 
                   (message.text, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    await message.answer("✅ Добавлен!")
    await state.clear()

# --- ПАРСИНГ ---
async def start_parsing():
    log.info("Парсер запущен.")
    while True:
        await asyncio.sleep(60)

async def main():
    asyncio.create_task(start_parsing())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот остановлен.")
