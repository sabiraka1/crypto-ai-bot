# src/crypto_ai_bot/core/use_cases/eval_and_execute.py
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils import metrics
from crypto_ai_bot.core.events import BusProtocol

# локальная гистограмма без смены utils.metrics API
_HIST_BUCKETS_MS = (50, 100, 250, 500, 1000, 2000, 5000)

def _observe_hist(name: str, value_ms: int, labels: Optional[Dict[str, str]] = None) -> None:
    lbls = dict(labels or {})
    # Prometheus-подобный паттерн: bucket counters + sum
    placed = False
    for b in _HIST_BUCKETS_MS:
        le = str(b)
        if value_ms <= b:
            metrics.inc(f"{name}_bucket", {**lbls, "le": le})
            placed = True
        else:
            # для совместимости с простыми счётчиками — ничего
            pass
    metrics.inc(f"{name}_bucket", {**lbls, "le": "+Inf"})
    # sum/count
    metrics.observe(f"{name}_sum", value_ms, lbls)
    metrics.inc(f"{name}_count", lbls)

# аккуратные импорты UC
from .evaluate import evaluate as uc_evaluate
from .place_order import place_order as uc_place_order

# риск — мягко, если есть
try:
    from crypto_ai_bot.core.risk.manager import check as risk_check  # type: ignore
except Exception:  # pragma: no cover
    risk_check = None  # type: ignore


def eval_and_execute(
    cfg: Settings,
    broker: Any,
    repos: Any,  # ожидается контейнер с атрибутами: positions, trades, audit, uow, idempotency(опц.)
    *,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    limit: Optional[int] = None,
    bus: Optional[BusProtocol] = None,
) -> Dict[str, Any]:
    """
    Полный конвейер: evaluate → (risk?) → execute (через PositionManager).
    Публикует события (если передан bus) и пишет метрики.
    """
    sym = symbol or cfg.SYMBOL
    tf = timeframe or cfg.TIMEFRAME
    lim = int(limit or getattr(cfg, "LIMIT_BARS", 300))

    t_flow0 = time.perf_counter()

    # 1) EVALUATE
    decision = uc_evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=lim, bus=bus)

    # 2) RISK (мягко)
    risk_ok, risk_reason = True, ""
    if callable(risk_check):
        try:
            # Передаём то, что точно есть в любом режиме
            risk_ok, risk_reason = risk_check({"decision": decision}, cfg)  # type: ignore
        except Exception as e:  # не роняем поток из-за риска
            risk_ok, risk_reason = True, f"risk_check_failed:{type(e).__name__}"
            if bus:
                try:
                    bus.publish({"type": "RiskCheckFailed", "symbol": sym, "reason": str(e)})
                except Exception:
                    pass

    if bus:
        try:
            bus.publish(
                {
                    "type": "RiskChecked",
                    "symbol": sym,
                    "timeframe": tf,
                    "ok": risk_ok,
                    "reason": risk_reason,
                }
            )
        except Exception:
            pass

    # 3) BLOCK on risk
    if not risk_ok:
        metrics.inc("order_blocked_total", {"reason": risk_reason or "risk"})
        if bus:
            try:
                bus.publish(
                    {
                        "type": "OrderBlocked",
                        "symbol": sym,
                        "timeframe": tf,
                        "reason": risk_reason,
                        "decision": decision,
                    }
                )
            except Exception:
                pass
        flow_ms = int((time.perf_counter() - t_flow0) * 1000)
        _observe_hist("flow_latency_ms", flow_ms, {"stage": "blocked"})
        return {"status": "blocked", "symbol": sym, "timeframe": tf, "reason": risk_reason, "decision": decision}

    # 4) EXECUTE (но уважаем флаг ENABLE_TRADING)
    if not getattr(cfg, "ENABLE_TRADING", False):
        metrics.inc("order_skip_total", {"reason": "trading_disabled"})
        if bus:
            try:
                bus.publish({"type": "OrderSkipped", "symbol": sym, "reason": "trading_disabled"})
            except Exception:
                pass
        flow_ms = int((time.perf_counter() - t_flow0) * 1000)
        _observe_hist("flow_latency_ms", flow_ms, {"stage": "simulated"})
        return {"status": "simulated", "symbol": sym, "timeframe": tf, "decision": decision}

    # 5) PLACE
    result = uc_place_order(
        cfg,
        broker,
        positions_repo=repos.positions,
        trades_repo=repos.trades,
        audit_repo=repos.audit,
        uow=repos.uow,
        decision=decision,
        symbol=sym,
        bus=bus,
        idem_repo=getattr(repos, "idempotency", None),
    )

    flow_ms = int((time.perf_counter() - t_flow0) * 1000)
    _observe_hist("flow_latency_ms", flow_ms, {"stage": "executed" if result.get("status") == "executed" else "other"})

    # финальный ивент потока
    if bus:
        try:
            bus.publish(
                {
                    "type": "FlowFinished",
                    "symbol": sym,
                    "timeframe": tf,
                    "status": result.get("status"),
                    "latency_ms": flow_ms,
                }
            )
        except Exception:
            pass

    return {"status": "ok", "symbol": sym, "timeframe": tf, "decision": decision, "result": result}
