from crypto_ai_bot.core.brokers.symbols import parse_symbol, to_canonical_symbol, to_ccxt_symbol, to_native_symbol, from_native_symbol, symbol_variants

def test_parse_and_canonical():
    cases = ["BTC/USDT", "btc_usdt", "BTC-USDT", "btcusdt", "btc:usdt"]
    for s in cases:
        assert parse_symbol(s) == ("BTC","USDT")
        assert to_canonical_symbol(s) == "BTC/USDT"
        assert to_ccxt_symbol(s) == "BTC/USDT"

def test_native_gateio():
    assert to_native_symbol("BTC/USDT", "gateio") == "BTC_USDT"
    assert from_native_symbol("BTC_USDT", "gateio") == "BTC/USDT"

def test_native_binance_like():
    assert to_native_symbol("ETH/USDC", "binance") == "ETHUSDC"
    assert from_native_symbol("ETHUSDC", "binance") == "ETH/USDC"

def test_variants():
    vs = set(symbol_variants("BTC/USDT"))
    assert "BTC/USDT" in vs and "BTC_USDT" in vs and "BTC-USDT" in vs and "BTCUSDT" in vs
