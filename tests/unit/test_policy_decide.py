# tests/unit/test_policy_decide.py
from __future__ import annotations

import types
from decimal import Decimal

import pytest

from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.signals import policy


class _DummyBroker:
    pass


def _patch_build_and_risk(monkeypatch, rule_score: float, ai_score: float, ok: bool = True):
    def fake_build(cfg, broker, *, symbol, timeframe, limit):
        return {
            "indicators": {"ema20": 1, "ema50": 1, "rsi": 50, "macd_hist": 0.0, "atr": 0.0, "atr_pct": 0.0},
            "market": {"price": Decimal("100")},
            "rule_score": rule_score,
            "ai_score": ai_score,
        }

    def fake_check(features, cfg):
        return (ok, "" if ok else "blocked")

    monkeypatch.setattr(policy, "_build", types.SimpleNamespace(build=fake_build))
    monkeypatch.setattr(policy, "risk_manager", types.SimpleNamespace(check=fake_check))

    # простая взвешенная сумма (независимо от внутренней реализации _fusion)
    def fake_fuse(r, a, cfg):
        rw, aw = cfg.get_weights()
        return max(0.0, min(1.0, rw * float(r or 0) + aw * float(a or 0)))

    monkeypatch.setattr(policy, "_fusion", types.SimpleNamespace(fuse=fake_fuse))


def test_profile_conservative_holds_when_score_below_buy(monkeypatch):
    cfg = Settings.build()
    cfg.DECISION_PROFILE = "conservative"  # buy >= 0.65
    _patch_build_and_risk(monkeypatch, rule_score=0.60, ai_score=0.60)
    dec = policy.decide(cfg, _DummyBroker(), symbol=cfg.SYMBOL, timeframe=cfg.TIMEFRAME, limit=cfg.LIMIT_BARS)
    assert dec["action"] == "hold"
    assert dec["explain"]["context"]["profile"] == "conservative"


def test_profile_aggressive_buys_on_medium_score(monkeypatch):
    cfg = Settings.build()
    cfg.DECISION_PROFILE = "aggressive"  # buy >= ~0.52
    _patch_build_and_risk(monkeypatch, rule_score=0.56, ai_score=0.56)
    dec = policy.decide(cfg, _DummyBroker(), symbol=cfg.SYMBOL, timeframe=cfg.TIMEFRAME, limit=cfg.LIMIT_BARS)
    assert dec["action"] == "buy"
    assert 0.52 <= dec["score"] <= 0.60


def test_sell_threshold_triggers_sell(monkeypatch):
    cfg = Settings.build()
    cfg.DECISION_PROFILE = "balanced"  # sell <= 0.45
    _patch_build_and_risk(monkeypatch, rule_score=0.40, ai_score=0.40)
    dec = policy.decide(cfg, _DummyBroker(), symbol=cfg.SYMBOL, timeframe=cfg.TIMEFRAME, limit=cfg.LIMIT_BARS)
    assert dec["action"] == "sell"


def test_manual_overrides_take_precedence(monkeypatch):
    cfg = Settings.build()
    cfg.DECISION_PROFILE = "balanced"
    # Переопределяем пороги вручную:
    cfg.DECISION_BUY_THRESHOLD = 0.60
    cfg.DECISION_SELL_THRESHOLD = 0.40
    # Перевешиваем на AI:
    cfg.DECISION_RULE_WEIGHT = 0.20
    cfg.DECISION_AI_WEIGHT = 0.80

    _patch_build_and_risk(monkeypatch, rule_score=0.55, ai_score=0.65)
    dec = policy.decide(cfg, _DummyBroker(), symbol=cfg.SYMBOL, timeframe=cfg.TIMEFRAME, limit=cfg.LIMIT_BARS)
    # С учётом весов итог > 0.60 → buy
    assert dec["action"] == "buy"
    wx = dec["explain"]["weights"]
    assert pytest.approx(wx["ai"] + wx["rule"], 0.001) == 1.0
