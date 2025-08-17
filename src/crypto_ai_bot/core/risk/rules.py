# src/crypto_ai_bot/core/risk/rules.py
from __future__ import annotations

from typing import Any, Dict, Tuple

# измерение дрейфа времени — безопасный импорт
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift
except Exception:  # заглушка
    def measure_time_drift(urls=None, timeout: float = 1.5) -> float:
        return 0.0


def check_time_sync(features: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """
    Блокирует торговлю при дрейфе времени выше порога (ms).
    Если измерение недоступно — пропускаем (True,"ok").
    """
    limit_ms = int(getattr(cfg, "TIME_DRIFT_LIMIT_MS", 1000))
    urls = getattr(cfg, "TIME_DRIFT_URLS", None) or None

    try:
        drift = float(measure_time_drift(urls=urls, timeout=1.5))
    except Exception:
        # не получилось померить — не блокируем
        return True, "ok"

    if drift > limit_ms:
        return False, f"time_drift_exceeded:{int(drift)}ms>{limit_ms}ms"
    return True, "ok"


# Ниже — примеры сигнатур других правил. Оставляем как есть, если уже реализованы.
# Каждое правило — чистая функция, возвращает (ok:bool, reason:str).

def check_spread(features: Dict[str, Any], cfg) -> Tuple[bool, str]:  # optional
    return True, "ok"

def check_hours(features: Dict[str, Any], cfg) -> Tuple[bool, str]:  # optional
    return True, "ok"

def check_dd(features: Dict[str, Any], cfg) -> Tuple[bool, str]:     # optional
    return True, "ok"

def check_seq_losses(features: Dict[str, Any], cfg) -> Tuple[bool, str]:  # optional
    return True, "ok"

def check_max_exposure(features: Dict[str, Any], cfg) -> Tuple[bool, str]:  # optional
    return True, "ok"
