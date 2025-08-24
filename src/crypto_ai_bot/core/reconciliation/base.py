from __future__ import annotations
from typing import Protocol

class IReconciler(Protocol):
    async def run_once(self) -> None: ...
