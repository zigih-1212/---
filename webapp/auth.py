# webapp/auth.py
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException
from config import ADMIN_PASSWORD
from services.db import get_db

def init_admin_sessions_table():
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()

def create_admin_session() -> str:
    init_admin_sessions_table()
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    conn = get_db()
    try:
        conn.execute("INSERT INTO admin_sessions (token, expires_at) VALUES (?, ?)",
                     (token, expires.isoformat()))
        conn.commit()
    finally:
        conn.close()
    return token

def verify_admin_session(token: str) -> bool:
    if not token:
        return False
    conn = get_db()
    try:
        row = conn.execute("SELECT expires_at FROM admin_sessions WHERE token = ?", (token,)).fetchone()
        if not row:
            return False
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < expires
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
    token = request.cookies.get("admin_session")
    if not token or not verify_admin_session(token):
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    return True

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
