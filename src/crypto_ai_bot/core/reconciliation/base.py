from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Protocol


class IReconciler(Protocol):
    async def run_once(self) -> Dict[str, object]:
        """Выполняет один прогон сверки и возвращает агрегат/диагностику."""
        ...


@dataclass
class ReconciliationSuite:
    reconcilers: List[IReconciler] = field(default_factory=list)

    async def run_once(self) -> Dict[str, object]:
        result: Dict[str, object] = {}
        for r in self.reconcilers:
            try:
                name = r.__class__.__name__
            except Exception:
                name = "reconciler"
            try:
                part = await r.run_once()
                result[name] = part
            except Exception as exc:
                result[name] = {"error": str(exc)}
        return result

    async def loop(self, interval_sec: float) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                pass
            await asyncio.sleep(interval_sec)
