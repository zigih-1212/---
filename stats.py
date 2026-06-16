from datetime import datetime, timedelta, timezone

def get_blogger_stats(user_id: int) -> dict:
    """Полная статистика для блогера"""
    conn = get_db()
    try:
        # Основная статистика по постам
        row = conn.execute("""
            SELECT 
                COUNT(*) as total_posts,
                SUM(CASE WHEN status = 'published' THEN 1 ELSE 0 END) as published_posts,
                SUM(CASE WHEN published_at >= datetime('now', '-30 days') THEN 1 ELSE 0 END) as posts_last_30d,
                SUM(CASE WHEN status = 'published' AND published_at >= datetime('now', '-30 days') THEN 1 ELSE 0 END) as published_last_30d
            FROM posts 
            WHERE user_id = ?
        """, (user_id,)).fetchone()

        # Статистика по транзакциям (продажи)
        sales_row = conn.execute("""
            SELECT 
                COUNT(*) as total_sales,
                COALESCE(SUM(payout), 0.0) as total_earned,
                COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-30 days') THEN payout ELSE 0 END), 0.0) as earned_last_30d
            FROM transactions 
            WHERE sub_id = (SELECT sub_id FROM users WHERE user_id = ?) 
              AND status IN ('approved', 'paid')
        """, (user_id,)).fetchone()

        return {
            "total_posts": row["total_posts"] or 0,
            "published_posts": row["published_posts"] or 0,
            "posts_last_30d": row["posts_last_30d"] or 0,
            "published_last_30d": row["published_last_30d"] or 0,
            "total_sales": sales_row["total_sales"] or 0,
            "total_earned": round(float(sales_row["total_earned"] or 0), 2),
            "earned_last_30d": round(float(sales_row["earned_last_30d"] or 0), 2),
        }
    finally:
        conn.close()
