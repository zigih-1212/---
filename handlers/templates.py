import logging
import random
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services.db import get_db
from states import TemplateStates, CpcStates
from services.text_rewriter import generate_post_text
from services.admitad import get_delivery_for_store, get_random_promocode
from helpers import safe_edit

logger = logging.getLogger("autopost_bot.templates")
router = Router(name="templates")

DEFAULT_PRODUCT_TEMPLATE = (
    "🔥 <b>{title}</b>\n\n"
    "💰 {price_label}: {price} {currency}{discount_line}\n"
    "👉 {link}\n"
    "{promocode_line}{delivery_line}"
    "\n\nРеклама. {advertiser}. Erid: {erid}"
)

DEFAULT_VIDEO_TEMPLATE = (
    "🎬 <b>{title}</b>\n\n"
    "{description}\n\n"
    "🔗 <a href='{link}'>Смотреть</a>"
)

DEFAULT_CPC_TEMPLATE = (
    "👆 <b>{name}</b>\n\n"
    "Перейдите по ссылке:\n{link}"
)

def get_template_preview_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Шаблон товаров (CPA)", callback_data="templates:set_product")],
        [InlineKeyboardButton(text="📝 Шаблон видео", callback_data="templates:set_video")],
        [InlineKeyboardButton(text="📝 Шаблон кликов (CPC)", callback_data="templates:set_cpc")],
        [InlineKeyboardButton(text="🔄 Сбросить до стандартных", callback_data="templates:reset")],
        [InlineKeyboardButton(text="👀 Предпросмотр товара", callback_data="templates:preview_product")],
        [InlineKeyboardButton(text="👀 Предпросмотр видео", callback_data="templates:preview_video")],
        [InlineKeyboardButton(text="👀 Предпросмотр CPC", callback_data="templates:preview_cpc")],
        [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")],
    ])

@router.callback_query(F.data == "menu:templates")
async def cb_menu_templates(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        user = conn.execute("SELECT product_template, video_template, cpc_template FROM users WHERE user_id=?", (user_id,)).fetchone()
        product_tmpl = user["product_template"] if user else ""
        video_tmpl = user["video_template"] if user else ""
        cpc_tmpl = user["cpc_template"] if user else ""
    finally:
        conn.close()

    text = (
        "📝 <b>Шаблоны постов</b>\n\n"
        "<b>CPA товарный шаблон:</b>\n"
        f"<code>{product_tmpl or DEFAULT_PRODUCT_TEMPLATE}</code>\n\n"
        "<b>Видео-шаблон:</b>\n"
        f"<code>{video_tmpl or DEFAULT_VIDEO_TEMPLATE}</code>\n\n"
        "<b>CPC шаблон (клики):</b>\n"
        f"<code>{cpc_tmpl or DEFAULT_CPC_TEMPLATE}</code>\n\n"
        "CPA подстановки:\n"
        "<b>{title}, {price}, {currency}, {link}, {advertiser}, {erid}, {old_price}, {discount_percent}, {delivery_line}, {promocode_line}</b>\n\n"
        "CPC подстановки:\n"
        "<b>{name} — название рекламодателя, {link} — CPC-ссылка</b>\n\n"
        "Видео подстановки:\n"
        "<b>{title}, {link}, {description}</b>"
    )
    await safe_edit(callback.message, text, reply_markup=get_template_preview_buttons(), parse_mode=ParseMode.HTML)
    await callback.answer()

# --- Установка шаблона товара ---
@router.callback_query(F.data == "templates:set_product")
async def cb_set_product_template(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✏️ Введите шаблон для товарных постов. Можно менять порядок и добавлять эмодзи, но обязательные элементы должны остаться:\n\n"
        "Обязательные подстановки (их нельзя удалять):\n"
        "{title} — название товара\n"
        "{price} — цена\n"
        "{currency} — валюта (₽)\n"
        "{link} — ссылка «Посмотреть и заказать»\n"
        "{advertiser} — рекламодатель\n"
        "{erid} — ERID (обязательная маркировка)\n\n"
        "Необязательные (можно удалить или переместить):\n"
        "{old_price} — старая цена\n"
        "{discount_percent} — скидка в %\n"
        "{delivery_line} — строка с доставкой\n"
        "{promocode_line} — строка с промокодом\n"
        "{price_label} — слово «Цена»\n\n"
        "Пример стандартного шаблона:\n"
        "<code>🔥 {title}\n"
        "💰 {price_label}: {price} {currency}\n"
        "📦 {link}\n"
        "{discount_line}{delivery_line}{promocode_line}\n\n"
        "Реклама. {advertiser}. Erid: {erid}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="templates:cancel")]
        ])
    )
    await state.set_state(TemplateStates.waiting_product_template)
    await callback.answer()

@router.message(TemplateStates.waiting_product_template)
async def process_product_template(message: Message, state: FSMContext):
    template = message.text.strip()
    # Проверка длины
    if len(template) < 10:
        await message.answer("❌ Шаблон слишком короткий. Минимум 10 символов.")
        return
    # Проверка обязательных подстановок
    required = ['{title}', '{price}', '{currency}', '{link}', '{advertiser}', '{erid}']
    missing = [r for r in required if r not in template]
    if missing:
        await message.answer(
            f"❌ В шаблоне не хватает обязательных элементов: {', '.join(missing)}\n"
            "Пожалуйста, добавьте их и попробуйте снова."
        )
        return
    user_id = message.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET product_template=? WHERE user_id=?", (template, user_id))
        conn.commit()
    finally:
        conn.close()
    await message.answer("✅ Шаблон товаров сохранён! Сейчас покажу предпросмотр с реальным товаром...")
    await show_product_preview(message, user_id, template)
    await state.clear()
# --- Установка шаблона видео ---
@router.callback_query(F.data == "templates:set_video")
async def cb_set_video_template(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✏️ Введите шаблон для видео-анонсов. Можно использовать подстановки:\n"
        "{title} — название видео\n"
        "{link} — ссылка на видео\n"
        "{description} — описание (будет обрезано до 200 символов)\n\n"
        "Пример:\n"
        "<code>🎬 {title}\n\n{description}\n\n🔗 {link}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="templates:cancel")]
        ])
    )
    await state.set_state(TemplateStates.waiting_video_template)
    await callback.answer()
@router.message(TemplateStates.waiting_video_template)
async def process_video_template(message: Message, state: FSMContext):
    template = message.text.strip()
    if len(template) < 10:
        await message.answer("❌ Шаблон слишком короткий.")
        return
    user_id = message.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET video_template=? WHERE user_id=?", (template, user_id))
        conn.commit()
    finally:
        conn.close()
    await message.answer("✅ Шаблон видео сохранён! Предпросмотр с тестовыми данными:")
    await show_video_preview(message, template)
    await state.clear()

# --- Установка шаблона CPC ---
@router.callback_query(F.data == "templates:set_cpc")
async def cb_set_cpc_template(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✏️ Введите шаблон для CPC-постов (оплата за клик).\n\n"
        "Подстановки:\n"
        "<b>{name}</b> — название рекламодателя\n"
        "<b>{link}</b> — CPC-ссылка (обязательна)\n\n"
        "Пример стандартного шаблона:\n"
        "<code>👆 {name}\n\nПерейдите по ссылке:\n{link}</code>\n\n"
        "Можно добавлять эмодзи, менять порядок, но {link} обязателен.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="templates:cancel")]
        ])
    )
    await state.set_state(CpcStates.waiting_template)
    await callback.answer()

@router.message(CpcStates.waiting_template)
async def process_cpc_template(message: Message, state: FSMContext):
    template = message.text.strip()
    if len(template) < 5:
        await message.answer("❌ Шаблон слишком короткий. Минимум 5 символов.")
        return
    if "{link}" not in template:
        await message.answer("❌ В шаблоне обязательна подстановка {link} — CPC-ссылка.")
        return
    user_id = message.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET cpc_template=? WHERE user_id=?", (template, user_id))
        conn.commit()
    finally:
        conn.close()
    await message.answer("✅ CPC-шаблон сохранён! Предпросмотр:")
    await show_cpc_preview(message, template)
    await state.clear()

async def show_cpc_preview(message: Message, template: str):
    test_data = {
        "name": "Test Advertiser",
        "link": "https://example.com/cpc/ref"
    }
    try:
        text = template.format(**test_data)
    except KeyError as e:
        text = f"❌ Ошибка в шаблоне: неизвестная подстановка {e}"
    await message.answer(text, parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "templates:preview_cpc")
async def cb_preview_cpc(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        row = conn.execute("SELECT cpc_template FROM users WHERE user_id=?", (user_id,)).fetchone()
        tmpl = row["cpc_template"] if row and row["cpc_template"] else DEFAULT_CPC_TEMPLATE
    finally:
        conn.close()
    await show_cpc_preview(callback.message, tmpl)
    await callback.answer()

# --- Сброс шаблонов ---
@router.callback_query(F.data == "templates:reset")
async def cb_reset_templates(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        conn.execute("UPDATE users SET product_template='', video_template='', cpc_template='' WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    await safe_edit(callback.message, "✅ Все шаблоны сброшены до стандартных.", reply_markup=get_template_preview_buttons())
    await callback.answer()

# --- Предпросмотр товара ---
async def show_product_preview(message: Message, user_id: int, template: str = None):
    conn = get_db()
    try:
        product = conn.execute("""
            SELECT * FROM gdeslon_catalog
            WHERE user_id=? AND erid IS NOT NULL AND erid != ''
            ORDER BY RANDOM() LIMIT 1
        """, (user_id,)).fetchone()
        if not product:
            await message.answer("❌ Нет доступных товаров для предпросмотра.")
            return
    finally:
        conn.close()

    delivery_info = get_delivery_for_store(product["source"] or "")
    promocode = get_random_promocode(product["source"] or "")
    caption = generate_post_text(
        title=product["title"],
        price=product["price"],
        currency=product["currency"] or "₽",
        advertiser=product["advertiser"] or "Рекламодатель",
        erid=product["erid"],
        partner_url=product["partner_url"] or "https://example.com",
        old_price=product["old_price"],
        discount_percent=product["discount_percent"],
        delivery_info=delivery_info,
        promocode=promocode,
        custom_template=template  # будет использован пользовательский шаблон
    )
    await message.answer(caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def show_video_preview(message: Message, template: str):
    # Тестовые данные
    test_data = {
        "title": "Название видео",
        "link": "https://youtube.com/watch?v=test",
        "description": "Описание видео до 200 символов..."
    }
    try:
        text = template.format(**test_data)
    except KeyError as e:
        text = f"❌ Ошибка в шаблоне: неизвестная подстановка {e}"
    await message.answer(text, parse_mode=ParseMode.HTML)

@router.callback_query(F.data == "templates:preview_product")
async def cb_preview_product(callback: CallbackQuery):
    user_id = callback.from_user.id
    await show_product_preview(callback.message, user_id)
    await callback.answer()

@router.callback_query(F.data == "templates:preview_video")
async def cb_preview_video(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        template = conn.execute("SELECT video_template FROM users WHERE user_id=?", (user_id,)).fetchone()
        tmpl = template["video_template"] if template and template["video_template"] else DEFAULT_VIDEO_TEMPLATE
    finally:
        conn.close()
    await show_video_preview(callback.message, tmpl)
    await callback.answer()

@router.callback_query(F.data == "templates:cancel")
async def cb_templates_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb_menu_templates(callback)
    await callback.answer()
