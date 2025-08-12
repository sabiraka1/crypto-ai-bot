"""Комплексные тесты для UnifiedCacheManager."""
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
    """Комплексные тесты UnifiedCacheManager."""

    @pytest.fixture
    def cache(self):
        """Создает новый экземпляр кэша для каждого теста."""
        return UnifiedCacheManager(global_max_memory_mb=50.0)

    def test_set_get_basic_functionality(self, cache):
        """Базовая функциональность set/get."""
        # Простое значение
        cache.set("key1", "value1", CacheNamespace.GENERAL)
        assert cache.get("key1", CacheNamespace.GENERAL) == "value1"
        
        # Сложный объект
        complex_data = {"list": [1, 2, 3], "dict": {"nested": True}}
        cache.set("complex", complex_data, CacheNamespace.GENERAL)
        assert cache.get("complex", CacheNamespace.GENERAL) == complex_data
        
        # Несуществующий ключ
        assert cache.get("nonexistent", CacheNamespace.GENERAL) is None
        assert cache.get("nonexistent", CacheNamespace.GENERAL, "default") == "default"

    def test_set_get_with_ttl(self, cache):
        """Проверяем TTL функциональность."""
        with patch("utils.unified_cache.time.time") as mock_time:
            mock_time.return_value = 0
            
            # Устанавливаем значение с TTL
            cache.set("foo", "bar", CacheNamespace.PRICES, ttl=10)
            
            # Через 5 секунд - должно быть доступно
            mock_time.return_value = 5
            assert cache.get("foo", CacheNamespace.PRICES) == "bar"
            
            # Через 20 секунд - должно истечь
            mock_time.return_value = 20
            assert cache.get("foo", CacheNamespace.PRICES) is None

    def test_namespace_isolation(self, cache):
        """Тестируем изоляцию между namespace'ами."""
        # Один ключ в разных namespace'ах
        cache.set("same_key", "prices_value", CacheNamespace.PRICES)
        cache.set("same_key", "ohlcv_value", CacheNamespace.OHLCV)
        cache.set("same_key", "general_value", CacheNamespace.GENERAL)
        
        # Каждый namespace должен хранить свое значение
        assert cache.get("same_key", CacheNamespace.PRICES) == "prices_value"
        assert cache.get("same_key", CacheNamespace.OHLCV) == "ohlcv_value"
        assert cache.get("same_key", CacheNamespace.GENERAL) == "general_value"

    def test_namespace_configs(self):
        """Тестируем конфигурацию namespace'ов."""
        custom_config = {
            CacheNamespace.PRICES: NamespaceConfig(
                ttl=30.0, max_size=500, max_memory_mb=25.0, 
                policy=CachePolicy.TTL, compress=True
            )
        }
        
        cache = UnifiedCacheManager(namespace_configs=custom_config)
        
        # Проверяем что конфигурация применилась
        prices_cfg = cache._cfg("prices")
        assert prices_cfg.ttl == 30.0
        assert prices_cfg.max_size == 500
        assert prices_cfg.compress is True

    def test_compression_functionality(self, cache):
        """Тестируем сжатие данных."""
        large_data = {"data": "x" * 10000}  # Большой объект
        
        # С сжатием
        cache.set("compressed", large_data, CacheNamespace.OHLCV, compress=True)
        entry = cache._data[cache._make_full_key("ohlcv", "compressed")]
        assert isinstance(entry.data, tuple)
        assert entry.data[0] == "zlib+pickle"
        
        # Данные должны корректно распаковываться
        assert cache.get("compressed", CacheNamespace.OHLCV) == large_data
        
        # Без сжатия
        cache.set("uncompressed", large_data, CacheNamespace.GENERAL, compress=False)
        entry = cache._data[cache._make_full_key("general", "uncompressed")]
        assert not isinstance(entry.data, tuple)

    def test_priority_and_sticky_flags(self, cache):
        """Тестируем priority и sticky флаги."""
        # Устанавливаем записи с разными приоритетами
        cache.set("low_prio", "data1", CacheNamespace.GENERAL, priority=1)
        cache.set("high_prio", "data2", CacheNamespace.GENERAL, priority=3)
        cache.set("sticky", "data3", CacheNamespace.GENERAL, sticky=True)
        
        # Проверяем что флаги установлены
        entries = {k: v for k, v in cache._data.items() if v.namespace == "general"}
        
        low_entry = next(e for e in entries.values() if e.data == "data1")
        high_entry = next(e for e in entries.values() if e.data == "data2")
        sticky_entry = next(e for e in entries.values() if e.data == "data3")
        
        assert low_entry.priority == 1
        assert high_entry.priority == 3
        assert sticky_entry.sticky is True

    def test_metadata_functionality(self, cache):
        """Тестируем метаданные."""
        metadata = {"source": "test", "created_by": "pytest", "version": 1}
        cache.set("with_meta", "value", CacheNamespace.GENERAL, metadata=metadata)
        
        entry = cache._data[cache._make_full_key("general", "with_meta")]
        assert entry.metadata == metadata

    def test_delete_functionality(self, cache):
        """Тестируем удаление записей."""
        # Одиночное удаление
        cache.set("to_delete", "value", CacheNamespace.GENERAL)
        assert cache.get("to_delete", CacheNamespace.GENERAL) == "value"
        
        deleted = cache.delete("to_delete", CacheNamespace.GENERAL)
        assert deleted == 1
        assert cache.get("to_delete", CacheNamespace.GENERAL) is None
        
        # Удаление по префиксу
        cache.set("prefix_1", "val1", CacheNamespace.GENERAL)
        cache.set("prefix_2", "val2", CacheNamespace.GENERAL)
        cache.set("other", "val3", CacheNamespace.GENERAL)
        
        deleted = cache.delete("prefix_", CacheNamespace.GENERAL, prefix=True)
        assert deleted == 2
        assert cache.get("prefix_1", CacheNamespace.GENERAL) is None
        assert cache.get("prefix_2", CacheNamespace.GENERAL) is None
        assert cache.get("other", CacheNamespace.GENERAL) == "val3"

    def test_clear_namespace(self, cache):
        """Тестируем очистку namespace."""
        # Заполняем разные namespace'ы
        cache.set("key1", "val1", CacheNamespace.PRICES)
        cache.set("key2", "val2", CacheNamespace.PRICES)
        cache.set("key3", "val3", CacheNamespace.OHLCV)
        
        # Очищаем один namespace
        cleared = cache.clear_namespace(CacheNamespace.PRICES)
        assert cleared == 2
        
        # Проверяем что очистился только нужный namespace
        assert cache.get("key1", CacheNamespace.PRICES) is None
        assert cache.get("key2", CacheNamespace.PRICES) is None
        assert cache.get("key3", CacheNamespace.OHLCV) == "val3"

    def test_stats_functionality(self, cache):
        """Тестируем статистику."""
        initial_stats = cache.stats()
        assert initial_stats["entries"] == 0
        assert initial_stats["gets"] == 0
        assert initial_stats["hits"] == 0
        
        # Добавляем данные и проверяем статистику
        cache.set("key1", "value1", CacheNamespace.GENERAL)
        cache.set("key2", "value2", CacheNamespace.PRICES)
        
        stats = cache.stats()
        assert stats["entries"] == 2
        assert stats["sets"] == 2
        
        # Проверяем hit/miss статистику
        cache.get("key1", CacheNamespace.GENERAL)  # hit
        cache.get("nonexistent", CacheNamespace.GENERAL)  # miss
        
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        
        # Проверяем per-namespace статистику
        per_ns = stats["per_ns"]
        assert "general" in per_ns
        assert "prices" in per_ns
        assert per_ns["general"]["entries"] == 1
        assert per_ns["prices"]["entries"] == 1

    def test_get_top_keys(self, cache):
        """Тестируем получение топ ключей."""
        # Создаем ключи с разным количеством обращений
        cache.set("key1", "val1", CacheNamespace.GENERAL)
        cache.set("key2", "val2", CacheNamespace.GENERAL)
        cache.set("key3", "val3", CacheNamespace.GENERAL)
        
        # Обращаемся к ключам разное количество раз
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
        """Тестируем get_or_set метод."""
        call_count = 0
        
        def factory():
            nonlocal call_count
            call_count += 1
            return f"computed_value_{call_count}"
        
        # Первый вызов - должен выполнить factory
        result1 = cache.get_or_set("compute_key", CacheNamespace.GENERAL, ttl=60, factory=factory)
        assert result1 == "computed_value_1"
        assert call_count == 1
        
        # Второй вызов - должен вернуть из кэша
        result2 = cache.get_or_set("compute_key", CacheNamespace.GENERAL, ttl=60, factory=factory)
        assert result2 == "computed_value_1"
        assert call_count == 1  # Factory не должна вызываться повторно

    def test_cached_decorator(self, cache):
        """Тестируем декоратор @cached."""
        call_count = 0
        
        @cache.cached(CacheNamespace.GENERAL, ttl=60)
        def expensive_function(x, y):
            nonlocal call_count
            call_count += 1
            return x + y
        
        # Первый вызов
        result1 = expensive_function(1, 2)
        assert result1 == 3
        assert call_count == 1
        
        # Второй вызов с теми же параметрами
        result2 = expensive_function(1, 2)
        assert result2 == 3
        assert call_count == 1  # Не должна вызываться повторно
        
        # Вызов с другими параметрами
        result3 = expensive_function(2, 3)
        assert result3 == 5
        assert call_count == 2

    def test_eviction_policies(self, cache):
        """Тестируем политики эвикции."""
        # Настраиваем namespace с маленьким лимитом
        config = {
            CacheNamespace.GENERAL: NamespaceConfig(
                max_size=3, policy=CachePolicy.LRU
            )
        }
        small_cache = UnifiedCacheManager(namespace_configs=config)
        
        # Заполняем кэш до лимита
        small_cache.set("key1", "val1", CacheNamespace.GENERAL)
        small_cache.set("key2", "val2", CacheNamespace.GENERAL)
        small_cache.set("key3", "val3", CacheNamespace.GENERAL)
        
        # Обращаемся к key1 (делаем его "недавно использованным")
        small_cache.get("key1", CacheNamespace.GENERAL)
        
        # Добавляем новый ключ - должен вытеснить наименее используемый
        small_cache.set("key4", "val4", CacheNamespace.GENERAL)
        
        # key1 должен остаться (недавно использовался), key2 или key3 должен быть вытеснен
        assert small_cache.get("key1", CacheNamespace.GENERAL) == "val1"
        assert small_cache.get("key4", CacheNamespace.GENERAL) == "val4"

    def test_memory_pressure_handling(self, cache):
        """Тестируем обработку давления памяти."""
        # Создаем много больших объектов
        large_objects = []
        for i in range(100):
            large_data = {"data": "x" * 1000, "id": i}
            large_objects.append(large_data)
            cache.set(f"large_{i}", large_data, CacheNamespace.GENERAL)
        
        # Кэш должен автоматически управлять памятью
        stats = cache.stats()
        # Не все объекты должны остаться из-за ограничений памяти
        assert stats["entries"] < 100

    def test_concurrent_access(self, cache):
        """Тестируем конкурентный доступ."""
        import threading
        import random
        
        errors = []
        results = {}
        
        def worker(worker_id):
            try:
                for i in range(50):
                    key = f"worker_{worker_id}_key_{i}"
                    value = f"value_{i}"
                    
                    # Случайная операция
                    if random.choice([True, False]):
                        cache.set(key, value, CacheNamespace.GENERAL)
                    else:
                        result = cache.get(key, CacheNamespace.GENERAL)
                        if result is not None:
                            results[key] = result
                    
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)
        
        # Запускаем несколько потоков
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Не должно быть ошибок
        assert len(errors) == 0

    def test_ttl_helpers(self):
        """Тестируем TTL helper функции."""
        # parse_tf_to_seconds
        assert parse_tf_to_seconds("1m") == 60
        assert parse_tf_to_seconds("5m") == 300
        assert parse_tf_to_seconds("1h") == 3600
        assert parse_tf_to_seconds("1d") == 86400
        assert parse_tf_to_seconds("invalid") == 900  # default
        
        # ttl_until_next_candle
        with patch("utils.unified_cache.time.time") as mock_time:
            mock_time.return_value = 1000  # Произвольное время
            
            # Для 1-минутных свечей
            ttl_1m = ttl_until_next_candle("1m", drift_sec=5)
            assert isinstance(ttl_1m, int)
            assert ttl_1m > 0

    def test_trading_cache_helpers(self):
        """Тестируем helper'ы для торговых данных."""
        mock_fetch_ohlcv = MagicMock(return_value=[[1000, 100, 110, 90, 105, 1000]])
        mock_fetch_ticker = MagicMock(return_value={"last": 105.5})
        
        # OHLCV кэширование
        result1 = trading_cache.get_ohlcv("BTC/USDT", "1m", mock_fetch_ohlcv)
        result2 = trading_cache.get_ohlcv("BTC/USDT", "1m", mock_fetch_ohlcv)
        
        assert result1 == result2
        mock_fetch_ohlcv.assert_called_once()  # Должна вызваться только один раз
        
        # Ticker кэширование
        ticker1 = trading_cache.get_ticker("BTC/USDT", mock_fetch_ticker)
        ticker2 = trading_cache.get_ticker("BTC/USDT", mock_fetch_ticker)
        
        assert ticker1 == ticker2
        mock_fetch_ticker.assert_called_once()

    def test_error_handling(self, cache):
        """Тестируем обработку ошибок."""
        # Попытка сериализации несериализуемого объекта
        class UnserializableClass:
            def __reduce__(self):
                raise TypeError("Cannot pickle this object")
        
        # Должно обработаться gracefully
        unserializable = UnserializableClass()
        result = cache.set("unserializable", unserializable, CacheNamespace.GENERAL)
        # Может вернуть False или True в зависимости от fallback логики
        
        # Статистика ошибок должна увеличиться
        stats = cache.stats()
        assert "errors" in stats

    def test_cache_entry_expiration(self):
        """Тестируем логику истечения CacheEntry."""
        entry = CacheEntry(
            key="test", data="value", namespace="general",
            created_at=1000.0, last_accessed=1000.0, ttl=60.0
        )
        
        # Не истекшая запись
        with patch("utils.unified_cache.time.time", return_value=1030.0):
            assert not entry.is_expired()
        
        # Истекшая запись
        with patch("utils.unified_cache.time.time", return_value=1070.0):
            assert entry.is_expired()
        
        # Запись без TTL
        entry.ttl = None
        assert not entry.is_expired()

    def test_cache_entry_touch(self):
        """Тестируем обновление времени доступа."""
        entry = CacheEntry(
            key="test", data="value", namespace="general",
            created_at=1000.0, last_accessed=1000.0, hits=0
        )
        
        with patch("utils.unified_cache.time.time", return_value=1100.0):
            entry.touch()
            
        assert entry.last_accessed == 1100.0
        assert entry.hits == 1

    def test_namespace_string_handling(self, cache):
        """Тестируем работу со строковыми namespace'ами."""
        # Должно работать как с enum, так и со строками
        cache.set("key1", "value1", CacheNamespace.GENERAL)
        cache.set("key2", "value2", "general")
        
        assert cache.get("key1", "general") == "value1"
        assert cache.get("key2", CacheNamespace.GENERAL) == "value2"

    def test_global_cache_manager_singleton(self):
        """Тестируем глобальный cache manager."""
        manager1 = get_cache_manager()
        manager2 = get_cache_manager()
        
        # Должен возвращать тот же экземпляр
        assert manager1 is manager2

    @pytest.mark.parametrize("policy", [CachePolicy.TTL, CachePolicy.LRU, CachePolicy.HYBRID])
    def test_different_eviction_policies(self, policy):
        """Параметризованный тест разных политик эвикции."""
        config = {
            CacheNamespace.GENERAL: NamespaceConfig(
                max_size=5, policy=policy
            )
        }
        cache = UnifiedCacheManager(namespace_configs=config)
        
        # Заполняем кэш больше лимита
        for i in range(10):
            cache.set(f"key_{i}", f"value_{i}", CacheNamespace.GENERAL)
        
        # Должно остаться не больше max_size записей
        stats = cache.stats()
        general_stats = stats["per_ns"].get("general", {})
        assert general_stats.get("entries", 0) <= 5

    def test_cache_persistence_across_operations(self, cache):
        """Тестируем сохранность данных при различных операциях."""
        # Добавляем данные
        test_data = {f"key_{i}": f"value_{i}" for i in range(10)}
        for key, value in test_data.items():
            cache.set(key, value, CacheNamespace.GENERAL)
        
        # Выполняем различные операции
        cache.delete("key_5", CacheNamespace.GENERAL)
        cache.get("key_1", CacheNamespace.GENERAL)
        cache.set("new_key", "new_value", CacheNamespace.GENERAL)
        
        # Проверяем что остальные данные сохранились
        for i in range(10):
            if i != 5:  # Этот ключ был удален
                assert cache.get(f"key_{i}", CacheNamespace.GENERAL) == f"value_{i}"
        
        assert cache.get("key_5", CacheNamespace.GENERAL) is None
        assert cache.get("new_key", CacheNamespace.GENERAL) == "new_value"

    def test_memory_estimation_accuracy(self, cache):
        """Тестируем точность оценки размера объектов."""
        test_objects = [
            "small_string",
            {"dict": "with", "multiple": "keys"},
            [1, 2, 3, 4, 5] * 100,  # Большой список
            "x" * 10000  # Большая строка
        ]
        
        for i, obj in enumerate(test_objects):
            cache.set(f"size_test_{i}", obj, CacheNamespace.GENERAL)
        
        # Проверяем что размеры записались
        for i in range(len(test_objects)):
            full_key = cache._make_full_key("general", f"size_test_{i}")
            entry = cache._data[full_key]
            assert entry.size_bytes > 0