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
from services.admitad import fetch_admitad_catalog_for_user  # обновлённая функция
from keyboards.saas import kb_payment_methods
from services.admitad import ADULT_STORES
from aiogram.filters import Command

router = Router(name="saas")
# handlers/saas.py
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery, Message, LabeledPrice,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from states import SaasStates, PaymentFSM
from services.db import get_db
from services.saas_core import publish_post_with_fallback
from services.admitad import fetch_admitad_catalog_for_user
from keyboards.saas import kb_payment_methods
from services.admitad import ADULT_STORES

logger = logging.getLogger("autopost_bot.saas")

router = Router(name="saas")

# ---------------------------------------------------------------------------
# Магазины
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:categories")
async def cb_stores(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        # Получаем тариф пользователя и его лимит магазинов
        user_row = conn.execute("SELECT tariff_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        max_stores = 3  # значение по умолчанию
        if user_row and user_row["tariff_id"]:
            tariff_row = conn.execute("SELECT max_stores FROM tariffs WHERE id=?", (user_row["tariff_id"],)).fetchone()
            if tariff_row and tariff_row["max_stores"]:
                max_stores = tariff_row["max_stores"]

        user_stores = conn.execute(
            "SELECT category_id FROM user_category_preferences WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        user_store_ids = {r["category_id"] for r in user_stores}
        selected_count = len(user_store_ids)
    finally:
        conn.close()

    stores = [
        {"id": 1, "name": "AliExpress (пока недоступен)"},
        {"id": 2, "name": "Читай-город"},
        {"id": 3, "name": "Аквафор"},
        {"id": 4, "name": "Розовый кролик (18+)"},
        {"id": 5, "name": "Love Republic (пока недоступен)"},
        {"id": 6, "name": "Hi Store RU"},
        {"id": 7, "name": "KANZLER"},
        {"id": 8, "name": "KIKO MILANO"},
        {"id": 9, "name": "Moulinex"},
        {"id": 10, "name": "Playtoday"},
        {"id": 11, "name": "SELA"},
    ]

    text = f"🏪 <b>Выберите магазины для постинга:</b> (выбрано {selected_count}/{max_stores})\n\n"
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

    # Заглушки для недоступных магазинов
    if store_id == 1:  # AliExpress
        await callback.answer("❌ AliExpress временно недоступен (отсутствует маркировка ERID).", show_alert=True)
        return
    if store_id == 5:  # Love Republic
        await callback.answer("❌ Love Republic временно недоступен (отсутствует маркировка ERID).", show_alert=True)
        return

    conn = get_db()
    try:
        # Получаем лимит магазинов
        user_row = conn.execute("SELECT tariff_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        max_stores = 3
        if user_row and user_row["tariff_id"]:
            tariff_row = conn.execute("SELECT max_stores FROM tariffs WHERE id=?", (user_row["tariff_id"],)).fetchone()
            if tariff_row and tariff_row["max_stores"]:
                max_stores = tariff_row["max_stores"]

        existing = conn.execute(
            "SELECT 1 FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
            (user_id, store_id)
        ).fetchone()
        if existing:
            # Удаляем магазин
            conn.execute("DELETE FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                         (user_id, store_id))
        else:
            # Проверяем, не превышен ли лимит
            current_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM user_category_preferences WHERE user_id = ?",
                (user_id,)
            ).fetchone()["cnt"]
            if current_count >= max_stores:
                await callback.answer(f"❌ Ваш тариф позволяет выбрать не более {max_stores} магазинов.", show_alert=True)
                return
            conn.execute("INSERT INTO user_category_preferences (user_id, category_id) VALUES (?, ?)",
                         (user_id, store_id))
        conn.commit()
    finally:
        conn.close()

    # После изменения выбора обновляем сообщение
    await cb_stores(callback)
    await callback.answer()


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
            # Попробуем быстро пополнить каталог из Admitad (только выбранные магазины)
            await fetch_admitad_catalog_for_user(user_id, max_items_per_store=50)
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
        if source in ADULT_STORES:
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
            photo_url=photo_url,
            has_spoiler=(source in ADULT_STORES)
        )
        await asyncio.sleep(1)

    await callback.message.answer("✅ Пост опубликован!")


# ---------------------------------------------------------------------------
# Настройка источника товаров (заглушка)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "saas_set:gdeslon_apikey")
async def cb_saas_set_source(callback: CallbackQuery, state: FSMContext) -> None:
    text = (
        "📦 <b>Источник товаров: Admitad</b>\n\n"
        "Бот автоматически получает товары из магазинов-партнёров "
        "(Читай-город, Hi Store, KANZLER и др.) с готовой маркировкой ERID.\n"
        "API-ключ вводить не нужно — всё работает автоматически.\n\n"
        "Вы можете выбрать магазины в разделе «🏪 Магазины»."
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
            ans_text = "🗑 API-ключ удалён."
        else:
            ans_text = "✅ API-ключ сохранён!"
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

    # Остальная логика (если не gdeslon_apikey) – без изменений
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
# Промокоды (надёжный способ без FSM-фильтра)
# ---------------------------------------------------------------------------

@router.message(Command("promo"))
async def cmd_promo(message: Message, state: FSMContext):
    await state.update_data(waiting_promo=True)
    await message.answer(
        "🎁 Введите промокод прямо сейчас в чат:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")]
        ])
    )


@router.message(F.text)
async def handle_all_text(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("waiting_promo"):
        return

    code = message.text.strip().upper()
    logger.info(f"[PROMO] Пользователь {message.from_user.id} ввёл код: {code}")

    conn = get_db()
    try:
        promo = conn.execute("SELECT * FROM promocodes WHERE code = ?", (code,)).fetchone()
        if not promo:
            await message.answer("❌ Неверный или несуществующий промокод.")
            await state.update_data(waiting_promo=False)
            return

        activation = conn.execute("SELECT * FROM promocode_activations WHERE code = ?", (code,)).fetchone()
        if activation:
            await message.answer("❌ Этот промокод уже использован.")
            await state.update_data(waiting_promo=False)
            return

        channels = conn.execute(
            "SELECT channel_id, channel_title FROM channels WHERE user_id = ? AND is_active = 1",
            (message.from_user.id,)
        ).fetchall()
    finally:
        conn.close()

    if not channels:
        await message.answer("❌ У вас нет подключённых каналов.")
        await state.update_data(waiting_promo=False)
        return

    days = int(promo["days"])

    if len(channels) == 1:
        # Один канал — активируем сразу
        channel_id = channels[0]["channel_id"]
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO promocode_activations (code, user_id, channel_id) VALUES (?, ?, ?)",
                (code, message.from_user.id, channel_id)
            )
            new_until = datetime.now(timezone.utc) + timedelta(days=days)
            conn.execute(
                "UPDATE users SET subscription_until = ?, is_active = 1 WHERE user_id = ?",
                (new_until.isoformat(), message.from_user.id)
            )
            conn.commit()
        finally:
            conn.close()

        await message.answer(f"✅ Промокод активирован!\nПодписка продлена на {days} дней.")
        await state.update_data(waiting_promo=False)
        return

    # Несколько каналов — показываем выбор
    await state.update_data(promocode=code, promo_days=days, waiting_promo=False)
    kb_rows = []
    for ch in channels:
        kb_rows.append([InlineKeyboardButton(
            text=ch["channel_title"] or ch["channel_id"],
            callback_data=f"promo_channel:{ch['channel_id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")])

    await message.answer(
        "🎯 Выберите канал для активации промокода:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )


@router.callback_query(F.data.startswith("promo_channel:"))
async def promo_channel_selected(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.split(":")[1]
    data = await state.get_data()
    code = data.get("promocode")
    days = data.get("promo_days", 2)

    if not code or not days:
        await callback.answer("❌ Сессия истекла, попробуйте снова.", show_alert=True)
        return

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
def kb_tariffs() -> InlineKeyboardMarkup:
    from config import load_tariffs
    tariffs = load_tariffs()

    # Группируем тарифы по названию (Базовый, Профи, VIP)
    groups = {}
    for t in tariffs:
        base_name = t['name'].split('(')[0].strip()
        if base_name not in groups:
            groups[base_name] = []
        groups[base_name].append(t)

    order = ['Базовый', 'Профи', 'VIP']
    sorted_groups = {k: groups[k] for k in order if k in groups}

    rows = []
    for level, items in sorted_groups.items():
        emoji = {'Базовый': '🟢', 'Профи': '🔵', 'VIP': '👑'}.get(level, '⭐')
        rows.append([InlineKeyboardButton(text=f"{emoji} {level}", callback_data="none")])

        items.sort(key=lambda x: x['days'])
        for t in items:
            text = (
                f"📅 {t['days']} дн. — 💰 {t['price_rub']:.0f} ₽ | "
                f"📢 {t['max_channels']}кан. 🏪 {t['max_stores']}маг. 📬 {t['max_posts_per_day']}пост/д"
            )
            rows.append([InlineKeyboardButton(
                text=text,
                callback_data=f"buy:{t['id']}:{t['days']}"
            )])

    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "menu:tariffs")
async def cb_tariffs(callback: CallbackQuery) -> None:
    text = (
        "💎 <b>Выберите тарифный план</b>\n\n"
        "<u>Что входит в любой тариф:</u>\n"
        "• Автоматический постинг товаров из выбранных магазинов\n"
        "• Уникальные описания (ИИ-рерайт)\n"
        "• Маркировка рекламы (ERID) — всё по закону\n"
        "• Отслеживание продаж через SubID\n"
        "• Авто-закрепление постов (опционально)\n\n"
        "<i>Чем выше уровень — тем больше каналов, магазинов и постов в день.</i>"
    )
    await callback.message.edit_text(
        text,
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
# ---------------------------------------------------------------------------
# Магазины
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:categories")
async def cb_stores(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        # Получаем тариф пользователя и его лимит магазинов
        user_row = conn.execute("SELECT tariff_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        max_stores = 3  # значение по умолчанию
        if user_row and user_row["tariff_id"]:
            tariff_row = conn.execute("SELECT max_stores FROM tariffs WHERE id=?", (user_row["tariff_id"],)).fetchone()
            if tariff_row and tariff_row["max_stores"]:
                max_stores = tariff_row["max_stores"]

        user_stores = conn.execute("SELECT category_id FROM user_category_preferences WHERE user_id = ?", (user_id,)).fetchall()
        user_store_ids = {r["category_id"] for r in user_stores}
        selected_count = len(user_store_ids)
    finally:
        conn.close()

    stores = [
        {"id": 1, "name": "AliExpress (пока недоступен)"},
        {"id": 2, "name": "Читай-город"},
        {"id": 3, "name": "Аквафор"},
        {"id": 4, "name": "Розовый кролик (18+)"},
        {"id": 5, "name": "Love Republic (пока недоступен)"},
        {"id": 6, "name": "Hi Store RU"},
        {"id": 7, "name": "KANZLER"},
        {"id": 8, "name": "KIKO MILANO"},
        {"id": 9, "name": "Moulinex"},
        {"id": 10, "name": "Playtoday"},
        {"id": 11, "name": "SELA"},
    ]

    text = f"🏪 <b>Выберите магазины для постинга:</b> (выбрано {selected_count}/{max_stores})\n\n"
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

    # Заглушки для недоступных магазинов
    if store_id == 1:  # AliExpress
        await callback.answer("❌ AliExpress временно недоступен (отсутствует маркировка ERID).", show_alert=True)
        return
    if store_id == 5:  # Love Republic
        await callback.answer("❌ Love Republic временно недоступен (отсутствует маркировка ERID).", show_alert=True)
        return

    conn = get_db()
    try:
        # Получаем лимит магазинов
        user_row = conn.execute("SELECT tariff_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        max_stores = 3
        if user_row and user_row["tariff_id"]:
            tariff_row = conn.execute("SELECT max_stores FROM tariffs WHERE id=?", (user_row["tariff_id"],)).fetchone()
            if tariff_row and tariff_row["max_stores"]:
                max_stores = tariff_row["max_stores"]

        existing = conn.execute(
            "SELECT 1 FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
            (user_id, store_id)
        ).fetchone()
        if existing:
            # Удаляем магазин
            conn.execute("DELETE FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                         (user_id, store_id))
        else:
            # Проверяем, не превышен ли лимит
            current_count = conn.execute("SELECT COUNT(*) as cnt FROM user_category_preferences WHERE user_id = ?",
                                         (user_id,)).fetchone()["cnt"]
            if current_count >= max_stores:
                await callback.answer(f"❌ Ваш тариф позволяет выбрать не более {max_stores} магазинов.", show_alert=True)
                return
            conn.execute("INSERT INTO user_category_preferences (user_id, category_id) VALUES (?, ?)",
                         (user_id, store_id))
        conn.commit()
    finally:
        conn.close()

    # После изменения выбора обновляем сообщение
    await cb_stores(callback)
    await callback.answer()


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
            # Попробуем быстро пополнить каталог из Admitad (только выбранные магазины)
            await fetch_admitad_catalog_for_user(user_id, max_items_per_store=50)
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
        if source in ADULT_STORES:
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
            photo_url=photo_url,
            has_spoiler=(source in ADULT_STORES)
        )
        await asyncio.sleep(1)

    await callback.message.answer("✅ Пост опубликован!")


# ---------------------------------------------------------------------------
# Настройка источника товаров (заглушка)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "saas_set:gdeslon_apikey")
async def cb_saas_set_source(callback: CallbackQuery, state: FSMContext) -> None:
    text = (
        "📦 <b>Источник товаров: Admitad</b>\n\n"
        "Бот автоматически получает товары из магазинов-партнёров "
        "(Читай-город, Hi Store, KANZLER и др.) с готовой маркировкой ERID.\n"
        "API-ключ вводить не нужно — всё работает автоматически.\n\n"
        "Вы можете выбрать магазины в разделе «🏪 Магазины»."
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
            ans_text = "🗑 API-ключ удалён."
        else:
            ans_text = "✅ API-ключ сохранён!"
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

    # Остальная логика (если не gdeslon_apikey) – без изменений
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
# Промокоды (надёжный способ без привязки к FSM)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "promo:activate")
async def cb_promo_activate(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SaasStates.waiting_promocode)  # ← должно быть
    await callback.message.edit_text(
        "🎁 Введите промокод прямо сейчас в чат:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")]
        ])
    )
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
        await message.answer("❌ У вас нет подключённых каналов.")
        await state.clear()
        return

    days = int(promo["days"])

    if len(channels) == 1:
        channel_id = channels[0]["channel_id"]
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO promocode_activations (code, user_id, channel_id) VALUES (?, ?, ?)",
                (code, message.from_user.id, channel_id)
            )
            new_until = datetime.now(timezone.utc) + timedelta(days=days)
            conn.execute(
                "UPDATE users SET subscription_until = ?, is_active = 1 WHERE user_id = ?",
                (new_until.isoformat(), message.from_user.id)
            )
            conn.commit()
        finally:
            conn.close()

        await message.answer(f"✅ Промокод активирован!\nПодписка продлена на {days} дней.")
        await state.clear()
        return

    await state.update_data(promocode=code, promo_days=days)
    kb_rows = []
    for ch in channels:
        kb_rows.append([InlineKeyboardButton(
            text=ch["channel_title"] or ch["channel_id"],
            callback_data=f"promo_channel:{ch['channel_id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="cabinet:open")])

    await message.answer(
        "🎯 Выберите канал для активации промокода:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )

@router.callback_query(F.data.startswith("promo_channel:"))
async def promo_channel_selected(callback: CallbackQuery, state: FSMContext):
    channel_id = callback.data.split(":")[1]
    data = await state.get_data()
    code = data.get("promocode")
    days = data.get("promo_days", 2)

    if not code or not days:
        await callback.answer("❌ Сессия истекла, попробуйте снова.", show_alert=True)
        return

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
def kb_tariffs() -> InlineKeyboardMarkup:
    from config import load_tariffs
    tariffs = load_tariffs()

    # Группируем тарифы по названию (Базовый, Профи, VIP)
    groups = {}
    for t in tariffs:
        base_name = t['name'].split('(')[0].strip()
        if base_name not in groups:
            groups[base_name] = []
        groups[base_name].append(t)

    order = ['Базовый', 'Профи', 'VIP']
    sorted_groups = {k: groups[k] for k in order if k in groups}

    rows = []
    for level, items in sorted_groups.items():
        emoji = {'Базовый': '🟢', 'Профи': '🔵', 'VIP': '👑'}.get(level, '⭐')
        rows.append([InlineKeyboardButton(text=f"{emoji} {level}", callback_data="none")])

        items.sort(key=lambda x: x['days'])
        for t in items:
            text = (
                f"📅 {t['days']} дн. — 💰 {t['price_rub']:.0f} ₽ | "
                f"📢 {t['max_channels']}кан. 🏪 {t['max_stores']}маг. 📬 {t['max_posts_per_day']}пост/д"
            )
            rows.append([InlineKeyboardButton(
                text=text,
                callback_data=f"buy:{t['id']}:{t['days']}"
            )])

    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "menu:tariffs")
async def cb_tariffs(callback: CallbackQuery) -> None:
    text = (
        "💎 <b>Выберите тарифный план</b>\n\n"
        "<u>Что входит в любой тариф:</u>\n"
        "• Автоматический постинг товаров из выбранных магазинов\n"
        "• Уникальные описания (ИИ-рерайт)\n"
        "• Маркировка рекламы (ERID) — всё по закону\n"
        "• Отслеживание продаж через SubID\n"
        "• Авто-закрепление постов (опционально)\n\n"
        "<i>Чем выше уровень — тем больше каналов, магазинов и постов в день.</i>"
    )
    await callback.message.edit_text(
        text,
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
