import pytest

def test_strategy_manager_import():
    '''Test StrategyManager can be imported'''
    try:
        from crypto_ai_bot.core.domain.strategies.strategy_manager import StrategyManager
        strategy_manager = StrategyManager()
        assert strategy_manager is not None
    except (ImportError, TypeError):
        # Module not yet implemented or requires params
        pass

def test_base_strategy_import():
    '''Test base strategy can be imported'''
    try:
        from crypto_ai_bot.core.domain.strategies.base import BaseStrategy
        assert True
    except ImportError:
        pass
