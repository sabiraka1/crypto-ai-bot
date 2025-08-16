# tests/unit/test_policy_decide.py
from __future__ import annotations
from types import SimpleNamespace

import pytest

from crypto_ai_bot.core.signals import policy


class DummyBroker:
    pass


class Cfg(SimpleNamespace):
    MODE: str = "paper"
    SYMBOL: str = "BTC/USDT"
    TIMEFRAME: str = "1h"
    FEATURE_LIMIT: int = 300
    DECISION_RULE_WEIGHT: float = 0.7
    DECISION_AI_WEIGHT: float = 0.3
    SCORE_BUY_MIN: float = 0.6
    SCORE_SELL_MIN: float = 0.4
    SL_ATR_MULT: float = 1.5
    TP_ATR_MULT: float = 2.5


def test_decide_buy_with_heuristics(monkeypatch):
    # подменяем _build.build → возвращаем стабильные features
    def fake_build(cfg, broker, *, symbol, timeframe, limit):
        return {
            "indicators": {
                "ema_fast": 101.0,
                "ema_slow": 100.0,
                "rsi": 50.0,
                "macd_hist": 0.5,
                "atr_pct": 1.0,
            },
            "market": {"price": 100.0},
            "rule_score": None,  # заставим policy рассчитать _heuristic_rule_score
            "ai_score": None,
        }

    # risk_manager.check → ок
    def ok_check(features, cfg):
        return True, "ok"

    monkeypatch.setattr("crypto_ai_bot.core.signals._build.build", fake_build)
    monkeypatch.setattr("crypto_ai_bot.core.risk.manager.check", ok_check)

    dec = policy.decide(Cfg(), DummyBroker(), symbol="BTC/USDT", timeframe="1h", limit=300)
    assert dec["action"] == "buy"
    assert float(dec["score"]) >= 0.6
    assert dec["explain"]["signals"]["atr_pct"] == 1.0
    assert dec["explain"]["blocks"]["risk_ok"] is True
    assert "weights" in dec["explain"] and "thresholds" in dec["explain"]


def test_decide_blocked_by_risk(monkeypatch):
    def fake_build(cfg, broker, *, symbol, timeframe, limit):
        return {
            "indicators": {
                "ema_fast": 101.0,
                "ema_slow": 100.0,
                "rsi": 50.0,
                "macd_hist": 0.5,
                "atr_pct": 1.0,
            },
            "market": {"price": 100.0},
            "rule_score": 0.9,
            "ai_score": 0.9,
        }

    def blocked_check(features, cfg):
        return False, "time_drift_ms=5000>limit=1500"

    monkeypatch.setattr("crypto_ai_bot.core.signals._build.build", fake_build)
    monkeypatch.setattr("crypto_ai_bot.core.risk.manager.check", blocked_check)

    dec = policy.decide(Cfg(), DummyBroker(), symbol="BTC/USDT", timeframe="1h", limit=300)
    assert dec["action"] == "hold"
    assert dec["explain"]["blocks"]["risk_ok"] is False
