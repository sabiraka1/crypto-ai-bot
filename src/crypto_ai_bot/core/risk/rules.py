from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Tuple, Optional

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.utils.time_sync import measure_time_drift


@dataclass(frozen=True)
class RuleResult:
    ok: bool
    reason: str = ""
    extra: Dict[str, Any] | None = None


def check_time_sync(cfg) -> RuleResult:
    limit_ms: int = getattr(cfg, "TIME_DRIFT_LIMIT_MS", 0)
    if limit_ms <= 0:
        return RuleResult(ok=True, reason="time_sync_check_disabled")

    http = get_http_client()
    urls = getattr(cfg, "TIME_DRIFT_URLS", None)

    try:
        drift_ms = measure_time_drift(http=http, urls=urls, timeout=2.0)
    except Exception as e:
        metrics.inc("risk_time_sync_errors_total", {"stage": "measure_exception"})
        return RuleResult(ok=True, reason=f"time_sync_unavailable:{type(e).__name__}")

    # публикуем gauge; сохраняем совместимость, если вдруг кто-то читает summary
    try:
        if drift_ms is not None:
            metrics.set_gauge("time_drift_ms", float(drift_ms), {"mode": getattr(cfg, "MODE", "unknown")})
        else:
            metrics.inc("risk_time_sync_errors_total", {"stage": "no_result"})
    except Exception:
        pass

    if drift_ms is None:
        return RuleResult(ok=True, reason="time_sync_unavailable")

    if drift_ms > limit_ms:
        metrics.inc("risk_block_total", {"rule": "time_sync", "result": "blocked"})
        return RuleResult(
            ok=False,
            reason=f"time_drift_exceeded:{drift_ms}ms>{limit_ms}ms",
            extra={"drift_ms": drift_ms, "limit_ms": limit_ms},
        )

    metrics.inc("risk_check_total", {"rule": "time_sync", "result": "ok"})
    return RuleResult(ok=True, reason="time_sync_ok", extra={"drift_ms": drift_ms, "limit_ms": limit_ms})


# Заглушки прочих правил (как и было)
def check_hours(features: Dict[str, Any], cfg) -> RuleResult:
    return RuleResult(ok=True, reason="hours_ok")

def check_spread(features: Dict[str, Any], cfg) -> RuleResult:
    return RuleResult(ok=True, reason="spread_ok")

def check_max_exposure(current_exposure: Optional[Decimal], cfg) -> RuleResult:
    return RuleResult(ok=True, reason="exposure_ok")

def check_seq_losses(losses_count: Optional[int], cfg) -> RuleResult:
    return RuleResult(ok=True, reason="seq_losses_ok")
