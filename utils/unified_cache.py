# utils/unified_cache.py — УНИФИЦИРОВАННЫЙ КЭШ
# ВАЖНО: публичный API сохранён (get/set/cached) + get_or_set, TTL-хелперы.

from __future__ import annotations
import time, threading, pickle, zlib, sys, os
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable, Tuple, List
from enum import Enum

try:
    import psutil  # для мониторинга реального RSS (опционально)
except Exception:  # pragma: no cover
    psutil = None

# ────────────────────────────────────────────────────────────────────────────
class CachePolicy(Enum):
    TTL = "ttl"
    LRU = "lru"
    HYBRID = "hybrid"  # TTL + LRU (сначала TTL, затем LRU)

class CacheNamespace(Enum):
    OHLCV = "ohlcv"              # свечи
    PRICES = "prices"            # последние цены
    INDICATORS = "indicators"    # индикаторы
    CSV_READS = "csv_reads"      # чтение CSV
    MARKET_INFO = "market_info"  # инфо рынка/тикеры
    ML_FEATURES = "ml_features"  # фичи/индикаторы
    ORDER_STATUS = "order_status"
    TELEGRAM = "telegram"
    CHARTS = "charts"
    GENERAL = "general"

@dataclass
class CacheEntry:
    key: str
    data: Any                   # либо объект, либо ("zlib+pickle", bytes)
    namespace: str
    created_at: float
    last_accessed: float
    hits: int = 0
    size_bytes: int = 0
    ttl: Optional[float] = None
    priority: int = 1           # 1..3 (3 — важнее)
    sticky: bool = False        # нельзя выселять при давлении
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return (time.time() - self.created_at) > self.ttl

    def touch(self) -> None:
        self.last_accessed = time.time()
        self.hits += 1

@dataclass
class NamespaceConfig:
    ttl: Optional[float] = None               # TTL по умолчанию (сек)
    max_size: int = 1000                      # лимит записей в ns
    max_memory_mb: float = 100.0              # лимит памяти для ns
    policy: CachePolicy = CachePolicy.HYBRID  # политика внутри ns
    auto_cleanup: bool = True
    compress: bool = False                    # хранить в сжатом виде

# ────────────────────────────────────────────────────────────────────────────
class UnifiedCacheManager:
    def __init__(self,
                 namespace_configs: Optional[Dict[CacheNamespace, NamespaceConfig]] = None,
                 global_max_memory_mb: float = 512.0) -> None:
        self._lock = threading.RLock()
        self._data: Dict[str, CacheEntry] = {}
        self._ns_cfg: Dict[str, NamespaceConfig] = {}
        self.global_max_memory_mb = float(global_max_memory_mb)
        self._stats = {
            "gets": 0, "hits": 0, "misses": 0,
            "sets": 0, "evictions": 0, "expired": 0, "errors": 0
        }
        default_cfg = {
            CacheNamespace.OHLCV: NamespaceConfig(ttl=60.0, max_size=2000, max_memory_mb=128.0, policy=CachePolicy.LRU, compress=True),
            CacheNamespace.PRICES: NamespaceConfig(ttl=5.0, max_size=10000, max_memory_mb=50.0, policy=CachePolicy.TTL),
            CacheNamespace.INDICATORS: NamespaceConfig(ttl=120.0, max_size=2000, max_memory_mb=100.0, policy=CachePolicy.LRU, compress=False),
            CacheNamespace.CSV_READS: NamespaceConfig(ttl=30.0, max_size=5000, max_memory_mb=80.0, policy=CachePolicy.TTL, compress=False),
            CacheNamespace.MARKET_INFO: NamespaceConfig(ttl=3600.0, max_size=100, max_memory_mb=20.0, policy=CachePolicy.TTL),
            CacheNamespace.ML_FEATURES: NamespaceConfig(ttl=300.0, max_size=1000, max_memory_mb=100.0, policy=CachePolicy.LRU),
            CacheNamespace.ORDER_STATUS: NamespaceConfig(ttl=600.0, max_size=2000, max_memory_mb=64.0, policy=CachePolicy.LRU),
            CacheNamespace.TELEGRAM: NamespaceConfig(ttl=300.0, max_size=5000, max_memory_mb=32.0, policy=CachePolicy.LRU),
            CacheNamespace.CHARTS: NamespaceConfig(ttl=3600.0, max_size=500, max_memory_mb=256.0, policy=CachePolicy.LRU, compress=True),
            CacheNamespace.GENERAL: NamespaceConfig(ttl=900.0, max_size=99, max_memory_mb=128.0, policy=CachePolicy.HYBRID),
        }
        effective = namespace_configs or default_cfg
        for ns, cfg in effective.items():
            self._ns_cfg[self._ns_key(ns)] = cfg

    # ── Публичный API ──────────────────────────────────────────────────────
    def get(self, key: str, namespace: CacheNamespace | str, default: Any = None) -> Any:
        ns = self._ns_key(namespace)
        full_key = self._make_full_key(ns, key)
        try:
            with self._lock:
                self._stats["gets"] += 1
                entry = self._data.get(full_key)
                if not entry:
                    self._stats["misses"] += 1
                    return default
                if entry.is_expired():
                    self._stats["expired"] += 1
                    self._delete_full(full_key)
                    return default
                entry.touch()
                self._stats["hits"] += 1
                return self._unpack(entry.data)
        except Exception:
            self._stats["errors"] += 1
            logging.exception(
                "UnifiedCache.get failed",
                extra={"namespace": ns, "key_hash": hash(full_key)}
            )
            return default

    def set(self, key: str, value: Any, namespace: CacheNamespace | str,
            ttl: Optional[float] = None, *, priority: int = 1,
            sticky: bool = False, compress: Optional[bool] = None,
            metadata: Optional[Dict[str, Any]] = None) -> bool:
        ns = self._ns_key(namespace)
        try:
            cfg = self._cfg(ns)
            ttl_eff = cfg.ttl if ttl is None else float(ttl)
            do_compress = cfg.compress if compress is None else bool(compress)
            packed, size = self._pack(value, compress=do_compress)
            entry = CacheEntry(
                key=key, data=packed, namespace=ns,
                created_at=time.time(), last_accessed=time.time(),
                size_bytes=size, ttl=ttl_eff, priority=int(priority),
                sticky=bool(sticky), metadata=metadata or {}
            )
            full_key = self._make_full_key(ns, key)
            with self._lock:
                # точечная очистка просроченных
                self._cleanup_expired_locked(ns)
                # проверка/эвикция внутри namespace
                if not self._ensure_ns_capacity_locked(ns, size):
                    # глобальная эвикция и повторная попытка
                    self._evict_global_locked(size)
                    if not self._ensure_ns_capacity_locked(ns, size):
                        self._stats["errors"] += 1
                        logging.warning(
                            "UnifiedCache.set dropped entry due to capacity",
                            extra={
                                "namespace": ns,
                                "key_hash": hash(key),
                                "size_bytes": size,
                                "ns_config": {
                                    "max_size": cfg.max_size,
                                    "max_memory_mb": cfg.max_memory_mb,
                                    "policy": cfg.policy.value
                                }
                            }
                        )
                        return False
                # запись
                self._data[full_key] = entry
                self._stats["sets"] += 1
                # глобальное давление памяти
                self._enforce_global_memory_locked()
                return True
        except Exception:
            self._stats["errors"] += 1
            approx_size = None
            try:
                approx_size = len(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
            except Exception:
                pass
            logging.exception(
                "UnifiedCache.set failed",
                extra={
                    "namespace": ns,
                    "key_hash": hash(key),
                    "ttl": ttl,
                    "priority": priority,
                    "sticky": sticky,
                    "approx_pickle_size": approx_size
                }
            )
            return False

    def delete(self, key: str, namespace: CacheNamespace | str, *, prefix: bool = False) -> int:
        ns = self._ns_key(namespace)
        with self._lock:
            if not prefix:
                full_key = self._make_full_key(ns, key)
                return 1 if self._delete_full(full_key) else 0
            to_del = [k for k in self._data.keys() if k.startswith(ns + ":" + key)]
            for fk in to_del:
                self._delete_full(fk)
            return len(to_del)

    def clear_namespace(self, namespace: CacheNamespace | str) -> int:
        ns = self._ns_key(namespace)
        with self._lock:
            keys = [k for k, e in self._data.items() if e.namespace == ns]
            for fk in keys:
                self._delete_full(fk)
            return len(keys)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total_bytes = sum(e.size_bytes for e in self._data.values())
            return {
                **self._stats,
                "entries": len(self._data),
                "bytes": total_bytes,
                "rss_mb": self._rss_mb(),
                "per_ns": self._per_ns_stats_locked(),
            }

    def get_stats(self) -> Dict[str, Any]:
        return self.stats()

    def get_top_keys(self, namespace: CacheNamespace | str, limit: int = 10) -> List[Dict[str, Any]]:
        ns = self._ns_key(namespace)
        with self._lock:
            items = [(k, e) for k, e in self._data.items() if e.namespace == ns]
            items.sort(key=lambda kv: (kv[1].hits, kv[1].last_accessed), reverse=True)
            out = []
            for fk, e in items[:max(1, int(limit))]:
                out.append({
                    "key": fk.split(":", 1)[-1],
                    "hits": e.hits,
                    "size_bytes": e.size_bytes,
                    "age_sec": round(time.time() - e.created_at, 3),
                    "last_accessed_sec": round(time.time() - e.last_accessed, 3),
                    "metadata": e.metadata,
                })
            return out

    def get_or_set(self, key: str, namespace: CacheNamespace | str, ttl: Optional[float],
                   factory: Callable[[], Any], **set_kwargs) -> Any:
        sentinel = object()
        val = self.get(key, namespace, default=sentinel)
        if val is not sentinel:
            return val
        res = factory()
        self.set(key, res, namespace, ttl, **set_kwargs)
        return res

    def cached(self, namespace: CacheNamespace | str, ttl: Optional[float] = None,
               key_func: Optional[Callable[..., str]] = None, **set_kwargs):
        _SENTINEL = object()
        def decorator(func):
            def wrapper(*args, **kwargs):
                cache_key = key_func(*args, **kwargs) if key_func else self._function_key(func, args, kwargs)
                val = self.get(cache_key, namespace, default=_SENTINEL)
                if val is not _SENTINEL:
                    return val
                res = func(*args, **kwargs)
                self.set(cache_key, res, namespace, ttl, **set_kwargs)
                return res
            return wrapper
        return decorator

    # ── TTL-хелперы (для свечей) ───────────────────────────────────────────
    @staticmethod
    def parse_tf_to_seconds(tf: str) -> int:
        tf = (tf or "").strip().lower()
        if tf.endswith("m"):
            return max(60, int(tf[:-1]) * 60)
        if tf.endswith("h"):
            return int(tf[:-1]) * 3600
        if tf.endswith("d"):
            try:
                return int(tf[:-1]) * 86400
            except ValueError:
                return 900  # default 15m
        try:
            return max(1, int(tf))
        except Exception:
            return 900  # 15m по умолчанию
    @staticmethod
    def ttl_until_next_slot(seconds: int, drift_sec: int = 10) -> int:
        now = int(time.time())
        rem = seconds - (now % seconds)
        return max(1, rem + int(drift_sec))    

    @classmethod
    def ttl_until_next_candle(cls, tf: str, drift_sec: int = 10) -> int:
        return cls.ttl_until_next_slot(cls.parse_tf_to_seconds(tf), drift_sec=drift_sec)

    # ── Внутренние утилиты ────────────────────────────────────────────────
    def _ns_key(self, ns: CacheNamespace | str) -> str:
        return ns.value if isinstance(ns, CacheNamespace) else str(ns)

    def _cfg(self, ns: str) -> NamespaceConfig:
        return self._ns_cfg.get(ns, NamespaceConfig())

    def _make_full_key(self, ns: str, key: str) -> str:
        return f"{ns}:{key}"

    def _pack(self, value: Any, *, compress: bool) -> Tuple[Any, int]:
        try:
            if compress:
                payload = zlib.compress(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
                return ("zlib+pickle", payload), len(payload)
            raw = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
            return value, len(raw)
        except Exception:
            try:
                b = repr(value).encode("utf-8", "ignore")
                return value, len(b)
            except Exception:
                return value, 0

    def _unpack(self, data: Any) -> Any:
        if isinstance(data, tuple) and len(data) == 2 and data[0] == "zlib+pickle":
            try:
                return pickle.loads(zlib.decompress(data[1]))
            except Exception:
                self._stats["errors"] += 1
                return None
        return data

    def _delete_full(self, full_key: str) -> bool:
        e = self._data.pop(full_key, None)
        if e is not None:
            self._stats["evictions"] += 1
            return True
        return False

    def _cleanup_expired_locked(self, ns: Optional[str] = None) -> None:
        now = time.time()
        to_del: List[str] = []
        for k, e in self._data.items():
            if ns is not None and e.namespace != ns:
                continue
            if e.ttl is not None and (now - e.created_at) > e.ttl:
                to_del.append(k)
        if to_del:
            for fk in to_del:
                self._delete_full(fk)

    def _ensure_ns_capacity_locked(self, ns: str, incoming_size: int) -> bool:
        cfg = self._cfg(ns)
        ns_entries = [(k, e) for k, e in self._data.items() if e.namespace == ns and not e.sticky]
        if len(ns_entries) >= cfg.max_size:
            self._evict_ns_locked(ns, count=max(1, len(ns_entries)//10), policy=cfg.policy)
        ns_bytes = sum(e.size_bytes for _, e in ns_entries)
        if (ns_bytes + incoming_size) > (cfg.max_memory_mb * 1024 * 1024):
            self._evict_ns_locked(ns, count=max(1, len(ns_entries)//10), policy=cfg.policy)
            ns_entries = [(k, e) for k, e in self._data.items() if e.namespace == ns and not e.sticky]
            ns_bytes = sum(e.size_bytes for _, e in ns_entries)
        return (len(ns_entries) < cfg.max_size) and ((ns_bytes + incoming_size) <= (cfg.max_memory_mb * 1024 * 1024))

    def _evict_ns_locked(self, ns: str, *, count: int, policy: CachePolicy) -> None:
        now = time.time()
        entries = [(k, e) for k, e in self._data.items()
                   if e.namespace == ns and not e.sticky and not (e.ttl and (now - e.created_at) > e.ttl)]
        if policy == CachePolicy.TTL:
            entries.sort(key=lambda kv: (kv[1].priority, kv[1].hits, kv[1].last_accessed))
        elif policy == CachePolicy.LRU:
            entries.sort(key=lambda kv: (kv[1].priority, kv[1].last_accessed, kv[1].hits))
        else:  # HYBRID
            entries.sort(key=lambda kv: (kv[1].priority, kv[1].is_expired(), kv[1].last_accessed, kv[1].hits))
        for fk, _ in entries[:count]:
            self._delete_full(fk)

    def _evict_global_locked(self, incoming_size: int) -> None:
        entries = [(k, e) for k, e in self._data.items() if not e.sticky]
        entries.sort(key=lambda kv: (kv[1].priority, kv[1].hits, kv[1].last_accessed))
        freed = 0
        for fk, e in entries:
            self._delete_full(fk)
            freed += e.size_bytes
            if freed >= incoming_size:
                break

    def _enforce_global_memory_locked(self) -> None:
        total_bytes = sum(e.size_bytes for e in self._data.values())
        if total_bytes <= self.global_max_memory_mb * 1024 * 1024:
            return
        self._evict_global_locked(int(total_bytes - self.global_max_memory_mb * 1024 * 1024))
        try:
            if psutil is not None:
                rss = psutil.Process(os.getpid()).memory_info().rss
                limit = int(self.global_max_memory_mb * 1024 * 1024 * 1.10)  # 10% буфер
                if rss > limit:
                    entries = [(k, e) for k, e in self._data.items() if not e.sticky]
                    cut = max(1, len(entries) // 10)
                    entries.sort(key=lambda kv: (kv[1].priority, kv[1].hits, kv[1].last_accessed))
                    for fk, _ in entries[:cut]:
                        self._delete_full(fk)
        except Exception:
            pass

    def _per_ns_stats_locked(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for k, e in self._data.items():
            ns = e.namespace
            d = out.setdefault(ns, {"entries": 0, "bytes": 0})
            d["entries"] += 1
            d["bytes"] += e.size_bytes
        for ns, d in out.items():
            d["mb"] = round(d["bytes"] / (1024*1024), 3)
        return out

    def _rss_mb(self) -> Optional[float]:
        try:
            if psutil is None:
                return None
            return round(psutil.Process(os.getpid()).memory_info().rss / (1024*1024), 3)
        except Exception:
            return None

    def _function_key(self, func: Callable, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
        try:
            raw = (func.__module__, func.__qualname__, args, tuple(sorted(kwargs.items())))
            payload = pickle.dumps(raw, protocol=pickle.HIGHEST_PROTOCOL)
            import hashlib
            return hashlib.sha1(payload).hexdigest()
        except Exception:
            return f"{func.__module__}.{func.__qualname__}:{id(args)}:{id(kwargs)}"

# Глобальный синглтон
cache = UnifiedCacheManager()

# Алиасы
ttl_until_next_slot = UnifiedCacheManager.ttl_until_next_slot
ttl_until_next_candle = UnifiedCacheManager.ttl_until_next_candle
parse_tf_to_seconds = UnifiedCacheManager.parse_tf_to_seconds

# Domain helpers
class trading_cache:
    @staticmethod
    def _ohlcv_key(symbol: str, tf: str) -> str:
        return f"ohlcv:{symbol}:{tf}:v1"

    @staticmethod
    def get_ohlcv(symbol: str, tf: str, fetch_fn):
        ttl = ttl_until_next_candle(tf, drift_sec=10)
        key = trading_cache._ohlcv_key(symbol, tf)
        return cache.get_or_set(
            key, CacheNamespace.OHLCV, ttl,
            factory=lambda: fetch_fn(symbol, tf),
            priority=3, compress=True
        )

    @staticmethod
    def get_ticker(symbol: str, fetch_fn):
        key = f"ticker:{symbol}:v1"
        return cache.get_or_set(
            key, CacheNamespace.PRICES, ttl=2,
            factory=lambda: fetch_fn(symbol),
            priority=2
        )

    @staticmethod
    def get_orderbook(symbol: str, depth: int, fetch_fn):
        key = f"orderbook:{symbol}:{int(depth)}:v1"
        return cache.get_or_set(
            key, CacheNamespace.MARKET_INFO, ttl=2,
            factory=lambda: fetch_fn(symbol, depth),
            priority=2, compress=False
        )

    @staticmethod
    def invalidate_md(prefix: str = "") -> int:
        count = 0
        count += cache.delete(f"ohlcv:{prefix}", CacheNamespace.OHLCV, prefix=True)
        count += cache.delete(f"ticker:{prefix}", CacheNamespace.PRICES, prefix=True)
        count += cache.delete(f"orderbook:{prefix}", CacheNamespace.MARKET_INFO, prefix=True)
        return count

class telegram_cache:
    @staticmethod
    def _chart_key(hash_: str) -> str:
        return f"chart:{hash_}:v1"

    @staticmethod
    def get_chart(hash_: str, make_chart_fn):
        return cache.get_or_set(
            telegram_cache._chart_key(hash_), CacheNamespace.CHARTS, ttl=3600,
            factory=make_chart_fn, priority=1, compress=False
        )

    @staticmethod
    def invalidate_charts(prefix: str = "") -> int:
        return cache.delete(f"chart:{prefix}", CacheNamespace.CHARTS, prefix=True)

# Backwards-compatible aliases
def get_cache_manager():
    return cache

def cached_function(namespace, ttl=None, key_func=None, **set_kwargs):
    return cache.cached(namespace, ttl, key_func=key_func, **set_kwargs)
