# keyboards/saas.py
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
import os

WEBAPP_ADMIN_URL: str = os.getenv("WEBAPP_ADMIN_URL", "")

def kb_cabinet_menu(role: str = "saas"):
    if role == "saas":
        buttons = [
            [InlineKeyboardButton(text="🏪 Магазины", callback_data="menu:categories")],
            [InlineKeyboardButton(text="📢 Мои каналы", callback_data="menu:my_channels")],
            [InlineKeyboardButton(text="🚀 Force Post", callback_data="saas_force_post")],
            [InlineKeyboardButton(text="📊 Веб-статистика", callback_data="menu:webstats")],
            [InlineKeyboardButton(text="📖 Инструкция", callback_data="menu:instructions")],
            [InlineKeyboardButton(text="📜 Оферта", callback_data="menu:oferta")],
            [InlineKeyboardButton(text="📄 Политика конфиденциальности", callback_data="menu:privacy")],
            [InlineKeyboardButton(text="📞 Поддержка", callback_data="support:contact")],
        ]
    else:  # blogger
        buttons = [
            [InlineKeyboardButton(text="🏪 Магазины", callback_data="menu:categories")],
            [InlineKeyboardButton(text="📢 Мои Telegram-каналы", callback_data="menu:my_channels")],
            [InlineKeyboardButton(text="🎥 Мои видео-каналы", callback_data="blogger:social_channels")],
            [InlineKeyboardButton(text="🚀 Force Post", callback_data="saas_force_post")],
            [InlineKeyboardButton(text="📊 Веб-статистика", callback_data="menu:webstats")],
            [InlineKeyboardButton(text="📖 Инструкция", callback_data="menu:instructions")],
            [InlineKeyboardButton(text="📜 Оферта", callback_data="menu:oferta")],
            [InlineKeyboardButton(text="📄 Политика конфиденциальности", callback_data="menu:privacy")],
            [InlineKeyboardButton(text="📞 Поддержка", callback_data="support:contact")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

