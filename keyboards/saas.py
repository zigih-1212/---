# keyboards/saas.py
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
import os
from config import load_tariffs   # <-- уже не из main

WEBAPP_ADMIN_URL: str = os.getenv("WEBAPP_ADMIN_URL", "")

def kb_cabinet_menu(role: str = "saas"):
    if role == "saas":
        buttons = [
            [InlineKeyboardButton(text="🏪 Магазины", callback_data="menu:categories")],
            [InlineKeyboardButton(text="📢 Мои каналы", callback_data="menu:my_channels")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
            [InlineKeyboardButton(text="💎 Тарифы", callback_data="menu:tariffs")],
            [InlineKeyboardButton(text="🎁 Активировать промокод", callback_data="promo:activate")],
            [InlineKeyboardButton(text="📊 Веб-статистика", callback_data="menu:webstats")],
            [InlineKeyboardButton(text="📖 Инструкция", callback_data="menu:instructions")],
            [InlineKeyboardButton(text="📜 Оферта", callback_data="menu:oferta")],
            [InlineKeyboardButton(text="📝 Шаблоны постов", callback_data="menu:templates")],
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
            [InlineKeyboardButton(text="📝 Шаблоны постов", callback_data="menu:templates")],
            [InlineKeyboardButton(text="📞 Поддержка", callback_data="support:contact")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_tariffs(traffic_source: str = "") -> InlineKeyboardMarkup:
    tariffs = load_tariffs()
    rows = []
    for t in tariffs:
        text = f"⭐ {t['name']} — {t['price_rub']:.0f} руб. / {t['price_stars']} ⭐"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"buy:{t['id']}:{t['days']}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_payment_methods() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💳 Банковская карта (Sber / Т-Банк / Visa KG)",
            callback_data="pay:card"
        )],
        [InlineKeyboardButton(
            text="⭐ Telegram Stars",
            callback_data="pay:stars"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
    ])

def kb_saas_settings(user) -> InlineKeyboardMarkup:
    auto_pin = bool(user.get("auto_pin", 1))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ℹ️ Об источнике товаров", callback_data="saas_set:gdeslon_apikey")],
        [InlineKeyboardButton(text=f"📌 Авто-закреп постов: {'✅' if auto_pin else '❌'}", callback_data="saas_toggle:autopin")],
        [InlineKeyboardButton(text="🚀 Опубликовать сейчас (Force Post)", callback_data="saas_force_post")],
        [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")]
    ])
    return kb
