# tests/test_symbols.py
from crypto_ai_bot.core.brokers.symbols import normalize_symbol, normalize_timeframe

def test_normalize_symbol_variants():
    assert normalize_symbol("BTCUSDT") == "BTC/USDT"
    assert normalize_symbol("btc/usdt") == "BTC/USDT"
    assert normalize_symbol("BTC_USDT") == "BTC/USDT"
    assert normalize_symbol("BTC-USDt") == "BTC/USDT"
    # деривативные суффиксы игнорируются
    assert normalize_symbol("BTC/USDT:USDT") == "BTC/USDT"

def test_normalize_timeframe():
    assert normalize_timeframe("1m") == "1m"
    assert normalize_timeframe("60s") in ("1m","1m")  # алиас
    assert normalize_timeframe("1H") == "1h"
    assert normalize_timeframe("24h") == "1d"
    assert normalize_timeframe(None) == "1h"
