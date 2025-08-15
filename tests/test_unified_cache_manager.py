"""РљРѕРјРїР»РµРєСЃРЅС‹Рµ С‚РµСЃС‚С‹ РґР»СЏ UnifiedCacheManager."""
import time
import threading
import pickle
import zlib
from unittest.mock import patch, MagicMock
import pytest

from utils.unified_cache import (
    UnifiedCacheManager, CacheNamespace, CachePolicy, 
    NamespaceConfig, CacheEntry, get_cache_manager,
    ttl_until_next_candle, parse_tf_to_seconds, trading_cache
)


class TestUnifiedCacheManager:
    """РљРѕРјРїР»РµРєСЃРЅС‹Рµ С‚РµСЃС‚С‹ UnifiedCacheManager."""

    @pytest.fixture
    def cache(self):
        """РЎРѕР·РґР°РµС‚ РЅРѕРІС‹Р№ СЌРєР·РµРјРїР»СЏСЂ РєСЌС€Р° РґР»СЏ РєР°Р¶РґРѕРіРѕ С‚РµСЃС‚Р°."""
        return UnifiedCacheManager(global_max_memory_mb=50.0)

    def test_set_get_basic_functionality(self, cache):
        """Р‘Р°Р·РѕРІР°СЏ С„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅРѕСЃС‚СЊ set/get."""
        # РџСЂРѕСЃС‚РѕРµ Р·РЅР°С‡РµРЅРёРµ
        cache.set("key1", "value1", CacheNamespace.GENERAL)
        assert cache.get("key1", CacheNamespace.GENERAL) == "value1"
        
        # РЎР»РѕР¶РЅС‹Р№ РѕР±СЉРµРєС‚
        complex_data = {"list": [1, 2, 3], "dict": {"nested": True}}
        cache.set("complex", complex_data, CacheNamespace.GENERAL)
        assert cache.get("complex", CacheNamespace.GENERAL) == complex_data
        
        # РќРµСЃСѓС‰РµСЃС‚РІСѓСЋС‰РёР№ РєР»СЋС‡
        assert cache.get("nonexistent", CacheNamespace.GENERAL) is None
        assert cache.get("nonexistent", CacheNamespace.GENERAL, "default") == "default"

    def test_set_get_with_ttl(self, cache):
        """РџСЂРѕРІРµСЂСЏРµРј TTL С„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅРѕСЃС‚СЊ."""
        with patch("utils.unified_cache.time.time") as mock_time:
            mock_time.return_value = 0
            
            # РЈСЃС‚Р°РЅР°РІР»РёРІР°РµРј Р·РЅР°С‡РµРЅРёРµ СЃ TTL
            cache.set("foo", "bar", CacheNamespace.PRICES, ttl=10)
            
            # Р§РµСЂРµР· 5 СЃРµРєСѓРЅРґ - РґРѕР»Р¶РЅРѕ Р±С‹С‚СЊ РґРѕСЃС‚СѓРїРЅРѕ
            mock_time.return_value = 5
            assert cache.get("foo", CacheNamespace.PRICES) == "bar"
            
            # Р§РµСЂРµР· 20 СЃРµРєСѓРЅРґ - РґРѕР»Р¶РЅРѕ РёСЃС‚РµС‡СЊ
            mock_time.return_value = 20
            assert cache.get("foo", CacheNamespace.PRICES) is None

    def test_namespace_isolation(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј РёР·РѕР»СЏС†РёСЋ РјРµР¶РґСѓ namespace'Р°РјРё."""
        # РћРґРёРЅ РєР»СЋС‡ РІ СЂР°Р·РЅС‹С… namespace'Р°С…
        cache.set("same_key", "prices_value", CacheNamespace.PRICES)
        cache.set("same_key", "ohlcv_value", CacheNamespace.OHLCV)
        cache.set("same_key", "general_value", CacheNamespace.GENERAL)
        
        # РљР°Р¶РґС‹Р№ namespace РґРѕР»Р¶РµРЅ С…СЂР°РЅРёС‚СЊ СЃРІРѕРµ Р·РЅР°С‡РµРЅРёРµ
        assert cache.get("same_key", CacheNamespace.PRICES) == "prices_value"
        assert cache.get("same_key", CacheNamespace.OHLCV) == "ohlcv_value"
        assert cache.get("same_key", CacheNamespace.GENERAL) == "general_value"

    def test_namespace_configs(self):
        """РўРµСЃС‚РёСЂСѓРµРј РєРѕРЅС„РёРіСѓСЂР°С†РёСЋ namespace'РѕРІ."""
        custom_config = {
            CacheNamespace.PRICES: NamespaceConfig(
                ttl=30.0, max_size=500, max_memory_mb=25.0, 
                policy=CachePolicy.TTL, compress=True
            )
        }
        
        cache = UnifiedCacheManager(namespace_configs=custom_config)
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РєРѕРЅС„РёРіСѓСЂР°С†РёСЏ РїСЂРёРјРµРЅРёР»Р°СЃСЊ
        prices_cfg = cache._cfg("prices")
        assert prices_cfg.ttl == 30.0
        assert prices_cfg.max_size == 500
        assert prices_cfg.compress is True

    def test_compression_functionality(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј СЃР¶Р°С‚РёРµ РґР°РЅРЅС‹С…."""
        large_data = {"data": "x" * 10000}  # Р‘РѕР»СЊС€РѕР№ РѕР±СЉРµРєС‚
        
        # РЎ СЃР¶Р°С‚РёРµРј
        cache.set("compressed", large_data, CacheNamespace.OHLCV, compress=True)
        entry = cache._data[cache._make_full_key("ohlcv", "compressed")]
        assert isinstance(entry.data, tuple)
        assert entry.data[0] == "zlib+pickle"
        
        # Р”Р°РЅРЅС‹Рµ РґРѕР»Р¶РЅС‹ РєРѕСЂСЂРµРєС‚РЅРѕ СЂР°СЃРїР°РєРѕРІС‹РІР°С‚СЊСЃСЏ
        assert cache.get("compressed", CacheNamespace.OHLCV) == large_data
        
        # Р‘РµР· СЃР¶Р°С‚РёСЏ
        cache.set("uncompressed", large_data, CacheNamespace.GENERAL, compress=False)
        entry = cache._data[cache._make_full_key("general", "uncompressed")]
        assert not isinstance(entry.data, tuple)

    def test_priority_and_sticky_flags(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј priority Рё sticky С„Р»Р°РіРё."""
        # РЈСЃС‚Р°РЅР°РІР»РёРІР°РµРј Р·Р°РїРёСЃРё СЃ СЂР°Р·РЅС‹РјРё РїСЂРёРѕСЂРёС‚РµС‚Р°РјРё
        cache.set("low_prio", "data1", CacheNamespace.GENERAL, priority=1)
        cache.set("high_prio", "data2", CacheNamespace.GENERAL, priority=3)
        cache.set("sticky", "data3", CacheNamespace.GENERAL, sticky=True)
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ С„Р»Р°РіРё СѓСЃС‚Р°РЅРѕРІР»РµРЅС‹
        entries = {k: v for k, v in cache._data.items() if v.namespace == "general"}
        
        low_entry = next(e for e in entries.values() if e.data == "data1")
        high_entry = next(e for e in entries.values() if e.data == "data2")
        sticky_entry = next(e for e in entries.values() if e.data == "data3")
        
        assert low_entry.priority == 1
        assert high_entry.priority == 3
        assert sticky_entry.sticky is True

    def test_metadata_functionality(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј РјРµС‚Р°РґР°РЅРЅС‹Рµ."""
        metadata = {"source": "test", "created_by": "pytest", "version": 1}
        cache.set("with_meta", "value", CacheNamespace.GENERAL, metadata=metadata)
        
        entry = cache._data[cache._make_full_key("general", "with_meta")]
        assert entry.metadata == metadata

    def test_delete_functionality(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј СѓРґР°Р»РµРЅРёРµ Р·Р°РїРёСЃРµР№."""
        # РћРґРёРЅРѕС‡РЅРѕРµ СѓРґР°Р»РµРЅРёРµ
        cache.set("to_delete", "value", CacheNamespace.GENERAL)
        assert cache.get("to_delete", CacheNamespace.GENERAL) == "value"
        
        deleted = cache.delete("to_delete", CacheNamespace.GENERAL)
        assert deleted == 1
        assert cache.get("to_delete", CacheNamespace.GENERAL) is None
        
        # РЈРґР°Р»РµРЅРёРµ РїРѕ РїСЂРµС„РёРєСЃСѓ
        cache.set("prefix_1", "val1", CacheNamespace.GENERAL)
        cache.set("prefix_2", "val2", CacheNamespace.GENERAL)
        cache.set("other", "val3", CacheNamespace.GENERAL)
        
        deleted = cache.delete("prefix_", CacheNamespace.GENERAL, prefix=True)
        assert deleted == 2
        assert cache.get("prefix_1", CacheNamespace.GENERAL) is None
        assert cache.get("prefix_2", CacheNamespace.GENERAL) is None
        assert cache.get("other", CacheNamespace.GENERAL) == "val3"

    def test_clear_namespace(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј РѕС‡РёСЃС‚РєСѓ namespace."""
        # Р—Р°РїРѕР»РЅСЏРµРј СЂР°Р·РЅС‹Рµ namespace'С‹
        cache.set("key1", "val1", CacheNamespace.PRICES)
        cache.set("key2", "val2", CacheNamespace.PRICES)
        cache.set("key3", "val3", CacheNamespace.OHLCV)
        
        # РћС‡РёС‰Р°РµРј РѕРґРёРЅ namespace
        cleared = cache.clear_namespace(CacheNamespace.PRICES)
        assert cleared == 2
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РѕС‡РёСЃС‚РёР»СЃСЏ С‚РѕР»СЊРєРѕ РЅСѓР¶РЅС‹Р№ namespace
        assert cache.get("key1", CacheNamespace.PRICES) is None
        assert cache.get("key2", CacheNamespace.PRICES) is None
        assert cache.get("key3", CacheNamespace.OHLCV) == "val3"

    def test_stats_functionality(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј СЃС‚Р°С‚РёСЃС‚РёРєСѓ."""
        initial_stats = cache.stats()
        assert initial_stats["entries"] == 0
        assert initial_stats["gets"] == 0
        assert initial_stats["hits"] == 0
        
        # Р”РѕР±Р°РІР»СЏРµРј РґР°РЅРЅС‹Рµ Рё РїСЂРѕРІРµСЂСЏРµРј СЃС‚Р°С‚РёСЃС‚РёРєСѓ
        cache.set("key1", "value1", CacheNamespace.GENERAL)
        cache.set("key2", "value2", CacheNamespace.PRICES)
        
        stats = cache.stats()
        assert stats["entries"] == 2
        assert stats["sets"] == 2
        
        # РџСЂРѕРІРµСЂСЏРµРј hit/miss СЃС‚Р°С‚РёСЃС‚РёРєСѓ
        cache.get("key1", CacheNamespace.GENERAL)  # hit
        cache.get("nonexistent", CacheNamespace.GENERAL)  # miss
        
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        
        # РџСЂРѕРІРµСЂСЏРµРј per-namespace СЃС‚Р°С‚РёСЃС‚РёРєСѓ
        per_ns = stats["per_ns"]
        assert "general" in per_ns
        assert "prices" in per_ns
        assert per_ns["general"]["entries"] == 1
        assert per_ns["prices"]["entries"] == 1

    def test_get_top_keys(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј РїРѕР»СѓС‡РµРЅРёРµ С‚РѕРї РєР»СЋС‡РµР№."""
        # РЎРѕР·РґР°РµРј РєР»СЋС‡Рё СЃ СЂР°Р·РЅС‹Рј РєРѕР»РёС‡РµСЃС‚РІРѕРј РѕР±СЂР°С‰РµРЅРёР№
        cache.set("key1", "val1", CacheNamespace.GENERAL)
        cache.set("key2", "val2", CacheNamespace.GENERAL)
        cache.set("key3", "val3", CacheNamespace.GENERAL)
        
        # РћР±СЂР°С‰Р°РµРјСЃСЏ Рє РєР»СЋС‡Р°Рј СЂР°Р·РЅРѕРµ РєРѕР»РёС‡РµСЃС‚РІРѕ СЂР°Р·
        for _ in range(5):
            cache.get("key1", CacheNamespace.GENERAL)
        for _ in range(3):
            cache.get("key2", CacheNamespace.GENERAL)
        cache.get("key3", CacheNamespace.GENERAL)
        
        top_keys = cache.get_top_keys(CacheNamespace.GENERAL, limit=3)
        assert len(top_keys) == 3
        assert top_keys[0]["key"] == "key1"
        assert top_keys[0]["hits"] == 5
        assert top_keys[1]["key"] == "key2"
        assert top_keys[1]["hits"] == 3

    def test_get_or_set_functionality(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј get_or_set РјРµС‚РѕРґ."""
        call_count = 0
        
        def factory():
            nonlocal call_count
            call_count += 1
            return f"computed_value_{call_count}"
        
        # РџРµСЂРІС‹Р№ РІС‹Р·РѕРІ - РґРѕР»Р¶РµРЅ РІС‹РїРѕР»РЅРёС‚СЊ factory
        result1 = cache.get_or_set("compute_key", CacheNamespace.GENERAL, ttl=60, factory=factory)
        assert result1 == "computed_value_1"
        assert call_count == 1
        
        # Р’С‚РѕСЂРѕР№ РІС‹Р·РѕРІ - РґРѕР»Р¶РµРЅ РІРµСЂРЅСѓС‚СЊ РёР· РєСЌС€Р°
        result2 = cache.get_or_set("compute_key", CacheNamespace.GENERAL, ttl=60, factory=factory)
        assert result2 == "computed_value_1"
        assert call_count == 1  # Factory РЅРµ РґРѕР»Р¶РЅР° РІС‹Р·С‹РІР°С‚СЊСЃСЏ РїРѕРІС‚РѕСЂРЅРѕ

    def test_cached_decorator(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј РґРµРєРѕСЂР°С‚РѕСЂ @cached."""
        call_count = 0
        
        @cache.cached(CacheNamespace.GENERAL, ttl=60)
        def expensive_function(x, y):
            nonlocal call_count
            call_count += 1
            return x + y
        
        # РџРµСЂРІС‹Р№ РІС‹Р·РѕРІ
        result1 = expensive_function(1, 2)
        assert result1 == 3
        assert call_count == 1
        
        # Р’С‚РѕСЂРѕР№ РІС‹Р·РѕРІ СЃ С‚РµРјРё Р¶Рµ РїР°СЂР°РјРµС‚СЂР°РјРё
        result2 = expensive_function(1, 2)
        assert result2 == 3
        assert call_count == 1  # РќРµ РґРѕР»Р¶РЅР° РІС‹Р·С‹РІР°С‚СЊСЃСЏ РїРѕРІС‚РѕСЂРЅРѕ
        
        # Р’С‹Р·РѕРІ СЃ РґСЂСѓРіРёРјРё РїР°СЂР°РјРµС‚СЂР°РјРё
        result3 = expensive_function(2, 3)
        assert result3 == 5
        assert call_count == 2

    def test_eviction_policies(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј РїРѕР»РёС‚РёРєРё СЌРІРёРєС†РёРё."""
        # РќР°СЃС‚СЂР°РёРІР°РµРј namespace СЃ РјР°Р»РµРЅСЊРєРёРј Р»РёРјРёС‚РѕРј
        config = {
            CacheNamespace.GENERAL: NamespaceConfig(
                max_size=3, policy=CachePolicy.LRU
            )
        }
        small_cache = UnifiedCacheManager(namespace_configs=config)
        
        # Р—Р°РїРѕР»РЅСЏРµРј РєСЌС€ РґРѕ Р»РёРјРёС‚Р°
        small_cache.set("key1", "val1", CacheNamespace.GENERAL)
        small_cache.set("key2", "val2", CacheNamespace.GENERAL)
        small_cache.set("key3", "val3", CacheNamespace.GENERAL)
        
        # РћР±СЂР°С‰Р°РµРјСЃСЏ Рє key1 (РґРµР»Р°РµРј РµРіРѕ "РЅРµРґР°РІРЅРѕ РёСЃРїРѕР»СЊР·РѕРІР°РЅРЅС‹Рј")
        small_cache.get("key1", CacheNamespace.GENERAL)
        
        # Р”РѕР±Р°РІР»СЏРµРј РЅРѕРІС‹Р№ РєР»СЋС‡ - РґРѕР»Р¶РµРЅ РІС‹С‚РµСЃРЅРёС‚СЊ РЅР°РёРјРµРЅРµРµ РёСЃРїРѕР»СЊР·СѓРµРјС‹Р№
        small_cache.set("key4", "val4", CacheNamespace.GENERAL)
        
        # key1 РґРѕР»Р¶РµРЅ РѕСЃС‚Р°С‚СЊСЃСЏ (РЅРµРґР°РІРЅРѕ РёСЃРїРѕР»СЊР·РѕРІР°Р»СЃСЏ), key2 РёР»Рё key3 РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РІС‹С‚РµСЃРЅРµРЅ
        assert small_cache.get("key1", CacheNamespace.GENERAL) == "val1"
        assert small_cache.get("key4", CacheNamespace.GENERAL) == "val4"

    def test_memory_pressure_handling(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј РѕР±СЂР°Р±РѕС‚РєСѓ РґР°РІР»РµРЅРёСЏ РїР°РјСЏС‚Рё."""
        # РЎРѕР·РґР°РµРј РјРЅРѕРіРѕ Р±РѕР»СЊС€РёС… РѕР±СЉРµРєС‚РѕРІ
        large_objects = []
        for i in range(100):
            large_data = {"data": "x" * 1000, "id": i}
            large_objects.append(large_data)
            cache.set(f"large_{i}", large_data, CacheNamespace.GENERAL)
        
        # РљСЌС€ РґРѕР»Р¶РµРЅ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё СѓРїСЂР°РІР»СЏС‚СЊ РїР°РјСЏС‚СЊСЋ
        stats = cache.stats()
        # РќРµ РІСЃРµ РѕР±СЉРµРєС‚С‹ РґРѕР»Р¶РЅС‹ РѕСЃС‚Р°С‚СЊСЃСЏ РёР·-Р·Р° РѕРіСЂР°РЅРёС‡РµРЅРёР№ РїР°РјСЏС‚Рё
        assert stats["entries"] < 100

    def test_concurrent_access(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј РєРѕРЅРєСѓСЂРµРЅС‚РЅС‹Р№ РґРѕСЃС‚СѓРї."""
        import threading
        import random
        
        errors = []
        results = {}
        
        def worker(worker_id):
            try:
                for i in range(50):
                    key = f"worker_{worker_id}_key_{i}"
                    value = f"value_{i}"
                    
                    # РЎР»СѓС‡Р°Р№РЅР°СЏ РѕРїРµСЂР°С†РёСЏ
                    if random.choice([True, False]):
                        cache.set(key, value, CacheNamespace.GENERAL)
                    else:
                        result = cache.get(key, CacheNamespace.GENERAL)
                        if result is not None:
                            results[key] = result
                    
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)
        
        # Р—Р°РїСѓСЃРєР°РµРј РЅРµСЃРєРѕР»СЊРєРѕ РїРѕС‚РѕРєРѕРІ
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # РќРµ РґРѕР»Р¶РЅРѕ Р±С‹С‚СЊ РѕС€РёР±РѕРє
        assert len(errors) == 0

    def test_ttl_helpers(self):
        """РўРµСЃС‚РёСЂСѓРµРј TTL helper С„СѓРЅРєС†РёРё."""
        # parse_tf_to_seconds
        assert parse_tf_to_seconds("1m") == 60
        assert parse_tf_to_seconds("5m") == 300
        assert parse_tf_to_seconds("1h") == 3600
        assert parse_tf_to_seconds("1d") == 86400
        assert parse_tf_to_seconds("invalid") == 900  # default
        
        # ttl_until_next_candle
        with patch("utils.unified_cache.time.time") as mock_time:
            mock_time.return_value = 1000  # РџСЂРѕРёР·РІРѕР»СЊРЅРѕРµ РІСЂРµРјСЏ
            
            # Р”Р»СЏ 1-РјРёРЅСѓС‚РЅС‹С… СЃРІРµС‡РµР№
            ttl_1m = ttl_until_next_candle("1m", drift_sec=5)
            assert isinstance(ttl_1m, int)
            assert ttl_1m > 0

    def test_trading_cache_helpers(self):
        """РўРµСЃС‚РёСЂСѓРµРј helper'С‹ РґР»СЏ С‚РѕСЂРіРѕРІС‹С… РґР°РЅРЅС‹С…."""
        mock_fetch_ohlcv = MagicMock(return_value=[[1000, 100, 110, 90, 105, 1000]])
        mock_fetch_ticker = MagicMock(return_value={"last": 105.5})
        
        # OHLCV РєСЌС€РёСЂРѕРІР°РЅРёРµ
        result1 = trading_cache.get_ohlcv("BTC/USDT", "1m", mock_fetch_ohlcv)
        result2 = trading_cache.get_ohlcv("BTC/USDT", "1m", mock_fetch_ohlcv)
        
        assert result1 == result2
        mock_fetch_ohlcv.assert_called_once()  # Р”РѕР»Р¶РЅР° РІС‹Р·РІР°С‚СЊСЃСЏ С‚РѕР»СЊРєРѕ РѕРґРёРЅ СЂР°Р·
        
        # Ticker РєСЌС€РёСЂРѕРІР°РЅРёРµ
        ticker1 = trading_cache.get_ticker("BTC/USDT", mock_fetch_ticker)
        ticker2 = trading_cache.get_ticker("BTC/USDT", mock_fetch_ticker)
        
        assert ticker1 == ticker2
        mock_fetch_ticker.assert_called_once()

    def test_error_handling(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј РѕР±СЂР°Р±РѕС‚РєСѓ РѕС€РёР±РѕРє."""
        # РџРѕРїС‹С‚РєР° СЃРµСЂРёР°Р»РёР·Р°С†РёРё РЅРµСЃРµСЂРёР°Р»РёР·СѓРµРјРѕРіРѕ РѕР±СЉРµРєС‚Р°
        class UnserializableClass:
            def __reduce__(self):
                raise TypeError("Cannot pickle this object")
        
        # Р”РѕР»Р¶РЅРѕ РѕР±СЂР°Р±РѕС‚Р°С‚СЊСЃСЏ gracefully
        unserializable = UnserializableClass()
        result = cache.set("unserializable", unserializable, CacheNamespace.GENERAL)
        # РњРѕР¶РµС‚ РІРµСЂРЅСѓС‚СЊ False РёР»Рё True РІ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё РѕС‚ fallback Р»РѕРіРёРєРё
        
        # РЎС‚Р°С‚РёСЃС‚РёРєР° РѕС€РёР±РѕРє РґРѕР»Р¶РЅР° СѓРІРµР»РёС‡РёС‚СЊСЃСЏ
        stats = cache.stats()
        assert "errors" in stats

    def test_cache_entry_expiration(self):
        """РўРµСЃС‚РёСЂСѓРµРј Р»РѕРіРёРєСѓ РёСЃС‚РµС‡РµРЅРёСЏ CacheEntry."""
        entry = CacheEntry(
            key="test", data="value", namespace="general",
            created_at=1000.0, last_accessed=1000.0, ttl=60.0
        )
        
        # РќРµ РёСЃС‚РµРєС€Р°СЏ Р·Р°РїРёСЃСЊ
        with patch("utils.unified_cache.time.time", return_value=1030.0):
            assert not entry.is_expired()
        
        # РСЃС‚РµРєС€Р°СЏ Р·Р°РїРёСЃСЊ
        with patch("utils.unified_cache.time.time", return_value=1070.0):
            assert entry.is_expired()
        
        # Р—Р°РїРёСЃСЊ Р±РµР· TTL
        entry.ttl = None
        assert not entry.is_expired()

    def test_cache_entry_touch(self):
        """РўРµСЃС‚РёСЂСѓРµРј РѕР±РЅРѕРІР»РµРЅРёРµ РІСЂРµРјРµРЅРё РґРѕСЃС‚СѓРїР°."""
        entry = CacheEntry(
            key="test", data="value", namespace="general",
            created_at=1000.0, last_accessed=1000.0, hits=0
        )
        
        with patch("utils.unified_cache.time.time", return_value=1100.0):
            entry.touch()
            
        assert entry.last_accessed == 1100.0
        assert entry.hits == 1

    def test_namespace_string_handling(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј СЂР°Р±РѕС‚Сѓ СЃРѕ СЃС‚СЂРѕРєРѕРІС‹РјРё namespace'Р°РјРё."""
        # Р”РѕР»Р¶РЅРѕ СЂР°Р±РѕС‚Р°С‚СЊ РєР°Рє СЃ enum, С‚Р°Рє Рё СЃРѕ СЃС‚СЂРѕРєР°РјРё
        cache.set("key1", "value1", CacheNamespace.GENERAL)
        cache.set("key2", "value2", "general")
        
        assert cache.get("key1", "general") == "value1"
        assert cache.get("key2", CacheNamespace.GENERAL) == "value2"

    def test_global_cache_manager_singleton(self):
        """РўРµСЃС‚РёСЂСѓРµРј РіР»РѕР±Р°Р»СЊРЅС‹Р№ cache manager."""
        manager1 = get_cache_manager()
        manager2 = get_cache_manager()
        
        # Р”РѕР»Р¶РµРЅ РІРѕР·РІСЂР°С‰Р°С‚СЊ С‚РѕС‚ Р¶Рµ СЌРєР·РµРјРїР»СЏСЂ
        assert manager1 is manager2

    @pytest.mark.parametrize("policy", [CachePolicy.TTL, CachePolicy.LRU, CachePolicy.HYBRID])
    def test_different_eviction_policies(self, policy):
        """РџР°СЂР°РјРµС‚СЂРёР·РѕРІР°РЅРЅС‹Р№ С‚РµСЃС‚ СЂР°Р·РЅС‹С… РїРѕР»РёС‚РёРє СЌРІРёРєС†РёРё."""
        config = {
            CacheNamespace.GENERAL: NamespaceConfig(
                max_size=5, policy=policy
            )
        }
        cache = UnifiedCacheManager(namespace_configs=config)
        
        # Р—Р°РїРѕР»РЅСЏРµРј РєСЌС€ Р±РѕР»СЊС€Рµ Р»РёРјРёС‚Р°
        for i in range(10):
            cache.set(f"key_{i}", f"value_{i}", CacheNamespace.GENERAL)
        
        # Р”РѕР»Р¶РЅРѕ РѕСЃС‚Р°С‚СЊСЃСЏ РЅРµ Р±РѕР»СЊС€Рµ max_size Р·Р°РїРёСЃРµР№
        stats = cache.stats()
        general_stats = stats["per_ns"].get("general", {})
        assert general_stats.get("entries", 0) <= 5

    def test_cache_persistence_across_operations(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј СЃРѕС…СЂР°РЅРЅРѕСЃС‚СЊ РґР°РЅРЅС‹С… РїСЂРё СЂР°Р·Р»РёС‡РЅС‹С… РѕРїРµСЂР°С†РёСЏС…."""
        # Р”РѕР±Р°РІР»СЏРµРј РґР°РЅРЅС‹Рµ
        test_data = {f"key_{i}": f"value_{i}" for i in range(10)}
        for key, value in test_data.items():
            cache.set(key, value, CacheNamespace.GENERAL)
        
        # Р’С‹РїРѕР»РЅСЏРµРј СЂР°Р·Р»РёС‡РЅС‹Рµ РѕРїРµСЂР°С†РёРё
        cache.delete("key_5", CacheNamespace.GENERAL)
        cache.get("key_1", CacheNamespace.GENERAL)
        cache.set("new_key", "new_value", CacheNamespace.GENERAL)
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РѕСЃС‚Р°Р»СЊРЅС‹Рµ РґР°РЅРЅС‹Рµ СЃРѕС…СЂР°РЅРёР»РёСЃСЊ
        for i in range(10):
            if i != 5:  # Р­С‚РѕС‚ РєР»СЋС‡ Р±С‹Р» СѓРґР°Р»РµРЅ
                assert cache.get(f"key_{i}", CacheNamespace.GENERAL) == f"value_{i}"
        
        assert cache.get("key_5", CacheNamespace.GENERAL) is None
        assert cache.get("new_key", CacheNamespace.GENERAL) == "new_value"

    def test_memory_estimation_accuracy(self, cache):
        """РўРµСЃС‚РёСЂСѓРµРј С‚РѕС‡РЅРѕСЃС‚СЊ РѕС†РµРЅРєРё СЂР°Р·РјРµСЂР° РѕР±СЉРµРєС‚РѕРІ."""
        test_objects = [
            "small_string",
            {"dict": "with", "multiple": "keys"},
            [1, 2, 3, 4, 5] * 100,  # Р‘РѕР»СЊС€РѕР№ СЃРїРёСЃРѕРє
            "x" * 10000  # Р‘РѕР»СЊС€Р°СЏ СЃС‚СЂРѕРєР°
        ]
        
        for i, obj in enumerate(test_objects):
            cache.set(f"size_test_{i}", obj, CacheNamespace.GENERAL)
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ СЂР°Р·РјРµСЂС‹ Р·Р°РїРёСЃР°Р»РёСЃСЊ
        for i in range(len(test_objects)):
            full_key = cache._make_full_key("general", f"size_test_{i}")
            entry = cache._data[full_key]
            assert entry.size_bytes > 0







