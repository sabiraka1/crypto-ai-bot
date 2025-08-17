# src/crypto_ai_bot/app/bus_wiring.py
from __future__ import annotations

from typing import Any, Dict

from crypto_ai_bot.core.events import Bus  # синхронная безопасная реализация


def build_bus(cfg, repos) -> Any:
    """
    Строим Bus и вешаем минимально необходимые подписки.
    Сигнатура совместима с BusProtocol.publish(event_dict).
    """
    bus = Bus(dlq_max=int(getattr(cfg, "BUS_DLQ_MAX", 1000)))

    # --- handlers ---

    def _on_decision(ev: Dict[str, Any]) -> None:
        if not isinstance(ev, dict):
            return
        if ev.get("type") != "DecisionEvaluated":
            return
        # decisions repo может быть опциональным
        dec_repo = getattr(repos, "decisions", None)
        if not dec_repo:
            return
        try:
            dec_repo.insert(
                symbol=str(ev.get("symbol", "")),
                timeframe=str(ev.get("timeframe", "")),
                decision={
                    "score": ev.get("score"),
                    "action": ev.get("action"),
                    "size": ev.get("size"),
                    "latency_ms": ev.get("latency_ms"),
                },
                explain=ev.get("explain") or {},
            )
        except Exception:
            # ошибки хендлера уйдут в DLQ через сам Bus
            raise

    bus.subscribe("DecisionEvaluated", _on_decision)

    # можно расширять: OrderExecuted, FlowFinished и т.п.
    return bus
