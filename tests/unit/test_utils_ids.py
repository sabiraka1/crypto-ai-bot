## `tests/unit/test_utils_ids.py`
from crypto_ai_bot.utils.ids import sanitize_ascii, short_hash, make_idempotency_key, make_client_order_id
def test_sanitize_ascii_basic():
    assert sanitize_ascii("BTC/USDT") == "btc-usdt"
    assert sanitize_ascii("Téxt with ÜTF-8!") == "txt-with-tf-8"
def test_short_hash_is_stable_and_len():
    h1 = short_hash("hello", 12)
    h2 = short_hash("hello", 12)
    assert h1 == h2 and len(h1) == 12
def test_make_idempotency_key_bucket():
    key = make_idempotency_key("BTC/USDT", "buy", 60_000, ts_ms=1_699_920_123_456)
    assert key.startswith("btc-usdt:buy:")
    bucket = int(key.split(":")[-1])
    assert bucket % 60_000 == 0
def test_make_client_order_id_ascii_and_limit():
    key = "btc-usdt:buy:1699920000000"
    client_oid = make_client_order_id("gateio", key, ts_ms=1699920000123)
    assert client_oid.startswith("t-")
    assert len(client_oid) <= 64
    assert client_oid == client_oid.encode("ascii").decode("ascii")