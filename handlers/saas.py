# handlers/saas.py
import asyncio
import logging
import os
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
from services.admitad import fetch_admitad_catalog_for_user, ADULT_STORES, get_delivery_for_store, STORE_ID_MAP
from keyboards.saas import kb_payment_methods
from services.text_rewriter import generate_post_text
from services.admitad import get_random_promocode
from states import SaasStates, PaymentFSM, PayoutStates, TaxStates

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
        {"id": 3, "name": "Аквафор (пока недоступен)"},
        {"id": 4, "name": "Розовый кролик (18+)"},
        {"id": 5, "name": "Love Republic (пока недоступен)"},
        {"id": 6, "name": "Hi Store RU"},
        {"id": 7, "name": "KANZLER"},
        {"id": 8, "name": "KIKO MILANO"},
        {"id": 9, "name": "Moulinex"},
        {"id": 10, "name": "Playtoday"},
        {"id": 11, "name": "SELA"},
        {"id": 12, "name": "Galaxy Store (Pro/VIP)"},
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

    # Обработка Galaxy Store
    if store_id == 12:
        conn = get_db()
        try:
            user_row = conn.execute(
                "SELECT tariff_id FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
            if not user_row or not user_row["tariff_id"]:
                await callback.answer("❌ Galaxy Store доступен только на тарифе Pro и VIP.", show_alert=True)
                return
            tariff = conn.execute(
                "SELECT name FROM tariffs WHERE id=?", (user_row["tariff_id"],)
            ).fetchone()
            if not tariff or tariff["name"] not in ["Профи", "VIP"]:
                await callback.answer("❌ Galaxy Store доступен только на тарифе Pro и VIP.", show_alert=True)
                return
        finally:
            conn.close()

        # Проверяем, включён ли уже Galaxy Store
        conn = get_db()
        try:
            exists = conn.execute(
                "SELECT 1 FROM user_category_preferences WHERE user_id = ? AND category_id = 12",
                (user_id,)
            ).fetchone()
        finally:
            conn.close()
        if exists:
            # Удаляем
            conn = get_db()
            try:
                conn.execute(
                    "DELETE FROM user_category_preferences WHERE user_id = ? AND category_id = 12",
                    (user_id,)
                )
                conn.commit()
            finally:
                conn.close()
            await callback.answer("Galaxy Store удалён из ваших магазинов.")
            await cb_stores(callback)
            return
        else:
            # Показываем выбор города
            await show_city_selection(callback.message, user_id)
            await callback.answer()
            return

    # Стандартная логика для остальных магазинов
    if store_id == 1:
        await callback.answer("❌ AliExpress временно недоступен (отсутствует маркировка ERID).", show_alert=True)
        return
    if store_id == 3:
        await callback.answer("❌ Аквафор временно недоступен.", show_alert=True)
        return
    if store_id == 5:
        await callback.answer("❌ Love Republic временно недоступен (отсутствует маркировка ERID).", show_alert=True)
        return

    conn = get_db()
    try:
        # Получаем роль и тариф пользователя
        user_row = conn.execute("SELECT role, tariff_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        max_stores = 3

        # Проверка лимита только для SaaS, не для блогеров
        if user_row and user_row["role"] != "blogger" and user_row["tariff_id"]:
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
            if current_count >= max_stores and user_row["role"] != "blogger":
                await callback.answer(f"❌ Ваш тариф позволяет выбрать не более {max_stores} магазинов.", show_alert=True)
                return
            conn.execute("INSERT INTO user_category_preferences (user_id, category_id) VALUES (?, ?)",
                         (user_id, store_id))
        conn.commit()
    finally:
        conn.close()

    await cb_stores(callback)
    await callback.answer()

@router.callback_query(F.data == "promo:activate")
async def cb_promo_activate(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "🎁 Введите промокод (просто отправьте код, без команды /promo):"
    )
    await state.set_state(SaasStates.waiting_promocode)
    await callback.answer()

@router.message(SaasStates.waiting_promocode)
async def process_promocode_input(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    logger.info(f"[PROMO] Пользователь {message.from_user.id} ввёл код через кнопку: {code}")

    conn = get_db()
    try:
        # Ищем промокод без учёта регистра (приводим оба к верхнему)
        promo = conn.execute(
            "SELECT * FROM promocodes WHERE UPPER(code) = ?", (code,)
        ).fetchone()
        if not promo:
            await message.answer("❌ Неверный или несуществующий промокод.")
            await state.clear()
            return

        activation = conn.execute(
            "SELECT * FROM promocode_activations WHERE UPPER(code) = ?", (code,)
        ).fetchone()
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
                (promo["code"], message.from_user.id, channel_id)  # сохраняем оригинальный код
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
    else:
        # Несколько каналов – выбор (аналогично /promo)
        await state.update_data(promocode=promo["code"], promo_days=days)
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

    await state.clear()

@router.callback_query(F.data == "share_success")
async def cb_share_success(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        role = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()["role"]
    finally:
        conn.close()
    text = await generate_success_text(user_id, role)
    await callback.message.answer(text, parse_mode=ParseMode.HTML)
    await callback.answer("✅ Текст скопирован в следующее сообщение. Можете переслать его!", show_alert=True)
# ---------------------------------------------------------------------------
# Galaxy Store – выбор города
# ---------------------------------------------------------------------------
# Заглушка для CITY_DATA, если модуль catalog отсутствует
try:
    from catalog import CITY_DATA, get_city_name
except ImportError:
    # Если модуля нет, используем пустые данные, чтобы бот не падал
    CITY_DATA = {}
    def get_city_name(key):
        return key

async def show_city_selection(message: Message, user_id: int):
    if not CITY_DATA:
        await message.answer("Модуль выбора города временно недоступен.")
        return
    buttons = []
    for key, (rus_name, _) in CITY_DATA.items():
        buttons.append(InlineKeyboardButton(
            text=rus_name,
            callback_data=f"galaxy_city:{key}"
        ))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_galaxy_city")])
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.edit_text(
        "🏙 <b>Выберите ваш город для Galaxy Store:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=markup
    )


@router.callback_query(F.data.startswith("galaxy_city:"))
async def cb_galaxy_city_selected(callback: CallbackQuery):
    city_key = callback.data.split(":")[1]
    user_id = callback.from_user.id
    city_name = get_city_name(city_key)

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT 1 FROM user_category_preferences WHERE user_id = ? AND category_id = 12",
            (user_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE user_category_preferences SET city = ? WHERE user_id = ? AND category_id = 12",
                (city_key, user_id)
            )
        else:
            user_row = conn.execute("SELECT tariff_id FROM users WHERE user_id=?", (user_id,)).fetchone()
            max_stores = 3
            if user_row and user_row["tariff_id"]:
                tariff_row = conn.execute("SELECT max_stores FROM tariffs WHERE id=?", (user_row["tariff_id"],)).fetchone()
                if tariff_row and tariff_row["max_stores"]:
                    max_stores = tariff_row["max_stores"]
            current_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM user_category_preferences WHERE user_id = ?",
                (user_id,)
            ).fetchone()["cnt"]
            if current_count >= max_stores:
                await callback.answer(f"❌ Ваш тариф позволяет выбрать не более {max_stores} магазинов.", show_alert=True)
                return
            conn.execute(
                "INSERT INTO user_category_preferences (user_id, category_id, city) VALUES (?, ?, ?)",
                (user_id, 12, city_key)
            )
        conn.commit()
    finally:
        conn.close()

    await callback.answer(f"✅ Galaxy Store ({city_name}) добавлен в ваши магазины.")
    await cb_stores(callback)


@router.callback_query(F.data == "cancel_galaxy_city")
async def cb_cancel_galaxy_city(callback: CallbackQuery):
    await cb_stores(callback)
    await callback.answer()


# ---------------------------------------------------------------------------
# Force Post (единая логика)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "saas_force_post")
async def cb_saas_force_post(callback: CallbackQuery, bot: Bot) -> None:
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT force_preview_confirmed FROM users WHERE user_id = ?", (user_id,)).fetchone()
        preview_confirmed = bool(user["force_preview_confirmed"]) if user else False
    finally:
        conn.close()

    if preview_confirmed:
        await callback.answer("🚀 Публикую пост...", show_alert=True)
        await _force_post_immediate(callback, bot, user_id)
        return

    await callback.answer("🔍 Подбираю товар для предпросмотра...", show_alert=False)
    await _force_post_preview(callback, bot, user_id)


async def _force_post_immediate(callback: CallbackQuery, bot: Bot, user_id: int) -> None:
    conn = get_db()
    try:
        user_stores = conn.execute("SELECT category_id FROM user_category_preferences WHERE user_id = ?", (user_id,)).fetchall()
        store_ids = [r["category_id"] for r in user_stores]
        user_tmpl = conn.execute("SELECT product_template FROM users WHERE user_id = ?", (user_id,)).fetchone()
        custom_template = user_tmpl["product_template"] if user_tmpl and user_tmpl["product_template"] else None
        min_disc = conn.execute("SELECT min_discount FROM users WHERE user_id = ?", (user_id,)).fetchone()
        min_discount = min_disc["min_discount"] if min_disc else 0
    finally:
        conn.close()

    allowed_sources = [STORE_ID_MAP[sid] for sid in store_ids if sid in STORE_ID_MAP]

    conn = get_db()
    try:
        if allowed_sources:
            placeholders = ','.join('?' * len(allowed_sources))
            product = conn.execute(
                f"SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL AND source IN ({placeholders}) AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                (user_id, *allowed_sources, min_discount)
            ).fetchone()
        else:
            product = None

        if not product:
            if allowed_sources:
                conn.execute(
                    f"UPDATE gdeslon_catalog SET used = 0 WHERE user_id = ? AND source IN ({placeholders})",
                    (user_id, *allowed_sources)
                )
                conn.commit()
                product = conn.execute(
                    f"SELECT * FROM gdeslon_catalog WHERE user_id = ? AND erid != '' AND erid IS NOT NULL AND source IN ({placeholders}) AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                    (user_id, *allowed_sources, min_discount)
                ).fetchone()
            else:
                product = conn.execute(
                    "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                    (user_id, min_discount)
                ).fetchone()
                if not product:
                    conn.execute("UPDATE gdeslon_catalog SET used = 0 WHERE user_id = ?", (user_id,))
                    conn.commit()
                    product = conn.execute(
                        "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND erid != '' AND erid IS NOT NULL AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                        (user_id, min_discount)
                    ).fetchone()

        if product:
            conn.execute("UPDATE gdeslon_catalog SET used = 1 WHERE id = ?", (product["id"],))
            conn.commit()
    finally:
        conn.close()

    if not product:
        await callback.message.answer("❌ В каталоге пока нет товаров с маркировкой ERID.")
        return

    await _publish_product(callback, bot, user_id, product, custom_template)


async def _force_post_preview(callback: CallbackQuery, bot: Bot, user_id: int) -> None:
    conn = get_db()
    try:
        user_stores = conn.execute("SELECT category_id FROM user_category_preferences WHERE user_id = ?", (user_id,)).fetchall()
        store_ids = [r["category_id"] for r in user_stores]
        user_tmpl = conn.execute("SELECT product_template FROM users WHERE user_id = ?", (user_id,)).fetchone()
        custom_template = user_tmpl["product_template"] if user_tmpl and user_tmpl["product_template"] else None
        min_disc = conn.execute("SELECT min_discount FROM users WHERE user_id = ?", (user_id,)).fetchone()
        min_discount = min_disc["min_discount"] if min_disc else 0
    finally:
        conn.close()

    allowed_sources = [STORE_ID_MAP[sid] for sid in store_ids if sid in STORE_ID_MAP]

    conn = get_db()
    try:
        if allowed_sources:
            placeholders = ','.join('?' * len(allowed_sources))
            product = conn.execute(
                f"SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL AND source IN ({placeholders}) AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                (user_id, *allowed_sources, min_discount)
            ).fetchone()
        else:
            product = None

        if not product:
            if allowed_sources:
                conn.execute(
                    f"UPDATE gdeslon_catalog SET used = 0 WHERE user_id = ? AND source IN ({placeholders})",
                    (user_id, *allowed_sources)
                )
                conn.commit()
                product = conn.execute(
                    f"SELECT * FROM gdeslon_catalog WHERE user_id = ? AND erid != '' AND erid IS NOT NULL AND source IN ({placeholders}) AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                    (user_id, *allowed_sources, min_discount)
                ).fetchone()
            else:
                product = conn.execute(
                    "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                    (user_id, min_discount)
                ).fetchone()
                if not product:
                    conn.execute("UPDATE gdeslon_catalog SET used = 0 WHERE user_id = ?", (user_id,))
                    conn.commit()
                    product = conn.execute(
                        "SELECT * FROM gdeslon_catalog WHERE user_id = ? AND erid != '' AND erid IS NOT NULL AND (discount_percent IS NULL OR discount_percent >= ?) ORDER BY RANDOM() LIMIT 1",
                        (user_id, min_discount)
                    ).fetchone()
    finally:
        conn.close()

    if not product:
        await callback.message.answer("❌ В каталоге пока нет товаров с маркировкой ERID.")
        return

    partner_url = product['partner_url'] or ''
    title = product['title'] or ''
    price = product['price'] or 0
    currency = product['currency'] or '₽'
    advertiser = product['advertiser'] or 'Рекламодатель'
    erid = product['erid'] or ''
    photo_url = product["image_url"]
    source = product["source"] if "source" in product.keys() else ""
    adult = source in ADULT_STORES
    delivery_info = get_delivery_for_store(source)
    promocode = get_random_promocode(source)

    caption = generate_post_text(
        title=title,
        price=price,
        currency=currency,
        advertiser=advertiser,
        erid=erid,
        partner_url=partner_url,
        adult=adult,
        old_price=product["old_price"] if "old_price" in product.keys() else None,
        discount_percent=product["discount_percent"] if "discount_percent" in product.keys() else None,
        delivery_info=delivery_info,
        promocode=promocode,
        custom_template=custom_template
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"force_confirm:{product['id']}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"force_cancel:{product['id']}")],
    ])
    await callback.message.answer_photo(
        photo=photo_url,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
        has_spoiler=adult
    )


async def _publish_product(callback: CallbackQuery, bot: Bot, user_id: int, product, custom_template=None) -> None:
    partner_url = product['partner_url'] or ''
    title = product['title'] or ''
    price = product['price'] or 0
    currency = product['currency'] or '₽'
    advertiser = product['advertiser'] or 'Рекламодатель'
    erid = product['erid'] or ''
    photo_url = product["image_url"]
    source = product["source"] if "source" in product.keys() else ""

    channels = get_db().execute(
        "SELECT channel_id, sub_id FROM channels WHERE user_id = ? AND is_active = 1",
        (user_id,)
    ).fetchall()
    get_db().close()

    if not channels:
        await callback.message.answer("❌ У вас нет активных каналов.")
        return

    for ch in channels:
        final_url = partner_url
        if ch["sub_id"]:
            final_url += ('&' if '?' in final_url else '?') + 'subid=' + ch["sub_id"]
        adult = source in ADULT_STORES
        delivery_info = get_delivery_for_store(source)
        promocode = get_random_promocode(source)

        caption = generate_post_text(
            title=title, price=price, currency=currency,
            advertiser=advertiser, erid=erid, partner_url=final_url,
            adult=adult,
            old_price=product["old_price"] if "old_price" in product.keys() else None,
            discount_percent=product["discount_percent"] if "discount_percent" in product.keys() else None,
            delivery_info=delivery_info, promocode=promocode,
            custom_template=custom_template
        )

        msg = await publish_post_with_fallback(
            bot=bot, channel_id=ch["channel_id"],
            caption=caption, photo_url=photo_url, has_spoiler=adult
        )
        if msg:
            direct_link = f"https://t.me/{ch['channel_id'].lstrip('@')}/{msg.message_id}"
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

@router.callback_query(F.data.startswith("force_confirm:"))
async def cb_force_confirm(callback: CallbackQuery, bot: Bot) -> None:
    product_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    conn = get_db()
    try:
        product = conn.execute("SELECT * FROM gdeslon_catalog WHERE id = ? AND user_id = ?", (product_id, user_id)).fetchone()
        if not product:
            await callback.answer("❌ Товар не найден.", show_alert=True)
            return
        if product["used"] == 1:
            await callback.answer("❌ Этот товар уже был опубликован.", show_alert=True)
            await callback.message.delete()
            return

        # Помечаем как использованный
        conn.execute("UPDATE gdeslon_catalog SET used = 1 WHERE id = ?", (product_id,))
        conn.commit()
    finally:
        conn.close()

    # Публикация во все активные каналы
    channels = conn.execute(
        "SELECT channel_id, sub_id FROM channels WHERE user_id = ? AND is_active = 1",
        (user_id,)
    ).fetchall()
    conn.close()

    if not channels:
        await callback.answer("❌ Нет активных каналов.", show_alert=True)
        return

    partner_url = product['partner_url'] or ''
    title = product['title'] or ''
    price = product['price'] or 0
    currency = product['currency'] or '₽'
    advertiser = product['advertiser'] or 'Рекламодатель'
    erid = product['erid'] or ''
    photo_url = product["image_url"]
    source = product["source"] if "source" in product.keys() else ""
    adult = source in ADULT_STORES
    delivery_info = get_delivery_for_store(source)
    promocode = get_random_promocode(source)

    conn = get_db()
    try:
        user_tmpl = conn.execute("SELECT product_template FROM users WHERE user_id = ?", (user_id,)).fetchone()
        custom_template = user_tmpl["product_template"] if user_tmpl and user_tmpl["product_template"] else None
    finally:
        conn.close()

    for ch in channels:
        final_url = partner_url
        if ch["sub_id"]:
            if '?' in final_url:
                final_url += '&subid=' + ch["sub_id"]
            else:
                final_url += '?subid=' + ch["sub_id"]

        caption = generate_post_text(
            title=title,
            price=price,
            currency=currency,
            advertiser=advertiser,
            erid=erid,
            partner_url=final_url,
            adult=adult,
            old_price=product["old_price"] if "old_price" in product.keys() else None,
            discount_percent=product["discount_percent"] if "discount_percent" in product.keys() else None,
            delivery_info=delivery_info,
            promocode=promocode,
            custom_template=custom_template
        )

        msg = await publish_post_with_fallback(
            bot=bot,
            channel_id=ch["channel_id"],
            caption=caption,
            photo_url=photo_url,
            has_spoiler=adult
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

    await callback.message.delete()
    await callback.message.answer("✅ Пост успешно опубликован!")
    await callback.answer()

@router.callback_query(F.data.startswith("force_cancel:"))
async def cb_force_cancel(callback: CallbackQuery) -> None:
    # Товар не трогаем, он остаётся used=0
    await callback.message.delete()
    await callback.message.answer("🚫 Публикация отменена.")
    await callback.answer()
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


# ---------------------------------------------------------------------------
# Промокоды
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
# Фильтр минимальной скидки
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:discount_filter")
async def cb_discount_filter(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT min_discount FROM users WHERE user_id=?", (user_id,)).fetchone()
        min_discount = user["min_discount"] if user else 0
    finally:
        conn.close()

    text = f"🎯 <b>Фильтр минимальной скидки</b>\n\nТекущее значение: <b>{min_discount}%</b>\n\nТовары со скидкой ниже этого значения не будут публиковаться."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выключить", callback_data="discount_set:0"),
         InlineKeyboardButton(text="от 10%", callback_data="discount_set:10")],
        [InlineKeyboardButton(text="от 20%", callback_data="discount_set:20"),
         InlineKeyboardButton(text="от 30%", callback_data="discount_set:30")],
        [InlineKeyboardButton(text="от 50%", callback_data="discount_set:50")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
    ])
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("discount_set:"))
async def cb_discount_set(callback: CallbackQuery):
    percent = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET min_discount=? WHERE user_id=?", (percent, user_id))
        conn.commit()
    finally:
        conn.close()
    await callback.answer(f"✅ Минимальная скидка установлена: {percent}%", show_alert=True)
    await cb_discount_filter(callback)


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
# Финансы (история транзакций)
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:finance")
async def cb_finance(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT role, balance_available, balance_pending FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        available = user["balance_available"] or 0.0
        pending = user["balance_pending"] or 0.0
        role = user["role"]
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

    text = f"💰 <b>Финансы</b>\n\n" \
           f"💳 Доступно к выводу: <b>{available:.2f} ₽</b>\n" \
           f"⏳ В ожидании: <b>{pending:.2f} ₽</b>\n\n"

    if not transactions:
        text += "У вас пока нет заказов."
    else:
        text += "<b>Последние 20 транзакций:</b>\n"
        for t in transactions:
            status_emoji = {
                "pending": "⏳", "approved": "✅", "declined": "❌",
                "new": "🆕", "waiting": "⏳", "paid": "💳"
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

    kb_buttons = []
    # Если доступно к выводу >= MIN_PAYOUT, добавить кнопку запроса
    if available >= MIN_PAYOUT:
    kb_buttons.append([InlineKeyboardButton(text="💸 Запросить выплату", callback_data="payout:request")])
    kb_buttons.append([InlineKeyboardButton(text="📢 Поделиться успехом", callback_data="share_success")])
    kb_buttons.append([InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")])
    
    try:
        await callback.message.edit_text(full_text, parse_mode=ParseMode.HTML,
                                          reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))
    except Exception:
        await callback.message.answer(full_text, parse_mode=ParseMode.HTML,
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons))
    await callback.answer()

# ---------------------------------------------------------------------------
# Оферта
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


# handlers/saas.py — замените существующий @router.callback_query(F.data == "oferta:accept")
@router.callback_query(F.data == "oferta:accept")
async def cb_oferta_accept(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET oferta_accepted=1 WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    await callback.answer("✅ Вы приняли условия Оферты.", show_alert=False)
    # Запрос налогового статуса
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 Я Самозанятый / ИП", callback_data="tax:business")],
        [InlineKeyboardButton(text="👤 Обычное физлицо", callback_data="tax:individual")],
    ])
    await callback.message.answer(
        "Для возможности вывода средств укажите ваш налоговый статус в РФ:",
        reply_markup=kb
    )
    await state.set_state(TaxStates.waiting_tax_status)

@router.callback_query(F.data == "saas_toggle:force_preview_reset")
async def cb_force_preview_reset(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET force_preview_confirmed = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    await callback.answer("🔍 Предпросмотр снова будет показываться перед публикацией.", show_alert=True)
    await open_saas_settings(callback)
