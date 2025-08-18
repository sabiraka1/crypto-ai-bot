from __future__ import annotations
import time
from collections import deque
from threading import Lock
from typing import Callable, Deque, Dict, Tuple

class RateLimiter:
    """Потокобезопасный токен-бакет."""
    def __init__(self, max_calls: int, window: float) -> None:
        self.max_calls = max(1, int(max_calls))
        self.window = float(window)
        self._ts: Deque[float] = deque()
        self._lock = Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._ts and (now - self._ts[0]) >= self.window:
                self._ts.popleft()
            if len(self._ts) >= self.max_calls:
                sleep_for = self.window - (now - self._ts[0])
                if sleep_for > 0:
                    time.sleep(sleep_for)
                    # очистим окно ещё раз
                    now = time.monotonic()
                    while self._ts and (now - self._ts[0]) >= self.window:
                        self._ts.popleft()
            self._ts.append(time.monotonic())

# общий реестр лимитеров на процесс
_LIMITERS: Dict[Tuple[str, int], RateLimiter] = {}

def rate_limit(max_calls: int, window: float):
    """Декоратор, использующий процессный реестр лимитеров по имени функции."""
    def deco(fn: Callable):
        key = (fn.__name__, max_calls)
        _LIMITERS.setdefault(key, RateLimiter(max_calls, window))
        limiter = _LIMITERS[key]
        def wrapper(*args, **kwargs):
            limiter.acquire()
            return fn(*args, **kwargs)
        return wrapper
    return deco
