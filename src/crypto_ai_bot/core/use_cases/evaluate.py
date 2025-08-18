# src/crypto_ai_bot/core/use_cases/evaluate.py
from __future__ import annotations

from typing import Any, Dict

from crypto_ai_bot.utils import metrics
from crypto_ai_bot.utils.rate_limit import rate_limit
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe
from crypto_ai_bot.core.brokers.base import ExchangeInterface
from crypto_ai_bot.core.signals.policy import decide
from crypto_ai_bot.core.signals._build import build  # приватный билд фич

# контекст
from crypto_ai_bot.core.signals.context_blend import compute_context_score, blend_scores
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker
from crypto_ai_bot.utils.http_client import get_http_client
from crypto_ai_bot.market_context.snapshot import build_snapshot as build_market_context


@rate_limit(max_calls=60, window=60)  # спецификация
def evaluate(cfg: Any, broker: ExchangeInterface, *, symbol: str, timeframe: str, limit: int) -> Any:
    symbol_n = normalize_symbol(symbol)
    timeframe_n = normalize_timeframe(timeframe)

    # 1) строим фичи
    with metrics.timer() as t_build:
        features: Dict[str, Any] = build(cfg, broker, symbol=symbol_n, timeframe=timeframe_n, limit=int(limit))
    metrics.observe_histogram("latency_build_seconds", t_build.elapsed)

    # 2) основное решение (базовый score/действие)
    with metrics.timer() as t_dec:
        decision = decide(cfg, features)
    metrics.observe_histogram("latency_decide_seconds", t_dec.elapsed)

    # 3) контекст (мягко, по умолчанию веса=0 → только explain/метрики)
    alpha = float(getattr(cfg, "CONTEXT_DECISION_WEIGHT", 0.0) or 0.0)
    w_dom = float(getattr(cfg, "CTX_BTC_DOM_WEIGHT", 0.0) or 0.0)
    w_fng = float(getattr(cfg, "CTX_FNG_WEIGHT", 0.0) or 0.0)
    w_dxy = float(getattr(cfg, "CTX_DXY_WEIGHT", 0.0) or 0.0)

    ctx_used = False
    if alpha > 0.0 and (w_dom + w_fng + w_dxy) > 0.0:
        try:
            http = get_http_client()
            breaker = CircuitBreaker()
            ctx = build_market_context(cfg, http, breaker) or {}
            ctx_used = True
        except Exception:
            ctx = {}
    else:
        ctx = {}

    # достаём базовый score (если нет — аккуратно нормируем по action)
    try:
        base_score = float(getattr(decision, "score", None) or decision.get("score"))
    except Exception:
        base_score = None
    if base_score is None:
        act = str(getattr(decision, "action", None) or decision.get("action") or "hold").lower()
        # грубая эвристика при отсутствии явного score
        base_score = 0.5 if act == "hold" else (0.65 if act == "buy" else 0.35)

    # считаем контекстный вклад и бленд
    ctx_score_pm1 = compute_context_score(
        {"btc_dominance": ctx.get("btc_dominance"), "fear_greed": ctx.get("fear_greed"), "dxy": ctx.get("dxy")},
        w_btc_dom=w_dom, w_fng=w_fng, w_dxy=w_dxy,
    )
    blended = blend_scores(base_score, ctx_score_pm1, alpha=alpha)

    # метрики
    metrics.observe_histogram("decision_score_histogram", base_score)
    metrics.observe_histogram("decision_score_ctx_histogram", 0.5 * (ctx_score_pm1 + 1.0))
    metrics.observe_histogram("decision_score_blended_histogram", blended)
    if ctx_used:
        metrics.inc("context_used_total")
    else:
        metrics.inc("context_unused_total")

    # explain/декорируем решение (не меняем action — только добавляем поля)
    try:
        exp = decision.get("explain", {})
        exp["context"] = {
            "alpha": alpha,
            "weights": {"btc_dom": w_dom, "fng": w_fng, "dxy": w_dxy},
            "ctx": {"btc_dominance": ctx.get("btc_dominance"), "fear_greed": ctx.get("fear_greed"), "dxy": ctx.get("dxy")},
            "score_ctx_pm1": ctx_score_pm1,
            "score_base": base_score,
            "score_blended": blended,
        }
        decision["explain"] = exp
        # Дополняем корневые поля «на чтение» — пусть фронты/дашборд могут увидеть
        decision["score_base"] = base_score
        decision["score_blended"] = blended
    except Exception:
        # если решение не dict-подобное — просто возвращаем как есть
        pass

    return decision
