from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_ai_bot.utils.decimal import dec
from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import hist

_log = get_logger("strategy.base")


@dataclass(frozen=True)
class Signal:
    side: str  # "buy" | "sell" | "none"
    score: Decimal  # [-1..+1]
    reason: str = ""  # РєСЂР°С‚РєР°СЏ РїСЂРёС‡РёРЅР°


class BaseStrategy:
    """
    РЁР°Р±Р»РѕРЅРЅС‹Р№ РјРµС‚РѕРґ:
      - prepare()  -> РїРѕРґРіРѕС‚РѕРІРєР° С„РёС‡/РєСЌС€Р° (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)
      - signal()   -> СЃС‚РѕСЂРѕРЅР°/score
      - sizing()   -> С†РµР»РµРІРѕР№ СЂР°Р·РјРµСЂ (quote/base) (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)
      - validate() -> РёРЅРІР°СЂРёР°РЅС‚С‹, С„РёР»СЊС‚СЂС‹
    Р’РЅРµС€РЅРёР№ РєРѕРЅС‚СЂР°РєС‚: generate(ctx, md) -> dict
    """

    name: str = "base"

    async def prepare(self, ctx: Any, md: Any) -> None:
        return None

    async def signal(self, ctx: Any, md: Any) -> Signal:  # override
        return Signal(side="none", score=dec("0"), reason="noimpl")

    async def sizing(self, ctx: Any, md: Any, sig: Signal) -> dict[str, str | Decimal]:
        # РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ вЂ” Р±РµР· РёР·РјРµРЅРµРЅРёСЏ СЂР°Р·РјРµСЂР°; РєРѕРЅРєСЂРµС‚РЅС‹Рµ СЃС‚СЂР°С‚РµРіРёРё РїРµСЂРµРѕРїСЂРµРґРµР»СЏСЋС‚
        return {"mode": "fixed_quote", "quote_amount": dec(str(getattr(ctx, "FIXED_AMOUNT", "0") or "0"))}

    async def validate(self, ctx: Any, md: Any, sig: Signal) -> tuple[bool, str]:
        # РѕР±С‰РёР№ С„РёР»СЊС‚СЂ: Р·Р°РїСЂРµС‰Р°РµРј Р±РµСЃСЃРјС‹СЃР»РµРЅРЅС‹Рµ СЃРёРіРЅР°Р»С‹
        if sig.side not in ("buy", "sell", "none"):
            return False, "invalid_side"
        return True, ""

    async def generate(self, ctx: Any, md: Any) -> dict[str, Any]:
        t0 = __import__("time").time()
        await self.prepare(ctx, md)

        sig = await self.signal(ctx, md)
        ok, why = await self.validate(ctx, md, sig)
        if not ok or sig.side == "none":
            hist(
                "strategy.generate.ms",
                (__import__("time").time() - t0) * 1000,
                {"name": self.name, "side": "none"},
            )
            return {"action": "skip", "reason": why or sig.reason, "score": str(sig.score)}

        size = await self.sizing(ctx, md, sig)
        out = {
            "action": sig.side,
            "score": str(sig.score),
            "sizing": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in size.items()},
            "reason": sig.reason,
        }
        hist(
            "strategy.generate.ms",
            (__import__("time").time() - t0) * 1000,
            {"name": self.name, "side": sig.side},
        )
        return out
