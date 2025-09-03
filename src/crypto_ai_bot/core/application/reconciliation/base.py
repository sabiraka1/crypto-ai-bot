from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class IReconciler(Protocol):
    async def reconcile(self, *, symbol: str) -> dict[str, Any] | None: ...

@dataclass(frozen=True)
class ReconciliationSuite:
    reconcilers: Sequence[IReconciler]

    async def run(self, *, symbol: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in self.reconcilers:
            res = await r.reconcile(symbol=symbol)
            if isinstance(res, dict):
                out.append(res)
        return out

