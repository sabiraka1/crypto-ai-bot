# src/crypto_ai_bot/core/metrics.py
from __future__ import annotations
import time

# ── Fallback: если prometheus_client нет, метрики — no-op ────────────────
try:
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore
    PROM_ENABLED = True
except Exception:
    PROM_ENABLED = False

    class _NoOp:
        def labels(self, *a, **k): return self
        def inc(self, *a, **k): pass
        def dec(self, *a, **k): pass
        def set(self, *a, **k): pass
        def observe(self, *a, **k): pass

    def Counter(*a, **k): return _NoOp()
    def Gauge(*a, **k): return _NoOp()
    def Histogram(*a, **k): return _NoOp()

# ── Основные счётчики цикла/сделок ────────────────────────────────────────
TRADING_LOOPS        = Counter("trading_loops_total", "Trading loop iterations")
SIGNALS_TOTAL        = Counter("signals_generated_total", "Signals generated")
ENTRY_ATTEMPTS       = Counter("entry_attempts_total", "Entry attempts")
POSITIONS_OPENED     = Counter("positions_opened_total", "Positions opened")
POSITIONS_CLOSED     = Counter("positions_closed_total", "Positions closed")

POSITIONS_OPEN_GAUGE = Gauge("positions_open", "Open positions")
LAST_SCORE           = Gauge("last_score_total", "Last total score (0..1)")
ATR_PCT              = Gauge("atr_pct", "ATR percent on primary timeframe")

FETCH_OHLCV_LATENCY  = Histogram(
    "fetch_ohlcv_seconds", "Duration of OHLCV fetch",
    buckets=(0.05, 0.1, 0.2, 0.5, 1, 2, 5)
)
DECISION_LATENCY     = Histogram(
    "decision_latency_seconds", "End-to-end decision latency",
    buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1, 2)
)

# ── Новые метрики: скор, контекст, флаги ──────────────────────────────────
RULE_SCORE             = Gauge("rule_score", "Raw rule score (0..1)")
RULE_SCORE_PENALIZED   = Gauge("rule_score_penalized", "Rule score after context penalties (0..1)")

BTC_DOMINANCE_PCT      = Gauge("btc_dominance_pct", "BTC dominance percent")
DXY_CHANGE_1D_PCT      = Gauge("dxy_change_1d_pct", "DXY 1-day change percent")
FEAR_GREED_INDEX       = Gauge("fear_greed_index", "Fear & Greed Index (0..100)")

CONTEXT_LAST_UPDATE_TS = Gauge("context_last_update_ts", "Context snapshot last update time (unix)")

# Лейбловая метрика-флаг: factor ∈ {btc_dominance, dxy_change_1d, fear_greed_overheated, fear_greed_undershoot}
CONTEXT_FLAG = Gauge("context_flag", "Context factor state (0/1)", ["factor"])

# Список «базовых» флагов, которые будем обнулять перед установкой активных
KNOWN_CONTEXT_FLAGS = (
    "btc_dominance",
    "dxy_change_1d",
    "fear_greed_overheated",
    "fear_greed_undershoot",
)

def reset_context_flags() -> None:
    """Сбрасывает все известные контекстные флаги в 0 (удобно перед обновлением)."""
    for name in KNOWN_CONTEXT_FLAGS:
        CONTEXT_FLAG.labels(factor=name).set(0)

def push_context_metrics(
    *,
    rule_score: float | None,
    rule_score_penalized: float | None,
    snapshot,       # ContextSnapshot | None
    penalties: dict | None,   # {"enabled": bool, "applied": [ {"factor": str, "value": x, "delta": y}, ... ]}
) -> None:
    """
    Обновляет все новые метрики /metrics по результатам агрегатора.
    Безопасно к None: если чего-то нет — ставим нейтральные значения.
    """
    try:
        # rule scores
        RULE_SCORE.set(float(rule_score) if rule_score is not None else 0.0)
        RULE_SCORE_PENALIZED.set(float(rule_score_penalized) if rule_score_penalized is not None else 0.0)

        # snapshot values
        if snapshot is not None:
            BTC_DOMINANCE_PCT.set(float(snapshot.btc_dominance) if snapshot.btc_dominance is not None else 0.0)
            DXY_CHANGE_1D_PCT.set(float(snapshot.dxy_change_1d) if snapshot.dxy_change_1d is not None else 0.0)
            FEAR_GREED_INDEX.set(float(snapshot.fear_greed) if snapshot.fear_greed is not None else 0.0)
            # timestamp
            try:
                ts = getattr(snapshot, "ts", None)
                CONTEXT_LAST_UPDATE_TS.set(float(ts.timestamp()) if ts else time.time())
            except Exception:
                CONTEXT_LAST_UPDATE_TS.set(time.time())
        else:
            # если снапшота нет — выставляем «нейтральные нули»
            BTC_DOMINANCE_PCT.set(0.0)
            DXY_CHANGE_1D_PCT.set(0.0)
            FEAR_GREED_INDEX.set(0.0)
            CONTEXT_LAST_UPDATE_TS.set(time.time())

        # flags
        reset_context_flags()
        if penalties and penalties.get("enabled"):
            for item in penalties.get("applied", []) or []:
                factor = str(item.get("factor", "")).strip() or "unknown"
                # ставим 1 только на активные факторы
                CONTEXT_FLAG.labels(factor=factor).set(1)

    except Exception:
        # метрики — best effort; не блокируем цикл
        pass
