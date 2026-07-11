# webapp/routes_postback.py
import logging
import re
from fastapi import APIRouter, Request
from services.db import get_db
from utils import apply_referral_bonus

logger = logging.getLogger("autopost_bot.postback")

router = APIRouter()

@router.post("/api/admitad/postback")
async def admitad_postback(request: Request):
    data = await request.json()
    action = data.get("action")
    action_id = data.get("action_id")
    payment_sum = float(data.get("payment_sum", 0))
    status = data.get("status", "pending")
    subid1 = data.get("subid1", "")

    if not subid1 or not action_id:
        return {"ok": False, "error": "missing subid1 or action_id"}

    conn = get_db()
    try:
        match = re.search(r'uid(\d+)$', subid1)
        if not match:
            return {"ok": False, "error": "invalid subid1"}
        user_id = int(match.group(1))

        user = conn.execute("SELECT commission_rate FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            return {"ok": False, "error": "user not found"}
        commission_rate = user["commission_rate"] or 0.95

        user_amount = round(payment_sum * commission_rate, 2)

        conn.execute("""
            INSERT OR IGNORE INTO admitad_transactions 
            (admitad_id, user_id, action, action_id, payment_sum, payment_status, subid1)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (data.get("id"), user_id, action, action_id, payment_sum, status, subid1))

        if status in ("pending", "new"):
            conn.execute("UPDATE users SET balance_pending = balance_pending + ? WHERE user_id = ?", (user_amount, user_id))
        elif status == "approved":
            conn.execute("UPDATE users SET balance_pending = balance_pending - ?, balance_available = balance_available + ? WHERE user_id = ?", (user_amount, user_amount, user_id))

        conn.commit()

        apply_referral_bonus(user_id, user_amount)

        return {"ok": True}
    except Exception as e:
        logger.error(f"Postback error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()
