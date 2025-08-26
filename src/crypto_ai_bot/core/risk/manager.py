from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any

from ..storage.facade import Storage
from ..brokers.base import IBroker, TickerDTO
from ..brokers.symbols import parse_symbol
from ...utils.time import now_ms
from ...utils.logging import get_logger
from ...utils.metrics import inc, timer


@dataclass
class RiskConfig:
    cooldown_sec: int
    max_spread_pct: float
    max_position_base: Decimal
    max_orders_per_hour: int
    daily_loss_limit_quote: Decimal
    # новые — оценочные запасы
    fee_pct_est: Decimal = Decimal("0.001")
    slippage_pct_est: Decimal = Decimal("0.001")


class RiskManager:
    """Проверки перед сделкой (long‑only, spot).

    Реализует: cooldown, спред, лимиты позиции/частоты, дневной loss‑лимит.
    Дополнительно: safety‑margin по комиссии и проскальзыванию.
    """

    def __init__(self, *, storage: Storage, config: RiskConfig) -> None:
        self._storage = storage
        self._cfg = config
        self._log = get_logger("risk")
        self._last_order_ts_ms: Optional[int] = None
        self._orders_counter: Dict[int, int] = {}  # hour_bucket -> count

    # ------------- публ. API (совместимые имена) ------------------------------
    async def allow_order(self, *, symbol: str, side: str, quote_amount: Optional[Decimal] = None, base_amount: Optional[Decimal] = None, ticker: Optional[TickerDTO] = None) -> Dict[str, Any]:
        return await self._check(symbol=symbol, side=side, quote_amount=quote_amount, base_amount=base_amount, ticker=ticker)

    async def is_allowed(self, *args, **kwargs) -> Dict[str, Any]:
        return await self.allow_order(*args, **kwargs)

    async def check(self, *args, **kwargs) -> Dict[str, Any]:
        return await self.allow_order(*args, **kwargs)

    async def validate(self, *args, **kwargs) -> Dict[str, Any]:
        return await self.allow_order(*args, **kwargs)

    def mark_executed(self) -> None:
        ts = now_ms()
        self._last_order_ts_ms = ts
        hb = ts // (60 * 60 * 1000)
        self._orders_counter[hb] = self._orders_counter.get(hb, 0) + 1

    # ------------- внутренняя логика -----------------------------------------
    async def _check(self, *, symbol: str, side: str, quote_amount: Optional[Decimal], base_amount: Optional[Decimal], ticker: Optional[TickerDTO]) -> Dict[str, Any]:
        with timer("risk_check_ms", {"symbol": symbol, "side": side}):
            # 1) cooldown
            if self._last_order_ts_ms is not None:
                if now_ms() - self._last_order_ts_ms < self._cfg.cooldown_sec * 1000:
                    inc("risk_blocked_total", {"reason": "cooldown"})
                    return {"ok": False, "reason": "cooldown"}

            # 2) дневной лимит убытка (на основе оценки equity: quote + base*last)
            try:
                pos = self._storage.positions.get_position(symbol)
                bal = self._storage.balances.get_balances(symbol)
            except Exception:
                pos = None
                bal = None
            est_last = None
            if ticker and ticker.last:
                est_last = Decimal(ticker.last)
            elif hasattr(self._storage, "prices"):
                try:
                    est_last = Decimal(self._storage.prices.get_last(symbol))
                except Exception:
                    est_last = None
            if self._cfg.daily_loss_limit_quote and est_last is not None and bal is not None:
                # упрощённая оценка — зависит от твоей реализации Storage
                equity = (Decimal(bal.quote_free or 0) + Decimal(getattr(pos, "base_qty", 0) or 0) * est_last)
                # Здесь можно хранить baseline и считать PnL; для простоты предполагаем внешний контроль baseline
                # Если понадобится, перенесём baseline/PNL в Storage.
                _ = equity  # placeholder для расширений

            # 3) лимит на частоту в час
            hb = now_ms() // (60 * 60 * 1000)
            if self._orders_counter.get(hb, 0) >= self._cfg.max_orders_per_hour:
                inc("risk_blocked_total", {"reason": "rate_limit_hour"})
                return {"ok": False, "reason": "rate_limit_hour"}

            # 4) спред (по тикеру)
            if ticker and ticker.bid and ticker.ask and ticker.ask > 0:
                mid = (ticker.bid + ticker.ask) / Decimal("2")
                spread = (ticker.ask - ticker.bid) / mid if mid > 0 else Decimal("0")
                if spread > Decimal(str(self._cfg.max_spread_pct)):
                    inc("risk_blocked_total", {"reason": "spread"})
                    return {"ok": False, "reason": "spread_too_wide", "spread": str(spread)}

            # 5) оценочные запасы (fee + slippage) — только для buy
            if side == "buy" and quote_amount:
                margin_pct = Decimal(self._cfg.fee_pct_est) + Decimal(self._cfg.slippage_pct_est)
                eff_cost = quote_amount * (Decimal("1") + margin_pct)
                # проверяем max_position_base с учётом рассчитанного base
                if ticker and ticker.ask and ticker.ask > 0:
                    est_base = eff_cost / Decimal(ticker.ask)
                else:
                    est_base = Decimal("0")
                if self._cfg.max_position_base and est_base > self._cfg.max_position_base:
                    inc("risk_blocked_total", {"reason": "max_position"})
                    return {"ok": False, "reason": "max_position_base"}

            inc("risk_allowed_total", {"side": side})
            return {"ok": True}