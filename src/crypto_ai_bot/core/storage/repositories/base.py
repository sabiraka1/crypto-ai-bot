from __future__ import annotations
from typing import Any, Dict, Optional
from crypto_ai_bot.utils import metrics

class _WriteCountingRepo:
    """
    Базовый класс, инкрементирующий счётчик записей для ANALYZE-порога.
    Репозитории должны звать _inc_writes("table", n).
    """
    def __init__(self, con, cfg=None) -> None:
        self._con = con
        self._cfg = cfg

    def _inc_writes(self, table: str, n: int = 1) -> None:
        try:
            metrics.inc("db_writes_total", {"table": table})
        except Exception:
            pass
        try:
            if self._cfg is not None:
                # мягко: если поля нет — игнорим
                current = getattr(self._cfg, "DB_WRITES_SINCE_ANALYZE", 0) or 0
                setattr(self._cfg, "DB_WRITES_SINCE_ANALYZE", int(current) + int(n))
        except Exception:
            pass
