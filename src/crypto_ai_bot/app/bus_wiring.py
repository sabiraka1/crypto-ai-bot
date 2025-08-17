# src/crypto_ai_bot/app/bus_wiring.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, DefaultDict
from collections import defaultdict

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.percentiles import RollingQuantiles


# Квантили по событиям (глобально для процесса)
# decision[(symbol, tf)] -> RQ
# order[(symbol, tf, side)] -> RQ
# flow[(symbol, tf)] -> RQ
_decision_q: DefaultDict[Tuple[str, str], RollingQuantiles] = defaultdict(lambda: RollingQuantiles(512))
_order_q: DefaultDict[Tuple[str, str, str], RollingQuantiles] = defaultdict(lambda: RollingQuantiles(512))
_flow_q: DefaultDict[Tuple[str, str], RollingQuantiles] = defaultdict(lambda: RollingQuantiles(512))


def _get(d: dict, key: str, default=None):
    try:
        return d.get(key, default)
    except Exception:
        return default


def _gauge_quantiles(prefix: str, labels: Dict[str, str], rq: RollingQuantiles) -> None:
    p95 = rq.p95()
    p99 = rq.p99()
    if p95 is not None:
        try:
            metrics.gauge(f"{prefix}_p95_ms", float(p95), labels)
        except Exception:
            pass
    if p99 is not None:
        try:
            metrics.gauge(f"{prefix}_p99_ms", float(p99), labels)
        except Exception:
            pass


def build_bus(cfg, repos) -> Any:
    from crypto_ai_bot.core.events.bus import Bus  # реализация уже есть

    bus = Bus(dlq_max=int(getattr(cfg, "BUS_DLQ_MAX", 1000)))

    # -------- DecisionEvaluated --------
    def _on_decision(ev: Dict[str, Any]) -> None:
        if not isinstance(ev, dict) or ev.get("type") != "DecisionEvaluated":
            return
        symbol = str(_get(ev, "symbol", ""))
        timeframe = str(_get(ev, "timeframe", ""))
        score = _get(ev, "score")
        action = _get(ev, "action")
        size = _get(ev, "size")
        latency_ms = _get(ev, "latency_ms")

        metrics.inc("decision_evaluated_total", {"symbol": symbol, "tf": timeframe, "action": str(action)})
        if latency_ms is not None:
            try:
                metrics.gauge("decision_latency_ms", float(latency_ms), {"symbol": symbol, "tf": timeframe})
            except Exception:
                pass
            # квантили по (symbol, tf)
            rq = _decision_q[(symbol, timeframe)]
            rq.add(float(latency_ms))
            _gauge_quantiles("decision_latency", {"symbol": symbol, "tf": timeframe}, rq)

        dec_repo = getattr(repos, "decisions", None)
        if dec_repo:
            try:
                dec_repo.insert(
                    symbol=symbol,
                    timeframe=timeframe,
                    decision={
                        "score": score,
                        "action": action,
                        "size": size,
                        "latency_ms": latency_ms,
                    },
                    explain=_get(ev, "explain") or {},
                )
            except Exception:
                # пусть Bus положит в DLQ для диагностики
                raise

    bus.subscribe("DecisionEvaluated", _on_decision)

    # -------- OrderExecuted --------
    def _on_order_executed(ev: Dict[str, Any]) -> None:
        if not isinstance(ev, dict) or ev.get("type") != "OrderExecuted":
            return
        symbol = str(_get(ev, "symbol", ""))
        timeframe = str(_get(ev, "timeframe", ""))
        side = str(_get(ev, "side", "")).lower()  # buy/sell
        qty = _get(ev, "qty")
        price = _get(ev, "price")
        order_id = _get(ev, "order_id")
        latency_ms = _get(ev, "latency_ms")

        metrics.inc("orders_executed_total", {"symbol": symbol, "tf": timeframe, "side": side})
        if latency_ms is not None:
            try:
                metrics.gauge("order_latency_ms", float(latency_ms), {"symbol": symbol, "tf": timeframe, "side": side})
            except Exception:
                pass
            rq = _order_q[(symbol, timeframe, side)]
            rq.add(float(latency_ms))
            _gauge_quantiles("order_latency", {"symbol": symbol, "tf": timeframe, "side": side}, rq)

        # аудиты — как было
        audit = getattr(repos, "audit", None)
        if audit:
            try:
                audit.insert(
                    kind="order_executed",
                    payload={
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "side": side,
                        "qty": qty,
                        "price": price,
                        "order_id": order_id,
                        "latency_ms": latency_ms,
                    },
                )
            except Exception:
                raise

    bus.subscribe("OrderExecuted", _on_order_executed)

    # -------- OrderFailed --------
    def _on_order_failed(ev: Dict[str, Any]) -> None:
        if not isinstance(ev, dict) or ev.get("type") != "OrderFailed":
            return
        symbol = str(_get(ev, "symbol", ""))
        timeframe = str(_get(ev, "timeframe", ""))
        side = str(_get(ev, "side", "")).lower()
        error = str(_get(ev, "error", "unknown"))

        metrics.inc("orders_failed_total", {"symbol": symbol, "tf": timeframe, "side": side})

        audit = getattr(repos, "audit", None)
        if audit:
            try:
                audit.insert(
                    kind="order_failed",
                    payload={"symbol": symbol, "timeframe": timeframe, "side": side, "error": error},
                )
            except Exception:
                raise

    bus.subscribe("OrderFailed", _on_order_failed)

    # -------- FlowFinished --------
    def _on_flow_finished(ev: Dict[str, Any]) -> None:
        if not isinstance(ev, dict) or ev.get("type") != "FlowFinished":
            return
        symbol = str(_get(ev, "symbol", ""))
        timeframe = str(_get(ev, "timeframe", ""))
        flow_latency_ms = _get(ev, "flow_latency_ms")

        metrics.inc("flow_finished_total", {"symbol": symbol, "tf": timeframe})
        if flow_latency_ms is not None:
            try:
                metrics.gauge("flow_latency_ms", float(flow_latency_ms), {"symbol": symbol, "tf": timeframe})
            except Exception:
                pass
            rq = _flow_q[(symbol, timeframe)]
            rq.add(float(flow_latency_ms))
            _gauge_quantiles("flow_latency", {"symbol": symbol, "tf": timeframe}, rq)

    bus.subscribe("FlowFinished", _on_flow_finished)

    return bus


def snapshot_quantiles() -> Dict[str, Dict[str, float]]:
    """
    Отдаёт текущие p95/p99 с «плоскими» ключами — удобно для алертов.
    Ключи:
      decision:<symbol>:<tf>
      order:<symbol>:<tf>:<side>
      flow:<symbol>:<tf>
    """
    out: Dict[str, Dict[str, float]] = {}

    for (symbol, tf), rq in _decision_q.items():
        p95, p99 = rq.p95(), rq.p99()
        if p95 is not None or p99 is not None:
            out[f"decision:{symbol}:{tf}"] = {}
            if p95 is not None:
                out[f"decision:{symbol}:{tf}"]["p95"] = float(p95)
            if p99 is not None:
                out[f"decision:{symbol}:{tf}"]["p99"] = float(p99)

    for (symbol, tf, side), rq in _order_q.items():
        p95, p99 = rq.p95(), rq.p99()
        if p95 is not None or p99 is not None:
            out[f"order:{symbol}:{tf}:{side}"] = {}
            if p95 is not None:
                out[f"order:{symbol}:{tf}:{side}"]["p95"] = float(p95)
            if p99 is not None:
                out[f"order:{symbol}:{tf}:{side}"]["p99"] = float(p99)

    for (symbol, tf), rq in _flow_q.items():
        p95, p99 = rq.p95(), rq.p99()
        if p95 is not None or p99 is not None:
            out[f"flow:{symbol}:{tf}"] = {}
            if p95 is not None:
                out[f"flow:{symbol}:{tf}"]["p95"] = float(p95)
            if p99 is not None:
                out[f"flow:{symbol}:{tf}"]["p99"] = float(p99)

    return out
