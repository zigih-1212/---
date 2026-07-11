# utils.py
import logging
import feedparser
from aiogram import Bot
from services.db import get_db
from config import ADMIN_IDS
from config import MIN_PAYOUT
from config import BOT_USERNAME

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

async def check_payout_threshold(user_id: int, bot: Bot):
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT balance_available, payout_notified FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
        if not user:
            return
        available = user["balance_available"] or 0.0
        notified = user["payout_notified"]
        if available >= MIN_PAYOUT and not notified:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"🎉 <b>Поздравляем!</b>\n\n"
                        f"Ваш доступный баланс достиг <b>{available:.2f} ₽</b>.\n"
                        f"Вы можете запросить выплату в разделе «💰 Финансы»."
                    ),
                    parse_mode=ParseMode.HTML
                )
                conn.execute("UPDATE users SET payout_notified=1 WHERE user_id=?", (user_id,))
                conn.commit()
                logger.info(f"Payout threshold notification sent to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send payout notification to {user_id}: {e}")
        elif available < MIN_PAYOUT and notified:
            conn.execute("UPDATE users SET payout_notified=0 WHERE user_id=?", (user_id,))
            conn.commit()
    finally:
        conn.close()
# utils.py

async def generate_success_text(user_id: int, role: str = "blogger") -> str:
    """Создаёт сообщение для кнопки «Поделиться успехом»."""
    conn = get_db()
    try:
        # Общая статистика по постам
        total_posts = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE user_id=? AND status='published'",
            (user_id,)
        ).fetchone()[0] or 0

        # Топ-3 магазина за всё время
        top_stores = conn.execute("""
            SELECT g.source, COUNT(*) as cnt
            FROM posts p
            JOIN gdeslon_catalog g ON p.donor_post_id LIKE 'admitad_' || g.id || '_%'
            WHERE p.user_id=? AND p.status='published'
            GROUP BY g.source
            ORDER BY cnt DESC
            LIMIT 3
        """, (user_id,)).fetchall()

        # Баланс
        balance = conn.execute(
            "SELECT balance_available, balance_pending FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
        available = balance["balance_available"] or 0
        pending = balance["balance_pending"] or 0
        total_earned = available + pending

        # Транзакции за 30 дней
        recent_earn = conn.execute("""
            SELECT SUM(payment_sum) FROM admitad_transactions
            WHERE user_id=? AND time >= strftime('%s', 'now', '-30 days')
        """, (user_id,)).fetchone()[0] or 0

    finally:
        conn.close()

    if role == "saas":
        role_text = "SaaS-клиент AutoPost"
    else:
        role_text = "Блогер AutoPost"

    lines = [
        f"🚀 Я зарабатываю с AutoPost Bot!",
        f"👤 {role_text}",
        f"📬 Опубликовано постов: {total_posts}",
    ]

    if top_stores:
        stores_str = ", ".join([f"{s['source']} ({s['cnt']} пост.)" for s in top_stores])
        lines.append(f"🏪 Топ магазинов: {stores_str}")

    lines.append(f"💰 Заработано за 30 дней: {recent_earn:.0f} ₽")
    lines.append(f"💳 Общий баланс: {total_earned:.0f} ₽ (доступно {available:.0f} ₽)")

    if role == "blogger":
        # Реферальная ссылка
        sub_id = conn.execute("SELECT sub_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if sub_id:
            ref_link = f"https://t.me/{BOT_USERNAME}?start={sub_id['sub_id']}"
            lines.append(f"\n🔗 Присоединяйся: {ref_link}")

    return "\n".join(lines)

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
