import pytest
from crypto_ai_bot.core.safety.instance_lock import InstanceLock

def test_instance_lock_basic(container):
    conn = container.storage.conn
    lock1 = InstanceLock(conn, name="bot")
    assert lock1.acquire(ttl_sec=2) is True

    # второй лок в том же процессе с другим объектом — не должен перебить до истечения ttl
    lock2 = InstanceLock(conn, name="bot")
    assert lock2.acquire(ttl_sec=2) is False

    # heartbeat продлевает
    lock1.heartbeat(ttl_sec=2)
    assert lock2.acquire(ttl_sec=2) is False

    # release освобождает
    lock1.release()
    assert lock2.acquire(ttl_sec=2) is True
