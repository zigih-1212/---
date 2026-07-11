# utils.py
import logging
import feedparser
from aiogram import Bot
from services.db import get_db
from config import ADMIN_IDS


logger = logging.getLogger("autopost_bot.referral")

def log_admin_action(admin_id: int, action: str, details: str = ""):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO admin_audit (admin_id, action, details) VALUES (?, ?, ?)",
            (admin_id, action, details)
        )
        conn.commit()
    finally:
        conn.close()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def apply_referral_bonus(user_id: int, action_amount: float):
    REFERRAL_RATE = 0.10
    if action_amount <= 0:
        return
    conn = get_db()
    try:
        user = conn.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user or not user["referrer_id"]:
            return
        referrer_id = user["referrer_id"]
        bonus = round(action_amount * REFERRAL_RATE, 2)
        conn.execute("UPDATE users SET balance_pending = balance_pending + ? WHERE user_id = ?", (bonus, referrer_id))
        conn.commit()
        logger.info(f"Referral bonus: +{bonus} to user {referrer_id} from user {user_id}")
    except Exception as e:
        logger.error(f"Failed to apply referral bonus for user {user_id}: {e}")
    finally:
        conn.close()

async def check_rss_and_publish(bot: Bot):
    """Проверяет RSS-ленты YouTube и Rutube и публикует новые видео."""
    conn = get_db()
    try:
        channels = conn.execute("""
            SELECT sc.id, sc.user_id, sc.platform, sc.channel_id, sc.last_video_id,
                   c.channel_id as tg_channel
            FROM social_channels sc
            JOIN channels c ON sc.user_id = c.user_id AND c.is_active = 1
            WHERE sc.is_active = 1 AND sc.platform IN ('youtube', 'rutube')
        """).fetchall()
    finally:
        conn.close()

    for ch in channels:
        if ch["platform"] == "youtube":
            # Формируем URL RSS: для channel_id (UC...) или username
            if ch["channel_id"].startswith("UC"):
                rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
            else:
                # Если это username, придётся использовать другой способ, пока пропустим
                logger.warning(f"YouTube username {ch['channel_id']} not supported yet")
                continue
        elif ch["platform"] == "rutube":
            rss_url = f"https://rutube.ru/api/rss/channel/{ch['channel_id']}/"
        else:
            continue

        try:
            feed = feedparser.parse(rss_url)
        except Exception as e:
            logger.error(f"Error parsing RSS for {ch['channel_id']}: {e}")
            continue

        if not feed.entries:
            continue

        latest_entry = feed.entries[0]  # Первый — самый свежий
        video_id = latest_entry.get('id', '') or latest_entry.get('link', '')
        if video_id == ch["last_video_id"]:
            continue  # Уже публиковали

        # Публикуем
        title = latest_entry.get('title', 'Новое видео')
        link = latest_entry.get('link', '')
        description = latest_entry.get('summary', '')[:200]
        caption = f"🎬 <b>{title}</b>\n\n{description}\n\n🔗 <a href='{link}'>Смотреть</a>"

        try:
            await bot.send_message(ch["tg_channel"], caption, parse_mode=ParseMode.HTML)
            logger.info(f"Published new video {video_id} to {ch['tg_channel']}")
        except Exception as e:
            logger.error(f"Failed to publish to {ch['tg_channel']}: {e}")
            continue

        # Обновляем last_video_id
        conn = get_db()
        try:
            conn.execute("UPDATE social_channels SET last_video_id=? WHERE id=?", (video_id, ch["id"]))
            conn.commit()
        finally:
            conn.close()
