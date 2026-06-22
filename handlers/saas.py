"""
handlers/saas.py — Обработчики команд и колбэков для SaaS-клиентов
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
from datetime import datetime, timedelta, timezone
import sqlite3

# Импортируем нужные объекты из основного модуля
# Чтобы избежать циклического импорта, эти функции должны быть определены в main.py
from main import (
    get_db, is_admin, show_user_cabinet,
    kb_cabinet_menu, kb_main_menu, kb_payment_methods, kb_tariffs,
    load_tariffs, is_night_time, add_to_saas_queue, process_saas_core,
    rewrite_text_with_ai, find_product_links, prepare_post_content,
    flush_saas_queue_for_user, fetch_gdeslon_catalog, refill_all_catalogs,
    # и другие, если понадобятся
)

logger = logging.getLogger("autopost_bot.saas")

router = Router()

@router.callback_query(F.data == "menu:my_channels")
async def cb_my_channels(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        channels = conn.execute(
            "SELECT id, channel_title, channel_id FROM channels WHERE user_id=? AND is_active=1",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    if channels:
        text = "📢 <b>Ваши подключенные каналы:</b>\n\n"
        kb_rows = []
        for i, ch in enumerate(channels, 1):
            text += f"{i}. {ch['channel_title']} (<code>{ch['channel_id']}</code>)\n"
            kb_rows.append([InlineKeyboardButton(
                text=f"🗑 Удалить {ch['channel_title']}",
                callback_data=f"channel_delete:{ch['id']}"
            )])
        text += "\n<i>Для добавления нового канала отправьте его @username прямо сейчас.</i>"
        kb_rows.append([InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    else:
        text = "📢 <b>У вас пока нет подключенных каналов.</b>\n\nДля добавления канала отправьте его @username."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")]
        ])

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except:
        pass
    await state.set_state(OnboardingStates.waiting_saas_tg_channel)
    await callback.answer()

@router.callback_query(F.data.startswith("channel_delete:"))
async def cb_delete_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("DELETE FROM channels WHERE id = ? AND user_id = ?", (channel_id, user_id))
        conn.commit()
        await callback.answer("✅ Канал удалён.", show_alert=True)
    finally:
        conn.close()
    # Обновляем список каналов
    await cb_my_channels(callback, state=None)  # state здесь не нужен, можно передать заглушку

@router.callback_query(F.data == "menu:categories")
async def cb_categories(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        all_cats = conn.execute("SELECT id, name FROM product_categories WHERE is_active = 1").fetchall()
        user_cats = conn.execute("SELECT category_id FROM user_category_preferences WHERE user_id = ?", (user_id,)).fetchall()
        user_cat_ids = {r["category_id"] for r in user_cats}
    finally:
        conn.close()

    text = "📂 <b>Выберите категории товаров:</b>\n\n"
    kb_rows = []
    for cat in all_cats:
        emoji = "✅" if cat["id"] in user_cat_ids else "❌"
        text += f"{emoji} {cat['name']}\n"
        kb_rows.append([InlineKeyboardButton(
            text=f"{emoji} {cat['name']}",
            callback_data=f"cat_toggle:{cat['id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("cat_toggle:"))
async def cb_toggle_category(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    conn = get_db()
    try:
        existing = conn.execute("SELECT 1 FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                                (user_id, cat_id)).fetchone()
        if existing:
            conn.execute("DELETE FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                         (user_id, cat_id))
        else:
            # Проверка лимита по тарифу
            tariff = conn.execute("SELECT t.max_categories FROM users u JOIN tariffs t ON u.tariff_id = t.id WHERE u.user_id = ?",
                                  (user_id,)).fetchone()
            max_cat = tariff["max_categories"] if tariff and tariff["max_categories"] else 3
            current_count = conn.execute("SELECT COUNT(*) as cnt FROM user_category_preferences WHERE user_id = ?",
                                         (user_id,)).fetchone()["cnt"]
            if current_count >= max_cat:
                await callback.answer(f"❌ Ваш тариф позволяет выбрать не более {max_cat} категорий", show_alert=True)
                return
            conn.execute("INSERT INTO user_category_preferences (user_id, category_id) VALUES (?, ?)",
                         (user_id, cat_id))
        conn.commit()
    finally:
        conn.close()

    # Сразу наполняем каталог для этого пользователя по выбранной категории
    keyword = None
    conn = get_db()
    try:
        cat = conn.execute("SELECT keyword FROM product_categories WHERE id = ?", (cat_id,)).fetchone()
        if cat:
            keyword = cat["keyword"]
    finally:
        conn.close()

    if keyword:
        await fetch_gdeslon_catalog(user_id, keyword, limit=5)

    await cb_categories(callback)
    await callback.answer()

@router.callback_query(F.data == "saas_force_post")
async def cb_saas_force_post(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer("🚀 Публикую пост из каталога...", show_alert=True)
    user_id = callback.from_user.id

    # Берём только товар с ERID (ручная публикация должна быть безопасной)
    conn = get_db()
    try:
        product = conn.execute(
            "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL ORDER BY RANDOM() LIMIT 1",
            (user_id,)
        ).fetchone()
        if product:
            conn.execute("UPDATE gdeslon_catalog SET used = 1 WHERE id = ?", (product["id"],))
            conn.commit()
    finally:
        conn.close()

    if not product:
        await callback.message.answer("❌ В каталоге нет товаров с маркировкой ERID. Дождитесь пополнения или используйте автоматическую публикацию.")
        return

    # Формируем пост (используя существующую логику)
    caption = (
        f"{product['title']}\n\n"
        f"💰 Цена: {product['price']} {product['currency']}\n\n"
        f"<a href='{product['partner_url']}'>👉 Посмотреть и заказать</a>\n\n"
        f"Реклама. {product['advertiser']}"
    )
    if product.get('erid'):
        caption += f". Erid: {product['erid']}"

    from main import publish_post_with_fallback  # можно импортировать заранее
    conn = get_db()
    try:
        channels = conn.execute("SELECT channel_id FROM channels WHERE user_id = ? AND is_active = 1", (user_id,)).fetchall()
    finally:
        conn.close()

    for ch in channels:
        await publish_post_with_fallback(bot, channel_id=ch["channel_id"], caption=caption, photo_url=product["image_url"])

    await callback.message.answer("✅ Пост опубликован!")

@router.callback_query(F.data == "saas_set:gdeslon_apikey")
async def cb_saas_set_gdeslon_apikey(callback: CallbackQuery, state: FSMContext):
    text = (
        "🔑 <b>Настройка API-ключа GdeSlon</b>\n\n"
        "Отправьте сообщением ваш API-ключ от GdeSlon.\n"
        "<i>Если вы хотите удалить ключ, отправьте цифру 0</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:settings")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await state.set_state(SaasStates.waiting_apikey)
    await state.update_data(input_type="gdeslon_apikey")
    await callback.answer()

@router.message(SaasStates.waiting_apikey)
async def msg_saas_text_input(message: Message, state: FSMContext):
    data = await state.get_data()
    input_type = data.get("input_type", "apikey")

    if input_type == "gdeslon_apikey":
        api_key = message.text.strip()
        user_id = message.from_user.id
        if api_key == "0":
            api_key = None
            ans_text = "🗑 API-ключ GdeSlon удалён."
        else:
            ans_text = "✅ API-ключ GdeSlon успешно сохранён!"
        conn = get_db()
        try:
            conn.execute("UPDATE users SET api_key=? WHERE user_id=?", (api_key, user_id))
            conn.commit()
        finally:
            conn.close()
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Вернуться в настройки", callback_data="menu:settings")]
        ])
        await message.answer(ans_text, reply_markup=kb)
        return
    # Если другой тип ввода – оставляем старую логику (можно перенести её же)
