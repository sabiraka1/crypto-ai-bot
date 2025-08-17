# src/crypto_ai_bot/core/events/factory.py
from __future__ import annotations
from typing import Dict

from .async_bus import AsyncBus

# Рекомендованные дефолты backpressure для типов событий
# (можно переопределить через Settings.EVENT_BACKPRESSURE_MAP)
_DEFAULTS: Dict[str, Dict[str, str | int]] = {
    "DecisionEvaluated": {"strategy": "keep_latest", "maxsize": 100},  # высокочастотные, держим только свежие
    "FlowFinished":      {"strategy": "drop_oldest", "maxsize": 1000}, # телеметрия
    "OrderExecuted":     {"strategy": "block",       "maxsize": 100},  # важные события — не теряем
    "OrderFailed":       {"strategy": "block",       "maxsize": 100},
}

def build_bus(cfg) -> AsyncBus:
    """
    Фабрика асинхронной шины с конфигурируемым backpressure:
      - дефолты из _DEFAULTS
      - затем пользовательские overrides из Settings.EVENT_BACKPRESSURE_MAP
    """
    bus = AsyncBus()

    # собрать карту настроек
    overrides: Dict[str, Dict[str, str | int]] = {}
    overrides.update(_DEFAULTS)
    try:
        user_map = getattr(cfg, "EVENT_BACKPRESSURE_MAP", None) or {}
        # ожидаем формат: {event_type: {"strategy": "...", "maxsize": N}}
        for et, conf in dict(user_map).items():
            if isinstance(conf, dict):
                overrides[et] = {**overrides.get(et, {}), **conf}
    except Exception:
        pass

    # применить конфигурацию
    for et, conf in overrides.items():
        bus.configure_backpressure(et,
            strategy=str(conf.get("strategy", "block")),
            maxsize=int(conf.get("maxsize", 1000))
        )

    return bus
