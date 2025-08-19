from types import SimpleNamespace
import pytest
from crypto_ai_bot.core.use_cases.evaluate import evaluate_and_maybe_execute

class DummyLimiter:
    def __init__(self, allow=True):
        self.allow = allow
        self.called = 0
    def try_acquire(self, token):
        self.called += 1
        return self.allow

def make_settings(**kwargs):
    """Создает объект настроек с заданными атрибутами."""
    defaults = {"SYMBOL": "BTC/USDT"}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)

def test_hold_action_no_execution(monkeypatch):
    """Тест: при действии 'hold' торговый цикл завершается без исполнения ордера."""
    settings = make_settings()
    # Переопределяем build_features и decide_policy для возврата hold-действия
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate.build_features",
                        lambda sym, **kwargs: {"features": {}, "context": {"now_ms": 1234567890}})
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate.decide_policy",
                        lambda features, context: {"action": "hold", "score": 0.0})
    result = evaluate_and_maybe_execute(
        cfg=settings,
        broker=None,
        trades_repo=None,
        positions_repo=None,
        exits_repo=None,
        idempotency_repo=None,
        limiter=None,
        risk_manager=None
    )
    assert result.get("note") == "hold"
    assert "executed" not in result

def test_risk_blocked(monkeypatch):
    """Тест: если RiskManager блокирует торговлю, возвращается 'risk_blocked', а ордер не исполняется."""
    settings = make_settings()
    risk_manager = lambda **kwargs: {"allow": False, "reason": "test_block"}
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate.build_features",
                        lambda sym, **kwargs: {"features": {}, "context": {"now_ms": 0}})
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate.decide_policy",
                        lambda features, context: {"action": "buy", "score": 1.0})
    place_order_called = {"called": False}
    def dummy_place_order(**kwargs):
        place_order_called["called"] = True
        return {"accepted": True}
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate", "place_order", dummy_place_order)
    result = evaluate_and_maybe_execute(
        cfg=settings,
        broker=None,
        trades_repo=None,
        positions_repo=None,
        exits_repo=None,
        idempotency_repo=None,
        limiter=None,
        risk_manager=risk_manager
    )
    assert result.get("note") == "risk_blocked"
    assert result.get("executed", {}).get("error") == "risk_blocked"
    assert place_order_called["called"] is False

def test_rate_limited_no_execution(monkeypatch):
    """Тест: при срабатывании лимитера скорость выполнения не выполняется и возвращается 'rate_limited'."""
    settings = make_settings()
    limiter = DummyLimiter(allow=False)
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate.build_features",
                        lambda sym, **kwargs: {"features": {}, "context": {"now_ms": 0}})
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate.decide_policy",
                        lambda features, context: {"action": "buy", "score": 0.5})
    called_flag = {"called": False}
    def dummy_place_order(**kwargs):
        called_flag["called"] = True
        return {"accepted": True}
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate", "place_order", dummy_place_order)
    result = evaluate_and_maybe_execute(
        cfg=settings,
        broker=None,
        trades_repo=None,
        positions_repo=None,
        exits_repo=None,
        idempotency_repo=None,
        limiter=limiter,
        risk_manager=None
    )
    assert result.get("note") == "rate_limited"
    assert result.get("executed", {}).get("error") == "rate_limited"
    assert called_flag["called"] is False
    assert limiter.called == 1

def test_successful_execution(monkeypatch):
    """Тест: полный цикл при разрешенном сигнале и успешном размещении ордера."""
    settings = make_settings()
    limiter = DummyLimiter(allow=True)
    risk_manager = lambda **kwargs: {"allow": True}
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate.build_features",
                        lambda sym, **kwargs: {"features": {}, "context": {"now_ms": 0}})
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate.decide_policy",
                        lambda features, context: {"action": "sell", "score": 0.8})
    dummy_order_result = {"accepted": True, "executed_price": 123.45, "executed_qty": 0.1, "idempotency_key": "ABC123"}
    monkeypatch.setattr("crypto_ai_bot.core.use_cases.evaluate", "place_order", lambda **kwargs: dummy_order_result)
    result = evaluate_and_maybe_execute(
        cfg=settings,
        broker=None,
        trades_repo=None,
        positions_repo=None,
        exits_repo=None,
        idempotency_repo=None,
        limiter=limiter,
        risk_manager=risk_manager
    )
    assert result.get("executed") == dummy_order_result
    # Не ожидается примечаний о блокировке
    assert result.get("note") is None or result.get("note") not in ("risk_blocked", "rate_limited")
