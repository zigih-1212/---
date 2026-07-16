# utils/feature_flags.py
import logging
from services.db import get_db

logger = logging.getLogger("autopost_bot.features")

# Кэш для настроек (чтобы не ходить в БД каждый раз)
_settings_cache = None
_cache_time = None


def get_beta_mode() -> bool:
    """
    Возвращает, включён ли режим бета-тестирования глобально.
    """
    global _settings_cache, _cache_time
    from datetime import datetime, timedelta
    
    # Кэш на 10 секунд, чтобы не нагружать БД
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
    """
    Проверяет, является ли пользователь бета-тестером.
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT beta_tester FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return bool(row and row["beta_tester"] == 1)
    except Exception as e:
        logger.error(f"Ошибка проверки beta_tester для {user_id}: {e}")
        return False
    finally:
        conn.close()


def is_feature_enabled(user_id: int, feature_name: str) -> bool:
    """
    Проверяет, доступна ли функция пользователю.
    Если бета-режим выключен — функция доступна всем.
    Если бета-режим включён — функция доступна только бета-тестерам.
    """
    try:
        if not get_beta_mode():
            return True  # бета-режим выключен → всем доступно
        return is_beta_tester(user_id)  # бета-режим включён → только тестерам
    except Exception as e:
        logger.error(f"Ошибка в is_feature_enabled: {e}")
        return False  # при ошибке — функция недоступна


def set_beta_mode(enabled: bool) -> bool:
    """
    Включает или выключает глобальный режим бета-тестирования.
    """
    conn = get_db()
    try:
        value = "on" if enabled else "off"
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('beta_mode', ?)",
            (value,)
        )
        conn.commit()
        # Сбрасываем кэш
        global _settings_cache
        _settings_cache = None
        logger.info(f"✅ Режим бета-тестирования: {'ВКЛЮЧЁН' if enabled else 'ВЫКЛЮЧЁН'}")
        return True
    except Exception as e:
        logger.error(f"Ошибка установки beta_mode: {e}")
        return False
    finally:
        conn.close()


def add_beta_tester(user_id: int) -> bool:
    """
    Добавляет пользователя в список бета-тестеров.
    """
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
    """
    Удаляет пользователя из списка бета-тестеров.
    """
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
    """
    Возвращает список всех бета-тестеров.
    """
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
