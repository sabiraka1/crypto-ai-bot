from __future__ import annotations

from typing import Any, Optional
from decimal import Decimal

from ..brokers.base import IBroker
from ..storage.facade import Storage
from ...utils.logging import get_logger
from ...utils.metrics import inc, timer
from ...utils.time import now_ms


class OrdersReconciler:
    """
    Мягкая сверка открытых ордеров.
    - Ничего не меняет (только лог/метрики)
    - Если брокер не умеет fetch_open_orders — пропускаем
    - Логируем количество открытых ордеров и базовые поля
    """

    def __init__(self, *, storage: Storage, broker: IBroker, symbol: str) -> None:
        self._log = get_logger("reconcile.orders")
        self._storage = storage
        self._broker = broker
        self._symbol = symbol

    async def run_once(self) -> None:
        fetch_open = getattr(self._broker, "fetch_open_orders", None)
        if not callable(fetch_open):
            self._log.info("skip_no_fetch_open_orders")
            return

        with timer("reconcile_orders_ms", {"symbol": self._symbol}):
            try:
                open_orders = await fetch_open(self._symbol)  # type: ignore
            except Exception as exc:
                self._log.error("fetch_open_orders_failed", extra={"error": str(exc)})
                inc("reconcile_orders", {"symbol": self._symbol, "status": "fetch_failed"})
                return

            n = len(open_orders or [])
            inc("reconcile_orders", {"symbol": self._symbol, "status": "ok", "count": str(n)})
            self._log.info("open_orders_count", extra={"symbol": self._symbol, "count": n})

            if not open_orders:
                return

            # Логируем верхнеуровневую сводку (не спамим всеми полями)
            now = now_ms()
            for o in open_orders:
                try:
                    # поддержим dict и объектоподобный ответ
                    oid = (o.get("id") if isinstance(o, dict) else getattr(o, "id", None)) or "?"
                    side = (o.get("side") if isinstance(o, dict) else getattr(o, "side", None)) or "?"
                    amount = (o.get("amount") if isinstance(o, dict) else getattr(o, "amount", None))
                    remaining = (o.get("remaining") if isinstance(o, dict) else getattr(o, "remaining", None))
                    ts = (o.get("timestamp") if isinstance(o, dict) else getattr(o, "timestamp", None))
                    age_ms = (now - int(ts)) if ts else None

                    self._log.warning(
                        "open_order_exists",
                        extra={
                            "id": oid,
                            "side": side,
                            "amount": str(amount) if amount is not None else "?",
                            "remaining": str(remaining) if remaining is not None else "?",
                            "age_ms": int(age_ms) if age_ms is not None else None,
                        },
                    )
                except Exception:
                    self._log.warning("open_order_unknown_format")
