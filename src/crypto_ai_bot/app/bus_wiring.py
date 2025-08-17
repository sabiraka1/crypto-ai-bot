# src/crypto_ai_bot/app/bus_wiring.py
from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics


def _get(d: dict, key: str, default=None):
    try:
        return d.get(key, default)
    except Exception:
        return default


def build_bus(cfg, repos) -> Any:
    """
    Сборка шины событий и подписок.
    Ожидается, что реализация Bus уже есть в проекте (core/events/bus.py или аналог)
    и предоставляет интерфейс:
        bus = Bus(dlq_max=int)
        bus.subscribe(event_type: str, handler: Callable[[dict], None])
        bus.publish(event: dict)
        bus.health() -> dict
        bus.dlq_dump(limit: int) -> list[dict]
    """
    # Импортируем локально, чтобы не ломать сборку, если путь отличается
    from crypto_ai_bot.core.events.bus import Bus  # реализация уже есть в проекте

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

        # Метрики
        metrics.inc("decision_evaluated_total", {"symbol": symbol, "tf": timeframe, "action": str(action)})
        if latency_ms is not None:
            try:
                metrics.gauge("decision_latency_ms", float(latency_ms), {"symbol": symbol, "tf": timeframe})
            except Exception:
                pass

        # Сохранение решения (если репозиторий доступен)
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
            except Exception as e:
                # пробрасываем, чтобы Bus положил в DLQ и показал в health
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

        # Трейды обычно уже пишутся в UC.place_order; здесь только метрики/аудит по событию.
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
                # не критично для пайплайна — отправим в DLQ
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

    bus.subscribe("FlowFinished", _on_flow_finished)

    return bus
