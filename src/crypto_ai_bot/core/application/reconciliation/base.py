from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class IReconciler(Protocol):
    async def reconcile(self, *, symbol: str) -> dict[str, Any] | None: ...

    # Минимальный контракт: на вход символ, на выход либо dict результата, либо None.


@dataclass(frozen=True)
class ReconciliationSuite:
    """Запускает набор сверок и собирает результаты в список dict."""

    reconcilers: Sequence[IReconciler]

    async def run(self, *, symbol: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in self.reconcilers:
            res = await r.reconcile(symbol=symbol)
            if isinstance(res, dict):
                out.append(res)
        return out
