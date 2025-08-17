# src/crypto_ai_bot/core/risk/manager.py
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from crypto_ai_bot.core.risk import rules
from crypto_ai_bot.utils import metrics


RuleFn = Callable[[Dict[str, Any], Any], Tuple[bool, str]]

# порядок проверок: сначала время, затем остальные
_DEFAULT_RULE_ORDER: List[str] = [
    "check_time_sync",
    "check_hours",
    "check_spread",
    "check_dd",
    "check_seq_losses",
    "check_max_exposure",
]


def _resolve_rule(name: str) -> RuleFn | None:
    fn = getattr(rules, name, None)
    if callable(fn):
        return fn  # type: ignore
    return None


def check(features: Dict[str, Any], cfg) -> Tuple[bool, str]:
    """
    Пробегаемся по правилам. На первом отказе — стоп.
    """
    for name in _DEFAULT_RULE_ORDER:
        fn = _resolve_rule(name)
        if fn is None:
            continue
        ok, reason = (True, "ok")
        try:
            ok, reason = fn(features, cfg)
        except Exception as e:
            metrics.inc("risk_rule_errors_total", {"rule": name, "type": type(e).__name__})
            ok, reason = False, f"rule_error:{name}:{type(e).__name__}"

        if not ok:
            metrics.inc("risk_block_total", {"rule": name})
            return False, reason

    return True, "ok"
