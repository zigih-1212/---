# utils.py
import logging
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
