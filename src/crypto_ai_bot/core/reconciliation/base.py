from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class IReconciler(Protocol):
    async def run_once(self) -> None: ...
