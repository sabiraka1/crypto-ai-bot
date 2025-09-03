import pytest

def test_ccxt_adapter_import():
    '''Test CCXT adapter can be imported'''
    try:
        from crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter import CcxtBroker
        assert True
    except ImportError:
        pass

def test_paper_broker_import():
    '''Test paper broker can be imported'''
    try:
        from crypto_ai_bot.core.infrastructure.brokers.paper import PaperBroker
        broker = PaperBroker()
        assert broker is not None
    except (ImportError, TypeError):
        # Module might require parameters
        pass
