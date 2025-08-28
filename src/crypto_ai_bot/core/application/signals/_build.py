# src/crypto_ai_bot/core/application/signals/_build.py
from __future__ import annotations
from decimal import Decimal
from typing import Dict, Any

from crypto_ai_bot.core.infrastructure.brokers.base import IBroker
from crypto_ai_bot.core.infrastructure.brokers.symbols import parse_symbol
from crypto_ai_bot.core.infrastructure.storage.facade import Storage
from crypto_ai_bot.core.domain.signals._build import SignalInputs, build_signal

async def build_signal_from_runtime(*, symbol: str, broker: IBroker, storage: Storage) -> Dict[str, Any]:
    """
    Оркестрация: тянем рыночные/учётные данные из инфраструктуры и
    превращаем их в чистые входы для доменного билдера.
    """
    t = await broker.fetch_ticker(symbol)
    mid = (t.bid + t.ask) / Decimal("2") if t.bid and t.ask else (t.last or Decimal("0"))
    spread = ((t.ask - t.bid) / mid) if t.bid and t.ask and mid > 0 else Decimal("0")

    pos = storage.positions.get_position(symbol)
    base_local = pos.base_qty if pos else Decimal("0")

    bal = await broker.fetch_balance(symbol)
    free_q = bal.free_quote
    free_b = bal.free_base

    inputs = SignalInputs(
        last=t.last or Decimal("0"),
        bid=t.bid,
        ask=t.ask,
        spread_frac=spread,
        position_base=base_local,
        free_quote=free_q,
        free_base=free_b,
    )
    sig = build_signal(inputs)
    return {"action": sig.action, "strength": str(sig.strength), "meta": sig.meta}
