from __future__ import annotations
from typing import Any


def validate_settings(settings: Any) -> list[str]:
    """Проверка конфигурации. Возвращает список текстов ошибок (пусто — всё ок)."""
    errors: list[str] = []

    mode = str(getattr(settings, "MODE", "paper")).lower()
    if mode not in {"paper", "live"}:
        errors.append("MODE должен быть 'paper' или 'live'")

    # Для LIVE обязательны ключи API
    if mode == "live":
        if not getattr(settings, "API_KEY", None):
            errors.append("Для MODE=live требуется API_KEY")
        if not getattr(settings, "API_SECRET", None):
            errors.append("Для MODE=live требуется API_SECRET")

    # Временные параметры и торговые лимиты
    ttl = int(getattr(settings, "IDEMPOTENCY_TTL_SEC", 60) or 60)
    if ttl <= 0:
        errors.append("IDEMPOTENCY_TTL_SEC должен быть > 0")

    fixed_amount = float(getattr(settings, "FIXED_AMOUNT", 10.0) or 10.0)
    if fixed_amount <= 0:
        errors.append("FIXED_AMOUNT должен быть > 0")

    return errors