# src/crypto_ai_bot/core/brokers/paper_exchange.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Dict, Optional

from .base import ExchangeInterface, TransientExchangeError, PermanentExchangeError
from .symbols import split_symbol, to_exchange_symbol
from crypto_ai_bot.utils import metrics

# Для рыночных котировок используем любой реальный источник (ccxt-адаптер) в режиме read-only
try:
    from .ccxt_exchange import CcxtExchange  # type: ignore
except Exception:
    CcxtExchange = None  # type: ignore


def _to_dec(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


@dataclass
class PaperExchange(ExchangeInterface):
    """
    Симулятор сделок поверх живых котировок (через реальный MD-провайдер).
    - Балансы и PnL считаются локально.
    - Заявки исполняются немедленно по last ± slippage.
    - Комиссия удерживается в котируемой валюте (quote).
    - Idempotency: по client_order_id защищаемся от повторов.
    """

    exchange_name: str
    contract: str = "spot"
    md: Any = None  # market-data provider (ExchangeInterface совместимый)
    fee_pct: Decimal = Decimal("0.001")           # 0.1% по умолчанию
    slippage_bps: int = 5                         # 5 bps = 0.05%
    balances: Dict[str, Decimal] = field(default_factory=dict)
    _orders: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    _seq: int = 0

    # -------------------------- Фабрика --------------------------

    @classmethod
    def from_settings(cls, cfg) -> "PaperExchange":
        ex_name = getattr(cfg, "EXCHANGE", "bybit").lower()
        contract = getattr(cfg, "CONTRACT_TYPE", "spot").lower()

        md_provider = None
        if CcxtExchange is not None:
            md_provider = CcxtExchange.from_settings(cfg)

        # стартовые балансы
        init_balances = {}
        # Ожидаем либо словарь, либо пары валют
        if hasattr(cfg, "PAPER_BALANCES") and isinstance(cfg.PAPER_BALANCES, dict):
            init_balances = {k: _to_dec(v) for k, v in cfg.PAPER_BALANCES.items()}
        else:
            # дефолт: 10_000 USDT, 0 базовой
            quote = getattr(cfg, "QUOTE_ASSET", "USDT")
            init_balances[quote] = _to_dec(getattr(cfg, "PAPER_QUOTE_INIT", "10000"))
            base = getattr(cfg, "BASE_ASSET", None)
            if base:
                init_balances[base] = _to_dec(getattr(cfg, "PAPER_BASE_INIT", "0"))

        fee = _to_dec(getattr(cfg, "PAPER_FEE_PCT", "0.001"))
        slp = int(getattr(cfg, "PAPER_SLIPPAGE_BPS", 5))

        return cls(exchange_name=ex_name, contract=contract, md=md_provider, fee_pct=fee, slippage_bps=slp, balances=init_balances)

    # -------------------------- Вспомогательные --------------------------

    def _price_with_slippage(self, last: Decimal, side: str) -> Decimal:
        # side=buy → цена чуть хуже (выше), side=sell → ниже
        bps = Decimal(self.slippage_bps) / Decimal(10_000)
        if side.lower() == "buy":
            return (last * (Decimal("1") + bps)).quantize(Decimal("0.00000001"), rounding=ROUND_FLOOR)
        return (last * (Decimal("1") - bps)).quantize(Decimal("0.00000001"), rounding=ROUND_FLOOR)

    def _next_id(self) -> str:
        self._seq += 1
        return f"paper-{int(time.time()*1000)}-{self._seq}"

    def _last_price(self, symbol: str) -> Decimal:
        if self.md is None:
            raise TransientExchangeError("no market data provider configured for PaperExchange")
        t = self.md.fetch_ticker(symbol)
        p = t.get("last") or t.get("close") or t.get("price")
        if p is None:
            raise TransientExchangeError("ticker has no price")
        return _to_dec(p)

    # -------------------------- Интерфейс --------------------------

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        if self.md is None:
            raise TransientExchangeError("no market data provider configured for PaperExchange")
        return self.md.fetch_ohlcv(symbol, timeframe, limit)

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        if self.md is None:
            raise TransientExchangeError("no market data provider configured for PaperExchange")
        t = self.md.fetch_ticker(symbol)
        t["provider"] = "paper/md"
        return t

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
        # идемпотентность
        if client_order_id and client_order_id in self._orders:
            return self._orders[client_order_id]

        base, quote = split_symbol(symbol)
        amt = _to_dec(amount)
        if amt <= 0:
            raise PermanentExchangeError("amount must be positive")

        last = self._last_price(symbol)
        fill_price = self._price_with_slippage(last, side)
        if type_.lower() == "limit" and price is not None:
            # симулируем исполнение лимита сразу, если «лучше» рынка
            p = _to_dec(price)
            if side.lower() == "buy":
                fill_price = min(fill_price, p)
            else:
                fill_price = max(fill_price, p)

        # комиссия в котируемой валюте
        fee = (fill_price * amt * self.fee_pct).quantize(Decimal("0.00000001"))
        cost = (fill_price * amt).quantize(Decimal("0.00000001"))

        if side.lower() == "buy":
            # нужно достаточно quote
            q = self.balances.get(quote, Decimal("0"))
            need = cost + fee
            if q < need:
                raise PermanentExchangeError("insufficient quote balance")
            self.balances[quote] = q - need
            self.balances[base] = self.balances.get(base, Decimal("0")) + amt
        else:
            # sell: достаточно base
            b = self.balances.get(base, Decimal("0"))
            if b < amt:
                raise PermanentExchangeError("insufficient base balance")
            self.balances[base] = b - amt
            self.balances[quote] = self.balances.get(quote, Decimal("0")) + (cost - fee)

        oid = client_order_id or self._next_id()
        order = {
            "id": oid,
            "symbol": to_exchange_symbol(self.exchange_name, symbol, contract=self.contract),
            "type": type_,
            "side": side,
            "amount": float(amt),
            "price": float(fill_price),
            "filled": float(amt),
            "status": "closed",
            "fee": {"currency": quote, "cost": float(fee)},
            "timestamp": int(time.time() * 1000),
        }
        if client_order_id:
            self._orders[client_order_id] = order
        return order

    def fetch_balance(self) -> Dict[str, Any]:
        total = {k: float(v) for k, v in self.balances.items()}
        return {"total": total, "free": total, "used": {k: 0.0 for k in total.keys()}}

    def cancel_order(self, order_id: str, *, symbol: str | None = None) -> Dict[str, Any]:
        # все ордера исполняются немедленно → отменять нечего
        return {"id": order_id, "status": "canceled", "note": "paper immediate or cancel"}

    def close(self) -> None:
        try:
            if self.md and hasattr(self.md, "close"):
                self.md.close()
        except Exception:
            pass
