import re
import time

from crypto_ai_bot.utils.ids import (
    make_idempotency_key,
    make_correlation_id,
    make_client_order_id,
)

def test_make_idempotency_key_is_deterministic_in_bucket():
    now = int(time.time() * 1000)
    k1 = make_idempotency_key("BTC/USDT", "BUY", 60_000, now_ms=now, amount=0.001)
    k2 = make_idempotency_key("btc_usdt", "buy", 60_000, now_ms=now + 30_000, amount=0.001)
    assert k1 == k2  # один и тот же bucket → один и тот же ключ

def test_make_idempotency_key_changes_between_buckets():
    now = int(time.time() * 1000)
    k1 = make_idempotency_key("BTC/USDT", "BUY", 60_000, now_ms=now, amount=0.001)
    k2 = make_idempotency_key("BTC/USDT", "BUY", 60_000, now_ms=now + 61_000, amount=0.001)
    assert k1 != k2

def test_make_correlation_id_is_uuid_like():
    cid = make_correlation_id()
    assert re.fullmatch(r"[0-9a-fA-F\-]{36}", cid) is not None

def test_make_client_order_id_gateio_prefix_and_length():
    key = "very-long-key-with-юбка-and-spaces" * 3
    cid = make_client_order_id("gateio", key, max_len=28)
    assert cid.startswith("t-")
    assert len(cid) <= 28
    # только ASCII-символы
    assert re.fullmatch(r"[A-Za-z0-9._\-]+", cid) is not None

def test_make_client_order_id_stable_truncation():
    key = "x" * 200
    cid1 = make_client_order_id("gateio", key, max_len=28)
    cid2 = make_client_order_id("gateio", key, max_len=28)
    assert cid1 == cid2  # усечение + хэш → детерминированно
