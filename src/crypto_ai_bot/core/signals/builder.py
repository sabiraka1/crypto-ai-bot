# src/crypto_ai_bot/core/signals/builder.py
from __future__ import annotations
from typing import Any, Dict, Optional, List
from crypto_ai_bot.core.brokers.symbols import normalize_symbol

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def _last_price(broker: Any, symbol: str) -> float:
    try:
        t = broker.fetch_ticker(symbol)
        return _safe_float(t.get("last") or t.get("close") or 0.0)
    except Exception:
        return 0.0

def _internal_metrics(*, broker: Any = None, positions_repo: Any = None, symbol: str) -> Dict[str, Any]:
    """Собираем внутренние метрики (всегда безопасно, без падений)."""
    out: Dict[str, Any] = {"open_positions": None, "notional_exposure_usd": None, "time_drift_ms": None}
    # позиции
    try:
        if positions_repo and hasattr(positions_repo, "get_open"):
            rows: List[Dict[str, Any]] = positions_repo.get_open()
            out["open_positions"] = len(rows)
            if broker:
                total = 0.0
                for r in rows:
                    s = str(r.get("symbol") or symbol)
                    qty = _safe_float(r.get("qty"), 0.0)
                    px = _last_price(broker, s)
                    total += qty * px
                out["notional_exposure_usd"] = total
    except Exception:
        pass
    # дрейф времени
    try:
        if broker:
            from crypto_ai_bot.utils.time_sync import measure_time_drift_ms
            m = measure_time_drift_ms(broker)
            out["time_drift_ms"] = int(m.get("drift_ms", 0))
    except Exception:
        pass
    return out

def build(
    symbol: str,
    *,
    cfg: Any,
    broker: Any = None,
    positions_repo: Any = None,
    external: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Единая точка сборки фич и контекста.
    - external: сюда можно передать внешние индикаторы (btc_dominance, fear_greed, dxy, и т.п.)
    - broker/positions_repo: чтобы добавить внутренние метрики (open_positions, notional_exposure_usd, time_drift_ms)
    Возвращает: {"context": {...}, "features": {...}}
    """
    sym = normalize_symbol(symbol or getattr(cfg, "SYMBOL", "BTC/USDT"))
    tf = getattr(cfg, "TIMEFRAME", "1h")

    # Контекст: минимум — символ и таймфрейм
    context: Dict[str, Any] = {"symbol": sym, "timeframe": tf}

    # Внешние фичи (как и раньше собирались _build.py)
    features: Dict[str, Any] = {}
    if isinstance(external, dict):
        features.update(external)

    # Внутренние метрики
    internal = _internal_metrics(broker=broker, positions_repo=positions_repo, symbol=sym)
    context["internal"] = internal

    return {"context": context, "features": features}
