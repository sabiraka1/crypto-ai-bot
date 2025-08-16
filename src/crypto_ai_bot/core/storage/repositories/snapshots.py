from __future__ import annotations
from typing import Any, Dict, List

class SqliteSnapshotRepository:
    """Минимальный заглушечный репозиторий снимков, чтобы не валить импорты в тестах.
    Реальную схему/CRUD можно добавить позже.
    """
    def __init__(self, con) -> None:
        self.con = con

    def insert(self, snapshot: Dict[str, Any]) -> None:
        # no-op для совместимости
        pass

    def list_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        return []
