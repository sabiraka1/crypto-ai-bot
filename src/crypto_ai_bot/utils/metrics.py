# src/crypto_ai_bot/utils/metrics.py
from __future__ import annotations
from typing import Dict, Mapping, Any

# здесь предполагается ваш внутренний регистратор/экспортер метрик
# Ниже — тонкие обёртки, чтобы всегда приводить labels к dict[str,str].

def _labels(lbl: Mapping[str, Any] | None) -> Dict[str, str]:
    if not lbl:
        return {}
    return {str(k): str(v) for k, v in lbl.items()}

def inc(name: str, labels: Mapping[str, Any] | None = None, value: int = 1) -> None:
    from crypto_ai_bot.utils.metrics_backend import inc as _inc  # ваш реальный бекенд
    _inc(name, _labels(labels), value)

def gauge(name: str, value: float, labels: Mapping[str, Any] | None = None) -> None:
    from crypto_ai_bot.utils.metrics_backend import gauge as _gauge
    _gauge(name, float(value), _labels(labels))

def observe_histogram(name: str, value: float, labels: Mapping[str, Any] | None = None) -> None:
    from crypto_ai_bot.utils.metrics_backend import observe_histogram as _obs
    _obs(name, float(value), _labels(labels))
