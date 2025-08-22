from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple, Dict
import time
import datetime as _dt

from ..storage.facade import Storage
from ..brokers.symbols import parse_symbol
from ...utils.time import now_ms
from ...utils.metrics import inc


@dataclass(frozen=True)
class RiskConfig:
    # базовые правила
    cooldown_sec: int = 0
    max_spread_pct: float = 0.0

    # дополнительные гардрейлы (по умолчанию выключены)
    daily_loss_limit_quote: Optional[Decimal] = None  # лимит дневного УБЫТКА (в quote)
    max_position_base: Optional[Decimal] = None       # потолок позиции (в base) для BUY
    max_orders_per_hour: Optional[int] = None         # лимит числа ордеров в текущем UTC-часе


class RiskManager:
    def __init__(self, storage: Storage, config: Optional[RiskConfig] = None):
        self._storage = storage
        self._cfg = config or RiskConfig()
        # счётчик ордеров по бакету часа: ключ = (YYYYMMDD:HH, symbol)
        self._orders_counter: Dict[Tuple[str, str], int] = {}

    # ---------- helpers (internal) ----------

    @staticmethod
    def _pair_str(symbol: str) -> str:
        """Нормализованный вид пары: поддержка разных версий symbols.py."""
        try:
            ps = parse_symbol(symbol)
            return getattr(ps, "as_pair", None) or getattr(ps, "pair", None) or str(symbol)
        except Exception:
            return str(symbol)

    @staticmethod
    def _ev_get(evaluation, key, default=None):
        """Достаёт поле как из dict, так и из объекта (dataclass/namespace)."""
        if isinstance(evaluation, dict):
            return evaluation.get(key, default)
        return getattr(evaluation, key, default)

    # ---------- public API ----------

    async def check(self, *, symbol: str, action: str, evaluation) -> Tuple[bool, str]:
        """
        Возвращает (allowed, reason). reason == "" при allowed.
        Приоритет причин блокировки:
          1) no_position (для SELL)
          2) cooldown_active
          3) spread_too_wide
          4) position_cap_exceeded
          5) orders_limit_reached
          6) daily_loss_limit_reached
        """
        action = action.lower().strip()
        sym = self._pair_str(symbol)

        # 1) SELL без позиции запрещён
        if action == "sell":
            base_qty = self._storage.positions.get_base_qty(sym)
            if base_qty <= Decimal("0"):
                inc("risk_blocked_total", {"reason": "no_position"})
                return False, "no_position"

        # 2) cooldown
        if self._cfg.cooldown_sec and self._cfg.cooldown_sec > 0:
            last = self._ev_get(evaluation, "last_trade_ts_ms", 0) or 0
            if last:
                delta = (now_ms() - int(last)) / 1000.0
                if delta < self._cfg.cooldown_sec:
                    inc("risk_blocked_total", {"reason": "cooldown_active"})
                    return False, "cooldown_active"

        # 3) спред (совместимость: принимаем и spread_pct, и spread)
        spread_val = self._ev_get(evaluation, "spread_pct", None)
        if spread_val is None:
            spread_val = self._ev_get(evaluation, "spread", 0.0)
        try:
            spread = float(spread_val or 0.0)
        except Exception:
            spread = 0.0

        if self._cfg.max_spread_pct and spread > self._cfg.max_spread_pct:
            inc("risk_blocked_total", {"reason": "spread_too_wide"})
            return False, "spread_too_wide"

        # 4) ограничение позиции (только для BUY)
        if action == "buy" and self._cfg.max_position_base is not None:
            pos = self._storage.positions.get_base_qty(sym)
            if pos >= self._cfg.max_position_base:
                inc("risk_blocked_total", {"reason": "position_cap_exceeded"})
                return False, "position_cap_exceeded"

        # 5) лимит ордеров в текущем часу
        if self._cfg.max_orders_per_hour is not None:
            if self._orders_in_current_hour(sym) >= self._cfg.max_orders_per_hour:
                inc("risk_blocked_total", {"reason": "orders_limit_reached"})
                return False, "orders_limit_reached"

        # 6) дневной лимит УБЫТКА (считаем только когда позиция плоская)
        if self._cfg.daily_loss_limit_quote is not None:
            if self._storage.positions.get_base_qty(sym) == Decimal("0"):
                pnl = self._calc_today_realized_pnl_quote(sym)
                if pnl <= (Decimal("0") - self._cfg.daily_loss_limit_quote):
                    inc("risk_blocked_total", {"reason": "daily_loss_limit_reached"})
                    return False, "daily_loss_limit_reached"

        return True, ""

    def on_order_placed(self, *, symbol: str) -> None:
        """Регистрирует факт размещения ордера (для троттлинга по часу)."""
        key = (self._hour_bucket(), self._pair_str(symbol))
        self._orders_counter[key] = self._orders_counter.get(key, 0) + 1

    # ---------- helpers (counters, time) ----------

    def _orders_in_current_hour(self, symbol: str) -> int:
        return self._orders_counter.get((self._hour_bucket(), self._pair_str(symbol)), 0)

    @staticmethod
    def _hour_bucket() -> str:
        # UTC-часовой бакет: YYYYMMDD:HH
        return time.strftime("%Y%m%d:%H", time.gmtime())

    def _calc_today_realized_pnl_quote(self, symbol: str) -> Decimal:
        """
        Реализованный PnL за текущий UTC-день:
          net cashflow = Σ(cost SELL) − Σ(cost BUY) для закрытых сделок за день.
        Считается только при нулевой позиции (вызов check это проверяет).
        """
        conn = getattr(self._storage, "conn", None)
        if conn is None:
            return Decimal("0")

        # начало дня UTC (timezone-aware, без DeprecationWarning)
        now = _dt.datetime.now(_dt.timezone.utc)
        day_start_dt = _dt.datetime(year=now.year, month=now.month, day=now.day, tzinfo=_dt.timezone.utc)
        day_start = int(day_start_dt.timestamp() * 1000)

        cur = conn.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN side='sell' THEN cost ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN side='buy'  THEN cost ELSE 0 END), 0)
            FROM trades
            WHERE symbol = ? AND status = 'closed' AND ts_ms >= ?
            """,
            (symbol, day_start),
        )
        sell_sum, buy_sum = cur.fetchone()
        try:
            return Decimal(str(sell_sum or 0)) - Decimal(str(buy_sum or 0))
        except Exception:
            return Decimal("0")
