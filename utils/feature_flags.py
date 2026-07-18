# utils/feature_flags.py
"""Система управления фичами: per-feature флаги вместо глобального beta_mode."""
import logging
from services.db import get_db
from datetime import datetime

logger = logging.getLogger("autopost_bot.features")

# Кэш для статусов фич (обновляется каждые 10 секунд)
_features_cache = {}
_cache_time = None


def _invalidate_cache() -> None:
    """Очистить кэш фич."""
    global _features_cache, _cache_time
    _features_cache = {}
    _cache_time = None


def get_feature_status(feature_name: str) -> str:
    """
    Получить статус фичи: 'dev' | 'beta' | 'released'
    dev      → никто не видит
    beta     → видят только beta_tester=1
    released → видят все
    """
    global _features_cache, _cache_time
    from datetime import timedelta

    # Проверяем кэш (10-секундный TTL)
    if _cache_time and datetime.now() < _cache_time + timedelta(seconds=10):
        if feature_name in _features_cache:
            return _features_cache[feature_name]

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT status FROM features WHERE name = ?",
            (feature_name,),
        ).fetchone()
        status = row["status"] if row else "dev"  # по умолчанию "dev"
        _features_cache[feature_name] = status
        if not _cache_time:
            _cache_time = datetime.now()
        return status
    except Exception as e:
        logger.error(f"Ошибка получения статуса фичи {feature_name}: {e}")
        return "dev"  # по умолчанию скрыто
    finally:
        conn.close()


def is_beta_tester(user_id: int) -> bool:
    """Является ли пользователь бета-тестером."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT beta_tester FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return bool(row and row["beta_tester"] == 1)
    except Exception as e:
        logger.error(f"Ошибка проверки beta_tester для {user_id}: {e}")
        return False
    finally:
        conn.close()


def is_feature_enabled(user_id: int, feature_name: str) -> bool:
    """
    Доступна ли конкретная фича пользователю?
    
    Логика:
    - status='released' → доступна всем
    - status='beta'     → доступна только бета-тестерам
    - status='dev'      → никому не доступна (даже тестерам)
    """
    status = get_feature_status(feature_name)
    
    if status == "released":
        return True
    
    if status == "beta":
        return is_beta_tester(user_id)
    
    # status == "dev"
    return False


async def is_feature_available_async(user_id: int, feature_name: str = "preview_post") -> bool:
    """Async-обёртка для FastAPI/aiogram handlers."""
    return is_feature_enabled(user_id, feature_name)


def can_use_beta_commands(user_id: int, *, is_admin: bool = False) -> bool:
    """Может ли пользователь вызывать beta-команды бота (/preview и т.п.)."""
    if is_admin:
        return True
    return is_beta_tester(user_id)


# ============================================================================
# === УПРАВЛЕНИЕ ФИЧАМИ (для админов) ======================================
# ============================================================================

def set_feature_status(feature_name: str, status: str) -> bool:
    """
    Установить статус фичи.
    status: 'dev' | 'beta' | 'released'
    """
    if status not in ("dev", "beta", "released"):
        logger.error(f"Неверный статус: {status}")
        return False

    conn = get_db()
    try:
        # Проверяем, есть ли уже такая фича
        existing = conn.execute(
            "SELECT name FROM features WHERE name = ?",
            (feature_name,),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE features SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                (status, feature_name),
            )
        else:
            conn.execute(
                "INSERT INTO features (name, status) VALUES (?, ?)",
                (feature_name, status),
            )

        conn.commit()
        _invalidate_cache()
        logger.info(f"✅ Фича '{feature_name}' → статус '{status}'")
        return True
    except Exception as e:
        logger.error(f"Ошибка установки статуса фичи: {e}")
        return False
    finally:
        conn.close()


def get_all_features() -> list:
    """Получить все фичи со статусами."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT name, status, created_at, updated_at FROM features ORDER BY name"
        ).fetchall()
        return [
            {
                "name": r["name"],
                "status": r["status"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Ошибка получения списка фич: {e}")
        return []
    finally:
        conn.close()


def add_beta_tester(user_id: int) -> bool:
    """Добавить пользователя в бета-тестеры."""
    conn = get_db()
    try:
        conn.execute("UPDATE users SET beta_tester = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        logger.info(f"✅ Пользователь {user_id} добавлен в бета-тестеры")
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления бета-тестера {user_id}: {e}")
        return False
    finally:
        conn.close()


def remove_beta_tester(user_id: int) -> bool:
    """Удалить пользователя из бета-тестеров."""
    conn = get_db()
    try:
        conn.execute("UPDATE users SET beta_tester = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        logger.info(f"✅ Пользователь {user_id} удалён из бета-тестеров")
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления бета-тестера {user_id}: {e}")
        return False
    finally:
        conn.close()


def get_beta_testers() -> list:
    """Получить список всех бета-тестеров."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT user_id, username FROM users WHERE beta_tester = 1 ORDER BY user_id"
        ).fetchall()
        return [{"user_id": r["user_id"], "username": r["username"]} for r in rows]
    except Exception as e:
        logger.error(f"Ошибка получения списка бета-тестеров: {e}")
        return []
    finally:
        conn.close()
