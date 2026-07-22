# handlers/saas.py
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery, Message, LabeledPrice,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo
)
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from states import SaasStates, PaymentFSM
from services.db import get_db
from services.saas_core import publish_post_with_fallback, generate_subid2
from services.admitad import fetch_admitad_catalog_for_user, ADULT_STORES, get_delivery_for_store, STORE_ID_MAP
from keyboards.saas import kb_cabinet_menu
from services.text_rewriter import generate_post_text
from services.admitad import get_random_promocode
from states import SaasStates, PaymentFSM, PayoutStates, TaxStates
from helpers import generate_success_text, show_user_cabinet, safe_edit
from config import MIN_PAYOUT, ADMIN_IDS, WEBAPP_ADMIN_URL

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
        cpa_count = conn.execute(
            "SELECT COUNT(*) FROM user_category_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        cpc_count = conn.execute(
            "SELECT COUNT(*) FROM cpc_campaigns WHERE user_id = ? AND is_active = 1", (user_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    text = (
        "🏪 <b>Магазины для постинга</b>\n\n"
        f"🛒 Покупка (CPA): <b>{cpa_count}</b> магазинов\n"
        f"👆 Клики (CPC): <b>{cpc_count}</b> рекламодателей\n\n"
        "Выберите тип монетизации:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛒 Покупка (CPA)", callback_data="stores:cpa"),
            InlineKeyboardButton(text="👆 Клики (CPC)", callback_data="stores:cpc"),
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
    ])
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "stores:cpa")
async def cb_stores_cpa(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user_stores = conn.execute(
            "SELECT category_id FROM user_category_preferences WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        user_store_ids = {r["category_id"] for r in user_stores}
    finally:
        conn.close()

    from services.admitad import STORE_ID_MAP, get_available_stores
    stores_config = get_available_stores()

    stores = []
    for store_id, store_name in STORE_ID_MAP.items():
        info = stores_config.get(store_name, {})
        stores.append({
            "id": store_id,
            "name": store_name,
            "available": info.get("available", True),
            "adult": info.get("adult", False),
            "requires_city": store_name == "Galaxy Store"
        })

    text = f"🛒 <b>Покупка (CPA)</b> — доход за заказ\nВыбрано: {len(user_store_ids)}\n\n"
    kb_rows = []
    for store in stores:
        label = store["name"]
        if not store["available"]:
            label += " ⛔"
        elif store["adult"]:
            label += " 🔞 18+"
        if store["requires_city"]:
            label += " *"
        emoji = "✅" if store["id"] in user_store_ids else "❌"
        kb_rows.append([InlineKeyboardButton(
            text=f"{emoji} {label}",
            callback_data=f"store_toggle:{store['id']}"
        )])

    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu:categories")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    footer = "\n\n* — выбор города | ⛔ — недоступен | 🔞 — 18+"
    await safe_edit(callback.message, text + footer, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "stores:cpc")
async def cb_stores_cpc(callback: CallbackQuery):
    user_id = callback.from_user.id
    campaigns = await _sync_cpc_campaigns(user_id)

    active = [c for c in campaigns if c["is_active"]]
    text = f"👆 <b>Клики (CPC)</b> — доход за клик\nАктивно: {len(active)} из {len(campaigns)}\n\n"

    kb_rows = []
    for c in campaigns:
        status = "✅" if c["is_active"] else "❌"
        name = c["name"]
        kb_rows.append([InlineKeyboardButton(
            text=f"{status} {name}",
            callback_data=f"cpc_toggle:{c['id']}"
        )])

    if not campaigns:
        text += "Нет подключённых рекламодателей.\nПодключите их в кабинете Admitad → Рекламодатели."

    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu:categories")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data.startswith("store_toggle:"))
async def cb_toggle_store(callback: CallbackQuery):
    store_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    from services.admitad import STORE_ID_MAP, get_available_stores
    store_name = STORE_ID_MAP.get(store_id)
    if not store_name:
        await callback.answer("❌ Магазин не найден", show_alert=True)
        return

    # Проверка конкретных магазинов, которые недоступны
    if store_id == 1:  # AliExpress
        await callback.answer("❌ AliExpress временно недоступен (отсутствует ERID).", show_alert=True)
        return
    if store_id == 3:  # Аквафор
        await callback.answer("❌ Аквафор временно недоступен.", show_alert=True)
        return
    if store_id == 5:  # Love Republic
        await callback.answer("❌ Love Republic временно недоступен.", show_alert=True)
        return

    # Проверка доступности из конфига
    store_info = get_available_stores().get(store_name, {})
    if not store_info.get("available", True):
        await callback.answer(f"❌ {store_name} временно недоступен.", show_alert=True)
        return

    # Для Galaxy Store — выбор города
    if store_name == "Galaxy Store":
        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT city FROM user_category_preferences WHERE user_id = ? AND category_id = 12",
                (user_id,)
            ).fetchone()
        finally:
            conn.close()
        if not existing or not existing["city"]:
            await show_city_selection(callback.message, user_id)
            await callback.answer()
            return

    # Для Розового кролика — предупреждение 18+
    if store_name == "Розовый кролик":
        # Проверим, включён ли уже магазин
        conn = get_db()
        try:
            existing = conn.execute(
                "SELECT 1 FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                (user_id, store_id)
            ).fetchone()
        finally:
            conn.close()
        if not existing:
            # Если добавляем — покажем предупреждение
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔞 Да, я подтверждаю", callback_data=f"store_confirm_adult:{store_id}")],
                [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:categories")]
            ])
            await safe_edit(callback.message, "⚠️ <b>Внимание!</b>\n\n"
                "Магазин «Розовый кролик» содержит товары для взрослых (18+).\n"
                "Убедитесь, что ваш канал соответствует возрастным ограничениям.\n\n"
                "Вы уверены, что хотите добавить этот магазин?",
                reply_markup=kb, parse_mode=ParseMode.HTML)
            await callback.answer()
            return
        else:
            # Если уже есть — удаляем
            await callback.answer(f"✅ {store_name} удалён из ваших магазинов.")
            conn = get_db()
            try:
                conn.execute(
                    "DELETE FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                    (user_id, store_id)
                )
                conn.commit()
            finally:
                conn.close()
            await cb_stores_cpa(callback)
            return

    # Стандартное переключение для остальных магазинов
    await callback.answer()
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT 1 FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
            (user_id, store_id)
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM user_category_preferences WHERE user_id = ? AND category_id = ?",
                (user_id, store_id)
            )
        else:
            conn.execute(
                "INSERT INTO user_category_preferences (user_id, category_id) VALUES (?, ?)",
                (user_id, store_id)
            )
        conn.commit()
    finally:
        conn.close()

    await cb_stores_cpa(callback)

# ---------------------------------------------------------------------------
# Циклический постинг — расписание по магазинам
# ---------------------------------------------------------------------------
INTERVAL_OPTIONS = [
    (1, "Каждый день"),
    (2, "Каждые 2 дня"),
    (3, "Каждые 3 дня"),
    (5, "Каждые 5 дней"),
    (7, "Раз в неделю"),
    (14, "Раз в 2 недели"),
    (30, "Раз в месяц"),
]

@router.callback_query(F.data == "menu:cyclic")
async def cb_cyclic_schedules(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        schedules = conn.execute(
            "SELECT store_id, interval_days, is_active FROM cyclic_schedules WHERE user_id=?",
            (user_id,)
        ).fetchall()
        user_stores = conn.execute(
            "SELECT category_id FROM user_category_preferences WHERE user_id=?",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    store_ids = {r["category_id"] for r in user_stores}
    sched_map = {r["store_id"]: r for r in schedules}

    if not store_ids:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏪 Сначала выберите магазины", callback_data="menu:categories")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
        ])
        await safe_edit(callback.message, "⏰ <b>Циклический постинг</b>\n\n"
            "Сначала выберите хотя бы один магазин в разделе «🏪 Магазины».",
            reply_markup=kb, parse_mode=ParseMode.HTML)
        await callback.answer()
        return

    from services.admitad import STORE_ID_MAP

    text = "⏰ <b>Циклический постинг</b>\n\n"
    text += "Настройте расписание для каждого магазина.\n"
    text += "Бот будет публиковать товары из магазина с установленной периодичностью.\n\n"

    kb_rows = []
    for sid in sorted(store_ids):
        store_name = STORE_ID_MAP.get(sid, f"ID {sid}")
        sched = sched_map.get(sid)
        if sched and sched["interval_days"]:
            label_map = {d: t for d, t in INTERVAL_OPTIONS}
            interval_text = label_map.get(sched["interval_days"], f"каждые {sched['interval_days']} дн.")
            status = "✅" if sched["is_active"] else "⏸"
            kb_rows.append([InlineKeyboardButton(
                text=f"{status} {store_name}: {interval_text}",
                callback_data=f"cyclic_set:{sid}"
            )])
        else:
            kb_rows.append([InlineKeyboardButton(
                text=f"❌ {store_name}: не настроено",
                callback_data=f"cyclic_set:{sid}"
            )])

    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data.startswith("cyclic_set:"))
async def cb_cyclic_set(callback: CallbackQuery):
    store_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    from services.admitad import STORE_ID_MAP
    store_name = STORE_ID_MAP.get(store_id, f"ID {store_id}")

    conn = get_db()
    try:
        sched = conn.execute(
            "SELECT interval_days, is_active FROM cyclic_schedules WHERE user_id=? AND store_id=?",
            (user_id, store_id)
        ).fetchone()
    finally:
        conn.close()

    current_text = ""
    if sched:
        label_map = {d: t for d, t in INTERVAL_OPTIONS}
        current_text = f"\nТекущее: {label_map.get(sched['interval_days'], str(sched['interval_days']) + ' дн.')}"
        if sched["is_active"]:
            current_text += " (активно)"
        else:
            current_text += " (приостановлено)"

    text = f"⏰ <b>Расписание: {store_name}</b>{current_text}\n\nВыберите периодичность публикации:"

    kb_rows = []
    for days, label in INTERVAL_OPTIONS:
        kb_rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"cyclic_apply:{store_id}:{days}"
        )])

    if sched:
        toggle_text = "⏸ Приостановить" if sched["is_active"] else "▶️ Возобновить"
        kb_rows.append([InlineKeyboardButton(
            text=toggle_text,
            callback_data=f"cyclic_toggle:{store_id}"
        )])
        kb_rows.append([InlineKeyboardButton(
            text="🗑 Удалить расписание",
            callback_data=f"cyclic_delete:{store_id}"
        )])

    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu:cyclic")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()

@router.callback_query(F.data.startswith("cyclic_apply:"))
async def cb_cyclic_apply(callback: CallbackQuery):
    parts = callback.data.split(":")
    store_id = int(parts[1])
    interval_days = int(parts[2])
    user_id = callback.from_user.id

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO cyclic_schedules (user_id, store_id, interval_days, is_active)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id, store_id) DO UPDATE SET interval_days=?, is_active=1
        """, (user_id, store_id, interval_days, interval_days))
        conn.commit()
    finally:
        conn.close()

    from services.admitad import STORE_ID_MAP
    store_name = STORE_ID_MAP.get(store_id, f"ID {store_id}")
    label_map = {d: t for d, t in INTERVAL_OPTIONS}
    interval_text = label_map.get(interval_days, f"каждые {interval_days} дн.")
    await callback.answer(f"✅ {store_name}: {interval_text}", show_alert=True)
    await cb_cyclic_schedules(callback)

@router.callback_query(F.data.startswith("cyclic_toggle:"))
async def cb_cyclic_toggle(callback: CallbackQuery):
    store_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    conn = get_db()
    try:
        conn.execute(
            "UPDATE cyclic_schedules SET is_active = 1 - is_active WHERE user_id=? AND store_id=?",
            (user_id, store_id)
        )
        conn.commit()
    finally:
        conn.close()

    await callback.answer("✅ Статус изменён")
    await cb_cyclic_schedules(callback)

@router.callback_query(F.data.startswith("cyclic_delete:"))
async def cb_cyclic_delete(callback: CallbackQuery):
    store_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    conn = get_db()
    try:
        conn.execute("DELETE FROM cyclic_schedules WHERE user_id=? AND store_id=?", (user_id, store_id))
        conn.commit()
    finally:
        conn.close()

    await callback.answer("🗑 Расписание удалено")
    await cb_cyclic_schedules(callback)

@router.callback_query(F.data == "promo:activate")
async def cb_promo_activate(callback: CallbackQuery, state: FSMContext):
    await safe_edit(callback.message,
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
    await safe_edit(message, "🏙 <b>Выберите ваш город для Galaxy Store:</b>", reply_markup=markup, parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("galaxy_city:"))
async def cb_galaxy_city_selected(callback: CallbackQuery):
    city_key = callback.data.split(":")[1]
    user_id = callback.from_user.id
    city_name = get_city_name(city_key)

    conn = get_db()
    try:
        user_row = conn.execute("SELECT role FROM users WHERE user_id=?", (user_id,)).fetchone()
        is_blogger_or_saas = user_row and user_row["role"] in ("blogger", "saas")

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
            conn.execute(
                "INSERT INTO user_category_preferences (user_id, category_id, city) VALUES (?, ?, ?)",
                (user_id, 12, city_key)
            )
        conn.commit()
    finally:
        conn.close()

    from services.admitad import fetch_admitad_catalog_for_user
    await fetch_admitad_catalog_for_user(user_id, max_items_per_store=50)
    
    await callback.answer(f"✅ Galaxy Store ({city_name}) добавлен в ваши магазины.")
    await cb_stores_cpa(callback)


@router.callback_query(F.data == "cancel_galaxy_city")
async def cb_cancel_galaxy_city(callback: CallbackQuery):
    await cb_stores_cpa(callback)
    await callback.answer()


# ---------------------------------------------------------------------------
# Force Post (единая логика)
# ---------------------------------------------------------------------------
import sqlite3

@router.callback_query(F.data == "saas_force_post")
async def cb_saas_force_post(callback: CallbackQuery, bot: Bot) -> None:
    """Обработчик кнопки принудительной публикации — выбор CPA или CPC"""
    user_id = callback.from_user.id

    conn = get_db()
    try:
        cpa_count = conn.execute(
            "SELECT COUNT(*) FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL",
            (user_id,)
        ).fetchone()[0]
        cpc_count = conn.execute(
            "SELECT COUNT(*) FROM cpc_campaigns WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    if cpa_count == 0 and cpc_count == 0:
        await callback.answer("❌ Нет доступных товаров или кампаний для публикации", show_alert=True)
        return

    text = "🚀 <b>Опубликовать сейчас</b>\n\nВыберите тип поста:"
    kb_rows = []
    if cpa_count > 0:
        kb_rows.append([InlineKeyboardButton(
            text=f"🛒 Покупка (CPA) — {cpa_count} товаров",
            callback_data="force_type:cpa"
        )])
    if cpc_count > 0:
        kb_rows.append([InlineKeyboardButton(
            text=f"👆 Клики (CPC) — {cpc_count} кампаний",
            callback_data="force_type:cpc"
        )])
    kb_rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cabinet:open")])

    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data == "force_type:cpa")
async def cb_force_type_cpa(callback: CallbackQuery, bot: Bot) -> None:
    """Force Post CPA — существующая логика"""
    user_id = callback.from_user.id
    logger.info(f"User {user_id} triggered force post CPA")

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT force_preview_confirmed FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        preview_confirmed = bool(user["force_preview_confirmed"]) if user else False

        channels_count = conn.execute(
            "SELECT COUNT(*) FROM channels WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ).fetchone()[0]

        if channels_count == 0:
            await callback.answer("❌ Нет активных каналов", show_alert=True)
            return

        product_count = conn.execute(
            "SELECT COUNT(*) FROM gdeslon_catalog WHERE user_id = ? AND used = 0 AND erid != '' AND erid IS NOT NULL",
            (user_id,)
        ).fetchone()[0]

        if product_count == 0:
            await callback.answer("❌ Нет доступных товаров для публикации", show_alert=True)
            return

    except sqlite3.Error as e:
        logger.error(f"Database error in cb_force_type_cpa for user {user_id}: {e}")
        await callback.answer("⚠️ Ошибка базы данных", show_alert=True)
        return
    finally:
        conn.close()

    if preview_confirmed:
        await callback.answer("🚀 Публикую CPA пост...", show_alert=True)
        await _force_post_immediate(callback, bot, user_id)
    else:
        await callback.answer("🔍 Подбираю товар...", show_alert=False)
        await _force_post_preview(callback, bot, user_id)


@router.callback_query(F.data == "force_type:cpc")
async def cb_force_type_cpc(callback: CallbackQuery, bot: Bot) -> None:
    """Force Post CPC — публикация CPC кампании"""
    user_id = callback.from_user.id
    logger.info(f"User {user_id} triggered force post CPC")

    conn = get_db()
    try:
        campaigns = conn.execute(
            "SELECT id, name, cpc_link, text, image_url, description, more_rules FROM cpc_campaigns WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ).fetchall()
        channels = conn.execute(
            "SELECT channel_id, sub_id, channel_title FROM channels WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    if not campaigns:
        await callback.answer("❌ Нет активных CPC-кампаний", show_alert=True)
        return
    if not channels:
        await callback.answer("❌ Нет активных каналов", show_alert=True)
        return

    await callback.answer("🚀 Публикую CPC пост...", show_alert=True)

    user_row = None
    conn = get_db()
    try:
        user_row = conn.execute(
            "SELECT product_template, cpc_template, default_auto_delete_hours FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
    finally:
        conn.close()

    cpc_template = user_row["cpc_template"] if user_row and user_row["cpc_template"] else None
    auto_delete_hours = user_row["default_auto_delete_hours"] if user_row and user_row["default_auto_delete_hours"] is not None else 168

    import random
    campaign = random.choice(campaigns)
    ch = channels[0] if len(channels) == 1 else None

    if not ch:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=ch_row["channel_title"] or ch_row["channel_id"],
                callback_data=f"force_cpc_channel:{campaign['id']}:{ch_row['channel_id']}"
            )] for ch_row in channels
        ])
        await safe_edit(callback.message, "📢 Выберите канал для CPC-поста:", reply_markup=kb)
        return

    try:
        await _publish_cpc_post(callback, bot, user_id, dict(campaign), dict(ch), cpc_template, auto_delete_hours)
    except Exception as e:
        logger.error(f"❌ Force CPC error for user {user_id}: {e}")
        try:
            await callback.message.answer(f"❌ Ошибка публикации CPC: {e}")
        except:
            pass


@router.callback_query(F.data.startswith("force_cpc_channel:"))
async def cb_force_cpc_channel(callback: CallbackQuery, bot: Bot) -> None:
    parts = callback.data.split(":")
    campaign_id = int(parts[1])
    channel_id = parts[2]
    user_id = callback.from_user.id

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, name, cpc_link, text, image_url, description, more_rules FROM cpc_campaigns WHERE id = ? AND user_id = ?",
            (campaign_id, user_id)
        ).fetchone()
        ch = conn.execute(
            "SELECT channel_id, sub_id, channel_title FROM channels WHERE channel_id = ? AND user_id = ?",
            (channel_id, user_id)
        ).fetchone()
        user_row = conn.execute(
            "SELECT cpc_template, default_auto_delete_hours FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not campaign or not ch:
        await callback.answer("❌ Не найдено", show_alert=True)
        return

    cpc_template = user_row["cpc_template"] if user_row and user_row["cpc_template"] else None
    auto_delete_hours = user_row["default_auto_delete_hours"] if user_row and user_row["default_auto_delete_hours"] is not None else 168

    await _publish_cpc_post(callback, bot, user_id, dict(campaign), dict(ch), cpc_template, auto_delete_hours)
    await callback.answer()


def _check_cpc_rules(text: str, rules: str) -> list:
    """Проверяет текст поста на нарушения правил кампании."""
    violations = []
    text_lower = text.lower()
    for line in rules.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        rule_lower = line.lower()
        # Извлекаем ключевые слова из правила
        # Простая эвристика: ищем ключевые слова в тексте
        if any(w in rule_lower for w in ["нельзя", "запрещено", "не допускается", "бан"]):
            # Берём слова после запрета как ключевые
            for marker in ["нельзя", "запрещено", "не допускается", "бан"]:
                if marker in rule_lower:
                    idx = rule_lower.index(marker) + len(marker)
                    keywords = rule_lower[idx:].strip().split()
                    keywords = [w for w in keywords if len(w) > 3]
                    for kw in keywords:
                        if kw in text_lower:
                            violations.append(line)
                            break
                    break
    return list(set(violations))


async def _publish_cpc_post(callback, bot, user_id, campaign, ch, cpc_template=None, auto_delete_hours=168, skip_rules=False):
    """Публикация одного CPC-поста с картинкой и кнопкой"""
    import re as _re
    sub_id = ch["sub_id"] or ""
    cpc_link = campaign["cpc_link"]
    name = campaign["name"]
    custom_text = campaign.get("text") or ""
    description = campaign.get("description") or ""
    more_rules = campaign.get("more_rules") or ""

    subid2 = generate_subid2(user_id, ch["channel_id"])
    separator = "&" if "?" in cpc_link else "?"
    final_url = f"{cpc_link}{separator}subid1={sub_id}&subid2={subid2}"

    erid_match = _re.search(r'erid=([^&]+)', final_url)
    erid_value = erid_match.group(1) if erid_match else ""
    hidden_link = f"<a href='{final_url}'>Перейти</a>"

    if cpc_template and "{link}" in cpc_template:
        post_text = cpc_template.replace("{link}", hidden_link)
    elif cpc_template and "{name}" in cpc_template:
        post_text = cpc_template.replace("{name}", name)
        post_text = post_text.rstrip() + f"\n\n{hidden_link}"
    elif cpc_template:
        post_text = cpc_template.rstrip() + f"\n\n{hidden_link}"
    elif custom_text:
        post_text = custom_text.rstrip() + f"\n\n{hidden_link}"
    elif description:
        post_text = f"👆 {name}\n\n{description}\n\n{hidden_link}"
    else:
        post_text = f"👆 {name}\n\n{hidden_link}"

    post_text = post_text.replace("{description}", description)

    reklama_line = f"Реклама. {name}. Erid: {erid_value}" if erid_value else ""
    post_text = f"{post_text}\n\n{reklama_line}"

    if len(post_text) > 1000:
        idx = post_text.rfind(hidden_link)
        if idx > 0:
            safe = post_text[idx:]
            head = post_text[:1000 - len(safe) - 3].rstrip()
            post_text = head + "..." + safe

    # Проверка правил
    if more_rules and not skip_rules:
        violations = _check_cpc_rules(post_text, more_rules)
        if violations:
            warn = "⚠️ <b>Нарушение правил:</b>\n" + "\n".join(f"• {v}" for v in violations)
            warn += "\n\n💡 Текст нарушает правила магазина. Публикация возможна, но выплата не гарантирована."
            kb_warn = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📤 Опубликовать всё равно", callback_data=f"cpc_force_confirm:{campaign.get('id', 0)}:{ch['channel_id']}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cabinet:open")],
            ])
            await safe_edit(callback.message, warn, reply_markup=kb_warn, parse_mode=ParseMode.HTML)
            return

    image_url = campaign.get("image_url") or ""

    logger.info(f"CPC post: name={name!r}, text={post_text[:100]!r}, image={image_url!r}, channel={ch['channel_id']}")

    msg = await publish_post_with_fallback(
        bot=bot, channel_id=ch["channel_id"],
        caption=post_text, photo_url=image_url,
        reply_markup=None, parse_mode=ParseMode.HTML,
    )

    if msg:
        direct_link = f"https://t.me/{ch['channel_id'].lstrip('@')}/{msg.message_id}"
        conn_rec = get_db()
        try:
            donor_post_id = f"cpc_{campaign.get('id', 0)}_{user_id}_{int(datetime.now(timezone.utc).timestamp())}"
            conn_rec.execute(
                "INSERT INTO posts (user_id, donor_post_id, channel_id, status, published_at, auto_delete_hours, caption, direct_link) "
                "VALUES (?, ?, ?, 'published', ?, ?, ?, ?)",
                (user_id, donor_post_id, ch["channel_id"], datetime.now(timezone.utc).isoformat(),
                 auto_delete_hours, post_text, direct_link)
            )
            conn_rec.commit()
        finally:
            conn_rec.close()
    try:
        await callback.answer("✅ CPC-пост опубликован", show_alert=False)
    except:
        pass


async def _force_post_immediate(callback: CallbackQuery, bot: Bot, user_id: int, channel_id: str = None) -> None:
    """Публикация поста сразу без предпросмотра"""


@router.callback_query(F.data.startswith("cpc_force_confirm:"))
async def cb_cpc_force_confirm(callback: CallbackQuery, bot: Bot) -> None:
    """Публикация CPC-поста после подтверждения (нарушая правила)"""
    parts = callback.data.split(":")
    campaign_id = int(parts[1])
    channel_id = parts[2]
    user_id = callback.from_user.id

    conn = get_db()
    try:
        campaign = conn.execute(
            "SELECT id, name, cpc_link, text, image_url, rules, more_rules, description FROM cpc_campaigns WHERE id = ? AND user_id = ?",
            (campaign_id, user_id)
        ).fetchone()
        ch = conn.execute(
            "SELECT channel_id, sub_id, channel_title FROM channels WHERE channel_id = ? AND user_id = ?",
            (channel_id, user_id)
        ).fetchone()
        user_row = conn.execute(
            "SELECT cpc_template, default_auto_delete_hours FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not campaign or not ch:
        await callback.answer("❌ Не найдено", show_alert=True)
        return

    cpc_template = user_row["cpc_template"] if user_row and user_row["cpc_template"] else None
    auto_delete_hours = user_row["default_auto_delete_hours"] if user_row and user_row["default_auto_delete_hours"] is not None else 168

    # Публикуем без проверки правил
    await _publish_cpc_post(callback, bot, user_id, dict(campaign), dict(ch), cpc_template, auto_delete_hours, skip_rules=True)
    await callback.answer()
    conn = get_db()
    try:
        # Получаем настройки пользователя
        user_stores = conn.execute(
            "SELECT category_id FROM user_category_preferences WHERE user_id = ?", 
            (user_id,)
        ).fetchall()
        store_ids = [r["category_id"] for r in user_stores]
        
        user_tmpl = conn.execute(
            "SELECT product_template, default_auto_delete_hours FROM users WHERE user_id = ?", 
            (user_id,)
        ).fetchone()
        custom_template = user_tmpl["product_template"] if user_tmpl else None
        auto_delete_hours = user_tmpl["default_auto_delete_hours"] if user_tmpl and user_tmpl["default_auto_delete_hours"] is not None else 168
        
        min_disc = conn.execute(
            "SELECT min_discount FROM users WHERE user_id = ?", 
            (user_id,)
        ).fetchone()
        min_discount = min_disc["min_discount"] if min_disc else 0
        
        # Получаем список каналов
        channels = conn.execute(
            "SELECT channel_id, channel_title FROM channels WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ).fetchall()
        
        if not channels:
            await callback.answer("❌ Нет активных каналов", show_alert=True)
            return
            
        # Если канал не выбран, но их несколько - предлагаем выбор
        if not channel_id and len(channels) > 1:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=ch["channel_title"] or ch["channel_id"], 
                    callback_data=f"force_channel:{ch['channel_id']}"
                )] for ch in channels
            ])
            await safe_edit(callback.message,
                "📢 Выберите канал для публикации:",
                reply_markup=kb
            )
            await callback.answer()
            return
    finally:
        conn.close()

    allowed_sources = [STORE_ID_MAP[sid] for sid in store_ids if sid in STORE_ID_MAP]

    conn = get_db()
    try:
        if allowed_sources:
            placeholders = ','.join('?' * len(allowed_sources))
            product = conn.execute(
                f"""SELECT * FROM gdeslon_catalog 
                WHERE user_id = ? AND used = 0 
                AND erid != '' AND erid IS NOT NULL 
                AND source IN ({placeholders}) 
                AND (discount_percent IS NULL OR discount_percent >= ?)
                ORDER BY 
                    CASE WHEN discount_percent >= 30 THEN 0  -- Приоритет товарам со скидкой 30%+
                    ELSE 1 END,
                    RANDOM()
                LIMIT 1""",
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
        await safe_edit(callback.message, "❌ В каталоге пока нет товаров с маркировкой ERID.")
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
        await safe_edit(callback.message, "❌ В каталоге пока нет товаров с маркировкой ERID.")
        return

    # ... (далее идёт формирование caption и показ предпросмотра, без изменений)

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
    conn_ad = get_db()
    try:
        urow = conn_ad.execute("SELECT default_auto_delete_hours FROM users WHERE user_id=?", (user_id,)).fetchone()
        auto_delete_hours = urow["default_auto_delete_hours"] if urow and urow["default_auto_delete_hours"] is not None else 168
    finally:
        conn_ad.close()
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
        await safe_edit(callback.message, "❌ У вас нет активных каналов.")
        return

    for ch in channels:
        final_url = partner_url
        if ch["sub_id"]:
            if '?' in final_url:
                final_url += '&subid=' + ch["sub_id"]
            else:
                final_url += '?subid=' + ch["sub_id"]
        # Добавляем subid2
        subid2 = generate_subid2(user_id, ch["channel_id"])
        if '?' in final_url:
            final_url += '&subid2=' + subid2
        else:
            final_url += '?subid2=' + subid2

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
                    (user_id, donor_post_id, channel_id, target_channel_id, subid1, subid2, direct_link, erid, status, published_at, caption, auto_delete_hours)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?)""",
                    (user_id, donor_post_id, ch['channel_id'], ch['channel_id'], ch['sub_id'], subid2, direct_link, erid,
                     datetime.now(timezone.utc).isoformat(), caption, auto_delete_hours)
                )
                conn_rec.commit()
            finally:
                conn_rec.close()

            # ===== АВТО-ЗАКРЕПЛЕНИЕ (если включено у пользователя) =====
            from services.saas_core import pin_post_if_enabled
            await pin_post_if_enabled(bot, user_id, ch["channel_id"], msg.message_id)

        await asyncio.sleep(1)

@router.callback_query(F.data.startswith("force_channel:"))
async def cb_force_channel_select(callback: CallbackQuery, bot: Bot):
    """Обработчик выбора канала для принудительной публикации"""
    channel_id = callback.data.split(":")[1]
    await _force_post_immediate(callback, bot, callback.from_user.id, channel_id)
    await callback.answer()

@router.callback_query(F.data.startswith("force_confirm:"))
async def cb_force_confirm(callback: CallbackQuery, bot: Bot) -> None:
    """Подтверждение публикации с предпросмотром"""
    product_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    conn = get_db()
    try:
        # Получаем товар
        product = conn.execute(
            "SELECT * FROM gdeslon_catalog WHERE id = ? AND user_id = ?", 
            (product_id, user_id)
        ).fetchone()
        urow = conn.execute("SELECT default_auto_delete_hours FROM users WHERE user_id=?", (user_id,)).fetchone()
        auto_delete_hours = urow["default_auto_delete_hours"] if urow and urow["default_auto_delete_hours"] is not None else 168
        if not product:
            await callback.answer("❌ Товар не найден", show_alert=True)
            return
            
        if product["used"] == 1:
            await callback.answer("⚠️ Этот товар уже публиковался", show_alert=True)
            await callback.message.delete()
            return

        # Помечаем как использованный
        conn.execute(
            "UPDATE gdeslon_catalog SET used = 1 WHERE id = ?", 
            (product_id,)
        )
        conn.commit()
        
        # Получаем каналы пользователя
        channels = conn.execute(
            "SELECT channel_id, sub_id FROM channels WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    if not channels:
        await callback.answer("❌ Нет активных каналов", show_alert=True)
        return
        
    # Логируем действие
    logger.info(f"User {user_id} force-publishing product {product_id} to {len(channels)} channels")

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
        # Добавляем subid2 для детализации трафика
        subid2 = generate_subid2(user_id, ch["channel_id"])
        if '?' in final_url:
            final_url += '&subid2=' + subid2
        else:
            final_url += '?subid2=' + subid2

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
                    (user_id, donor_post_id, channel_id, target_channel_id, subid1, subid2, direct_link, erid, status, published_at, caption, auto_delete_hours)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?)""",
                    (user_id, donor_post_id, ch['channel_id'], ch['channel_id'], ch['sub_id'], subid2, direct_link, erid,
                     datetime.now(timezone.utc).isoformat(), caption, auto_delete_hours)
                )
                conn_rec.commit()
            finally:
                conn_rec.close()
        await asyncio.sleep(1)

    await safe_edit(callback.message, "✅ Пост успешно опубликован!")
    await callback.answer()

@router.callback_query(F.data.startswith("force_cancel:"))
async def cb_force_cancel(callback: CallbackQuery) -> None:
    # Товар не трогаем, он остаётся used=0
    await safe_edit(callback.message, "🚫 Публикация отменена.")
    await callback.answer()
# ---------------------------------------------------------------------------
# Настройка источника товаров (заглушка)
# ---------------------------------------------------------------------------
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
            await safe_edit(callback.message, "❌ Промокод уже использован.")
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

    await safe_edit(callback.message, f"✅ Промокод активирован!\nПодписка продлена на {days} дн. до {new_until.strftime('%d.%m.%Y %H:%M')} (UTC).")
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
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
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

        # Проверка активной заявки на выплату
        active_request = conn.execute(
            "SELECT id, status FROM payout_requests WHERE user_id=? AND status IN ('processing','awaiting_receipt','receipt_uploaded') ORDER BY id DESC LIMIT 1",
            (user_id,)
        ).fetchone()
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
    if active_request:
        req_id, req_status = active_request["id"], active_request["status"]
        if req_status == "awaiting_receipt":
            kb_buttons.append([InlineKeyboardButton(text="📤 Отправить чек", callback_data=f"receipt:upload:{req_id}")])
            kb_buttons.append([InlineKeyboardButton(text="ℹ️ Статус: ожидание чека", callback_data="none")])
        elif req_status == "receipt_uploaded":
            kb_buttons.append([InlineKeyboardButton(text="⏳ Чек отправлен, ожидайте подтверждения", callback_data="none")])
        else:
            kb_buttons.append([InlineKeyboardButton(text="⏳ Заявка обрабатывается", callback_data="none")])
    else:
        if available >= MIN_PAYOUT:
            kb_buttons.append([InlineKeyboardButton(text="💸 Запросить выплату", callback_data="payout:request")])
        else:
            kb_buttons.append([InlineKeyboardButton(text="❌ Недостаточно средств для вывода", callback_data="none")])
    kb_buttons.append([InlineKeyboardButton(text="📢 Поделиться успехом", callback_data="share_success")])
    kb_buttons.append([InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")])

    await safe_edit(callback.message, full_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons), parse_mode=ParseMode.HTML)
    await callback.answer()
@router.callback_query(F.data.startswith("receipt:upload:"))
async def cb_receipt_upload(callback: CallbackQuery, state: FSMContext):
    request_id = int(callback.data.split(":")[2])
    user_id = callback.from_user.id
    # Проверим принадлежность заявки и статус
    conn = get_db()
    try:
        req = conn.execute("SELECT * FROM payout_requests WHERE id=? AND user_id=? AND status='awaiting_receipt'", 
                           (request_id, user_id)).fetchone()
        if not req:
            await callback.answer("❌ Заявка не найдена или не в статусе ожидания чека.", show_alert=True)
            return
    finally:
        conn.close()
    await safe_edit(callback.message, "📎 Прикрепите фото/скриншот чека из приложения «Мой налог».")
    await state.set_state(PayoutStates.waiting_for_receipt_photo)
    await state.update_data(payout_request_id=request_id)
    await callback.answer()

@router.message(PayoutStates.waiting_for_receipt_photo, F.photo)
async def process_receipt_photo(message: Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    request_id = data.get("payout_request_id")
    if not request_id:
        await message.answer("❌ Ошибка сессии. Попробуйте снова.")
        await state.clear()
        return

    # Получаем file_id фото
    photo = message.photo[-1]
    file_id = photo.file_id

    conn = get_db()
    try:
        # Обновляем статус заявки и сохраняем file_id (можно в отдельное поле, добавим receipt_photo)
        conn.execute("UPDATE payout_requests SET status='receipt_uploaded', receipt_photo=? WHERE id=?",
                     (file_id, request_id))
        conn.commit()
    finally:
        conn.close()

    # Уведомление админам
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_photo(
                admin_id,
                photo=file_id,
                caption=f"🧾 Чек по заявке #{request_id} от пользователя {user_id}.\n"
                        f"Проверьте и подтвердите выплату в админке.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🌐 Админка", web_app=WebAppInfo(url=WEBAPP_ADMIN_URL))]
                ])
            )
        except Exception as e:
            logger.error(f"Ошибка отправки чека админу {admin_id}: {e}")

    await message.answer("✅ Чек отправлен администратору. Ожидайте подтверждения.")
    await state.clear()
# ---------------------------------------------------------------------------
# Оферта
# ---------------------------------------------------------------------------
@router.callback_query(F.data == "menu:oferta")
async def cb_menu_oferta(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT role, oferta_accepted FROM users WHERE user_id=?", (user_id,)).fetchone()
        role = user["role"] if user else "blogger"
        accepted = bool(user["oferta_accepted"]) if user else False
    finally:
        conn.close()

    if role == "saas":
        text_oferta = (
            "📜 <b>Публичная оферта (SaaS-клиент)</b>\n\n"
            "Для использования сервиса необходимо принять условия Пользовательского соглашения.\n\n"
            "<b>ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ (ПУБЛИЧНАЯ ОФЕРТА)</b>\n"
            "<i>Последняя редакция: 15 июля 2026 года</i>\n\n"
            "Нажимая «Принимаю», вы соглашаетесь с условиями и даёте согласие на обработку персональных данных.\n\n"
            "<b>1. Термины</b>\n"
            "• Сервис – данный Telegram-бот (технологическая платформа).\n"
            "• CPA-сеть – партнёрская сеть Admitad.\n"
            "• SubID – уникальный цифровой идентификатор вашего канала.\n"
            "• Баланс – справочные данные о вознаграждении, не электронные деньги.\n\n"
            "<b>2. Предмет</b>\n"
            "Вы получаете бессрочный бесплатный доступ к SaaS-инструменту автопостинга товаров с партнёрскими ссылками. "
            "Доход от подтвержденных CPA-сетью заказов распределяется в пропорции: 70% – Пользователю, 30% – Сервису.\n\n"
            "<b>3. Учёт, трансфер средств и Налоги</b>\n"
            "• Единственный источник данных о заказах – CPA-сеть.\n"
            "• В ожидании – заказы на проверке у рекламодателя (30–90 дней).\n"
            "• Доступно к выводу – подтверждённые заказы, готовые к трансферу.\n"
            "• Трансфер средств производится по запросу. Для этого необходимо в веб-статистике нажать "
            "«💸 Запросить выплату» и указать реквизиты. Пользователь обязан иметь статус Самозанятого или ИП "
            "и самостоятельно уплачивать налоги со своей доли (70%). Сервис не является налоговым агентом Пользователя.\n\n"
            "<b>4. Маркировка рекламы (ФЗ №38)</b>\n"
            "• Сервис автоматически вшивает в посты токен (erid) и наименование рекламодателя из CPA-сети.\n"
            "• Пользователь (Рекламораспространитель) самостоятельно и в полном объеме несет ответственность за "
            "ежемесячную передачу статистики просмотров постов в ОРД через свой личный кабинет. "
            "Сервис является исключительно техническим инструментом и отчеты за Пользователя не сдает.\n\n"
            "<b>5. Запрещено</b>\n"
            "Спам, накрутка, самовыкупы, мотивированный трафик, брендовая реклама, размещение ссылок вне добавленных каналов. "
            "Запрещен контент, нарушающий Brand Safety (казино, пиратство, насилие). Нарушение – бан и обнуление баланса.\n\n"
            "<b>6. Ответственность</b>\n"
            "• Переводы ограничены суммами, реально полученными от CPA-сети по конкретному SubID Пользователя.\n"
            "• Администрация вправе заморозить операции по балансу на время проверки трафика со стороны CPA-сети (до 90 дней). "
            "Пользователь обязан предоставить фискальные чеки из приложения 'Мой Налог' за предыдущие периоды по первому требованию.\n\n"
            "<b>7. Реферальная программа</b>\n"
            "• Приглашая других пользователей по реферальной ссылке, вы получаете вознаграждение в размере "
            "10% от суммы чистого заработка привлеченного лица.\n"
            "• Реферальные начисления (10%) вычитаются из заработка приглашённого пользователя (его 70%) и перечисляются рефереру.\n\n"
            "<b>8. Персональные данные</b>\n"
            "Сервис обрабатывает следующие персональные данные Пользователя: Telegram ID, username, реквизиты для выплат, "
            "налоговый статус, статистику публикаций и транзакций. Данные используются исключительно для оказания услуг "
            "и выполнения требований законодательства. Принимая настоящую оферту, Пользователь даёт согласие на обработку "
            "своих персональных данных в соответствии с Федеральным законом №152-ФЗ «О персональных данных». "
            "Данные хранятся на серверах на территории Российской Федерации и не передаются третьим лицам, "
            "за исключением случаев, предусмотренных законом."
        )
    else:  # blogger
        text_oferta = (
            "📜 <b>Публичная оферта (Блогер / Партнер)</b>\n\n"
            "Для использования сервиса необходимо принять условия Пользовательского соглашения.\n\n"
            "<b>ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ (ПУБЛИЧНАЯ ОФЕРТА)</b>\n"
            "<i>Последняя редакция: 15 июля 2026 года</i>\n\n"
            "Нажимая «Принимаю», вы заключаете договор о совместном оказании рекламных услуг "
            "и даёте согласие на обработку персональных данных.\n\n"
            "<b>1. Термины</b>\n"
            "• Сервис – данный Telegram-бот.\n"
            "• CPA-сеть – партнёрская сеть Admitad.\n"
            "• SubID – уникальный цифровой ID вашего канала для учета продаж.\n"
            "• Баланс – справочные данные о доходе, не являются электронными деньгами.\n\n"
            "<b>2. Предмет и Финансовая модель</b>\n"
            "Вы получаете бесплатный доступ к автопостингу. Доход от подтвержденных CPA-сетью "
            "заказов распределяется в пропорции: 70% – Блогеру, 30% – Сервису.\n\n"
            "<b>3. Реферальная программа</b>\n"
            "• Приглашая блогеров по реферальной ссылке, вы получаете вознаграждение в размере "
            "10% от суммы чистого заработка привлеченного лица.\n"
            "• Реферальные начисления (10%) вычитаются из заработка приглашённого блогера (его 70%) и перечисляются рефереру "
            "по мере подтверждения заказов рекламодателями.\n\n"
            "<b>4. Учёт, трансфер средств и Налоги</b>\n"
            "• Единственный источник данных о заказах – статистика CPA-сети.\n"
            "• В ожидании – заказы на верификации у рекламодателя (30–90 дней).\n"
            "• Доступно к выводу – подтвержденные и фактически оплаченные заказы. Минимальная сумма: 3000 ₽.\n"
            "• Трансфер средств производится по запросу. Для этого необходимо в веб-статистике нажать "
            "«💸 Запросить выплату» и указать реквизиты. Блогер обязан самостоятельно "
            "декларировать доходы (иметь статус Самозанятого или ИП). Сервис не является "
            "налоговым агентом Блогера.\n\n"
            "<b>5. Маркировка рекламы (ФЗ №38)</b>\n"
            "• Сервис автоматически вшивает в посты токен (erid) и данные рекламодателя из CPA-сети.\n"
            "• Блогер самостоятельно несет полную юридическую ответственность за ежемесячное "
            "предоставление статистики просмотров постов в ОРД через свой личный кабинет. "
            "Сервис отчеты за Блогера не сдает.\n\n"
            "<b>6. Запрещенный трафик и Контент</b>\n"
            "Запрещены: спам, клик-фрод, самовыкупы, мотивированный трафик, брендовая реклама. "
            "Запрещен контент, нарушающий Brand Safety (казино, пиратство, насилие). "
            "Нарушение – блокировка и обнуление баланса.\n\n"
            "<b>7. Ответственность и Форс-мажор</b>\n"
            "• Трансферы ограничены суммами, реально поступившими на счет Сервиса по конкретному SubID Блогера.\n"
            "• При блокировке общего аккаунта в CPA-сети из-за фрода, операции замораживаются до разрешения спора. "
            "При подтверждении фрода баланс нарушителя аннулируется.\n"
            "• Блогер обязан предоставить фискальный чек из приложения 'Мой Налог' за полученный перевод "
            "в течение 24 часов, загрузив его в веб-статистике (кнопка «📤 Отправить чек»). "
            "В случае отказа Сервис вправе заблокировать аккаунт Блогера.\n\n"
            "<b>8. Персональные данные</b>\n"
            "Сервис обрабатывает следующие персональные данные Пользователя: Telegram ID, username, реквизиты для выплат, "
            "налоговый статус, статистику публикаций и транзакций. Данные используются исключительно для оказания услуг "
            "и выполнения требований законодательства. Принимая настоящую оферту, Пользователь даёт согласие на обработку "
            "своих персональных данных в соответствии с Федеральным законом №152-ФЗ «О персональных данных». "
            "Данные хранятся на серверах на территории Российской Федерации и не передаются третьим лицам, "
            "за исключением случаев, предусмотренных законом."
        )

    if not accepted:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принимаю", callback_data="oferta:accept")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
        ])

    await safe_edit(callback.message, text_oferta, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer()

# handlers/saas.py — замените существующий @router.callback_query(F.data == "oferta:accept")
@router.callback_query(F.data == "oferta:accept")
async def cb_oferta_accept(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET oferta_accepted=1 WHERE user_id=?", (user_id,))
        conn.commit()
        row = conn.execute("SELECT tax_status FROM users WHERE user_id=?", (user_id,)).fetchone()
        tax_status = row["tax_status"] if row else ""
    finally:
        conn.close()

    await callback.answer("✅ Вы приняли условия Оферты.", show_alert=False)

    if tax_status in ("business", "individual"):
        await show_user_cabinet(callback.message, user_id=user_id, edit_message=callback.message)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 Я Самозанятый / ИП", callback_data="tax:business")],
        [InlineKeyboardButton(text="👤 Обычное физлицо", callback_data="tax:individual")],
    ])
    await safe_edit(callback.message,
        "Для возможности вывода средств укажите ваш налоговый статус в РФ:",
        reply_markup=kb
    )
    await state.set_state(TaxStates.waiting_tax_status)

# ---------------------------------------------------------------------------
# CPC Рекламодатели
# ---------------------------------------------------------------------------
async def _sync_cpc_campaigns(user_id: int) -> list:
    """Подтягивает кампании из Admitad и синхронизирует с БД."""
    from services.admitad_subnetwork import get_website_campaigns, get_all_websites

    conn = get_db()
    try:
        channels = conn.execute(
            "SELECT admitad_website_id FROM channels WHERE user_id=? AND admitad_website_id IS NOT NULL",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    all_campaigns = {}
    for ch in channels:
        wid = ch["admitad_website_id"]
        campaigns = await get_website_campaigns(wid)
        for c in campaigns:
            cid = c.get("id")
            if cid and cid not in all_campaigns:
                gotolink = c.get("gotolink", "")
                cpc_link = gotolink.replace("/g/", "/c/") if gotolink else ""
                img = c.get("image") or ""
                if isinstance(img, dict):
                    img = img.get("url", "")
                logger.info(f"CPC sync: '{c.get('name')}' api_image={c.get('image')!r} parsed_img={img!r}")
                all_campaigns[cid] = {
                    "campaign_id": cid,
                    "name": c.get("name", f"ID {cid}"),
                    "cpc_link": cpc_link,
                    "image_url": img,
                    "description": c.get("description", "") or "",
                    "more_rules": c.get("more_rules", "") or "",
                    "traffics": c.get("traffics", []) or [],
                }

    if not all_campaigns:
        return []

    # OG-scraping для кампаний без картинки/описания
    from services.saas_core import scrape_og_data
    for cid, info in all_campaigns.items():
        if not info["image_url"] or not info["description"]:
            og = await scrape_og_data(info["cpc_link"])
            logger.info(f"OG scrape for '{info['name']}' ({info['cpc_link']}): image={og['og_image']!r}, desc={og['og_description'][:80]!r}")
            if not info["image_url"] and og["og_image"]:
                info["image_url"] = og["og_image"]
            if not info["description"] and og["og_description"]:
                info["description"] = og["og_description"]
            elif not info["description"] and og["og_title"]:
                info["description"] = og["og_title"]

    # Fallback: Banners API + Advertiser Info для кампаний всё ещё без картинки
    from services.admitad_subnetwork import get_campaign_banners, get_advertiser_info
    for cid, info in all_campaigns.items():
        if not info["image_url"]:
            banners = await get_campaign_banners(cid)
            for b in banners:
                img = b.get("image") or b.get("src") or ""
                if isinstance(img, dict):
                    img = img.get("url", "")
                if img and img.startswith("http"):
                    info["image_url"] = img
                    logger.info(f"Banners API: '{info['name']}' image={img!r}")
                    break
            if not info["image_url"]:
                details = await get_advertiser_info(cid)
                detail_img = details.get("image") or ""
                if isinstance(detail_img, dict):
                    detail_img = detail_img.get("url", "")
                if detail_img and detail_img.startswith("http"):
                    info["image_url"] = detail_img
                    logger.info(f"Advertiser info: '{info['name']}' image={detail_img!r}")

    conn = get_db()
    try:
        for cid, info in all_campaigns.items():
            existing = conn.execute(
                "SELECT id FROM cpc_campaigns WHERE user_id=? AND campaign_id=?",
                (user_id, cid)
            ).fetchone()
            if not existing and info["cpc_link"]:
                import json as _json
                traffics_str = _json.dumps(info["traffics"], ensure_ascii=False) if info["traffics"] else ""
                conn.execute(
                    "INSERT INTO cpc_campaigns (user_id, campaign_id, name, cpc_link, image_url, description, more_rules, traffics) VALUES (?,?,?,?,?,?,?,?)",
                    (user_id, cid, info["name"], info["cpc_link"], info["image_url"], info["description"], info["more_rules"], traffics_str)
                )
            elif existing:
                import json as _json
                traffics_str = _json.dumps(info["traffics"], ensure_ascii=False) if info["traffics"] else ""
                existing_row = conn.execute(
                    "SELECT image_url, description, more_rules, traffics FROM cpc_campaigns WHERE id=?", (existing["id"],)
                ).fetchone()
                if existing_row:
                    new_img = existing_row["image_url"] or info["image_url"]
                    new_desc = existing_row["description"] or info["description"]
                    new_rules = existing_row["more_rules"] or info["more_rules"]
                    new_traffics = existing_row["traffics"] or traffics_str
                    if new_img != existing_row["image_url"] or new_desc != existing_row["description"] or new_rules != existing_row["more_rules"] or new_traffics != existing_row["traffics"]:
                        conn.execute(
                            "UPDATE cpc_campaigns SET image_url=?, description=?, more_rules=?, traffics=? WHERE id=?",
                            (new_img, new_desc, new_rules, new_traffics, existing["id"])
                        )

        admin_settings = conn.execute("SELECT campaign_id, description, rules FROM cpc_admin_settings").fetchall()
        admin_map = {r["campaign_id"]: r for r in admin_settings}
        for row in conn.execute("SELECT id, campaign_id FROM cpc_campaigns WHERE user_id=?", (user_id,)).fetchall():
            admin = admin_map.get(row["campaign_id"])
            if admin:
                conn.execute(
                    "UPDATE cpc_campaigns SET description=?, more_rules=? WHERE id=?",
                    (admin["description"], admin["rules"], row["id"])
                )

        conn.commit()

        rows = conn.execute(
            "SELECT id, campaign_id, name, cpc_link, text, image_url, description, is_active, interval_hours, last_posted_at "
            "FROM cpc_campaigns WHERE user_id=? ORDER BY name",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    return [dict(r) for r in rows]


async def _build_cpc_list(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    campaigns = await _sync_cpc_campaigns(user_id)

    if not campaigns:
        text = (
            "👆 <b>Клики (CPC)</b>\n\n"
            "Нет подключённых рекламодателей.\n"
            "Подключите их в кабинете Admitad → Рекламодатели."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="cabinet:open")]
        ])
        return text, kb

    lines = ["👆 <b>Клики (CPC)</b>\n", "Нажмите чтобы включить/выключить:", ""]
    kb_rows = []

    for c in campaigns:
        status = "✅" if c["is_active"] else "⬜"
        name = c["name"]
        lines.append(f"{status} <b>{name}</b>")
        lines.append("")

        btn_status = f"{'🟢' if c['is_active'] else '🔴'} {name}"
        kb_rows.append([
            InlineKeyboardButton(text=btn_status, callback_data=f"cpc_toggle:{c['id']}"),
        ])

    kb_rows.append([InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")])
    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    return text, kb


@router.callback_query(F.data.startswith("cpc_toggle:"))
async def cb_cpc_toggle(callback: CallbackQuery):
    row_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    conn = get_db()
    try:
        row = conn.execute("SELECT is_active FROM cpc_campaigns WHERE id=? AND user_id=?", (row_id, user_id)).fetchone()
        if not row:
            await callback.answer("❌ Не найдено", show_alert=True)
            return
        new_val = 0 if row["is_active"] else 1
        conn.execute("UPDATE cpc_campaigns SET is_active=? WHERE id=?", (new_val, row_id))
        conn.commit()
    finally:
        conn.close()

    text, kb = await _build_cpc_list(user_id)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode=ParseMode.HTML)
    await callback.answer(f"{'Включено' if new_val else 'Выключено'}")


@router.message(Command("debug_cpc"))
async def debug_cpc(message: Message, bot: Bot):
    try:
        from services.admitad_subnetwork import get_access_token
        import httpx
        user_id = message.from_user.id
        conn = get_db()
        try:
            rows = conn.execute("SELECT campaign_id, name, image_url, more_rules FROM cpc_campaigns WHERE user_id=? LIMIT 5", (user_id,)).fetchall()
        finally:
            conn.close()

        if not rows:
            await message.answer("Нет CPC кампаний")
            return

        token = await get_access_token()
        if not token:
            await message.answer("❌ Нет токена Admitad")
            return

        conn2 = get_db()
        try:
            website_rows = conn2.execute(
                "SELECT DISTINCT admitad_website_id FROM channels WHERE user_id=? AND admitad_website_id IS NOT NULL",
                (user_id,)
            ).fetchall()
        finally:
            conn2.close()

        if not website_rows:
            await message.answer("❌ Нет подключённых площадок в каналах")
            return

        for r in rows:
            cid = r["campaign_id"]
            name = r["name"]
            found = False
            for wr in website_rows:
                wid = wr["admitad_website_id"]
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(
                        f"https://api.admitad.com/advcampaigns/website/{wid}/",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"limit": 500}
                    )
                    if resp.status_code == 200:
                        for c in resp.json().get("results", []):
                            if c.get("id") == cid:
                                import re as _re2
                                def strip_html(s):
                                    if not s: return ""
                                    return _re2.sub(r'<[^>]+>', '', s)
                                text = (
                                    f"<b>{c.get('name')} (id={cid})</b>\n"
                                    f"image: <code>{c.get('image')}</code>\n"
                                    f"description: {strip_html(c.get('description',''))[:200]}\n"
                                    f"raw_description: {strip_html(c.get('raw_description',''))[:200]}\n"
                                    f"more_rules: {strip_html(c.get('more_rules',''))[:200]}\n"
                                    f"traffics: {c.get('traffics')}\n"
                                    f"site_url: {c.get('site_url')}"
                                )
                                await message.answer(text, parse_mode=ParseMode.HTML)
                                found = True
                                break
                if found:
                    break
            if not found:
                await message.answer(f"{name} (id={cid}): не найдена в подключённых")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        logger.error(f"debug_cpc error: {e}", exc_info=True)