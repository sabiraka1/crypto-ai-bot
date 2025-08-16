from __future__ import annotations
from typing import Dict, Any, Tuple

from . import rules

def check(decision: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """Aggregate risk rules; stop on first failure with clear reason."""
    for rule_fn in (
        rules.check_time_sync,
        rules.check_size_limits,
    ):
        ok, reason = rule_fn(decision, cfg)
        if not ok:
            return False, reason
    return True, 'ok'
