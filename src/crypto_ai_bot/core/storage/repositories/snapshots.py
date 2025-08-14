
# -*- coding: utf-8 -*-
"""
core.storage.repositories.snapshots
Interface for feature snapshots.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

@dataclass
class Snapshot:
    ts: int
    symbol: str
    timeframe: str
    data: Dict[str, Any]

class SnapshotRepository:
    def save(self, s: Snapshot) -> None: ...
    def last(self, symbol: str, timeframe: str) -> Optional[Snapshot]: ...
    def list(self, symbol: str, timeframe: str, limit: int = 200) -> List[Snapshot]: ...


