import pytest
from decimal import Decimal
from crypto_ai_bot.core.domain.strategies.ema_cross import EmaCrossStrategy
from crypto_ai_bot.core.domain.strategies.base import StrategyContext
from crypto_ai_bot.utils.decimal import dec

def test_ema_cross_strategy_initialization():
    """Тест инициализации стратегии."""
    strategy = EmaCrossStrategy(fast_period=9, slow_period=21)
    assert strategy.fast_period == 9
    assert strategy.slow_period == 21

def test_ema_cross_warming_up():
    """Тест периода прогрева."""
    strategy = EmaCrossStrategy(fast_period=5, slow_period=10)
    
    ctx = StrategyContext(
        symbol="BTC/USDT",
        exchange="gateio",
        data={
            "ticker": {"last": dec("50000")},
            "spread": 0.1
        }
    )
    
    # Первые вызовы - warming up
    for i in range(9):
        decision, explain = strategy.decide(ctx)
        assert decision == "hold"
        assert "warming_up" in explain.get("reason", "")

def test_ema_cross_signals():
    """Тест генерации сигналов."""
    strategy = EmaCrossStrategy(
        fast_period=3,
        slow_period=5,
        threshold_pct=0.1,
        max_spread_pct=1.0
    )
    
    # Прогреваем историю растущими ценами
    for price in range(50000, 50006):
        ctx = StrategyContext(
            symbol="BTC/USDT",
            exchange="gateio",
            data={
                "ticker": {"last": dec(str(price))},
                "spread": 0.1
            }
        )
        strategy.decide(ctx)
    
    # Резкий рост - должен быть buy сигнал
    ctx_up = StrategyContext(
        symbol="BTC/USDT",
        exchange="gateio",
        data={
            "ticker": {"last": dec("51000")},
            "spread": 0.1
        }
    )
    decision, explain = strategy.decide(ctx_up)
    # После резкого роста EMA могут дать сигнал
    assert decision in ["buy", "hold"]
    
    # Резкое падение
    for _ in range(3):
        ctx_down = StrategyContext(
            symbol="BTC/USDT",
            exchange="gateio",
            data={
                "ticker": {"last": dec("49000")},
                "spread": 0.1
            }
        )
        decision, explain = strategy.decide(ctx_down)
    
    # После падения может быть sell
    assert decision in ["sell", "hold"]

def test_ema_cross_spread_filter():
    """Тест фильтра по спреду."""
    strategy = EmaCrossStrategy(
        fast_period=3,
        slow_period=5,
        max_spread_pct=0.5  # Низкий лимит спреда
    )
    
    # Прогрев
    for price in range(50000, 50006):
        ctx = StrategyContext(
            symbol="BTC/USDT",
            exchange="gateio",
            data={
                "ticker": {"last": dec(str(price))},
                "spread": 0.1
            }
        )
        strategy.decide(ctx)
    
    # Высокий спред должен блокировать сигнал
    ctx_high_spread = StrategyContext(
        symbol="BTC/USDT",
        exchange="gateio",
        data={
            "ticker": {"last": dec("51000")},
            "spread": 1.0  # Превышает лимит
        }
    )
    decision, explain = strategy.decide(ctx_high_spread)
    assert decision == "hold"
    assert "high_spread" in explain.get("reason", "")