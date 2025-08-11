# utils/unified_cache.py - ЦЕНТРАЛИЗОВАННАЯ СИСТЕМА КЭШИРОВАНИЯ

import time
import threading
import hashlib
import pickle
import logging
import gc
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import OrderedDict
import psutil
import os

class CachePolicy(Enum):
    """Политики кэширования"""
    LRU = "lru"              # Least Recently Used
    TTL = "ttl"              # Time To Live
    SIZE_BASED = "size"      # По размеру
    HYBRID = "hybrid"        # Комбинированная

class CacheNamespace(Enum):
    """Namespace'ы для разделения типов данных"""
    OHLCV = "ohlcv"                    # Рыночные данные
    PRICES = "prices"                  # Последние цены  
    INDICATORS = "indicators"          # Технические индикаторы
    CSV_READS = "csv_reads"           # Чтение CSV файлов
    MARKET_INFO = "market_info"       # Информация о рынках
    ML_FEATURES = "ml_features"       # ML фичи
    RISK_METRICS = "risk_metrics"     # Метрики риска

@dataclass
class CacheEntry:
    """Запись в кэше"""
    key: str
    data: Any
    namespace: str
    created_at: float
    last_accessed: float
    access_count: int = 0
    size_bytes: int = 0
    ttl: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Проверка на истечение TTL"""
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl
    
    def touch(self):
        """Обновление времени доступа"""
        self.last_accessed = time.time()
        self.access_count += 1

@dataclass 
class NamespaceConfig:
    """Конфигурация namespace"""
    ttl: Optional[float] = None         # TTL в секундах
    max_size: int = 1000               # Максимум записей
    max_memory_mb: float = 100.0       # Максимум памяти в MB
    policy: CachePolicy = CachePolicy.HYBRID
    auto_cleanup: bool = True          # Автоочистка
    compress: bool = False             # Сжатие данных

class UnifiedCacheManager:
    """
    🔧 UNIFIED CACHE MANAGER - Централизованная система кэширования
    
    Заменяет все разрозненные кэши в проекте:
    - technical_indicators._indicator_cache
    - exchange_client.ExchangeCache  
    - csv_handler._read_cache
    
    Особенности:
    - Разделение по namespace для разных типов данных
    - Множественные политики кэширования (LRU, TTL, Size-based)
    - Автоматическое управление памятью
    - Централизованная статистика и мониторинг
    - Thread-safe операции
    - Memory pressure handling
    """
    
    def __init__(self, global_max_memory_mb: float = 500.0):
        self.global_max_memory_mb = global_max_memory_mb
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._stats = {
            "hits": 0,
            "misses": 0, 
            "evictions": 0,
            "memory_pressure_cleanups": 0,
            "total_sets": 0,
            "total_gets": 0
        }
        
        # Конфигурации namespace по умолчанию
        self._namespace_configs = {
            CacheNamespace.OHLCV: NamespaceConfig(
                ttl=60.0,           # 1 минута для рыночных данных
                max_size=200,       # Много символов * таймфреймы
                max_memory_mb=150.0,
                policy=CachePolicy.TTL,
                compress=True       # OHLCV данные большие
            ),
            CacheNamespace.PRICES: NamespaceConfig(
                ttl=10.0,           # 10 секунд для цен
                max_size=500,       # Много символов
                max_memory_mb=50.0,
                policy=CachePolicy.TTL
            ),
            CacheNamespace.INDICATORS: NamespaceConfig(
                ttl=120.0,          # 2 минуты для индикаторов
                max_size=300,
                max_memory_mb=100.0,
                policy=CachePolicy.HYBRID,
                compress=True
            ),
            CacheNamespace.CSV_READS: NamespaceConfig(
                ttl=30.0,           # 30 секунд для CSV
                max_size=50,        # Немного CSV файлов
                max_memory_mb=80.0,
                policy=CachePolicy.LRU
            ),
            CacheNamespace.MARKET_INFO: NamespaceConfig(
                ttl=3600.0,         # 1 час для market info
                max_size=100,
                max_memory_mb=20.0,
                policy=CachePolicy.TTL
            ),
            CacheNamespace.ML_FEATURES: NamespaceConfig(
                ttl=300.0,          # 5 минут для ML фичей
                max_size=100,
                max_memory_mb=50.0,
                policy=CachePolicy.LRU
            ),
            CacheNamespace.RISK_METRICS: NamespaceConfig(
                ttl=60.0,           # 1 минута для риск-метрик  
                max_size=100,
                max_memory_mb=30.0,
                policy=CachePolicy.TTL
            )
        }
        
        # Запуск фонового процесса очистки
        self._cleanup_thread = None
        self._running = True
        self._start_background_cleanup()
        
        logging.info("🔧 UnifiedCacheManager initialized with %.1f MB limit", global_max_memory_mb)

    # =========================================================================
    # ОСНОВНЫЕ ОПЕРАЦИИ
    # =========================================================================

    def get(self, key: str, namespace: Union[str, CacheNamespace], 
            default: Any = None) -> Any:
        """Получение значения из кэша"""
        with self._lock:
            self._stats["total_gets"] += 1
            
            cache_key = self._build_cache_key(key, namespace)
            
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                
                # Проверка на истечение TTL
                if entry.is_expired():
                    del self._cache[cache_key]
                    self._stats["misses"] += 1
                    logging.debug(f"🔧 Cache MISS (expired): {cache_key}")
                    return default
                
                # Обновляем статистику доступа
                entry.touch()
                self._stats["hits"] += 1
                
                logging.debug(f"🔧 Cache HIT: {cache_key} (access #{entry.access_count})")
                return entry.data
            else:
                self._stats["misses"] += 1
                logging.debug(f"🔧 Cache MISS: {cache_key}")
                return default

    def set(self, key: str, data: Any, namespace: Union[str, CacheNamespace],
            ttl: Optional[float] = None, metadata: Dict[str, Any] = None) -> bool:
        """Установка значения в кэш"""
        with self._lock:
            self._stats["total_sets"] += 1
            
            try:
                cache_key = self._build_cache_key(key, namespace)
                ns_str = namespace.value if isinstance(namespace, CacheNamespace) else str(namespace)
                config = self._get_namespace_config(namespace)
                
                # Вычисляем размер данных
                try:
                    if config.compress:
                        serialized = pickle.dumps(data)
                        size_bytes = len(serialized)
                    else:
                        size_bytes = self._estimate_size(data)
                except Exception:
                    size_bytes = 1024  # Fallback оценка
                
                # Проверка лимитов namespace
                if not self._check_namespace_limits(namespace, size_bytes):
                    logging.warning(f"🔧 Cache SET rejected: namespace limits exceeded for {cache_key}")
                    return False
                
                # Создание записи
                entry = CacheEntry(
                    key=cache_key,
                    data=data,
                    namespace=ns_str,
                    created_at=time.time(),
                    last_accessed=time.time(),
                    size_bytes=size_bytes,
                    ttl=ttl or config.ttl,
                    metadata=metadata or {}
                )
                
                # Проверка глобальных лимитов памяти
                if self._check_memory_pressure():
                    self._handle_memory_pressure()
                
                self._cache[cache_key] = entry
                logging.debug(f"🔧 Cache SET: {cache_key} ({size_bytes} bytes)")
                
                return True
                
            except Exception as e:
                logging.error(f"🔧 Cache SET failed for {key}: {e}")
                return False

    def delete(self, key: str, namespace: Union[str, CacheNamespace]) -> bool:
        """Удаление ключа из кэша"""
        with self._lock:
            cache_key = self._build_cache_key(key, namespace)
            
            if cache_key in self._cache:
                del self._cache[cache_key]
                logging.debug(f"🔧 Cache DELETE: {cache_key}")
                return True
            
            return False

    def clear_namespace(self, namespace: Union[str, CacheNamespace]):
        """Очистка всего namespace"""
        with self._lock:
            ns_str = namespace.value if isinstance(namespace, CacheNamespace) else str(namespace)
            
            keys_to_delete = [
                key for key, entry in self._cache.items() 
                if entry.namespace == ns_str
            ]
            
            for key in keys_to_delete:
                del self._cache[key]
            
            logging.info(f"🔧 Cache cleared namespace '{ns_str}': {len(keys_to_delete)} entries")

    def clear_all(self):
        """Полная очистка кэша"""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logging.info(f"🔧 Cache cleared completely: {count} entries")

    # =========================================================================
    # ДЕКОРАТОРЫ ДЛЯ АВТОМАТИЧЕСКОГО КЭШИРОВАНИЯ
    # =========================================================================

    def cached(self, namespace: Union[str, CacheNamespace], 
               ttl: Optional[float] = None,
               key_func: Optional[Callable] = None):
        """Декоратор для автоматического кэширования функций"""
        def decorator(func):
            def wrapper(*args, **kwargs):
                # Генерация ключа
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    cache_key = self._generate_function_key(func, args, kwargs)
                
                # Попытка получить из кэша
                result = self.get(cache_key, namespace)
                if result is not None:
                    return result
                
                # Выполнение функции и кэширование результата
                result = func(*args, **kwargs)
                self.set(cache_key, result, namespace, ttl)
                
                return result
            
            return wrapper
        return decorator

    def _generate_function_key(self, func, args, kwargs) -> str:
        """Генерация ключа для функции"""
        try:
            key_data = f"{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            return hashlib.md5(key_data.encode()).hexdigest()[:16]
        except Exception:
            return f"{func.__name__}:{time.time()}"

    # =========================================================================
    # СТАТИСТИКА И МОНИТОРИНГ
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики кэша"""
        with self._lock:
            total_requests = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total_requests * 100) if total_requests > 0 else 0
            
            # Статистика по namespace
            ns_stats = {}
            total_memory = 0
            
            for ns in CacheNamespace:
                entries = [e for e in self._cache.values() if e.namespace == ns.value]
                ns_memory = sum(e.size_bytes for e in entries) / (1024 * 1024)  # MB
                total_memory += ns_memory
                
                ns_stats[ns.value] = {
                    "entries": len(entries),
                    "memory_mb": round(ns_memory, 2),
                    "avg_access_count": round(sum(e.access_count for e in entries) / len(entries), 1) if entries else 0
                }
            
            return {
                "global": {
                    **self._stats,
                    "total_entries": len(self._cache),
                    "hit_rate_pct": round(hit_rate, 2),
                    "total_memory_mb": round(total_memory, 2),
                    "memory_limit_mb": self.global_max_memory_mb
                },
                "namespaces": ns_stats,
                "memory_pressure": self._check_memory_pressure()
            }

    def get_top_keys(self, namespace: Optional[Union[str, CacheNamespace]] = None, 
                     limit: int = 10) -> List[Dict[str, Any]]:
        """Топ ключей по количеству обращений"""
        with self._lock:
            entries = list(self._cache.values())
            
            if namespace:
                ns_str = namespace.value if isinstance(namespace, CacheNamespace) else str(namespace)
                entries = [e for e in entries if e.namespace == ns_str]
            
            entries.sort(key=lambda x: x.access_count, reverse=True)
            
            return [
                {
                    "key": e.key,
                    "namespace": e.namespace,
                    "access_count": e.access_count,
                    "size_mb": round(e.size_bytes / (1024 * 1024), 3),
                    "age_seconds": round(time.time() - e.created_at, 1)
                }
                for e in entries[:limit]
            ]

    # =========================================================================
    # УПРАВЛЕНИЕ ПАМЯТЬЮ
    # =========================================================================

    def _check_memory_pressure(self) -> bool:
        """Проверка нехватки памяти"""
        current_memory = sum(e.size_bytes for e in self._cache.values()) / (1024 * 1024)
        return current_memory > self.global_max_memory_mb * 0.8  # 80% порог

    def _handle_memory_pressure(self):
        """Обработка нехватки памяти"""
        self._stats["memory_pressure_cleanups"] += 1
        logging.warning("🔧 Memory pressure detected, starting cleanup")
        
        # Удаляем истекшие записи
        expired_count = self._cleanup_expired()
        
        # Если все еще нехватка - удаляем LRU записи
        if self._check_memory_pressure():
            lru_count = self._cleanup_lru(target_reduction=0.3)  # Удаляем 30%
            logging.info(f"🔧 Memory pressure cleanup: {expired_count} expired + {lru_count} LRU")

    def _cleanup_expired(self) -> int:
        """Очистка истекших записей"""
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]
        
        for key in expired_keys:
            del self._cache[key]
        
        return len(expired_keys)

    def _cleanup_lru(self, target_reduction: float = 0.2) -> int:
        """Очистка наименее используемых записей"""
        if not self._cache:
            return 0
        
        target_count = int(len(self._cache) * target_reduction)
        entries = list(self._cache.items())
        
        # Сортируем по времени последнего доступа
        entries.sort(key=lambda x: x[1].last_accessed)
        
        removed_count = 0
        for key, entry in entries[:target_count]:
            del self._cache[key]
            removed_count += 1
            self._stats["evictions"] += 1
        
        return removed_count

    # =========================================================================
    # УТИЛИТЫ
    # =========================================================================

    def _build_cache_key(self, key: str, namespace: Union[str, CacheNamespace]) -> str:
        """Построение полного ключа кэша"""
        ns_str = namespace.value if isinstance(namespace, CacheNamespace) else str(namespace)
        return f"{ns_str}:{key}"

    def _get_namespace_config(self, namespace: Union[str, CacheNamespace]) -> NamespaceConfig:
        """Получение конфигурации namespace"""
        if isinstance(namespace, CacheNamespace):
            return self._namespace_configs.get(namespace, NamespaceConfig())
        else:
            # Дефолтная конфигурация для строковых namespace
            return NamespaceConfig()

    def _check_namespace_limits(self, namespace: Union[str, CacheNamespace], 
                               new_size_bytes: int) -> bool:
        """Проверка лимитов namespace"""
        config = self._get_namespace_config(namespace)
        ns_str = namespace.value if isinstance(namespace, CacheNamespace) else str(namespace)
        
        # Считаем текущие метрики namespace
        ns_entries = [e for e in self._cache.values() if e.namespace == ns_str]
        current_count = len(ns_entries)
        current_memory_mb = sum(e.size_bytes for e in ns_entries) / (1024 * 1024)
        new_memory_mb = new_size_bytes / (1024 * 1024)
        
        # Проверяем лимиты
        if current_count >= config.max_size:
            return False
        if current_memory_mb + new_memory_mb > config.max_memory_mb:
            return False
        
        return True

    def _estimate_size(self, data: Any) -> int:
        """Оценка размера данных в байтах"""
        try:
            if hasattr(data, '__sizeof__'):
                return data.__sizeof__()
            else:
                return len(str(data)) * 2  # Примерная оценка
        except Exception:
            return 1024  # Fallback

    def _start_background_cleanup(self):
        """Запуск фонового процесса очистки"""
        def cleanup_worker():
            while self._running:
                try:
                    time.sleep(60)  # Каждую минуту
                    if not self._running:
                        break
                    
                    with self._lock:
                        expired_count = self._cleanup_expired()
                        if expired_count > 0:
                            logging.debug(f"🔧 Background cleanup: {expired_count} expired entries")
                        
                        # Проверка memory pressure
                        if self._check_memory_pressure():
                            self._handle_memory_pressure()
                            
                except Exception as e:
                    logging.error(f"🔧 Background cleanup error: {e}")
        
        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True, name="CacheCleanup")
        self._cleanup_thread.start()

    def shutdown(self):
        """Корректное завершение работы"""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
        logging.info("🔧 UnifiedCacheManager shutdown completed")

# =========================================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР И УТИЛИТЫ
# =========================================================================

# Глобальный экземпляр кэш-менеджера
_global_cache_manager: Optional[UnifiedCacheManager] = None

def get_cache_manager() -> UnifiedCacheManager:
    """Получение глобального экземпляра кэш-менеджера"""
    global _global_cache_manager
    if _global_cache_manager is None:
        memory_limit = float(os.getenv("CACHE_MEMORY_LIMIT_MB", "500"))
        _global_cache_manager = UnifiedCacheManager(global_max_memory_mb=memory_limit)
    return _global_cache_manager

def cached_function(namespace: Union[str, CacheNamespace], ttl: Optional[float] = None):
    """Удобный декоратор для кэширования функций"""
    return get_cache_manager().cached(namespace, ttl)

# Алиасы для удобства
cache = get_cache_manager()

# Экспорт
__all__ = [
    'UnifiedCacheManager',
    'CacheNamespace', 
    'CachePolicy',
    'CacheEntry',
    'NamespaceConfig',
    'get_cache_manager',
    'cached_function',
    'cache'
]