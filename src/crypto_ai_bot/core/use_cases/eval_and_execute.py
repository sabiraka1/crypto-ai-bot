# src/crypto_ai_bot/core/use_cases/eval_and_execute.py
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.core.signals import policy


def _dec(v: Any) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")


def _build_idem_key(symbol: str, action: str, decision: Dict[str, Any]) -> str:
    # Унифицированный формат ключа (как в спецификации):
    # {symbol}:{side}:{size}:{timestamp_minute}:{decision_id[:8]}
    minute = int(time.time() // 60)
    size = decision.get("size") or 0
    d_id = str(decision.get("id") or "")[:8]
    return f"{symbol}:{action}:{size}:{minute}:{d_id}"


def eval_and_execute(
    cfg: Any,
    broker: Any,
    *,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    limit: Optional[int] = None,
    # репозитории/юнит-оф-ворк — опциональные: если не переданы, выполняем только evaluate
    positions_repo: Any = None,
    trades_repo: Any = None,
    audit_repo: Any = None,
    uow: Any = None,
    # идемпотентность — опциональна
    idempotency_repo: Any = None,
) -> Dict[str, Any]:
    """
    Полный конвейер: decide → (опционально risk/idem) → (опционально execute).
    Если репозитории или uow не переданы — возвращаем только результат оценки (без исполнения).
    """

    sym = symbol or getattr(cfg, "SYMBOL", "BTC/USDT")
    tf = timeframe or getattr(cfg, "TIMEFRAME", "1h")
    lim = int(limit or getattr(cfg, "FEATURE_LIMIT", 300))

    # 1) EVALUATE
    t0 = time.perf_counter()
    decision = policy.decide(cfg, broker, symbol=sym, timeframe=tf, limit=lim)
    if not isinstance(decision, dict):
        # допускаем pydantic-модель
        decision = decision.model_dump() if hasattr(decision, "model_dump") else dict(decision)

    action = (decision.get("action") or "hold").lower()
    metrics.inc("bot_decision_total", {"action": action})
    metrics.observe("latency_decide_seconds", time.perf_counter() - t0, {"symbol": sym, "tf": tf})

    # Безопасный fast-path: если нет репозиториев — только оценка
    have_repos = all([positions_repo, trades_repo, audit_repo, uow])
    if not have_repos:
        return {
            "status": "evaluated",
            "symbol": sym,
            "timeframe": tf,
            "decision": decision,
            "note": "execution skipped (no repositories/uow wired)",
        }

    # 2) IDEMPOTENCY (опционально)
    idem_key = None
    claimed = False
    if idempotency_repo:
        try:
            idem_key = _build_idem_key(sym, action, decision)
            claimed = idempotency_repo.claim(idem_key)
            if not claimed:
                return {
                    "status": "duplicate",
                    "symbol": sym,
                    "timeframe": tf,
                    "idempotency_key": idem_key,
                    "decision": decision,
                }
        except Exception as e:  # не роняем цикл из-за идемпотентности
            return {
                "status": "error",
                "error": f"idempotency_claim_failed: {type(e).__name__}: {e}",
                "decision": decision,
            }

    # 3) EXECUTE
    exec_result: Dict[str, Any] | None = None
    try:
        from .place_order import place_order

        exec_result = place_order(
            cfg,
            broker,
            positions_repo=positions_repo,
            trades_repo=trades_repo,
            audit_repo=audit_repo,
            uow=uow,
            decision=decision,
        )
        if idempotency_repo and claimed and idem_key:
            try:
                idempotency_repo.commit(idem_key, exec_result)
            except Exception:
                # даже если commit не удался — ордер уже отправили; логируем метрику
                metrics.inc("idempotency_commit_error_total", {"symbol": sym})
        return {
            "status": exec_result.get("status", "ok"),
            "symbol": sym,
            "timeframe": tf,
            "decision": decision,
            "executed": exec_result,
        }
    except Exception as e:
        if idempotency_repo and claimed and idem_key:
            try:
                idempotency_repo.release(idem_key)
            except Exception:
                metrics.inc("idempotency_release_error_total", {"symbol": sym})
        # Пробрасывать исключение наверх не будем — вернём структуру ошибки,
        # чтобы /tick отдавал 200 с понятным телом, а не 500.
        return {
            "status": "error",
            "error": f"execute_failed: {type(e).__name__}: {e}",
            "decision": decision,
        }
