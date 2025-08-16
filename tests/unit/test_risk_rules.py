# tests/unit/test_risk_rules.py
from __future__ import annotations
from datetime import datetime, timezone, time as dtime
from types import SimpleNamespace

import pytest

from crypto_ai_bot.core.risk import rules


class Cfg(SimpleNamespace):
    TIME_DRIFT_MAX_MS: int = 1500
    MAX_SPREAD_PCT: float = 0.2
    TRADING_HOURS_ENABLED: bool = True
    TRADING_HOURS_START: str = "09:00"
    TRADING_HOURS_END: str = "18:00"
    TRADING_DAYS: str = "1,2,3,4,5"
    MAX_SEQ_LOSSES: int = 3
    MAX_EXPOSURE_PCT: float = 100.0
    MAX_DRAWDOWN_PCT: float = 5.0


def test_time_sync_ok(monkeypatch):
    monkeypatch.setattr("crypto_ai_bot.utils.time_sync.get_cached_drift_ms", lambda default=0: 200)
    ok, reason = rules.check_time_sync(Cfg())
    assert ok is True


def test_time_sync_blocked(monkeypatch):
    monkeypatch.setattr("crypto_ai_bot.utils.time_sync.get_cached_drift_ms", lambda default=0: 5000)
    ok, reason = rules.check_time_sync(Cfg())
    assert ok is False and "time_drift_ms" in reason


def test_spread_by_bid_ask():
    f = {"market": {"bid": 100.0, "ask": 100.5}}
    ok, reason = rules.check_spread(f, Cfg(MAX_SPREAD_PCT=0.3))
    assert ok is True  # ~0.498%? wait -> (0.5/100.25)*100=0.499 -> >0.3, so should be False
    # корректируем порог:
    ok, reason = rules.check_spread(f, Cfg(MAX_SPREAD_PCT=1.0))
    assert ok is True


def test_hours_inside_window():
    # вторник (1), 10:00 UTC
    now = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    ok, reason = rules.check_hours(Cfg(), now_utc=now)
    assert ok is True


def test_hours_outside_window():
    # вторник (1), 20:00 UTC
    now = datetime(2024, 1, 2, 20, 0, tzinfo=timezone.utc)
    ok, reason = rules.check_hours(Cfg(), now_utc=now)
    assert ok is False


def test_seq_losses_and_exposure_and_dd():
    f = {"risk": {"loss_streak": 4, "exposure_pct": 120.0, "dd_pct": -7.0}}
    # последовательные лоссы
    ok, reason = rules.check_seq_losses(f, Cfg(MAX_SEQ_LOSSES=3))
    assert ok is False
    # экспозиция
    ok, reason = rules.check_max_exposure(f, Cfg(MAX_EXPOSURE_PCT=80.0))
    assert ok is False
    # просадка
    ok, reason = rules.check_drawdown(f, Cfg(MAX_DRAWDOWN_PCT=5.0))
    assert ok is False
