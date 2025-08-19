import sqlite3
import time
from crypto_ai_bot.core.storage.repositories import idempotency as idem_repo_module

SqliteIdempotencyRepository = idem_repo_module.SqliteIdempotencyRepository

def test_check_and_store_and_get():
    """Тест: сохранение нового ключа идемпотентности и получение его записи."""
    con = sqlite3.connect(":memory:")
    repo = SqliteIdempotencyRepository(con)
    key = "order:BTC-USDT:buy:1000000000000"  # корректный формат ключа
    result = repo.check_and_store(key, ttl_seconds=300)
    assert result is True  # первый вызов успешен
    rec = repo.get(key)
    assert rec is not None
    # rec: (key, created_ms, committed, state)
    assert rec[0] == key
    assert rec[2] == 0  # некоммитнуто
    assert rec[3] == "claimed"

def test_check_and_store_duplicate_and_expiry():
    """Тест: повторный вызов возвращает False для свежего ключа и True после истечения TTL."""
    con = sqlite3.connect(":memory:")
    repo = SqliteIdempotencyRepository(con)
    key = "order:ETH-USDT:sell:1000000000000"
    assert repo.check_and_store(key, ttl_seconds=1) is True
    # Повтор до TTL -> False (дубликат)
    assert repo.check_and_store(key, ttl_seconds=1) is False
    # Ист artificially: выставляем старый created_ms для эмуляции истечения TTL
    cur = con.execute("SELECT created_ms FROM idempotency WHERE key=?", (key,))
    created_ms = cur.fetchone()[0]
    expired_ms = created_ms - 2000  # на 2 секунды старше
    con.execute("UPDATE idempotency SET created_ms=? WHERE key=?", (expired_ms, key))
    # Теперь повторный check_and_store должен вернуть True (ключ просрочен и перезаписан)
    assert repo.check_and_store(key, ttl_seconds=1) is True

def test_commit_changes_status():
    """Тест: commit помечает ключ как выполненный, повторный check_and_store возвращает False."""
    con = sqlite3.connect(":memory:")
    repo = SqliteIdempotencyRepository(con)
    key = "order:BTC-USDT:buy:2000000000000"
    assert repo.check_and_store(key, ttl_seconds=5) is True
    # Коммитим ключ
    repo.commit(key)
    rec = repo.get(key)
    assert rec is not None
    assert rec[2] == 1  # committed = 1
    assert rec[3] == "committed"
    # Повторный вызов (ключ уже зафиксирован) -> False
    assert repo.check_and_store(key, ttl_seconds=5) is False

def test_cleanup_expired():
    """Тест: удаление просроченных некоммитнутых записей."""
    con = sqlite3.connect(":memory:")
    repo = SqliteIdempotencyRepository(con)
    # key1: устаревшая некоммитнутая запись
    key1 = "order:BTC-USDT:buy:3000000000000"
    assert repo.check_and_store(key1, ttl_seconds=1) is True
    con.execute("UPDATE idempotency SET created_ms=? WHERE key=?", (int(time.time()*1000) - 5000, key1))
    # key2: свежая некоммитнутая запись
    key2 = "order:ETH-USDT:buy:3000000000000"
    assert repo.check_and_store(key2, ttl_seconds=5) is True
    # key3: коммитнутая запись
    key3 = "order:XRP-USDT:buy:3000000000000"
    assert repo.check_and_store(key3, ttl_seconds=5) is True
    repo.commit(key3)
    # Чистим с TTL=1с (должен удалиться только key1)
    removed = repo.cleanup_expired(ttl_seconds=1)
    assert removed >= 1
    # key1 удален, key2 и key3 остаются
    assert repo.get(key1) is None
    assert repo.get(key2) is not None
    assert repo.get(key3) is not None
