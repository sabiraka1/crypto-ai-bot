"""
TTL Cache implementation for market data and other temporary storage.

Features:
- Generic type support
- Automatic expiration
- Manual deletion
- Clear all functionality
- Thread-safe operations
- Size limiting
"""
from __future__ import annotations

import threading
import time
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """
    Thread-safe TTL cache with automatic expiration.

    All items share the same TTL (time to live).
    Expired items are removed on access or during cleanup.
    """

    def __init__(
        self,
        ttl_sec: float = 30.0,
        max_size: Optional[int] = None,
        cleanup_interval: Optional[float] = None,
    ) -> None:
        """
        Initialize TTL cache.

        Args:
            ttl_sec: Time to live in seconds for all items
            max_size: Maximum number of items (None = unlimited)
            cleanup_interval: Automatic cleanup interval in seconds (None = no auto cleanup)
        """
        self._ttl = float(ttl_sec)
        self._max_size = max_size if (max_size is None or max_size >= 0) else None
        self._cleanup_interval = cleanup_interval

        # Storage: key -> (born_monotonic_ts, value)
        self._data: dict[Any, tuple[float, T]] = {}

        # Thread safety
        self._lock = threading.RLock()

        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0

        # Auto cleanup thread
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_cleanup = threading.Event()

        if cleanup_interval and cleanup_interval > 0:
            self._start_cleanup_thread()

    # ------------- core API -------------

    def get(self, key: Any) -> Optional[T]:
        """
        Get value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            now = time.monotonic()
            record = self._data.get(key)

            if not record:
                self._misses += 1
                return None

            born, value = record

            # Check expiration
            if (now - born) > self._ttl:
                # Remove expired entry
                del self._data[key]
                self._evictions += 1
                self._misses += 1
                return None

            self._hits += 1
            return value

    def put(self, key: Any, value: T) -> None:
        """
        Put value in cache with current timestamp.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self._lock:
            # Evict if size limit reached and this is a new key
            if self._max_size is not None and len(self._data) >= self._max_size and key not in self._data:
                self._evict_oldest()

            self._data[key] = (time.monotonic(), value)

    def delete(self, key: Any) -> bool:
        """
        Delete key from cache.

        Args:
            key: Cache key to delete

        Returns:
            True if key was present and deleted, False otherwise
        """
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cached entries and reset stats."""
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def size(self) -> int:
        """Get current number of cached items."""
        with self._lock:
            return len(self._data)

    # ------------- maintenance -------------

    def cleanup(self) -> int:
        """
        Remove all expired entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            now = time.monotonic()
            expired_keys = [k for k, (born, _) in self._data.items() if (now - born) > self._ttl]
            for k in expired_keys:
                del self._data[k]
                self._evictions += 1
            return len(expired_keys)

    def _evict_oldest(self) -> None:
        """Evict the oldest entry (internal use)."""
        if not self._data:
            return
        # Find the oldest by born timestamp
        oldest_key = min(self._data.items(), key=lambda kv: kv[1][0])[0]
        del self._data[oldest_key]
        self._evictions += 1

    # ------------- background thread -------------

    def _cleanup_loop(self) -> None:
        """Background cleanup thread loop."""
        interval = float(self._cleanup_interval or 0.0)
        while not self._stop_cleanup.is_set():
            self._stop_cleanup.wait(interval)
            if not self._stop_cleanup.is_set():
                self.cleanup()

    def _start_cleanup_thread(self) -> None:
        """Start background cleanup thread."""
        if self._cleanup_thread is None or not self._cleanup_thread.is_alive():
            self._stop_cleanup.clear()
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                daemon=True,
                name="TTLCache-Cleanup",
            )
            self._cleanup_thread.start()

    def stop_cleanup(self) -> None:
        """Stop background cleanup thread."""
        if self._cleanup_thread:
            self._stop_cleanup.set()
            self._cleanup_thread.join(timeout=1.0)
            self._cleanup_thread = None

    # nicety alias
    def close(self) -> None:
        """Alias for stop_cleanup()."""
        self.stop_cleanup()

    # ------------- stats / dunders -------------

    def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

            return {
                "size": len(self._data),
                "max_size": self._max_size,
                "ttl_sec": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": hit_rate,
                "total_requests": total_requests,
            }

    def __contains__(self, key: Any) -> bool:
        """Check if key exists and is not expired (no stats side-effects)."""
        with self._lock:
            rec = self._data.get(key)
            if not rec:
                return False
            born, _ = rec
            return (time.monotonic() - born) <= self._ttl

    def __len__(self) -> int:
        """Get current cache size."""
        return self.size()

    def __del__(self) -> None:
        """Cleanup on deletion."""
        try:
            self.stop_cleanup()
        except Exception:
            pass


class LRUCache(Generic[T]):
    """
    LRU (Least Recently Used) cache with optional TTL.

    Items are evicted based on usage; TTL (if set) acts as max age since last put().
    """

    def __init__(
        self,
        max_size: int = 100,
        ttl_sec: Optional[float] = None,
    ) -> None:
        """
        Initialize LRU cache.

        Args:
            max_size: Maximum number of items
            ttl_sec: Optional TTL in seconds
        """
        from collections import OrderedDict

        self._max_size = max_size
        self._ttl = float(ttl_sec) if ttl_sec is not None else None
        self._data: OrderedDict[Any, tuple[float, T]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: Any) -> Optional[T]:
        """Get value and mark as recently used."""
        with self._lock:
            if key not in self._data:
                return None

            born, value = self._data[key]

            # TTL check (based on monotonic age)
            if self._ttl is not None and (time.monotonic() - born) > self._ttl:
                del self._data[key]
                return None

            # Move to end (recently used)
            self._data.move_to_end(key)
            return value

    def put(self, key: Any, value: T) -> None:
        """Put value in cache."""
        with self._lock:
            # Remove if exists (to update position)
            if key in self._data:
                del self._data[key]

            # Add at the end with current born time
            self._data[key] = (time.monotonic(), value)

            # Evict if over capacity
            while len(self._data) > self._max_size:
                # Remove least recently used (first item)
                self._data.popitem(last=False)

    def delete(self, key: Any) -> bool:
        """Delete key from cache."""
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._data.clear()

    def size(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._data)


# Export
__all__ = [
    "TTLCache",
    "LRUCache",
]
