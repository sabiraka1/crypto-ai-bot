from __future__ import annotations

from typing import Dict, Any, List
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger("recon.discrepancy")


def build_report(*, discrepancies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Нормализует вывод сверок, логирует найденные расхождения."""
    for d in discrepancies:
        _log.warning("discrepancy", extra=d)
    return {"discrepancies": discrepancies, "count": len(discrepancies)}
