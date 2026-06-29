# handlers/saas.py
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery, Message, LabeledPrice,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from states import SaasStates, PaymentFSM
from services.db import get_db
from services.saas_core import publish_post_with_fallback
from services.admitad import fetch_admitad_catalog_for_user, ADULT_STORES
from keyboards.saas import kb_payment_methods

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
        user_row = conn.execute("SELECT tariff_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        max_stores = 3
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

    if store_id == 1:
        await callback.answer("❌ AliExpress временно недоступен (отсутствует маркировка ERID).", show_alert=True)
        return
    if store_id == 5:
        await callback.answer("❌ Love Republic временно недоступен (отсутствует маркировка ERID).", show_alert=True)
        return

    conn = get_db()
    try:
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
            conn.execute("DELETE FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                         (user_id, store_id))
        else:
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

    await cb_stores(callback)
    await callback.answer()


# ---------------------------------------------------------------------------
# Force Post
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "saas_force_post")
async def cb_saas_force_post(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer("🚀 Публикую пост из каталога...", show_alert=True)
    user_id = callback.from_user.id
    # Проверка кулдауна (1 минута)
    data = await state.get_data()
    last_force = data.get("last_force_post")
    if last_force:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last_force.replace("Z", "+00:00"))).total_seconds()
        if elapsed < 60:
            await callback.answer(f"⏳ Пожалуйста, подождите {int(60 - elapsed)} сек.", show_alert=True)
            return
    # Сохраняем время нажатия
    await state.update_data(last_force_post=datetime.now(timezone.utc).isoformat())
    
    conn = get_db()
    try:
        product = conn.execute(
            "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL ORDER BY RANDOM() LIMIT 1",
            (user_id,)
        ).fetchone()
        if not product:
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

    partner_url = product['partner_url'] or ''
    title = product['title'] or ''
    price = product['price'] or 0
    currency = product['currency'] or '₽'
    advertiser = product['advertiser'] or 'Рекламодатель'
    erid = product['erid'] or ''
    photo_url = product["image_url"]
    source = product["source"] if "source" in product.keys() else ""

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

        msg = await publish_post_with_fallback(
            bot=bot,
            channel_id=ch["channel_id"],
            caption=caption,
            photo_url=photo_url,
            has_spoiler=(source in ADULT_STORES)
        )
        if msg:
            direct_link = f"https://t.me/{ch['channel_id'].lstrip('@')}/{msg.message_id}" if ch['channel_id'] else ""
            donor_post_id = f"admitad_{product['id']}_{user_id}_{int(datetime.now(timezone.utc).timestamp())}"
            conn_rec = get_db()
            try:
                conn_rec.execute(
                    """INSERT INTO posts 
                    (user_id, donor_post_id, channel_id, target_channel_id, subid1, direct_link, status, published_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'published', ?)""",
                    (user_id, donor_post_id, ch['channel_id'], ch['channel_id'], ch['sub_id'], direct_link,
                     datetime.now(timezone.utc).isoformat())
                )
                conn_rec.commit()
            finally:
                conn_rec.close()
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
# Промокоды (активация командой /promo КОД)
# ---------------------------------------------------------------------------

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
# Запрос вывода средств (SaaS)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "payout:request")
async def cb_payout_request_start(callback: CallbackQuery, state: FSMContext):
    """Проверяет баланс и запрашивает номер карты."""
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT balance_available, payout_card FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
        available = user["balance_available"] if user else 0.0
        card = user["payout_card"] if user else None
    finally:
        conn.close()

    if available < 3000:
        await callback.answer(f"❌ Минимальная сумма для вывода – 3000 ₽. Ваш баланс: {available:.2f} ₽", show_alert=True)
        return

    # Если карта уже сохранена, показываем её и предлагаем сменить или сразу вывести
    if card:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Сменить карту", callback_data="payout:change_card_saas")],
            [InlineKeyboardButton(text="✅ Вывести на эту карту", callback_data="payout:confirm_saas")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:finance")]
        ])
        await callback.message.edit_text(
            f"💳 <b>Запрос вывода</b>\n\n"
            f"Текущая карта: <code>{card}</code>\n"
            f"Доступно к выводу: <b>{available:.2f} ₽</b>\n\n"
            f"Выберите действие:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )
        await state.update_data(payout_amount=available)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:finance")]
        ])
        await callback.message.edit_text(
            f"💳 <b>Запрос вывода</b>\n\n"
            f"Доступно к выводу: <b>{available:.2f} ₽</b>\n\n"
            f"Введите номер карты (16 цифр без пробелов) для получения выплаты:",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )
        await state.set_state(SaasStates.waiting_apikey)   # временно используем это состояние
        await state.update_data(payout_amount=available, waiting_payout_card=True)
    await callback.answer()


@router.callback_query(F.data == "payout:change_card_saas")
async def cb_payout_change_card_saas(callback: CallbackQuery, state: FSMContext):
    """Запрашивает новую карту."""
    await callback.message.edit_text(
        "💳 Введите новый номер карты (16 цифр без пробелов):",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:finance")]
        ])
    )
    await state.set_state(SaasStates.waiting_apikey)
    await state.update_data(waiting_payout_card=True)
    await callback.answer()


@router.callback_query(F.data == "payout:confirm_saas")
async def cb_payout_confirm_saas(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Подтверждает вывод на существующую карту."""
    data = await state.get_data()
    amount = data.get("payout_amount", 0)
    user_id = callback.from_user.id

    conn = get_db()
    try:
        user = conn.execute("SELECT balance_available, payout_card FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user or user["balance_available"] < amount:
            await callback.answer("❌ Недостаточно средств или сумма изменилась.", show_alert=True)
            return

        card = user["payout_card"]
        # Списываем сумму и создаём заявку
        conn.execute("UPDATE users SET balance_available = balance_available - ? WHERE user_id=?", (amount, user_id))
        conn.execute(
            "INSERT INTO payouts (user_id, amount_requested, amount_to_withdraw, amount_blogger, card, status) "
            "VALUES (?, ?, ?, ?, ?, 'pending')",
            (user_id, amount, amount, amount, card)
        )
        payout_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        conn.commit()
    finally:
        conn.close()

    # Уведомление админам
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💸 <b>Новая заявка на вывод #{payout_id}</b>\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"💳 Карта: <code>{card}</code>\n"
                f"💰 Сумма: <b>{amount:.2f} ₽</b>\n\n"
                f"<i>Переведите средства и нажмите кнопку ниже.</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Отправлено", callback_data=f"payout:done:{payout_id}:{user_id}")]
                ])
            )
        except:
            pass

    await callback.message.edit_text(
        f"✅ <b>Заявка создана!</b>\n\n"
        f"Сумма: <b>{amount:.2f} ₽</b> будет переведена на карту <code>{card}</code>.\n"
        f"Ожидайте уведомления о выполнении.",
        parse_mode=ParseMode.HTML
    )
    await state.clear()
    await callback.answer()



# ---------------------------------------------------------------------------
# Финансы (история транзакций Admitad) с дисклеймером
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:finance")
async def cb_finance(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        transactions = conn.execute("""
            SELECT admitad_id, payment_sum, currency, payment_status, order_id, action, time
            FROM admitad_transactions
            WHERE user_id = ?
            ORDER BY time DESC
            LIMIT 20
        """, (user_id,)).fetchall()
    finally:
        conn.close()

    disclaimer = (
        "⚠️ <b>Важная информация о начислениях:</b>\n"
        "• Деньги за заказы сначала попадают в <b>«В ожидании»</b>. "
        "Рекламодатели проверяют заказы на предмет возврата.\n"
        "• Средний срок подтверждения: от 30 до 60 дней (зависит от магазина).\n"
        "• Как только магазин подтверждает покупку, деньги переходят в <b>«Доступно к выводу»</b>.\n"
        "• Любые попытки накрутки, самовыкупов, спам-рассылок или рекламы на бренд запрещены. "
        "При обнаружении нарушений аккаунт блокируется без выплаты средств.\n"
        "• Вывод средств возможен при достижении порога <b>3000 ₽</b>.\n\n"
    )

    if not transactions:
        text = (
            "💰 <b>Финансы</b>\n\n"
            "У вас пока нет заказов. Как только по партнёрской ссылке совершат покупку, "
            "вы увидите её здесь.\n\n"
            "<i>Баланс можно посмотреть в Личном кабинете.</i>"
        )
    else:
        text = "💰 <b>Последние 20 транзакций</b>\n\n"
        for t in transactions:
            status_emoji = {
                "pending": "⏳",
                "approved": "✅",
                "declined": "❌",
                "new": "🆕",
                "waiting": "⏳",
                "paid": "💳"
            }.get(t["payment_status"], "❓")
            date_str = ""
            if t["time"]:
                try:
                    dt = datetime.fromtimestamp(int(t["time"]), tz=timezone.utc)
                    date_str = dt.strftime("%d.%m.%Y %H:%M")
                except:
                    date_str = str(t["time"])
            text += (
                f"{status_emoji} <b>{t['payment_sum']} {t['currency']}</b> "
                f"(статус: {t['payment_status']})\n"
                f"   Заказ #{t['order_id'] or '—'}, действие: {t['action'] or '—'}, "
                f"ID: {t['admitad_id']}\n"
                f"   Дата: {date_str}\n\n"
            )

    full_text = disclaimer + text

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")]
    ])

    try:
        await callback.message.edit_text(full_text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        await callback.message.answer(full_text, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer()

# ---------------------------------------------------------------------------
# Оферта (публичная)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:oferta")
async def cb_oferta(callback: CallbackQuery):
    text = (
        "<b>📜 ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ (ПУБЛИЧНАЯ ОФЕРТА)</b>\n"
        "<i>Последняя редакция: 28 июня 2026 года</i>\n\n"
        "Нажимая «Принимаю», вы соглашаетесь с условиями.\n\n"
        "<b>1. Термины</b>\n"
        "• <b>Сервис</b> – данный Telegram-бот.\n"
        "• <b>CPA-сеть</b> – партнёрская сеть Admitad.\n"
        "• <b>SubID</b> – уникальный цифровой идентификатор вашего канала.\n"
        "• <b>Баланс</b> – справочные данные о вознаграждении, не электронные деньги.\n\n"
        "<b>2. Предмет</b>\n"
        "Вы получаете доступ к автопостингу товаров с партнёрскими ссылками. "
        "Сервис удерживает комиссию <b>5%</b> от подтверждённого вознаграждения.\n\n"
        "<b>3. Учёт и выплаты</b>\n"
        "• Единственный источник данных о заказах – CPA-сеть.\n"
        "• <b>В ожидании</b> – заказы на проверке у рекламодателя (30–90 дней).\n"
        "• <b>Доступно к выводу</b> – подтверждённые заказы, готовые к выплате.\n"
        "• Выплата производится по запросу, за вычетом 5%.\n\n"
        "<b>4. Запрещено</b>\n"
        "Спам, накрутка, самовыкупы, мотивированный трафик, брендовая реклама. "
        "Публикация ссылок разрешена только в добавленных каналах.\n\n"
        "<b>5. Ответственность</b>\n"
        "• Выплаты ограничены суммами, реально полученными от CPA-сети.\n"
        "• При фроде или блокировке аккаунта баланс аннулируется.\n"
        "• Администрация может заморозить выплаты на время проверки (до 90 дней).\n\n"
        "<b>6. Изменения</b>\n"
        "Администрация может менять условия. Продолжение использования – согласие с новой редакцией."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принимаю", callback_data="oferta:accept")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
    ])
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "oferta:accept")
async def cb_oferta_accept(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET oferta_accepted=1 WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    await callback.answer("✅ Вы приняли условия Оферты.", show_alert=True)
    # Возвращаем в кабинет
    from main import show_user_cabinet
    await show_user_cabinet(callback.message, user_id=user_id)
