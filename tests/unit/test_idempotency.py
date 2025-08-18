# tests/test_idempotency.py
import sqlite3, time
from crypto_ai_bot.core.storage.repositories.idempotency import IdempotencyRepository

def test_check_and_store_atomic_and_cleanup():
    con = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    repo = IdempotencyRepository(con)
    key = "BTC/USDT:buy:123"

    # первое — ок
    assert repo.check_and_store(key, ttl_seconds=10) is True
    # повтор — дубликат
    assert repo.check_and_store(key, ttl_seconds=10) is False

    # протухание и очистка
    now_ms = int(time.time() * 1000)
    con.execute("UPDATE idempotency SET created_ms=?", (now_ms - 11_000,))
    removed = repo.cleanup_expired(ttl_seconds=10)
    assert removed >= 1

    # после очистки можно снова
    assert repo.check_and_store(key, ttl_seconds=10) is True
