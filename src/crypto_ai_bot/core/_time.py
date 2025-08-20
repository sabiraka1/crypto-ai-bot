# src/crypto_ai_bot/core/_time.py
"""
Shim-модуль времени: сохраняет совместимость старых импортов core._time,
проксируя функции из utils.time.
"""

from crypto_ai_bot.utils.time import now_ms, monotonic_ms, utc_now

__all__ = ["now_ms", "monotonic_ms", "utc_now"]
