import time
from crypto_ai_bot.core.infrastructure.cache import TTLCache

def test_ttlcache_put_get_and_expire():
    c = TTLCache(ttl_sec=0.02)
    c.put("k", 123)
    assert c.get("k") == 123
    time.sleep(0.03)
    assert c.get("k") is None  # истёк
