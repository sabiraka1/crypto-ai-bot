# src/crypto_ai_bot/context/snapshot.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ContextSnapshot:
    """
    Нейтральный снэпшот контекста рынка: безопасно работает «из коробки».
    Поля опциональны: если чего-то нет — агрегатор просто не применит штраф/бонус.
    """
    # Доминация BTC: суточное изменение в п.п. (например, +0.8)
    btc_dominance_delta_24h: Optional[float] = None
    # Индекс доллара DXY: 5-дневное изменение в %
    dxy_delta_5d: Optional[float] = None
    # Индекс страха/жадности (0..100), 50 — нейтрально
    fear_greed: Optional[int] = None
    # Режим рынка: STRONG_BULL | WEAK_BULL | SIDEWAYS | WEAK_BEAR | STRONG_BEAR
    market_condition: str = "SIDEWAYS"
    # Произвольные заметки/расчёты
    notes: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> Dict[str, Any]:
        return {
            "market_condition": self.market_condition,
            "btc_dominance_delta": self.btc_dominance_delta_24h,
            "dxy_delta": self.dxy_delta_5d,
            "fear_greed": self.fear_greed,
            "notes": self.notes,
        }

    @classmethod
    def neutral(cls) -> "ContextSnapshot":
        return cls(
            btc_dominance_delta_24h=None,
            dxy_delta_5d=None,
            fear_greed=50,
            market_condition="SIDEWAYS",
            notes={}
        )


def build_context_snapshot(
    btc_dom_delta_24h: Optional[float] = None,
    dxy_delta_5d: Optional[float] = None,
    fear_greed: Optional[int] = None,
    market_condition: Optional[str] = None,
    **extras: Any,
) -> ContextSnapshot:
    snap = ContextSnapshot(
        btc_dominance_delta_24h=btc_dom_delta_24h,
        dxy_delta_5d=dxy_delta_5d,
        fear_greed=fear_greed,
        market_condition=market_condition or "SIDEWAYS",
        notes={}
    )
    if extras:
        snap.notes.update(extras)
    return snap


__all__ = ["ContextSnapshot", "build_context_snapshot"]
