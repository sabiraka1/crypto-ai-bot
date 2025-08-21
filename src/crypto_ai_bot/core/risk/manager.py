from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol, Tuple, Dict, List

class IRule(Protocol):
    name: str
    async def allow(self, decision: str, symbol: str, ctx: Dict[str, Any]) -> Tuple[bool, str]: ...

@dataclass
class RiskManager:
    rules: List[IRule]

    async def allow(self, decision: str, symbol: str, ctx: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Пробегаем по правилам: первое, кто отклонит — блокирует сделку.
        Если правил нет — считаем, что разрешено.
        """
        for r in self.rules or []:
            ok, reason = await r.allow(decision, symbol, ctx)
            if not ok:
                return False, f"{r.name}:{reason}"
        return True, "ok"
