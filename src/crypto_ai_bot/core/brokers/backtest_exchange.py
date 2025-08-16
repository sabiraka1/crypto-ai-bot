# src/crypto_ai_bot/core/brokers/backtest_exchange.py
from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Dict, Iterable, List, Optional

from .base import ExchangeInterface, PermanentExchangeError
from .symbols import split_symbol, to_exchange_symbol


def _to_dec(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


@dataclass
class BacktestExchange(ExchangeInterface):
    """
    Реплей исторических OHLCV.
    - Данные подаются заранее (csv/dataframe/list[OHLCV]).
    - Текущая точка времени = индекс i; fetch_ohlcv возвращает хвост до i включительно.
    - create_order исполняет по close[i] ± slippage.
    - Балансы живут локально, комиссии удерживаются в quote.
    - Движение времени управляется через tick(step) снаружи тестового цикла.
    """

    exchange_name: str = "backtest"
    contract: str = "spot"
    ohlcv: List[List[float]] = field(default_factory=list)  # [ts, o, h, l, c, v]
    i: int = 0
    slippage_bps: int = 0
    fee_pct: Decimal = Decimal("0.0005")  # 0.05% для backtest
    balances: Dict[str, Decimal] = field(default_factory=dict)

    # ------------------- инициализация -------------------

    @classmethod
    def from_csv(cls, path: str, *, slippage_bps: int = 0, fee_pct: str = "0.0005", balances: Optional[Dict[str, Any]] = None) -> "BacktestExchange":
        rows: List[List[float]] = []
        with open(path, "r", encoding="utf-8") as f:
            r = csv.reader(f)
            for row in r:
                if not row or row[0].startswith("#"):
                    continue
                # ожидаем: ts, open, high, low, close, volume
                ts, o, h, l, c, v = row[:6]
                rows.append([float(ts), float(o), float(h), float(l), float(c), float(v)])
        bal = {k: _to_dec(v) for k, v in (balances or {"USDT": "10000"}).items()}
        return cls(ohlcv=rows, slippage_bps=int(slippage_bps), fee_pct=_to_dec(fee_pct), balances=bal)

    @classmethod
    def from_ohlcv(cls, rows: Iterable[Iterable[float]], *, slippage_bps: int = 0, fee_pct: str = "0.0005", balances: Optional[Dict[str, Any]] = None) -> "BacktestExchange":
        data = [[float(a), float(b), float(c), float(d), float(e), float(f)] for a, b, c, d, e, f in rows]
        bal = {k: _to_dec(v) for k, v in (balances or {"USDT": "10000"}).items()}
        return cls(ohlcv=data, slippage_bps=int(slippage_bps), fee_pct=_to_dec(fee_pct), balances=bal)

    # ------------------- управление временем -------------------

    def tick(self, step: int = 1) -> None:
        """Сдвинуть «текущее время» на step баров вперёд."""
        self.i = max(0, min(len(self.ohlcv) - 1, self.i + int(step)))

    # ------------------- утилиты -------------------

    def _cur_close(self) -> Decimal:
        if not self.ohlcv:
            raise PermanentExchangeError("no OHLCV loaded")
        ts, o, h, l, c, v = self.ohlcv[self.i]
        return _to_dec(c)

    def _price_with_slippage(self, last: Decimal, side: str) -> Decimal:
        bps = Decimal(self.slippage_bps) / Decimal(10_000)
        if side.lower() == "buy":
            return (last * (Decimal("1") + bps)).quantize(Decimal("0.00000001"), rounding=ROUND_FLOOR)
        return (last * (Decimal("1") - bps)).quantize(Decimal("0.00000001"), rounding=ROUND_FLOOR)

    # ------------------- интерфейс -------------------

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        if not self.ohlcv:
            raise PermanentExchangeError("no OHLCV loaded")
        end = self.i + 1
        start = max(0, end - int(limit))
        return self.ohlcv[start:end]

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        if not self.ohlcv:
            raise PermanentExchangeError("no OHLCV loaded")
        ts, o, h, l, c, v = self.ohlcv[self.i]
        return {
            "symbol": to_exchange_symbol(self.exchange_name, symbol, contract=self.contract),
            "timestamp": int(ts),
            "last": float(c),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": float(v),
            "provider": "backtest",
        }

    def create_order(
        self,
        symbol: str,
        type_: str,
        side: str,
        amount: Decimal,
        price: Optional[Decimal] = None,
        *,
        idempotency_key: str | None = None,
        client_order_id: str | None = None,
    ) -> Dict[str, Any]:
        base, quote = split_symbol(symbol)
        amt = _to_dec(amount)
        if amt <= 0:
            raise PermanentExchangeError("amount must be positive")

        last = self._cur_close()
        fill_price = self._price_with_slippage(last, side)
        if type_.lower() == "limit" and price is not None:
            p = _to_dec(price)
            if side.lower() == "buy":
                fill_price = min(fill_price, p)
            else:
                fill_price = max(fill_price, p)

        fee = (fill_price * amt * self.fee_pct).quantize(Decimal("0.00000001"))
        cost = (fill_price * amt).quantize(Decimal("0.00000001"))

        if side.lower() == "buy":
            q = self.balances.get(quote, Decimal("0"))
            need = cost + fee
            if q < need:
                raise PermanentExchangeError("insufficient quote balance")
            self.balances[quote] = q - need
            self.balances[base] = self.balances.get(base, Decimal("0")) + amt
        else:
            b = self.balances.get(base, Decimal("0"))
            if b < amt:
                raise PermanentExchangeError("insufficient base balance")
            self.balances[base] = b - amt
            self.balances[quote] = self.balances.get(quote, Decimal("0")) + (cost - fee)

        oid = f"bt-{int(time.time()*1000)}-{self.i}"
        return {
            "id": oid,
            "symbol": to_exchange_symbol(self.exchange_name, symbol, contract=self.contract),
            "type": type_,
            "side": side,
            "amount": float(amt),
            "price": float(fill_price),
            "filled": float(amt),
            "status": "closed",
            "fee": {"currency": quote, "cost": float(fee)},
            "timestamp": int(self.ohlcv[self.i][0]),
        }

    def fetch_balance(self) -> Dict[str, Any]:
        total = {k: float(v) for k, v in self.balances.items()}
        return {"total": total, "free": total, "used": {k: 0.0 for k in total.keys()}}

    def cancel_order(self, order_id: str, *, symbol: str | None = None) -> Dict[str, Any]:
        return {"id": order_id, "status": "canceled", "note": "backtest immediate or cancel"}

    def close(self) -> None:
        pass
