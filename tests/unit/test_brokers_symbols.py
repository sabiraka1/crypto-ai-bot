## `tests/unit/test_brokers_symbols.py`
import pytest
from crypto_ai_bot.core.brokers.symbols import parse_symbol, to_exchange_symbol, from_exchange_symbol
from crypto_ai_bot.utils.exceptions import ValidationError
def test_parse_symbol_and_conversions():
    p = parse_symbol("btc/usdt")
    assert p.base == "BTC" and p.quote == "USDT"
    ex = to_exchange_symbol("gateio", "BTC/USDT")
    assert ex == "BTC_USDT"
    back = from_exchange_symbol("gateio", ex)
    assert back == "BTC/USDT"
def test_invalid_exchange_symbol():
    with pytest.raises(ValidationError):
        from_exchange_symbol("gateio", "BTCUSDT")