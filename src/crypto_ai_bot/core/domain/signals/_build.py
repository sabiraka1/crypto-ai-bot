# src/crypto_ai_bot/core/domain/signals/_build.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any

from crypto_ai_bot.utils.decimal import dec


@dataclass(frozen=True)
class SignalInputs:
    """Чистые входы для расчета сигналов, без внешних зависимостей."""
    last: Decimal
    bid: Optional[Decimal]
    ask: Optional[Decimal]
    spread_frac: Decimal
    position_base: Decimal
    free_quote: Decimal
    free_base: Decimal


@dataclass(frozen=True)
class Signal:
    """Результат расчета торгового сигнала."""
    action: str              # 'buy' | 'sell' | 'hold'
    strength: Decimal        # 0..1
    meta: Dict[str, Any]


def build_signal(inp: SignalInputs) -> Signal:
    """
    Чистая бизнес-логика сигналов.
    Никаких обращений к брокеру/БД/сети — только расчёты.
    
    Args:
        inp: Входные данные для расчета сигнала
        
    Returns:
        Signal с действием, силой и метаданными
    """
    # Пример тривиальной логики: если поза 0 и спред умеренный — buy, иначе hold
    if inp.position_base <= 0 and inp.spread_frac < dec("0.005") and inp.free_quote > dec("10"):
        return Signal(
            action="buy", 
            strength=dec("0.6"), 
            meta={"reason": "flat_and_spread_ok"}
        )
    
    if inp.position_base > 0 and inp.spread_frac > dec("0.02"):
        return Signal(
            action="sell", 
            strength=dec("0.4"), 
            meta={"reason": "wide_spread_trim"}
        )
    
    return Signal(
        action="hold", 
        strength=dec("0.1"), 
        meta={"reason": "no_edge"}
    )