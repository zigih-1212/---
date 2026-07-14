# handlers/social.py
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.db import get_db
from config import BOT_USERNAME

logger = logging.getLogger("autopost_bot.social")

router = Router(name="social")

# Состояния FSM
class SocialStates(StatesGroup):
    waiting_add_link = State()
    waiting_manual_link = State()

# ---------- Клавиатуры ----------
def kb_social_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить YouTube / Rutube", callback_data="social:add_channel")],
        [InlineKeyboardButton(text="📤 Ручной пост (TikTok/Instagram)", callback_data="social:manual_post")],
        [InlineKeyboardButton(text="📋 Мои каналы", callback_data="social:list_channels")],
        [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="cabinet:open")]
    ])

# ---------- Основное меню «Мои видео-каналы» ----------
@router.callback_query(F.data == "blogger:social_channels")
async def cb_social_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎥 <b>Мои видео-каналы</b>\n\n"
        "Здесь можно подключить YouTube или Rutube каналы — бот будет автоматически анонсировать новые видео.\n"
        "Для TikTok и Instagram используйте ручную отправку ссылки.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_social_main()
    )
    await callback.answer()

# ---------- Добавление YouTube/Rutube ----------
@router.callback_query(F.data == "social:add_channel")
async def cb_add_channel_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "🔗 Отправьте ссылку на ваш YouTube или Rutube канал.\n"
        "Например:\n"
        "• <code>https://www.youtube.com/@username</code>\n"
        "• <code>https://rutube.ru/channel/12345/</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="social:main")]
        ])
    )
    await state.set_state(SocialStates.waiting_add_link)
    await callback.answer()

@router.message(SocialStates.waiting_add_link)
async def process_add_channel_link(message: Message, state: FSMContext):
    url = message.text.strip()
    user_id = message.from_user.id

    platform = None
    channel_id = None
    channel_url = url

    if "youtube.com" in url or "youtu.be" in url:
        platform = "youtube"
        # Если есть /channel/UC...
        if "/channel/" in url:
            channel_id = url.split("/channel/")[1].split("/")[0].split("?")[0]
        # Если есть /@username
        elif "/@" in url:
            username = url.split("/@")[1].split("/")[0].split("?")[0]
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(f"https://www.youtube.com/@{username}")
                    if resp.status_code == 200:
                        # Ищем externalId в мета-тегах
                        match = re.search(r'"externalId":"(UC[\w-]+)"', resp.text)
                        if match:
                            channel_id = match.group(1)
                        else:
                            # Запасной вариант: canonical URL
                            match = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]+)">', resp.text)
                            if match:
                                channel_id = match.group(1)
                            else:
                                await message.answer("❌ Не удалось определить ID канала. Попробуйте использовать прямую ссылку вида https://www.youtube.com/channel/UC...")
                                return
                    else:
                        await message.answer("❌ Не удалось загрузить страницу канала. Проверьте ссылку.")
                        return
            except Exception as e:
                logger.error(f"Ошибка получения channel_id: {e}")
                await message.answer("❌ Произошла ошибка при определении ID канала. Попробуйте позже.")
                return
        else:
            await message.answer("❌ Неверный формат ссылки. Укажите ссылку с /channel/... или /@username.")
            return
    elif "rutube.ru" in url:
        platform = "rutube"
        match = re.search(r'rutube\.ru/channel/(\d+)', url)
        if match:
            channel_id = match.group(1)
        else:
            await message.answer("❌ Неверный формат ссылки на Rutube. Ожидается: https://rutube.ru/channel/12345/")
            return
    else:
        await message.answer("❌ Поддерживаются только YouTube и Rutube. Для TikTok и Instagram используйте ручной постинг.")
        return

    # Сохраняем в БД
    conn = get_db()
    try:
        exists = conn.execute(
            "SELECT id FROM social_channels WHERE user_id=? AND platform=? AND channel_id=?",
            (user_id, platform, channel_id)
        ).fetchone()
        if exists:
            await message.answer("⚠️ Этот канал уже добавлен.")
            await state.clear()
            return

        conn.execute(
            "INSERT INTO social_channels (user_id, platform, channel_id, channel_url) VALUES (?, ?, ?, ?)",
            (user_id, platform, channel_id, channel_url)
        )
        conn.commit()
    finally:
        conn.close()

    await message.answer(f"✅ Канал {platform} добавлен! Новые видео будут автоматически публиковаться в ваши Telegram-каналы.")
    await state.clear()
    await message.answer("🎥 Управление видео-каналами:", reply_markup=kb_social_main())

# ---------- Список каналов ----------
@router.callback_query(F.data == "social:list_channels")
async def cb_list_channels(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db()
    try:
        channels = conn.execute(
            "SELECT id, platform, channel_id, channel_url FROM social_channels WHERE user_id=? AND is_active=1",
            (user_id,)
        ).fetchall()
    finally:
        conn.close()

    if not channels:
        text = "📋 У вас пока нет подключённых видео-каналов."
    else:
        text = "📋 <b>Ваши видео-каналы:</b>\n\n"
        for ch in channels:
            platform_emoji = {"youtube": "▶️", "rutube": "📺"}.get(ch["platform"], "❓")
            text += f"{platform_emoji} {ch['platform']}: {ch['channel_id']}\n"
            text += f"   <a href='{ch['channel_url']}'>Ссылка</a>\n"
        text += "\nНажмите на кнопку, чтобы удалить:"
    kb_rows = []
    for ch in channels:
        kb_rows.append([InlineKeyboardButton(
            text=f"🗑 Удалить {ch['platform']} ({ch['channel_id'][:15]}...)",
            callback_data=f"social:delete:{ch['id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="social:main")])
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()

@router.callback_query(F.data.startswith("social:delete:"))
async def cb_delete_channel(callback: CallbackQuery):
    channel_id = int(callback.data.split(":")[2])
    user_id = callback.from_user.id
    conn = get_db()
    conn.execute("DELETE FROM social_channels WHERE id=? AND user_id=?", (channel_id, user_id))
    conn.commit()
    conn.close()
    await callback.answer("✅ Канал удалён", show_alert=True)
    await cb_list_channels(callback)

# ---------- Ручной постинг (TikTok/Instagram) ----------
@router.callback_query(F.data == "social:manual_post")
async def cb_manual_post_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📤 Отправьте ссылку на видео или пост из TikTok или Instagram.\n"
        "Бот опубликует её в ваши каналы с подписью.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="social:main")]
        ])
    )
    await state.set_state(SocialStates.waiting_manual_link)
    await callback.answer()

@router.message(SocialStates.waiting_manual_link)
async def process_manual_link(message: Message, state: FSMContext, bot: Bot):
    url = message.text.strip()
    user_id = message.from_user.id

    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer("❌ Некорректная ссылка.")
        return

    conn = get_db()
    try:
        channels = conn.execute(
            "SELECT channel_id FROM channels WHERE user_id=? AND is_active=1",
            (user_id,)
        ).fetchall()
        user_template = conn.execute("SELECT video_template FROM users WHERE user_id=?", (user_id,)).fetchone()
        tmpl = user_template["video_template"] if user_template and user_template["video_template"] else DEFAULT_VIDEO_TEMPLATE
    finally:
        conn.close()

    if not channels:
        await message.answer("❌ У вас нет активных Telegram-каналов.")
        return

    caption = tmpl.format(title=url, link=url, description="")
    for ch in channels:
        try:
            await bot.send_message(ch["channel_id"], caption, parse_mode=ParseMode.HTML)
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка отправки в {ch['channel_id']}: {e}")

    await message.answer("✅ Ссылка опубликована во всех ваших каналах.")
    await state.clear()

# ---------- Возврат в главное меню соцсетей ----------
@router.callback_query(F.data == "social:main")
async def cb_social_main_return(callback: CallbackQuery):
    await cb_social_main(callback)
