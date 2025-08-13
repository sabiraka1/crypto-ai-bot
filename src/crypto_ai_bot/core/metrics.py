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

# ── Основные метрики ─────────────────────────────────────────────────────
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
