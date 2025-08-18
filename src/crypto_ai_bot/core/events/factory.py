# src/crypto_ai_bot/events/factory.py
from __future__ import annotations

from typing import Dict, Any, Optional

DEFAULT_BACKPRESSURE_MAP: Dict[str, Dict[str, Any]] = {
    # Решение обновляется часто → держим последнее
    "DecisionEvaluated": {"strategy": "keep_latest", "queue_size": 1024, "workers": 1},
    # Успешные/неуспешные ордера важны, но могут «сыпаться» пачками → дропаем старое
    "OrderExecuted": {"strategy": "drop_oldest", "queue_size": 2048, "workers": 1},
    "OrderFailed":   {"strategy": "drop_oldest", "queue_size": 2048, "workers": 1},
    # Завершение потока — достаточно последнее
    "FlowFinished":  {"strategy": "keep_latest", "queue_size": 1024, "workers": 1},
    # Блокировки риска полезно не терять (анализ причин) — но ограничим размер
    "RiskBlocked":   {"strategy": "drop_oldest", "queue_size": 1024, "workers": 1},
    # Ошибки брокера для наблюдаемости
    "BrokerError":   {"strategy": "drop_oldest", "queue_size": 1024, "workers": 1},
}

def build_strategy_map(cfg: Any) -> Dict[str, Dict[str, Any]]:
    """
    Можно расширить ENV-переопределениями позже, сейчас возвращаем дефолт.
    Совместимо с app.bus_wiring (если оно использует готовую map).
    """
    return dict(DEFAULT_BACKPRESSURE_MAP)

def build_async_bus(cfg: Any, repos: Optional[Any] = None):
    """
    Опциональная фабрика шины (если хочешь использовать напрямую).
    В проекте уже есть app.bus_wiring.build_bus — это просто удобный аналог.
    """
    try:
        from crypto_ai_bot.core.events.async_bus import AsyncEventBus
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"async bus unavailable: {type(e).__name__}: {e}")
    smap = build_strategy_map(cfg)
    dlq_max = int(getattr(cfg, "BUS_DLQ_MAX", 1000))
    return AsyncEventBus(strategy_map=smap, dlq_max=dlq_max)
