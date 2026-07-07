# webapp/auth.py
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from config import ADMIN_PASSWORD
from services.db import get_db

security = HTTPBasic()

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != "admin" or credentials.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return credentials.username

def generate_user_token(user_id: int) -> str:
    """Создаёт временный токен для пользователя."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET stats_token=?, stats_token_expires=? WHERE user_id=?",
            (token, expires.isoformat(), user_id)
        )
        conn.commit()
    finally:
        conn.close()
    return token

def get_user_id_from_token(token: str) -> int:
    """Возвращает user_id по токену или ошибку."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id, stats_token_expires FROM users WHERE stats_token=?",
            (token,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Token not found")
        expires = datetime.fromisoformat(row["stats_token_expires"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires:
            raise HTTPException(status_code=401, detail="Token expired")
        return row["user_id"]
    finally:
        conn.close()
