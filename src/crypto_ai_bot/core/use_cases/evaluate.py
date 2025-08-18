# src/crypto_ai_bot/core/use_cases/evaluate.py
from __future__ import annotations

from typing import Any, Dict, Optional

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

# опционально для расширенного контекста
try:
    from crypto_ai_bot.utils.time_sync import measure_time_drift
except Exception:  # pragma: no cover
    measure_time_drift = None  # type: ignore


@rate_limit(max_calls=60, window=60)  # спецификация
def evaluate(
    cfg: Any,
    broker: ExchangeInterface,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    # --- новые необязательные параметры, чтобы не ломать внешние вызовы ---
    repos: Optional[Any] = None,
    http: Optional[Any] = None,
) -> Any:
    """
    Основной расчёт решения. Дополнено внутренним контекстом:
    - exposure_open_positions
    - exposure_notional_quote (эвристика)
    - time_drift_ms
    """
    symbol_n = normalize_symbol(symbol)
    timeframe_n = normalize_timeframe(timeframe)

    # 1) строим фичи (внешние)
    with metrics.timer() as t_build:
        features: Dict[str, Any] = build(cfg, broker, symbol=symbol_n, timeframe=timeframe_n, limit=int(limit))
    metrics.observe_histogram("latency_build_seconds", t_build.elapsed)

    # 2) основное решение (базовый score/действие)
    with metrics.timer() as t_dec:
        decision = decide(cfg, features)
    metrics.observe_histogram("latency_decide_seconds", t_dec.elapsed)

    # 3) контекст рынка (внешний, мягкий)
    alpha = float(getattr(cfg, "CONTEXT_DECISION_WEIGHT", 0.0) or 0.0)
    w_dom = float(getattr(cfg, "CTX_BTC_DOM_WEIGHT", 0.0) or 0.0)
    w_fng = float(getattr(cfg, "CTX_FNG_WEIGHT", 0.0) or 0.0)
    w_dxy = float(getattr(cfg, "CTX_DXY_WEIGHT", 0.0) or 0.0)

    ctx_used = False
    if alpha > 0.0 and (w_dom + w_fng + w_dxy) > 0.0:
        try:
            http_client = http or get_http_client()
            breaker = CircuitBreaker()
            ctx = build_market_context(cfg, http_client, breaker) or {}
            ctx_used = True
        except Exception:
            ctx = {}
    else:
        ctx = {}

    # 4) ДОПОЛНИТЕЛЬНЫЙ ВНУТРЕННИЙ КОНТЕКСТ (экспозиция + дрейф времени)
    #    — опционально, чтобы не ломать внешние вызовы evaluate()
    exposure_open = None
    exposure_notional = None
    try:
        if repos and hasattr(repos, "positions") and hasattr(repos.positions, "get_open"):
            _opens = repos.positions.get_open() or []
            exposure_open = len(_opens)
            # простая эвристика в кватах (USDT): суммарный размер * текущая цена
            try:
                t = broker.fetch_ticker(symbol_n)
                last = float(t.get("last") or t.get("close") or 0.0)
            except Exception:
                last = 0.0
            size_sum = 0.0
            for p in _opens:
                try:
                    size_sum += abs(float(p.get("qty") or p.get("size") or 0.0))
                except Exception:
                    continue
            exposure_notional = (size_sum * last) if (size_sum and last) else 0.0
    except Exception:
        pass

    drift_ms = None
    try:
        if measure_time_drift is not None:
            http_client = http or get_http_client()
            urls = getattr(cfg, "TIME_DRIFT_URLS", None)
            timeout = float(getattr(cfg, "CONTEXT_HTTP_TIMEOUT_SEC", 2.0) or 2.0)
            drift_ms = measure_time_drift(cfg=cfg, http=http_client, urls=urls, timeout=timeout)
    except Exception:
        drift_ms = None

    # Вклеиваем внутренний контекст в features, чтобы downstream-логика могла читать из единого места
    try:
        features.setdefault("context", {})
        if exposure_open is not None:
            features["context"]["exposure_open_positions"] = int(exposure_open)
        if exposure_notional is not None:
            features["context"]["exposure_notional_quote"] = float(exposure_notional)
        if drift_ms is not None:
            features["context"]["time_drift_ms"] = int(drift_ms)
    except Exception:
        pass

    # достаём базовый score
    try:
        base_score = float(getattr(decision, "score", None) or decision.get("score"))
    except Exception:
        base_score = None
    if base_score is None:
        act = str(getattr(decision, "action", None) or decision.get("action") or "hold").lower()
        base_score = 0.5 if act == "hold" else (0.65 if act == "buy" else 0.35)

    # вклад контекста и бленд
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

    # explain/обогащение (не меняем action)
    try:
        exp = decision.get("explain", {})
        exp["context"] = {
            "alpha": alpha,
            "weights": {"btc_dom": w_dom, "fng": w_fng, "dxy": w_dxy},
            "ctx": {
                "btc_dominance": ctx.get("btc_dominance"),
                "fear_greed": ctx.get("fear_greed"),
                "dxy": ctx.get("dxy"),
                # внутренняя часть — здесь же, чтобы /why это увидел
                "exposure_open_positions": exposure_open,
                "exposure_notional_quote": exposure_notional,
                "time_drift_ms": drift_ms,
            },
            "score_ctx_pm1": ctx_score_pm1,
            "score_base": base_score,
            "score_blended": blended,
        }
        decision["explain"] = exp
        decision["score_base"] = base_score
        decision["score_blended"] = blended
    except Exception:
        pass

    return decision
