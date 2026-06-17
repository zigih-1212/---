"""
stats.py — Модуль статистики для блогеров и SaaS-клиентов
"""

import sqlite3
import logging
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger("autopost_bot")

DB_PATH = "/app/data/autopost.db"
MIN_PAYOUT = 2000.0

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


# =============================================================================
# === БЛОГЕР ==================================================================
# =============================================================================

def get_blogger_stats(user_id: int) -> Dict:
    """Полная статистика для блогера"""
    conn = get_db()
    try:
        post_stats = conn.execute("""
            SELECT
                COUNT(*) as total_posts,
                SUM(CASE WHEN status = 'published' THEN 1 ELSE 0 END) as published_posts,
                SUM(CASE WHEN published_at >= datetime('now', '-30 days') THEN 1 ELSE 0 END) as posts_last_30d,
                SUM(CASE WHEN status = 'published' AND published_at >= datetime('now', '-30 days') THEN 1 ELSE 0 END) as published_last_30d
            FROM posts
            WHERE user_id = ?
        """, (user_id,)).fetchone()

        sales_stats = conn.execute("""
            SELECT
                COUNT(*) as total_sales,
                COALESCE(SUM(payout), 0.0) as total_earned,
                COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-30 days') THEN payout ELSE 0 END), 0.0) as earned_last_30d
            FROM transactions
            WHERE sub_id = (SELECT sub_id FROM users WHERE user_id = ?)
              AND status IN ('approved', 'paid')
        """, (user_id,)).fetchone()

        return {
            "total_posts":      int(post_stats["total_posts"] or 0),
            "published_posts":  int(post_stats["published_posts"] or 0),
            "posts_last_30d":   int(post_stats["posts_last_30d"] or 0),
            "published_last_30d": int(post_stats["published_last_30d"] or 0),
            "total_sales":      int(sales_stats["total_sales"] or 0),
            "total_earned":     round(float(sales_stats["total_earned"] or 0), 2),
            "earned_last_30d":  round(float(sales_stats["earned_last_30d"] or 0), 2),
        }
    except Exception as e:
        logger.error(f"Ошибка get_blogger_stats для {user_id}: {e}")
        return {
            "total_posts": 0, "published_posts": 0, "posts_last_30d": 0,
            "published_last_30d": 0, "total_sales": 0,
            "total_earned": 0.0, "earned_last_30d": 0.0,
        }
    finally:
        conn.close()


# =============================================================================
# === SAAS ====================================================================
# =============================================================================

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


def get_saas_channel_stats(user_id: int, channel_id: str, period: str = "30d") -> Dict:
    """
    Статистика по одному каналу SaaS-клиента за выбранный период.
    period: '7d' | '30d' | 'all'
    """
    conn = get_db()
    try:
        cfg = STAT_PERIODS.get(period, STAT_PERIODS["30d"])
        days = cfg["days"]

        if days:
            date_filter = f"AND created_at >= datetime('now', '-{days} days')"
        else:
            date_filter = ""

        post_stats = conn.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'published'  THEN 1 ELSE 0 END) as published,
                SUM(CASE WHEN status = 'quarantine' THEN 1 ELSE 0 END) as quarantine,
                SUM(CASE WHEN status = 'error'      THEN 1 ELSE 0 END) as errors,
                MAX(published_at) as last_published_at
            FROM posts
            WHERE user_id = ? AND channel_id = ?
            {date_filter}
        """, (user_id, channel_id)).fetchone()

        channel_row = conn.execute("""
            SELECT channel_title FROM channels
            WHERE user_id = ? AND channel_id = ?
        """, (user_id, channel_id)).fetchone()

        channel_title = channel_row["channel_title"] if channel_row else channel_id

        last_pub = post_stats["last_published_at"]
        if last_pub:
            try:
                dt = datetime.fromisoformat(last_pub.replace("Z", "+00:00"))
                last_pub_fmt = dt.strftime("%d %b, %H:%M")
            except Exception:
                last_pub_fmt = str(last_pub)[:16]
        else:
            last_pub_fmt = "—"

        return {
            "channel_id":       channel_id,
            "channel_title":    channel_title,
            "period_label":     cfg["label"],
            "total":            int(post_stats["total"] or 0),
            "published":        int(post_stats["published"] or 0),
            "quarantine":       int(post_stats["quarantine"] or 0),
            "errors":           int(post_stats["errors"] or 0),
            "last_published_at": last_pub_fmt,
        }
    except Exception as e:
        logger.error(f"Ошибка get_saas_channel_stats [{channel_id}]: {e}")
        return {
            "channel_id":       channel_id,
            "channel_title":    channel_id,
            "period_label":     STAT_PERIODS.get(period, {}).get("label", ""),
            "total":      0,
            "published":  0,
            "quarantine": 0,
            "errors":     0,
            "last_published_at": "—",
        }
    finally:
        conn.close()
        
