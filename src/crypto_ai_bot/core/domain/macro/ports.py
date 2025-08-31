from __future__ import annotations
from typing import Protocol

class DxyPort(Protocol):
    async def change_pct(self) -> float | None: ...

class BtcDomPort(Protocol):
    async def change_pct(self) -> float | None: ...

class FomcCalendarPort(Protocol):
    async def event_today(self) -> bool: ...
