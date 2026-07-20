"""
channel_manager.py — «Шпионский режим»: управление Telegram-каналами через бота.
Предоставляет функции для админ-панели и хендлеров.
"""

import logging
from typing import Optional, Dict, Any, List

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger("autopost_bot.channel_manager")

# =============================================================================
# === ПРОВЕРКА ПРАВ БОТА ======================================================
# =============================================================================
async def check_bot_admin(bot: Bot, channel_id: str) -> Dict[str, Any]:
    """
    Проверяет статус бота в канале.
    Возвращает словарь:
        is_admin: bool
        can_post: bool
        status: str (creator/administrator/member/left/kicked)
        error: str | None
    """
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=bot.id)
        status = member.status
        is_admin = status in ("creator", "administrator")
        can_post = is_admin and (status == "creator" or getattr(member, "can_post_messages", False))
        return {
            "is_admin": is_admin,
            "can_post": can_post,
            "status": status,
            "error": None
        }
    except TelegramAPIError as e:
        logger.error(f"check_bot_admin error for {channel_id}: {e}")
        return {
            "is_admin": False,
            "can_post": False,
            "status": "unknown",
            "error": str(e)
        }

# =============================================================================
# === ИНФОРМАЦИЯ О КАНАЛЕ ====================================================
# =============================================================================
async def get_chat_info(bot: Bot, channel_id: str) -> Optional[Dict[str, Any]]:
    """
    Получает основную информацию о канале/чате.
    Возвращает словарь с полями:
        id, title, username, description, invite_link, member_count,
        photo_url (приблизительно)
    или None при ошибке.
    """
    try:
        chat = await bot.get_chat(chat_id=channel_id)
        info = {
            "id": chat.id,
            "title": chat.title,
            "username": getattr(chat, "username", None),
            "description": getattr(chat, "description", None),
            "invite_link": getattr(chat, "invite_link", None),
            "member_count": await _get_member_count(bot, channel_id),
            "photo_url": None
        }
        # Попытка получить фото (файл не скачиваем, только file_id)
        if chat.photo:
            file = await bot.get_file(chat.photo.small_file_id)
            info["photo_url"] = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
        return info
    except TelegramAPIError as e:
        logger.error(f"get_chat_info error for {channel_id}: {e}")
        return None

async def _get_member_count(bot: Bot, channel_id: str) -> Optional[int]:
    """Возвращает количество участников канала (если доступно)."""
    try:
        count = await bot.get_chat_member_count(chat_id=channel_id)
        return count
    except TelegramAPIError:
        return None

      # =============================================================================
# === ЧТЕНИЕ ПОСЛЕДНИХ ПОСТОВ КАНАЛА =========================================
# =============================================================================
async def get_recent_posts(bot: Bot, channel_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Возвращает список последних сообщений из канала (требует админских прав).
    Каждое сообщение — словарь с полями:
        message_id, date, text, photo_url, video_url
    """
    try:
        messages = []
        async for msg in bot.get_chat_history(chat_id=channel_id, limit=limit):
            post = {
                "message_id": msg.message_id,
                "date": msg.date.isoformat() if msg.date else None,
                "text": msg.text or msg.caption or "",
                "photo_url": None,
                "video_url": None
            }
            if msg.photo:
                # Берем самое большое фото
                file = await bot.get_file(msg.photo[-1].file_id)
                post["photo_url"] = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
            if msg.video:
                file = await bot.get_file(msg.video.file_id)
                post["video_url"] = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
            messages.append(post)
        return messages
    except TelegramAPIError as e:
        logger.error(f"get_recent_posts error for {channel_id}: {e}")
        return []

# =============================================================================
# === ПУБЛИКАЦИЯ ТЕСТОВОГО ПОСТА =============================================
# =============================================================================
async def publish_test_post(bot: Bot, channel_id: str, text: str,
                          photo_url: Optional[str] = None,
                          check_permissions: bool = True,
                          max_retries: int = 3) -> Optional[int]:
    """Publishes post to channel with retries and enhanced error handling.
    
    Args:
        bot: Bot instance
        channel_id: Target channel ID
        text: Post text
        photo_url: Optional photo URL
        check_permissions: Verify bot has posting rights
        max_retries: Maximum attempts to publish
        
    Returns:
        message_id if successful, None otherwise
    """
    if check_permissions:
        try:
            member = await bot.get_chat_member(channel_id, bot.id)
            if not getattr(member, 'can_post_messages', False):
                logger.warning(f"No posting rights in channel {channel_id}")
                return None
        except TelegramAPIError as e:
            logger.error(f"Permission check failed for {channel_id}: {e}")
            return None

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            from aiogram.enums import ParseMode
            if photo_url:
                msg = await bot.send_photo(
                    chat_id=channel_id,
                    photo=photo_url,
                    caption=text[:1024],  # Telegram caption limit
                    parse_mode=ParseMode.HTML
                )
            else:
                msg = await bot.send_message(
                    chat_id=channel_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False
                )
            logger.info(f"Successfully published to {channel_id} (attempt {attempt})")
            return msg.message_id
        except TelegramAPIError as e:
            last_error = str(e)
            logger.warning(f"Publish attempt {attempt} failed for {channel_id}: {e}")
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
    """
    Публикует пост в канал (требует админских прав).
    Возвращает message_id или None при ошибке.
    """
    try:
        from aiogram.enums import ParseMode
        if photo_url:
            msg = await bot.send_photo(
                chat_id=channel_id,
                photo=photo_url,
                caption=text,
                parse_mode=ParseMode.HTML
            )
        else:
            msg = await bot.send_message(
                chat_id=channel_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )
        return msg.message_id
    except TelegramAPIError as e:
        logger.error(f"publish_test_post error for {channel_id}: {e}")
        return None

# =============================================================================
# === СМЕНА ОПИСАНИЯ КАНАЛА ==================================================
# =============================================================================
async def set_chat_description(bot: Bot, channel_id: str, description: str) -> bool:
    """Меняет описание канала (требует админских прав)."""
    try:
        await bot.set_chat_description(chat_id=channel_id, description=description)
        return True
    except TelegramAPIError as e:
        logger.error(f"set_chat_description error for {channel_id}: {e}")
        return False

# =============================================================================
# === СМЕНА АВАТАРА КАНАЛА ====================================================
# =============================================================================
async def set_chat_photo(bot: Bot, channel_id: str, photo_url: str) -> bool:
    """
    Устанавливает аватар канала по URL.
    Внимание: URL должен быть прямой ссылкой на файл.
    """
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                if resp.status != 200:
                    return False
                photo_bytes = await resp.read()
        from aiogram.types import FSInputFile
        # Сохраняем во временный файл
        with open("/tmp/chat_photo.jpg", "wb") as f:
            f.write(photo_bytes)
        photo = FSInputFile("/tmp/chat_photo.jpg")
        await bot.set_chat_photo(chat_id=channel_id, photo=photo)
        return True
    except Exception as e:
        logger.error(f"set_chat_photo error for {channel_id}: {e}")
        return False

# =============================================================================
# === ПОЛУЧЕНИЕ СПИСКА АДМИНИСТРАТОРОВ =======================================
# =============================================================================
async def get_chat_administrators(bot: Bot, channel_id: str) -> List[Dict[str, Any]]:
    """Возвращает список администраторов канала."""
    try:
        admins = await bot.get_chat_administrators(chat_id=channel_id)
        result = []
        for member in admins:
            user = member.user
            result.append({
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "status": member.status,
                "can_post": getattr(member, "can_post_messages", False) if member.status != "creator" else True
            })
        return result
    except TelegramAPIError as e:
        logger.error(f"get_chat_administrators error for {channel_id}: {e}")
        return []

  # =============================================================================
# === ИНТЕГРАЦИОННЫЕ ХЕЛПЕРЫ ДЛЯ АДМИН-ПАНЕЛИ ================================
# =============================================================================

async def get_full_channel_report(bot: Bot, channel_id: str) -> Dict[str, Any]:
    """
    Собирает полный отчёт о канале: информацию, права бота, последние посты, админов.
    Используется в админ-панели для карточки канала.
    """
    info = await get_chat_info(bot, channel_id) or {}
    rights = await check_bot_admin(bot, channel_id)
    posts = await get_recent_posts(bot, channel_id, limit=5) if rights["is_admin"] else []
    admins = await get_chat_administrators(bot, channel_id) if rights["is_admin"] else []

    return {
        "info": info,
        "rights": rights,
        "recent_posts": posts,
        "administrators": admins
    }


async def channel_quick_action(bot: Bot, channel_id: str, action: str, **kwargs) -> Dict[str, Any]:
    """
    Универсальная функция для быстрых действий с каналом из админ-панели.
    action может быть: 'publish', 'set_description', 'set_photo'.
    Возвращает результат операции.
    """
    if action == "publish":
        msg_id = await publish_test_post(bot, channel_id, kwargs.get("text", ""), kwargs.get("photo_url"))
        return {"ok": msg_id is not None, "message_id": msg_id}
    elif action == "set_description":
        ok = await set_chat_description(bot, channel_id, kwargs.get("description", ""))
        return {"ok": ok}
    elif action == "set_photo":
        ok = await set_chat_photo(bot, channel_id, kwargs.get("photo_url", ""))
        return {"ok": ok}
    else:
        return {"ok": False, "error": "Unknown action"}


# =============================================================================
# === ОБЁРТКА ДЛЯ БЕЗОПАСНОЙ ПУБЛИКАЦИИ (ФОЛБЭК НА ТЕКСТ) ===================
# =============================================================================

async def safe_publish_to_channel(bot: Bot, channel_id: str, text: str,
                                  photo_url: Optional[str] = None,
                                  video_url: Optional[str] = None) -> Optional[int]:
    """
    Пытается опубликовать пост с фото/видео, при неудаче — падает до текста.
    Возвращает message_id или None.
    """
    from aiogram.enums import ParseMode
    from aiogram.exceptions import TelegramAPIError

    if video_url:
        try:
            msg = await bot.send_video(channel_id, video_url, caption=text, parse_mode=ParseMode.HTML)
            return msg.message_id
        except TelegramAPIError as e:
            logger.warning(f"Video failed, trying photo: {e}")

    if photo_url:
        try:
            msg = await bot.send_photo(channel_id, photo_url, caption=text, parse_mode=ParseMode.HTML)
            return msg.message_id
        except TelegramAPIError as e:
            logger.warning(f"Photo failed, trying text only: {e}")

    try:
        msg = await bot.send_message(channel_id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
        return msg.message_id
    except TelegramAPIError as e:
        logger.error(f"Text publish failed: {e}")
        return None
