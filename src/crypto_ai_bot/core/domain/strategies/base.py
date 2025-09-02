from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


# ==== РЎРѕРІРјРµСЃС‚РёРјС‹Р№ РїСѓР±Р»РёС‡РЅС‹Р№ API РґР»СЏ СЃС‚СЂР°С‚РµРіРёР№ ====

@dataclass(frozen=True)
class Decision:
    """
    Р РµС€РµРЅРёРµ СЃС‚СЂР°С‚РµРіРёРё:
    - action: 'buy' | 'sell' | 'hold'
    - confidence: 0..1 (РІРµСЃ)
    - quote_amount/base_amount: Р¶РµР»Р°РµРјС‹Рµ РѕР±СЉС‘РјС‹
    - reason: РїРѕСЏСЃРЅРµРЅРёРµ (РґР»СЏ Р»РѕРіРѕРІ/СѓРІРµРґРѕРјР»РµРЅРёР№)
    """
    action: str
    confidence: float = 0.0
    quote_amount: str | None = None
    base_amount: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class StrategyContext:
    """РљРѕРЅС‚РµРєСЃС‚ РіРµРЅРµСЂР°С†РёРё СЃРёРіРЅР°Р»Р°."""
    symbol: str
    settings: Any
    data: dict[str, Any] | None = None  # Р”РѕР±Р°РІР»РµРЅ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё СЃ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёРј РєРѕРґРѕРј


class MarketData(Protocol):
    """РџРѕСЂС‚ РґР»СЏ РїРѕР»СѓС‡РµРЅРёСЏ СЂС‹РЅРѕС‡РЅС‹С… РґР°РЅРЅС‹С…."""
    async def get_ohlcv(
        self, symbol: str, timeframe: str = "1m", limit: int = 200
    ) -> Sequence[tuple[Any, ...]]: ...
    async def get_ticker(self, symbol: str) -> dict[str, Any]: ...


# Р”Р»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё СЃРѕ СЃС‚Р°СЂС‹Рј РёРјРµРЅРѕРІР°РЅРёРµРј:
MarketData = MarketData


class BaseStrategy(ABC):
    """Р‘Р°Р·РѕРІС‹Р№ РєРѕРЅС‚СЂР°РєС‚ СЃС‚СЂР°С‚РµРіРёРё."""

    @abstractmethod
    async def generate(self, *, md: MarketData, ctx: StrategyContext) -> Decision: ...
    
    # Р”РѕР±Р°РІР»СЏРµРј РјРµС‚РѕРґ decide РґР»СЏ РѕР±СЂР°С‚РЅРѕР№ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё
    def decide(self, ctx: StrategyContext) -> tuple[str, dict[str, Any]]:
        """Р›РµРіР°СЃРё РјРµС‚РѕРґ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё СЃРѕ СЃС‚Р°СЂС‹Рј РєРѕРґРѕРј."""
        # Р‘СѓРґРµС‚ РїРµСЂРµРѕРїСЂРµРґРµР»РµРЅ РІ РєРѕРЅРєСЂРµС‚РЅС‹С… СЃС‚СЂР°С‚РµРіРёСЏС…
        return "hold", {"reason": "not_implemented"}
