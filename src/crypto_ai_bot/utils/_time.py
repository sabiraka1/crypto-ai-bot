from __future__ import annotations

"""
Единая точка времени:
- now_ms()          — UNIX time в миллисекундах
- monotonic_ms()    — монотонное время (для измерений)
- check_sync()      — (опц.) проверка дрейфа часов, сейчас заглушка под расширение
"""

import time
from typing import Optional


def now_ms() -> int:
    return int(time.time() * 1000)


def monotonic_ms() -> int:
    return int(time.perf_counter() * 1000)


def check_sync(exchange: object | None = None) -> Optional[int]:
    """
    Возвратите дрейф часов в мс (если есть внешний источник), иначе None.
    Заглушка: не делает внешних запросов, расширяется позже.
    """
    try:
        # место под реализацию: запрос времени у биржи/тайм-сервиса
        return None
    except Exception:
        return None
