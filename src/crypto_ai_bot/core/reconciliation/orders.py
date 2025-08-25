from __future__ import annotations

import asyncio
from typing import Any, Optional, Dict, List
from decimal import Decimal

from ..brokers.base import IBroker
from ..events.bus import AsyncEventBus
from ...utils.logging import get_logger
from ...utils.metrics import inc, timer
from ...utils.time import now_ms

# --- лёгкая сводка для /status ---
_last_status: Dict[str, Any] | None = None


def get_last_status() -> Optional[Dict[str, Any]]:
    return _last_status


class OrdersReconciler:
    """
    Мягкая сверка открытых ордеров:
    - Ничего не мутирует (только лог/метрики)
    - Отмечает "застарелые" ордера (age_ms > stale_ms)
    - Опционально шлёт событие в EventBus (если bus передан)
    """

    def __init__(
        self,
        *,
        broker: IBroker,
        symbol: str,
        bus: Optional[AsyncEventBus] = None,
        stale_ms: int = 10 * 60 * 1000,  # 10 минут по умолчанию
    ) -> None:
        self._log = get_logger("reconcile.orders")
        self._broker = broker
        self._symbol = symbol
        self._bus = bus
        self._stale_ms = int(stale_ms)

    async def run_once(self) -> None:
        global _last_status

        fetch_open = getattr(self._broker, "fetch_open_orders", None)
        if not callable(fetch_open):
            self._log.info("skip_no_fetch_open_orders")
            _last_status = {"ok": True, "count": 0, "stale": 0, "reason": "no_api"}
            return

        with timer("reconcile_orders_ms", {"symbol": self._symbol}):
            try:
                open_orders: List[Dict[str, Any]] = await fetch_open(self._symbol)  # type: ignore
            except Exception as exc:
                self._log.error("fetch_open_orders_failed", extra={"error": str(exc)})
                inc("reconcile_orders", {"symbol": self._symbol, "status": "fetch_failed"})
                _last_status = {"ok": False, "error": str(exc)}
                return

            n = len(open_orders or [])
            inc("reconcile_orders", {"symbol": self._symbol, "status": "ok", "count": str(n)})
            self._log.info("open_orders_count", extra={"symbol": self._symbol, "count": n})

            if not open_orders:
                _last_status = {"ok": True, "count": 0, "stale": 0}
                return

            now = now_ms()
            stale_cnt = 0
            for o in open_orders:
                try:
                    oid = (o.get("id") if isinstance(o, dict) else getattr(o, "id", None)) or "?"
                    side = (o.get("side") if isinstance(o, dict) else getattr(o, "side", None)) or "?"
                    amount = (o.get("amount") if isinstance(o, dict) else getattr(o, "amount", None))
                    remaining = (o.get("remaining") if isinstance(o, dict) else getattr(o, "remaining", None))
                    ts = (o.get("timestamp") if isinstance(o, dict) else getattr(o, "timestamp", None))
                    age_ms = (now - int(ts)) if ts else None

                    is_stale = bool(age_ms is not None and age_ms > self._stale_ms)
                    if is_stale:
                        stale_cnt += 1
                        inc("reconcile_orders_stale", {"symbol": self._symbol, "side": side or "?"})
                        self._log.warning(
                            "open_order_stale",
                            extra={
                                "id": oid,
                                "side": side,
                                "amount": str(amount) if amount is not None else "?",
                                "remaining": str(remaining) if remaining is not None else "?",
                                "age_ms": int(age_ms),
                            },
                        )
                        # опционально публикуем событие (soft)
                        if self._bus:
                            key = self._symbol.replace("/", "-").lower()
                            try:
                                await self._bus.publish(
                                    "reconcile.order_stale",
                                    {
                                        "symbol": self._symbol,
                                        "id": oid,
                                        "side": side,
                                        "age_ms": int(age_ms),
                                        "remaining": str(remaining) if remaining is not None else None,
                                    },
                                    key=key,
                                )
                            except Exception as exc:
                                self._log.error("publish_stale_event_failed", extra={"error": str(exc)})
                    else:
                        # просто информативный лог, чтобы видеть активность
                        self._log.info(
                            "open_order_seen",
                            extra={
                                "id": oid,
                                "side": side,
                                "remaining": str(remaining) if remaining is not None else "?",
                                "age_ms": int(age_ms) if age_ms is not None else None,
                            },
                        )
                except Exception:
                    self._log.warning("open_order_unknown_format")

            _last_status = {"ok": True, "count": n, "stale": stale_cnt}
