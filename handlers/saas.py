# handlers/saas.py
import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from states import SaasStates, PaymentFSM
from services.db import get_db
from services.saas_core import publish_post_with_fallback
from services.admitad import fetch_admitad_catalog
from keyboards.saas import kb_tariffs, kb_payment_methods
from config import load_tariffs

router = Router(name="saas")

# ---------------------------------------------------------------------------
# Категории
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:categories")
async def cb_stores(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user_stores = conn.execute("SELECT category_id FROM user_category_preferences WHERE user_id = ?", (user_id,)).fetchall()
        user_store_ids = {r["category_id"] for r in user_stores}
    finally:
        conn.close()

    stores = [
        {"id": 1, "name": "AliExpress (пока недоступен)"},
        {"id": 2, "name": "Читай-город"},
        {"id": 3, "name": "Аквафор"},
        {"id": 4, "name": "Розовый кролик (18+)"},
    ]

    text = "🏪 <b>Выберите магазины для постинга:</b>\n\n"
    kb_rows = []
    for store in stores:
        emoji = "✅" if store["id"] in user_store_ids else "❌"
        text += f"{emoji} {store['name']}\n"
        kb_rows.append([InlineKeyboardButton(
            text=f"{emoji} {store['name']}",
            callback_data=f"store_toggle:{store['id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("store_toggle:"))
async def cb_toggle_store(callback: CallbackQuery):
    store_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # AliExpress пока не доступен
    if store_id == 1:
        await callback.answer("❌ AliExpress временно недоступен (отсутствует маркировка ERID).", show_alert=True)
        return

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT 1 FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
            (user_id, store_id)
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                         (user_id, store_id))
        else:
            conn.execute("INSERT INTO user_category_preferences (user_id, category_id) VALUES (?, ?)",
                         (user_id, store_id))
        conn.commit()
    finally:
        conn.close()

    await cb_stores(callback)
    await callback.answer()
@router.callback_query(F.data.startswith("cat_toggle:"))
async def cb_toggle_category(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT 1 FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
            (user_id, cat_id)
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                         (user_id, cat_id))
        else:
            tariff = conn.execute(
                "SELECT t.max_categories FROM users u JOIN tariffs t ON u.tariff_id = t.id WHERE u.user_id = ?",
                (user_id,)
            ).fetchone()
            max_cat = tariff["max_categories"] if tariff and tariff["max_categories"] else 3
            current_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM user_category_preferences WHERE user_id = ?",
                (user_id,)
            ).fetchone()["cnt"]
            if current_count >= max_cat:
                await callback.answer(f"❌ Ваш тариф позволяет выбрать не более {max_cat} магазинов", show_alert=True)
                return
            conn.execute("INSERT INTO user_category_preferences (user_id, category_id) VALUES (?, ?)",
                         (user_id, cat_id))
        conn.commit()
    finally:
        conn.close()

    # Наполняем каталог по добавленной/удалённой категории
    keyword = None
    conn = get_db()
    try:
        cat = conn.execute("SELECT keyword FROM product_categories WHERE id = ?", (cat_id,)).fetchone()
        if cat:
            keyword = cat["keyword"]
    finally:
        conn.close()

    if keyword:
        await fetch_admitad_catalog(user_id, max_items=20)

    await cb_categories(callback)
    await callback.answer()

    if not existing and keyword:
        await callback.answer("✅ магазин добавлен, загружаем товары...", show_alert=False)
        await fetch_admitad_catalog(user_id, max_items=20)
        if saved > 0:
            await callback.answer(f"Загружено {saved} товаров", show_alert=True)
        else:
            await callback.answer("Товары не найдены, попробуйте позже", show_alert=True)

# ---------------------------------------------------------------------------
# Force Post
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "saas_force_post")
async def cb_saas_force_post(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer("🚀 Публикую пост из каталога...", show_alert=True)
    user_id = callback.from_user.id

    # Проверим, есть ли доступные товары с ERID, если нет — пополним каталог
    conn = get_db()
    try:
        product = conn.execute(
            "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL ORDER BY RANDOM() LIMIT 1",
            (user_id,)
        ).fetchone()
        if not product:
            # Попробуем быстро пополнить каталог из Admitad
            await fetch_admitad_catalog(user_id, max_items=20)
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
        await callback.message.answer(
            "❌ В каталоге пока нет товаров с маркировкой ERID. Попробуйте позже или выберите больше магазинов."
        )
        return

    # Подготовка данных
    partner_url = product['partner_url'] or ''
    title = product['title'] or ''
    price = product['price'] or 0
    currency = product['currency'] or '₽'
    advertiser = product['advertiser'] or 'Рекламодатель'
    erid = product['erid'] or ''
    photo_url = product["image_url"]
    source = product["source"] if "source" in product.keys() else ""

    # Получаем каналы пользователя
    conn = get_db()
    try:
        channels = conn.execute(
            "SELECT channel_id, sub_id FROM channels WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    if not channels:
        await callback.message.answer("❌ У вас нет активных каналов. Добавьте канал в разделе «Мои каналы».")
        return

    # Публикуем в каждый канал с SubID и пометкой 18+
    for ch in channels:
        final_url = partner_url
        if ch["sub_id"]:
            if '?' in final_url:
                final_url += '&subid=' + ch["sub_id"]
            else:
                final_url += '?subid=' + ch["sub_id"]

        adult_warning = ""
        if source == "Розовый кролик":
            adult_warning = "🔞 18+\n"

        caption = adult_warning + f"{title}\n\n"
        if price > 0:
            caption += f"💰 Цена: {price} {currency}\n\n"
        caption += f"👉 <a href='{final_url}'>Посмотреть и заказать</a>\n\n"
        caption += f"Реклама. {advertiser}. Erid: {erid}"

        await publish_post_with_fallback(
            bot=bot,
            channel_id=ch["channel_id"],
            caption=caption,
            photo_url=photo_url
        )
        await asyncio.sleep(1)

    await callback.message.answer("✅ Пост опубликован!")

# ---------------------------------------------------------------------------
# Настройка API-ключа GdeSlon
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "saas_set:gdeslon_apikey")
async def cb_saas_set_source(callback: CallbackQuery, state: FSMContext) -> None:
    text = (
        "📦 <b>Источник товаров: Admitad</b>\n\n"
        "Бот автоматически получает товары из магазинов-партнёров "
        "(Читай-город, AliExpress и др.) с готовой маркировкой ERID.\n"
        "API-ключ вводить не нужно — всё работает автоматически.\n\n"
        "<i>В будущем вы сможете подключить свой аккаунт Admitad для отслеживания статистики.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в настройки", callback_data="menu:settings")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.message(SaasStates.waiting_apikey)
async def msg_saas_text_input(message: Message, state: FSMContext) -> None:
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

    # Остальная старая логика (если input_type == "sku" или apikey) оставлена для совместимости,
    # но не актуальна; можно просто проигнорировать или оставить как есть.
    api_key = message.text.strip()
    user_id = message.from_user.id
    if api_key == "0":
        api_key = None
        ans_text = "🗑 API-ключ удалён."
    else:
        ans_text = "✅ API-ключ успешно сохранён!"
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

# ---------------------------------------------------------------------------
# Промокоды
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "promo:activate")
async def cb_promo_activate(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎁 Введите промокод:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")]
        ])
    )
    await state.set_state(SaasStates.waiting_promocode)
    await callback.answer()

@router.message(SaasStates.waiting_promocode)
async def promo_code_entered(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    conn = get_db()
    try:
        promo = conn.execute("SELECT * FROM promocodes WHERE code = ?", (code,)).fetchone()
        if not promo:
            await message.answer("❌ Неверный или несуществующий промокод.")
            await state.clear()
            return

        activation = conn.execute("SELECT * FROM promocode_activations WHERE code = ?", (code,)).fetchone()
        if activation:
            await message.answer("❌ Этот промокод уже использован.")
            await state.clear()
            return

        channels = conn.execute(
            "SELECT channel_id, channel_title FROM channels WHERE user_id = ? AND is_active = 1",
            (message.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    if not channels:
        await message.answer("❌ У вас нет подключённых каналов. Сначала добавьте канал в разделе «Мои каналы».")
        await state.clear()
        return

    await state.update_data(promocode=code, promo_days=promo["days"])

    kb_rows = []
    for ch in channels:
        kb_rows.append([InlineKeyboardButton(
            text=ch["channel_title"] or ch["channel_id"],
            callback_data=f"promo_channel:{ch['channel_id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")])

    await message.answer(
        "🎯 Выберите канал, для которого хотите активировать промокод:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )
    await state.set_state(SaasStates.choosing_channel_for_promo)

@router.callback_query(SaasStates.choosing_channel_for_promo, F.data.startswith("promo_channel:"))
async def promo_channel_selected(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.split(":")[1]
    data = await state.get_data()
    code = data.get("promocode")
    days = data.get("promo_days", 2)

    conn = get_db()
    try:
        existing = conn.execute("SELECT * FROM promocode_activations WHERE code = ?", (code,)).fetchone()
        if existing:
            await callback.message.answer("❌ Промокод уже использован.")
            await state.clear()
            return

        conn.execute(
            "INSERT INTO promocode_activations (code, user_id, channel_id) VALUES (?, ?, ?)",
            (code, callback.from_user.id, channel_id)
        )
        new_until = datetime.now(timezone.utc) + timedelta(days=days)
        conn.execute(
            "UPDATE users SET subscription_until = ?, is_active = 1 WHERE user_id = ?",
            (new_until.isoformat(), callback.from_user.id)
        )
        conn.commit()
    finally:
        conn.close()

    await callback.message.edit_text(
        f"✅ Промокод активирован!\nПодписка продлена на {days} дн. до {new_until.strftime('%d.%m.%Y %H:%M')} (UTC)."
    )
    await state.clear()
    await callback.answer("Готово!", show_alert=True)

# ---------------------------------------------------------------------------
# Тарифы и оплата
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:tariffs")
async def cb_tariffs(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "💎 <b>Выберите тариф:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_tariffs()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("buy:"))
async def cb_select_tariff(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return
    tariff_id = int(parts[1])
    days = int(parts[2])
    await state.update_data(chosen_tariff_id=tariff_id, chosen_days=days)
    await callback.message.edit_text(
        "💎 <b>Выберите способ оплаты:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_payment_methods()
    )
    await callback.answer()

@router.callback_query(F.data == "pay:stars")
async def cb_pay_stars(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    tariff_id = data.get("chosen_tariff_id")
    days = data.get("chosen_days")
    if not tariff_id:
        await callback.answer("❌ Сначала выберите тариф", show_alert=True)
        return

    conn = get_db()
    try:
        tariff = conn.execute("SELECT name, price_stars FROM tariffs WHERE id=?", (tariff_id,)).fetchone()
        if not tariff:
            await callback.answer("Тариф не найден", show_alert=True)
            return
        stars = tariff["price_stars"]
        name = tariff["name"]
    finally:
        conn.close()

    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Подписка {name}",
        description=f"Доступ на {days} дней ко всем функциям AutoPost.",
        payload=f"tariff_{tariff_id}_{days}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{name} ({days} дн.)", amount=stars)],
        provider_token="",
        start_parameter="subscribe",
    )
    await callback.message.edit_text(
        "⭐ <b>Счёт отправлен в чат!</b>\n\nОплатите его, и подписка активируется автоматически.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tariffs")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "pay:card")
async def cb_pay_card(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    tariff_id = data.get("chosen_tariff_id")
    days = data.get("chosen_days")
    if not tariff_id:
        await callback.answer("❌ Сначала выберите тариф", show_alert=True)
        return

    conn = get_db()
    try:
        tariff = conn.execute("SELECT name, price_rub FROM tariffs WHERE id=?", (tariff_id,)).fetchone()
        if not tariff:
            await callback.answer("Тариф не найден", show_alert=True)
            return
        rub = tariff["price_rub"]
        name = tariff["name"]
    finally:
        conn.close()

    order_code = f"T{tariff_id}-U{callback.from_user.id}"
    conn = get_db()
    conn.execute(
        "INSERT INTO payouts (user_id, amount_requested, amount_to_withdraw, amount_blogger, card, status) "
        "VALUES (?, ?, ?, ?, ?, 'pending')",
        (callback.from_user.id, rub, rub, 0, order_code)
    )
    conn.commit()
    conn.close()

    # Импорт реквизитов из main – временное решение через os.getenv
    import os
    CARD_SBER = os.getenv("PAY_SBER", "2202 2081 0829 0025")
    CARD_TBANK = os.getenv("PAY_TBANK", "2200 7013 7009 3863")
    CARD_VISA_KG = os.getenv("PAY_VISA_KG", "4196720087839790")
    CARD_TON = os.getenv("PAY_CRYPTO_TON", "UQCua97IuHkQy5F5NPHBray_FJRJoWZa1OOLnq-geGIbGT")

    text = (
        f"💳 <b>Оплата картой</b>\n\n"
        f"Тариф: <b>{name}</b> ({days} дн.)\n"
        f"Сумма: <b>{rub:.0f} ₽</b>\n\n"
        f"💬 <b>Ваш код заказа:</b> <code>{order_code}</code>\n"
        f"<i>Обязательно укажите этот код в комментарии к платежу!</i>\n\n"
        f"Сбер: <code>{CARD_SBER}</code>\n"
        f"Т-Банк: <code>{CARD_TBANK}</code>\n"
        f"Visa KG: <code>{CARD_VISA_KG}</code>\n\n"
        f"TON: <code>{CARD_TON}</code>\n\n"
        "После оплаты пришлите чек администратору.\n"
    )
    await callback.message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tariffs")]
        ])
    )
    await callback.answer()
