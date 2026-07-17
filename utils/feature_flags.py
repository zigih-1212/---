# utils/feature_flags.py
"""Единый модуль для beta-режима и feature flags."""
import logging
from services.db import get_db

logger = logging.getLogger("autopost_bot.features")

_settings_cache = None
_cache_time = None


def _invalidate_cache() -> None:
    global _settings_cache
    _settings_cache = None


def get_beta_mode() -> bool:
    """Включён ли глобальный режим бета-тестирования."""
    global _settings_cache, _cache_time
    from datetime import datetime, timedelta

    if _settings_cache is not None and _cache_time and datetime.now() < _cache_time + timedelta(seconds=10):
        return _settings_cache

    conn = get_db()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = 'beta_mode'").fetchone()
        value = row["value"] == "on" if row else False
        _settings_cache = value
        _cache_time = datetime.now()
        return value
    except Exception as e:
        logger.error(f"Ошибка получения beta_mode: {e}")
        return False
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


def is_feature_enabled(user_id: int, feature_name: str = "preview_post") -> bool:
    """
    Доступна ли функция пользователю.
    beta_mode=off → всем; beta_mode=on → только бета-тестерам.
    feature_name зарезервирован для будущих per-feature флагов.
    """
    del feature_name  # пока все beta-фичи используют один глобальный флаг
    if not get_beta_mode():
        return True
    return is_beta_tester(user_id)


async def is_feature_available_async(user_id: int, feature_name: str = "preview_post") -> bool:
    """Async-обёртка для FastAPI/aiogram handlers."""
    return is_feature_enabled(user_id, feature_name)


def can_use_beta_commands(user_id: int, *, is_admin: bool = False) -> bool:
    """Может ли пользователь вызывать beta-команды бота (/preview и т.п.)."""
    if is_admin:
        return True
    return is_beta_tester(user_id)


def set_beta_mode(enabled: bool) -> bool:
    """Включить или выключить глобальный beta-режим."""
    conn = get_db()
    try:
        value = "on" if enabled else "off"
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('beta_mode', ?)",
            (value,),
        )
        conn.commit()
        _invalidate_cache()
        logger.info(f"✅ Режим бета-тестирования: {'ВКЛЮЧЁН' if enabled else 'ВЫКЛЮЧЕН'}")
        return True
    except Exception as e:
        logger.error(f"Ошибка установки beta_mode: {e}")
        return False
    finally:
        conn.close()


def toggle_beta_mode() -> bool:
    """Переключить beta-режим. Возвращает новое состояние (True = включён)."""
    new_state = not get_beta_mode()
    set_beta_mode(new_state)
    return new_state


def add_beta_tester(user_id: int) -> bool:
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
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT user_id, username FROM users WHERE beta_tester = 1"
        ).fetchall()
        return [{"user_id": r["user_id"], "username": r["username"]} for r in rows]
    except Exception as e:
        logger.error(f"Ошибка получения списка бета-тестеров: {e}")
        return []
    finally:
        conn.close()
