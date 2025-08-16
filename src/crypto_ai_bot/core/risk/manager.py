from __future__ import annotations

"""
Агрегация правил риска. Все проверки — чистые функции.
"""

from typing import Any, Dict, Tuple, Callable, List
from . import rules


Rule = Callable[[Dict[str, Any], object], Tuple[bool, str | None]]

DEFAULT_RULES: List[Rule] = [
    rules.check_time_sync,
    rules.check_spread,
    rules.check_hours,
    rules.check_seq_losses,
    rules.check_max_exposure,
]


def check(features: Dict[str, Any], cfg, custom_rules: List[Rule] | None = None) -> Tuple[bool, str | None]:
    rs = custom_rules or DEFAULT_RULES
    for r in rs:
        try:
            ok, reason = r(features, cfg)
        except Exception as e:
            return False, f"risk_rule_error:{r.__name__}:{type(e).__name__}"
        if not ok:
            return False, reason
    return True, None
