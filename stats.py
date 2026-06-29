"""
stats.py — Модуль статистики SaaS-клиентов
"""

import sqlite3
import logging
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger("autopost_bot")

DB_PATH = "/app/data/autopost.db"

# Периоды для переключения статистики
STAT_PERIODS = {
    "7d":  {"label": "7 дней",    "days": 7},
    "30d": {"label": "30 дней",   "days": 30},
    "all": {"label": "Всё время", "days": None},
}


def get_db():
    """Локальная копия get_db, чтобы избежать циклического импорта"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def get_saas_channels(user_id: int) -> List[Dict]:
    """Список активных каналов SaaS-клиента."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT channel_id, channel_title
            FROM channels
            WHERE user_id = ? AND is_active = 1
            ORDER BY id ASC
        """, (user_id,)).fetchall()
        return [
            {"channel_id": r["channel_id"], "channel_title": r["channel_title"]}
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Ошибка get_saas_channels для {user_id}: {e}")
        return []
    finally:
        conn.close()


def get_saas_overview(user_id: int) -> Dict:
    """Общая статистика SaaS-клиента с разбивкой по магазинам."""
    conn = get_db()
    try:
        total_posts = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE user_id=? AND status='published'",
            (user_id,)
        ).fetchone()[0]
        posts_30d = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE user_id=? AND status='published' AND published_at >= datetime('now', '-30 days')",
            (user_id,)
        ).fetchone()[0]
        store_stats = conn.execute("""
            SELECT g.source, COUNT(*) as cnt
            FROM posts p
            JOIN gdeslon_catalog g ON g.partner_url = p.donor_post_id
            WHERE p.user_id=? AND p.status='published'
            GROUP BY g.source
            ORDER BY cnt DESC
        """, (user_id,)).fetchall()
    finally:
        conn.close()
    return {
        "total_posts": total_posts or 0,
        "posts_30d": posts_30d or 0,
        "by_store": {row[0]: row[1] for row in store_stats}
    }


def get_saas_channel_stats_new(user_id: int, channel_id: str, period: str = "30d") -> Dict:
    """Статистика по одному каналу с разбивкой по магазинам за период."""
    conn = get_db()
    try:
        cfg = STAT_PERIODS.get(period, STAT_PERIODS["30d"])
        days = cfg["days"]
        date_filter = f"AND p.published_at >= datetime('now', '-{days} days')" if days else ""
        post_stats = conn.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN p.status='published' THEN 1 ELSE 0 END) as published,
                SUM(CASE WHEN p.status='error' THEN 1 ELSE 0 END) as errors,
                MAX(p.published_at) as last_published_at
            FROM posts p
            WHERE p.user_id=? AND p.channel_id=?
            {date_filter}
        """, (user_id, channel_id)).fetchone()
        store_stats = conn.execute(f"""
            SELECT g.source, COUNT(*) as cnt
            FROM posts p
            JOIN gdeslon_catalog g ON g.partner_url = p.donor_post_id
            WHERE p.user_id=? AND p.channel_id=? AND p.status='published'
            {date_filter}
            GROUP BY g.source
            ORDER BY cnt DESC
        """, (user_id, channel_id)).fetchall()
        channel_title = channel_id
        channel_row = conn.execute(
            "SELECT channel_title FROM channels WHERE user_id=? AND channel_id=?",
            (user_id, channel_id)
        ).fetchone()
        if channel_row:
            channel_title = channel_row[0]
        last_pub = post_stats["last_published_at"]
        if last_pub:
            try:
                dt = datetime.fromisoformat(last_pub.replace("Z", "+00:00"))
                last_pub_fmt = dt.strftime("%d %b, %H:%M")
            except:
                last_pub_fmt = str(last_pub)[:16]
        else:
            last_pub_fmt = "—"
    finally:
        conn.close()
    return {
        "channel_id": channel_id,
        "channel_title": channel_title,
        "period_label": cfg["label"],
        "total": int(post_stats["total"] or 0),
        "published": int(post_stats["published"] or 0),
        "errors": int(post_stats["errors"] or 0),
        "last_published_at": last_pub_fmt,
        "by_store": {row[0]: row[1] for row in store_stats}
    }
