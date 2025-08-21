import pytest

from crypto_ai_bot.core.brokers.symbols import (
    parse_symbol,
    to_exchange_symbol,
    from_exchange_symbol,
)

def test_parse_symbol_variants():
    assert parse_symbol("BTC/USDT") == ("BTC", "USDT")
    assert parse_symbol("btc_usdt") == ("BTC", "USDT")
    assert parse_symbol("btc-usdt") == ("BTC", "USDT")

def test_to_exchange_symbol_gateio():
    assert to_exchange_symbol("gateio", "BTC/USDT") == "BTC_USDT"

def test_from_exchange_symbol_gateio():
    assert from_exchange_symbol("gateio", "BTC_USDT") == "BTC/USDT"

def test_unknown_exchange_passthrough_std():
    # для неизвестной биржи остаётся STD-вид
    assert to_exchange_symbol("unknown", "BTC/USDT") == "BTC/USDT"
    assert from_exchange_symbol("unknown", "BTC-USDT") == "BTC/USDT"
