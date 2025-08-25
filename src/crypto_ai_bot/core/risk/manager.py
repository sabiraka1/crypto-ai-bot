from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Deque, Dict, Optional, Tuple

from ..brokers.base import IBroker
from ..brokers.symbols import parse_symbol
from ..storage.facade import Storage
from ..events.bus import AsyncEventBus  # зарезервировано для сигналов, если понадобится
from ...utils.metrics import inc, timer
from ...utils.logging import get_logger

_log = get_logger("risk.manager")


@dataclass
class RiskConfig:
    cooldown_sec: int = 60
    max_spread_pct: float = 0.002  # 0.2%
    max_position_base: Decimal = Decimal("10")
    max_orders_per_hour: int = 12
    daily_loss_limit_quote: Decimal = Decimal("100")


class RiskManager:
    """Лёгкий Risk‑менеджер для spot long‑only.

    Проверяет перед исполнением:
      * cooldown: минимальная пауза между ордерами
      * max_spread_pct: (ask - bid) / mid
      * max_position_base: ограничение накопленной базовой позиции
      * max_orders_per_hour: скользящее окно в памяти
      * daily_loss_limit_quote: оценка убытка за сутки по портфелю (quote + base*last)
    """

    def __init__(self, *, storage: Storage, config: RiskConfig) -> None:
        self._storage = storage
        self._cfg = config
        # runtime‑состояние (в памяти)
        self._last_trade_ts: Optional[float] = None
        self._order_times: Deque[float] = deque(maxlen=max(1, config.max_orders_per_hour * 2))
        self._pnl_baseline_by_day: Dict[str, Decimal] = {}

    def _now(self) -> float:
        return time.time()

    def _day_key(self) -> str:
        # YYYY‑MM‑DD в UTC (грубая аппроксимация по epoch‑сек)
        return time.strftime("%Y-%m-%d", time.gmtime())

    async def check(self, *, symbol: str, action: str, evaluation: Dict) -> Tuple[bool, Optional[str]]:
        labels = {"symbol": symbol, "action": action}
        with timer("risk_check_ms", labels):
            # 0) HOLD — ничего не блокируем
            if action not in ("buy", "sell"):
                inc("risk_allowed_total", {**labels, "reason": "hold"})
                return True, None

            # 1) Cooldown
            if self._last_trade_ts is not None:
                dt = self._now() - self._last_trade_ts
                if dt < self._cfg.cooldown_sec:
                    inc("risk_blocked_total", {**labels, "reason": "cooldown"})
                    return False, f"cooldown:{int(self._cfg.cooldown_sec - dt)}s"

            # 2) Spread
            broker: IBroker = evaluation.get("context", {}).get("broker") or None  # evaluation может не нести брокера
            try:
                # если нет в контексте, дернём напрямую (быстро и безопасно)
                if broker is None:
                    broker = evaluation.get("broker")  # на всякий случай
                if broker is None:
                    raise RuntimeError("broker_not_in_context")
                t = await broker.fetch_ticker(symbol)
                mid = (t.bid + t.ask) / Decimal("2") if (t.bid and t.ask) else t.last
                sp = (t.ask - t.bid) / mid if mid > 0 else Decimal("1")
                if float(sp) > self._cfg.max_spread_pct:
                    inc("risk_blocked_total", {**labels, "reason": "spread"})
                    return False, "spread"
            except Exception as exc:
                # не блокируем по неполадке тикера, но логируем
                _log.error("spread_check_failed", extra={"error": str(exc)})

            # 3) Max position (по base)
            base_qty = self._storage.positions.get_base_qty(symbol) or Decimal("0")
            if action == "buy" and base_qty >= self._cfg.max_position_base:
                inc("risk_blocked_total", {**labels, "reason": "position_limit"})
                return False, "position_limit"

            # 4) Orders/hour
            now = self._now()
            one_hour_ago = now - 3600.0
            while self._order_times and self._order_times[0] < one_hour_ago:
                self._order_times.popleft()
            if len(self._order_times) >= self._cfg.max_orders_per_hour:
                inc("risk_blocked_total", {**labels, "reason": "rate_limit"})
                return False, "orders_per_hour"

            # 5) Daily loss limit (по стоимости портфеля)
            try:
                # Оценка: quote + base*last
                p = parse_symbol(symbol)
                if broker is None:
                    raise RuntimeError("broker_not_in_context")
                t = await broker.fetch_ticker(symbol)
                bal = await broker.fetch_balance(symbol)
                portfolio = bal.free_quote + bal.free_base * t.last
                day = self._day_key()
                baseline = self._pnl_baseline_by_day.get(day)
                if baseline is None:
                    self._pnl_baseline_by_day.clear()  # новый день — очистим
                    self._pnl_baseline_by_day[day] = portfolio
                else:
                    loss = baseline - portfolio
                    if loss > self._cfg.daily_loss_limit_quote:
                        inc("risk_blocked_total", {**labels, "reason": "daily_loss"})
                        return False, "daily_loss"
            except Exception as exc:
                _log.error("pnl_check_failed", extra={"error": str(exc)})

            inc("risk_allowed_total", {**labels, "reason": "ok"})
            return True, None

    # Вызвать после успешной заявки
    def mark_executed(self) -> None:
        self._last_trade_ts = self._now()
        self._order_times.append(self._last_trade_ts)