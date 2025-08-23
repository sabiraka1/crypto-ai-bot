from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple, List

from ..brokers.symbols import parse_symbol
from ..storage.facade import Storage
from ...utils.time import now_ms, bucket_ms_floor


@dataclass
class RiskConfig:
    # v1 (уже были)
    cooldown_sec: int = 30                          # пауза после размещения ордера
    max_spread_pct: float = 0.3                     # допустимый спред (0.3 = 0.3%)
    max_position_base: Optional[Decimal] = None     # кап по размеру позиции в BASE
    max_orders_per_hour: Optional[int] = None       # лимит ордеров в час
    daily_loss_limit_quote: Optional[Decimal] = None  # дневной лимит реализованных потерь (в QUOTE, абсолют)

    # v2 (новые — по умолчанию выключены, чтобы не ломать текущее поведение)
    loss_streak_limit: int = 0                      # максимум подряд убыточных закрытий за сегодня (0 = выкл)
    daily_drawdown_limit_quote: Optional[Decimal] = None  # дневная просадка (реализованный убыток) в QUOTE
    max_volatility_pct: Optional[float] = None      # фильтр по волатильности (если в evaluation придёт volatility_pct)


class RiskManager:
    """
    Проверки выполняются в фиксированном приоритете:

    1) no_position            — запрет SELL без позиции
    2) cooldown_active        — пауза после последнего ордера
    3) spread_too_wide        — спред превышает порог
    4) volatility_too_high    — (опц.) волатильность выше порога
    5) position_cap_exceeded  — достигнут лимит позиции (BASE)
    6) orders_limit_reached   — превышен лимит ордеров в текущем часовом окне
    7) daily_loss_limit_reached     — дневной лимит реализованных потерь
    8) daily_drawdown_limit_reached — дневная просадка (реализованный PnL) превышает порог
    9) loss_streak_limit_reached    — серия подряд убыточных закрытий (за сегодня)
    """

    def __init__(self, *, storage: Storage, config: Optional[RiskConfig] = None) -> None:
        self._storage = storage
        self._cfg = config or RiskConfig()
        # учёт ордеров в часовых окнах: ключ (hour_bucket_ms, symbol_pair) → count
        self._orders_bucket: Dict[Tuple[int, str], int] = {}
        # учёт для cooldown: symbol_pair → ts_ms последнего размещённого ордера
        self._last_order_ts: Dict[str, int] = {}

    # --- публичное API, вызывается из use-cases ---

    async def check(self, *, symbol: str, action: str, evaluation: dict) -> Tuple[bool, str]:
        """
        Возвращает (allowed, reason). При allowed reason == "".
        evaluation может содержать поля: spread (в процентах), volatility_pct (если посчитана снаружи).
        """
        action = (action or "").strip().lower()
        sym = parse_symbol(symbol).as_pair
        now = now_ms()

        # 1) SELL без позиции
        if action == "sell":
            base_qty = self._storage.positions.get_base_qty(sym)
            if not base_qty or base_qty <= 0:
                return False, "no_position"

        # 2) cooldown
        if self._cfg.cooldown_sec and self._cfg.cooldown_sec > 0:
            last = self._last_order_ts.get(sym, 0)
            if last and now - last < self._cfg.cooldown_sec * 1000:
                return False, "cooldown_active"

        # 3) spread
        spread = float(evaluation.get("spread") or 0.0)
        if self._cfg.max_spread_pct is not None and spread > float(self._cfg.max_spread_pct):
            return False, "spread_too_wide"

        # 4) (опц.) волатильность
        if self._cfg.max_volatility_pct is not None:
            vol = float(evaluation.get("volatility_pct") or 0.0)
            if vol > float(self._cfg.max_volatility_pct):
                return False, "volatility_too_high"

        # 5) лимит позиции для BUY
        if action == "buy" and self._cfg.max_position_base is not None:
            pos = self._storage.positions.get_base_qty(sym)
            if pos is not None and pos >= self._cfg.max_position_base:
                return False, "position_cap_exceeded"

        # 6) лимит ордеров в текущем часовом бакете
        if self._cfg.max_orders_per_hour and self._cfg.max_orders_per_hour > 0:
            hb = self._hour_bucket()
            used = self._orders_bucket.get((hb, sym), 0)
            if used >= self._cfg.max_orders_per_hour:
                return False, "orders_limit_reached"

        # 7) дневной лимит потерь (реализованных)
        if self._cfg.daily_loss_limit_quote is not None:
            loss = self._today_realized_loss_quote(sym)  # отрицательное или 0
            if abs(loss) >= self._cfg.daily_loss_limit_quote:
                return False, "daily_loss_limit_reached"

        # 8) дневная просадка (реализованный PnL за день)
        if self._cfg.daily_drawdown_limit_quote is not None:
            dd = self._today_drawdown_quote(sym)  # отрицательное или 0
            if abs(dd) >= self._cfg.daily_drawdown_limit_quote:
                return False, "daily_drawdown_limit_reached"

        # 9) серия убыточных закрытий (за сегодня)
        if self._cfg.loss_streak_limit and self._cfg.loss_streak_limit > 0:
            if self._today_loss_streak_reached(sym, self._cfg.loss_streak_limit):
                return False, "loss_streak_limit_reached"

        return True, ""

    def on_order_placed(self, *, symbol: str) -> None:
        """Регистрирует факт размещения ордера: для троттлинга и cooldown."""
        sym = parse_symbol(symbol).as_pair
        hb = self._hour_bucket()
        key = (hb, sym)
        self._orders_bucket[key] = self._orders_bucket.get(key, 0) + 1
        self._last_order_ts[sym] = now_ms()

    # --- helpers ---

    def _hour_bucket(self) -> int:
        # округление вниз к часу (в мс)
        return int(bucket_ms_floor(now_ms(), 60 * 60 * 1000))

    def _today_bounds_ms(self) -> Tuple[int, int]:
        # используем UTC для стабильности
        now = _dt.datetime.utcnow()
        start = _dt.datetime(now.year, now.month, now.day)  # 00:00 UTC
        start_ms = int(start.timestamp() * 1000)
        end_ms = start_ms + 24 * 60 * 60 * 1000
        return start_ms, end_ms

    # --- расчёты по TRADES (реализованный PnL) ---

    def _fetch_today_trades(self, symbol: str) -> List[Tuple[str, Decimal, Decimal]]:
        """
        Возвращает список (side, amount, cost) за сегодняшний день по символу.
        side: 'buy'|'sell'; amount — в BASE; cost — в QUOTE.
        """
        start_ms, end_ms = self._today_bounds_ms()
        cur = self._storage.conn.cursor()
        # Имена таблицы/полей соответствуют 0001_init.sql и тестам (side/amount/price/cost/ts_ms)
        rows = cur.execute(
            "SELECT side, amount, cost FROM trades WHERE symbol=? AND ts_ms>=? AND ts_ms<? ORDER BY ts_ms ASC",
            (symbol, start_ms, end_ms),
        ).fetchall()
        out: List[Tuple[str, Decimal, Decimal]] = []
        for side, amt, cost in rows:
            out.append((str(side), Decimal(str(amt)), Decimal(str(cost))))
        return out

    def _fifo_closed_pnls_today(self, symbol: str) -> List[Decimal]:
        """
        FIFO-парсинг сделок за сегодня → список PnL по каждому SELL (в QUOTE).
        """
        trades = self._fetch_today_trades(symbol)
        # очередь BUY-лотов (amount_base, cost_quote)
        lots: List[Tuple[Decimal, Decimal]] = []
        pnls: List[Decimal] = []

        for side, amt, cost in trades:
            if side == "buy":
                lots.append((amt, cost))
            elif side == "sell":
                remain = amt
                sell_cost_total = cost  # cost уже в QUOTE для всей продажи
                buy_cost_alloc = Decimal("0")
                # распределяем продажу по BUY-лотам
                while remain > 0 and lots:
                    b_amt, b_cost = lots[0]
                    if b_amt <= remain:
                        # полностью закрываем buy-лот
                        buy_cost_alloc += b_cost
                        remain -= b_amt
                        lots.pop(0)
                    else:
                        # частично закрываем buy-лот
                        # оценим квоту пропорционально количеству
                        ratio = (remain / b_amt)
                        buy_cost_alloc += (b_cost * ratio)
                        lots[0] = (b_amt - remain, b_cost * (Decimal("1") - ratio))
                        remain = Decimal("0")
                # PnL по этой продаже (может быть <0)
                pnl = sell_cost_total - buy_cost_alloc
                pnls.append(pnl)
            else:
                # неизвестная сторона — игнор
                pass

        return pnls

    def _today_realized_loss_quote(self, symbol: str) -> Decimal:
        """
        Возвращает суммарный реализованный УБЫТОК за сегодня (≤ 0).
        """
        pnls = self._fifo_closed_pnls_today(symbol)
        loss = sum((p for p in pnls if p < 0), Decimal("0"))
        return loss  # отрицательное или 0

    def _today_drawdown_quote(self, symbol: str) -> Decimal:
        """
        Возвращает дневную просадку (минимум кумулятивного реализованного PnL за сегодня), ≤ 0.
        Для простоты считаем равной сумме всех отрицательных закрытий (консервативно).
        """
        pnls = self._fifo_closed_pnls_today(symbol)
        dd = sum((p for p in pnls if p < 0), Decimal("0"))
        return dd  # отрицательное или 0

    def _today_loss_streak_reached(self, symbol: str, limit: int) -> bool:
        """
        Истинно, если подряд было >= limit убыточных закрытий за сегодня.
        """
        if limit <= 0:
            return False
        pnls = self._fifo_closed_pnls_today(symbol)
        streak = 0
        for p in reversed(pnls):  # от последних к первым
            if p < 0:
                streak += 1
                if streak >= limit:
                    return True
            else:
                break
        return False
