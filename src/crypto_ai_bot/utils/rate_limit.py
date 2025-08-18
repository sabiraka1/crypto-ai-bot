from __future__ import annotations
import time
from threading import RLock
from typing import Optional


class TokenBucket:
    """
    Простой thread-safe токен-бакет: refill по фиксированной скорости.
    Единицы: токены в минуту (rpm). burst — максимальная ёмкость.
    """
    def __init__(self, rpm: float, burst: float | None = None):
        self.rpm = float(rpm)
        self.burst = float(burst if burst is not None else rpm)
        self.tokens = self.burst
        self.last = time.time()
        self._lock = RLock()

    def acquire(self, tokens: float = 1.0, timeout: float = 5.0) -> bool:
        """
        Пытаемся получить 'tokens'. При необходимости ждём до timeout.
        Возвращает True/False (успех/таймаут).
        """
        end = time.time() + float(timeout)
        with self._lock:
            while True:
                now = time.time()
                # пополнение
                elapsed = max(0.0, now - self.last)
                self.last = now
                self.tokens = min(self.burst, self.tokens + (self.rpm / 60.0) * elapsed)
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                # ждём до следующего пополнения
                if now >= end:
                    return False
                time.sleep(min(0.05, end - now))


class MultiLimiter:
    """
    Набор бакетов по ключам/методам. Например:
    - public_read
    - private_read
    - private_write
    """
    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = RLock()

    def set_bucket(self, key: str, rpm: float, burst: Optional[float] = None) -> None:
        with self._lock:
            self._buckets[key] = TokenBucket(rpm=rpm, burst=burst)

    def acquire(self, key: str, tokens: float = 1.0, timeout: float = 5.0) -> bool:
        with self._lock:
            bucket = self._buckets.get(key)
        if bucket is None:
            # нет ограничителя — разрешаем (по умолчанию)
            return True
        return bucket.acquire(tokens=tokens, timeout=timeout)
