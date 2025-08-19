# src/crypto_ai_bot/core/signals/_fusion.py
"""
Модуль слияния сигналов и принятия торговых решений.
Обрабатывает входящие сигналы, применяет веса и пороги для генерации решений.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, TypedDict, NotRequired

# Метрики и необязательная синхронизация времени — как в старом _build.py
from crypto_ai_bot.utils import metrics  # noqa: F401
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift_ms  # optional
except Exception:  # noqa: BLE001
    measure_time_drift_ms = None  # type: ignore

# ---- Параметры из прежнего policy.py ----
BUY_TH = 0.6    # Порог для покупки
SELL_TH = -0.6  # Порог для продажи


class Explain(TypedDict, total=False):
    """Структура для объяснения принятого решения."""
    source: NotRequired[str]
    reason: NotRequired[str]
    signals: Dict[str, float]
    blocks: list
    weights: Dict[str, float]
    thresholds: Dict[str, float]
    context: Dict[str, Any]


@dataclass
class Decision:
    """Торговое решение с обоснованием."""
    action: str   # 'buy' | 'sell' | 'hold'
    score: float = 0.0
    reason: Optional[str] = None


def _weighted_sum(signals: Dict[str, float], weights: Optional[Dict[str, float]]) -> Tuple[float, Dict[str, float]]:
    """
    Базовая агрегация сигналов: взвешенная сумма нормированных значений [-1..+1].
    
    Args:
        signals: Словарь сигналов {название: значение}
        weights: Веса для сигналов (опционально)
        
    Returns:
        Кортеж (итоговый_счет, вклады_сигналов)
    """
    score = 0.0
    contrib: Dict[str, float] = {}
    w = weights or {}
    for k, v in (signals or {}).items():
        w_k = float(w.get(k, 1.0))
        c = float(v) * w_k
        contrib[k] = c
        score += c
    return score, contrib


def decide(signals: Dict[str, float], ctx: Dict[str, Any]) -> Decision:
    """
    Принятие торгового решения на основе сигналов.
    
    Совместимо с прежним policy.decide(...):
    - signals: {feature_name: normalized_float in [-1..1]}
    - ctx: может содержать weights, BUY_THRESHOLD, SELL_THRESHOLD
    
    Args:
        signals: Нормализованные сигналы [-1..1]
        ctx: Контекст с весами и порогами
        
    Returns:
        Решение с действием и обоснованием
    """
    if not signals:
        return Decision("hold", 0.0, "no_signals")

    weights = ctx.get("weights") or {}
    score, _ = _weighted_sum(signals, weights)

    # Получаем пороги из контекста или используем дефолтные
    buy_th = float(ctx.get("BUY_THRESHOLD", BUY_TH))
    sell_th = float(ctx.get("SELL_THRESHOLD", SELL_TH))

    # Принимаем решение на основе порогов
    if score >= buy_th:
        return Decision("buy", score, "score>=buy_th")
    if score <= sell_th:
        return Decision("sell", score, "score<=sell_th")
    return Decision("hold", score, "in_band")


def build(features: Dict[str, float], context: Dict[str, Any], cfg: Any) -> Dict[str, Any]:
    """
    Построение расширенного контекста для принятия решений.
    
    Замена прежнего _build.build(...):
    - добавляет time_drift_ms в context (если доступна util time_sync),
    - инкрементит метрику ошибок при неудаче, не создавая жёсткой зависимости.
    
    Args:
        features: Словарь признаков/сигналов
        context: Базовый контекст
        cfg: Конфигурация с таймаутами
        
    Returns:
        Расширенный контекст с дополнительными данными
    """
    ctx = dict(context or {})
    drift_val = None
    
    # Пытаемся измерить дрифт времени (опционально)
    if measure_time_drift_ms:
        try:
            timeout = float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0))
            drift_val = float(measure_time_drift_ms(timeout=timeout))  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            # Инкрементим метрику ошибок без жесткой зависимости
            try:
                metrics.inc("context_time_drift_errors_total")
            except Exception:
                pass
            drift_val = None
            
    ctx["time_drift_ms"] = drift_val
    return {"features": features or {}, "context": ctx}


def fuse_and_decide(features: Dict[str, float], cfg: Any, context: Optional[Dict[str, Any]] = None) -> Tuple[Decision, Dict[str, Any]]:
    """
    Комбинированный вызов: построение контекста + принятие решения.
    
    Args:
        features: Словарь признаков/сигналов
        cfg: Конфигурация
        context: Дополнительный контекст (опционально)
        
    Returns:
        Кортеж (решение, расширенный_контекст)
    """
    # Сначала строим расширенный контекст
    built = build(features, context or {}, cfg)
    ctx = built["context"]
    
    # Затем принимаем решение на основе признаков и контекста
    dec = decide(built["features"], ctx)
    return dec, ctx


__all__ = [
    "Decision",
    "Explain",
    "decide",
    "build",
    "fuse_and_decide",
]