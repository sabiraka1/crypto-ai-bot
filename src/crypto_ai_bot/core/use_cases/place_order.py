from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any, Dict, Optional

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.rate_limit import RateLimiter
from crypto_ai_bot.core.positions.manager import open as open_position
from crypto_ai_bot.core.storage.repositories.idempotency import build_key, SqliteIdempotencyRepository

_RL = RateLimiter()

def place_order(cfg, broker, positions_repo, audit_repo, decision: Dict[str, Any], *, idem_repo: Optional[SqliteIdempotencyRepository] = None) -> Dict[str, Any]:
    # rate-limit по спецификации: 10/min
    calls = int(getattr(cfg, "RL_EXECUTE_CALLS", 10))
    per_s = int(getattr(cfg, "RL_EXECUTE_PERIOD_S", 60))
    symbol = decision.get("symbol") or getattr(cfg, "SYMBOL", "BTC/USDT")
    key_rl = f"exec:{symbol}:{decision.get('action')}"
    if not _RL.allow(key_rl, calls=calls, per_seconds=per_s):
        return {"status": "rate_limited", "rate_key": key_rl, "calls": calls, "per_s": per_s}

    size = str(decision.get("size", "0"))
    side = str(decision.get("action", "hold"))
    ts_ms = int(time.time() * 1000)
    decision_id = str(decision.get("id") or decision.get("decision_id") or "dec")
    idem_key = build_key(symbol, side, size, ts_ms, decision_id)

    if idem_repo is not None:
        if not idem_repo.claim(idem_key, ttl_seconds=int(getattr(cfg, "IDEMPOTENCY_TTL_S", 300))):
            original = idem_repo.get_original_order(idem_key)
            return {"status": "duplicate", "idempotency_key": idem_key, "original": original}

    # NB: пример — здесь вызывается ваш positions manager / брокер
    res = open_position(symbol=symbol, side=side, size=Decimal(size), sl=None, tp=None)  # возможно у тебя своя логика

    if idem_repo is not None:
        try:
            idem_repo.commit(idem_key, payload=json.dumps(res).encode("utf-8"))
        except Exception:
            # в случае ошибки коммита не ломаем исполнение — это вторично
            pass

    metrics.inc("orders_submitted_total", {"side": side})
    return {"status": "submitted", "result": res, "idempotency_key": idem_key}
