# webapp/auth.py
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException
from services.db import get_db
from config import ADMIN_IDS

# Таблица для временных токенов входа
def init_admin_tokens_table():
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()

def generate_admin_token(user_id: int) -> str:
    """Создаёт токен для входа админа (действует 1 час)."""
    init_admin_tokens_table()
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    conn = get_db()
    try:
        conn.execute("INSERT INTO admin_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
                     (token, user_id, expires.isoformat()))
        conn.commit()
    finally:
        conn.close()
    return token

def verify_admin_token(token: str) -> int | None:
    """Проверяет токен и возвращает user_id админа или None."""
    if not token:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id, expires_at FROM admin_tokens WHERE token = ?",
            (token,)
        ).fetchone()
        if not row:
            return None
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires:
            return None
        return row["user_id"]
    finally:
        conn.close()

# Сессии (куки) для уже вошедших админов
def init_admin_sessions_table():
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()

def create_admin_session(user_id: int) -> str:
    """Создаёт сессию (куку) для админа на 24 часа."""
    init_admin_sessions_table()
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    conn = get_db()
    try:
        conn.execute("INSERT INTO admin_sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                     (token, user_id, expires.isoformat()))
        conn.commit()
    finally:
        conn.close()
    return token

def verify_admin_session(token: str) -> int | None:
    """Проверяет сессию и возвращает user_id админа."""
    if not token:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT user_id, expires_at FROM admin_sessions WHERE token = ?",
            (token,)
        ).fetchone()
        if not row:
            return None
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires:
            return None
        # Дополнительно проверяем, что user_id всё ещё админ
        if row["user_id"] not in ADMIN_IDS:
            return None
        return row["user_id"]
    finally:
        conn.close()

def delete_admin_session(token: str):
    conn = get_db()
    try:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()

async def admin_required(request: Request):
    """Зависимость для защищённых страниц: проверяет куку."""
    token = request.cookies.get("admin_session")
    user_id = verify_admin_session(token)
    if not user_id:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    return user_id

# Генерация токенов для обычных пользователей (статистика)
def generate_user_token(user_id: int) -> str:
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
