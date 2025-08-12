"""Тесты для ExchangeCacheCompat."""

import pytest
from unittest.mock import MagicMock, patch
from trading.exchange_client import ExchangeCacheCompat, CacheNamespace

class TestExchangeCacheCompat:
    """Тесты совместимости кэша биржи с unified cache"""
    
    @patch("trading.exchange_client.get_cache_manager")
    def test_set_and_get_use_unified_cache(self, mock_get_cache_manager):
        """Проверяем, что set/get используют единый кэш с нужным пространством имён"""
        mock_cache = MagicMock()
        mock_get_cache_manager.return_value = mock_cache
        
        ecc = ExchangeCacheCompat()
        
        # Тест set
        ecc.set("price:BTC", 1.23)
        mock_cache.set.assert_called_once()
        args, kwargs = mock_cache.set.call_args
        assert args[0] == "price:BTC"
        assert args[1] == 1.23
        assert args[2] == CacheNamespace.PRICES
        
        # Тест get
        mock_cache.get.return_value = 5
        result = ecc.get("somekey", ecc.price_ttl)
        mock_cache.get.assert_called_with("somekey", CacheNamespace.PRICES)
        assert result == 5

    @patch("trading.exchange_client.get_cache_manager")
    def test_clear_calls_all_namespaces(self, mock_get_cache_manager):
        """Проверяем, что очистка происходит для всех пространств имён"""
        mock_cache = MagicMock()
        mock_get_cache_manager.return_value = mock_cache
        
        ecc = ExchangeCacheCompat()
        ecc.clear()
        
        # Проверяем что все exchange namespace'ы очищены
        mock_cache.clear_namespace.assert_any_call(CacheNamespace.PRICES)
        mock_cache.clear_namespace.assert_any_call(CacheNamespace.OHLCV)
        mock_cache.clear_namespace.assert_any_call(CacheNamespace.MARKET_INFO)
        assert mock_cache.clear_namespace.call_count == 3

    @patch("trading.exchange_client.get_cache_manager")
    def test_key_prefix_to_namespace_mapping(self, mock_get_cache_manager):
        """Тест правильного маппинга префиксов ключей к namespace'ам"""
        mock_cache = MagicMock()
        mock_get_cache_manager.return_value = mock_cache
        
        ecc = ExchangeCacheCompat()
        
        # Тестируем разные префиксы
        test_cases = [
            ("price:BTC/USDT", CacheNamespace.PRICES),
            ("ohlcv:BTC/USDT:1h", CacheNamespace.OHLCV),
            ("market:BTC/USDT", CacheNamespace.MARKET_INFO),
            ("unknown_prefix:data", CacheNamespace.MARKET_INFO)  # fallback
        ]
        
        for key, expected_namespace in test_cases:
            ecc.set(key, "test_value")
        
        # Проверяем что каждый ключ попал в правильный namespace
        calls = mock_cache.set.call_args_list
        for i, (key, expected_namespace) in enumerate(test_cases):
            assert calls[i][0][2] == expected_namespace, f"Key {key} mapped to wrong namespace"

    @patch("trading.exchange_client.get_cache_manager")
    def test_ttl_to_namespace_mapping(self, mock_get_cache_manager):
        """Тест правильного маппинга TTL к namespace'ам"""
        mock_cache = MagicMock()
        mock_get_cache_manager.return_value = mock_cache
        
        ecc = ExchangeCacheCompat(price_ttl=10, ohlcv_ttl=60, market_ttl=3600)
        
        # Тестируем get с разными TTL
        test_cases = [
            (10, CacheNamespace.PRICES),
            (60, CacheNamespace.OHLCV),
            (3600, CacheNamespace.MARKET_INFO),
            (999, CacheNamespace.MARKET_INFO)  # unknown TTL → fallback
        ]
        
        for ttl, expected_namespace in test_cases:
            ecc.get("test_key", ttl)
        
        calls = mock_cache.get.call_args_list
        for i, (ttl, expected_namespace) in enumerate(test_cases):
            assert calls[i][0][1] == expected_namespace, f"TTL {ttl} mapped to wrong namespace"

    @patch("trading.exchange_client.get_cache_manager")
    def test_fallback_when_unified_cache_unavailable(self, mock_get_cache_manager):
        """Тест fallback режима при недоступности unified cache"""
        mock_get_cache_manager.return_value = None  # Unified cache недоступен
        
        ecc = ExchangeCacheCompat()
        
        # Операции должны работать без ошибок
        ecc.set("test_key", "test_value")  # Не должно падать
        result = ecc.get("test_key", 60)   # Должно вернуть None
        
        assert result is None

    @patch("trading.exchange_client.get_cache_manager")
    def test_statistics_with_unified_cache(self, mock_get_cache_manager):
        """Тест получения статистики из unified cache"""
        mock_cache = MagicMock()
        mock_get_cache_manager.return_value = mock_cache
        
        # Настраиваем мок статистики
        mock_cache.get_stats.return_value = {
            "global": {"hits": 100, "misses": 20},
            "namespaces": {
                "prices": {"entries": 50, "memory_mb": 1.5},
                "ohlcv": {"entries": 30, "memory_mb": 2.1}
            }
        }
        
        ecc = ExchangeCacheCompat()
        stats = ecc.get_stats()
        
        # Проверяем что статистика получена и обработана
        assert stats["unified_cache"] is True
        assert stats["hits"] == 100
        assert "namespaces" in stats

    @patch("trading.exchange_client.get_cache_manager")
    def test_cache_miss_and_hit(self, mock_get_cache_manager):
        """Тест правильной обработки cache hit/miss"""
        mock_cache = MagicMock()
        mock_get_cache_manager.return_value = mock_cache
        
        ecc = ExchangeCacheCompat()
        
        # Тест cache miss
        mock_cache.get.return_value = None
        result = ecc.get("missing_key", 60)
        assert result is None
        
        # Тест cache hit
        mock_cache.get.return_value = "cached_value"
        result = ecc.get("existing_key", 60)
        assert result == "cached_value"