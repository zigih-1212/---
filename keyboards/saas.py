# keyboards/saas.py
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
import os

WEBAPP_ADMIN_URL: str = os.getenv("WEBAPP_ADMIN_URL", "")

def kb_cabinet_menu(role: str = "saas"):
    if role == "saas":
        buttons = [
            [InlineKeyboardButton(text="🏪 Магазины", callback_data="menu:categories")],
            [InlineKeyboardButton(text="📢 Мои каналы", callback_data="menu:my_channels")],
            [InlineKeyboardButton(text="⚙️ Периодичность постов", callback_data="blogger:post_interval")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
            [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="blogger:referral")],
            [InlineKeyboardButton(text="📊 Веб-статистика", callback_data="menu:webstats")],
            [InlineKeyboardButton(text="📖 Инструкция", callback_data="menu:instructions")],
            [InlineKeyboardButton(text="📜 Оферта", callback_data="menu:oferta")],
            [InlineKeyboardButton(text="📄 Политика конфиденциальности", callback_data="menu:privacy")],
            [InlineKeyboardButton(text="🧾 Налоговый статус", callback_data="tax_status:change")],
            [InlineKeyboardButton(text="📞 Поддержка", callback_data="support:contact")],
        ]
    else:  # blogger
        buttons = [
            [InlineKeyboardButton(text="🏪 Магазины", callback_data="menu:categories")],
            [InlineKeyboardButton(text="📢 Мои Telegram-каналы", callback_data="menu:my_channels")],
            [InlineKeyboardButton(text="⚙️ Периодичность постов", callback_data="blogger:post_interval")],
            [InlineKeyboardButton(text="🎥 Мои видео-каналы", callback_data="blogger:social_channels")],
            [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="blogger:referral")],
            [InlineKeyboardButton(text="📊 Веб-статистика", callback_data="menu:webstats")],
            [InlineKeyboardButton(text="📖 Инструкция", callback_data="menu:instructions")],
            [InlineKeyboardButton(text="📜 Оферта", callback_data="menu:oferta")],
            [InlineKeyboardButton(text="📄 Политика конфиденциальности", callback_data="menu:privacy")],
            [InlineKeyboardButton(text="📞 Поддержка", callback_data="support:contact")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_saas_settings(user) -> InlineKeyboardMarkup:
    auto_pin = bool(user.get("auto_pin", 1))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ℹ️ Об источнике товаров", callback_data="saas_set:gdeslon_apikey")],
        [InlineKeyboardButton(text=f"📌 Авто-закреп постов: {'✅' if auto_pin else '❌'}", callback_data="saas_toggle:autopin")],
        [InlineKeyboardButton(text="🚀 Опубликовать сейчас (Force Post)", callback_data="saas_force_post")],
        [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")]
    ])
    return kb
