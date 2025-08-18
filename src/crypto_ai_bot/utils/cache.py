# src/crypto_ai_bot/utils/cache.py
from __future__ import annotations

import time
import threading
from collections import OrderedDict
from typing import Any, Optional


class TTLCache:
    """
    Простой потокобезопасный TTL-кэш с ограничением размера.
    - O(1) get/set
    - Вытеснение по LRU при переполнении
    - Просроченные элементы удаляются лениво (на чтении/записи)

    Использование:
        c = TTLCache(ttl_sec=300, maxsize=128)
        c.set("k", 123)          # TTL берётся из дефолтного
        v = c.get("k")           # 123 или None, если истёк
        c.set("k2", 42, ttl=10)  # кастомный TTL
    """

    def __init__(self, ttl_sec: int = 300, maxsize: int = 256) -> None:
        self.ttl = int(max(1, ttl_sec))
        self.maxsize = int(max(1, maxsize))
        self._lock = threading.RLock()
        # key -> (value, expires_at)
        self._data: "OrderedDict[str, tuple[Any, float]]" = OrderedDict()

    def _now(self) -> float:
        return time.time()

    def _purge_expired(self) -> None:
        now = self._now()
        # удаляем только с головы (старые по LRU), пока просрочены
        with self._lock:
            keys = list(self._data.keys())
            for k in keys:
                _, exp = self._data[k]
                if exp <= now:
                    self._data.pop(k, None)
                else:
                    # дальше элементы свежее по времени доступа
                    break

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            self._purge_expired()
            item = self._data.get(key)
            if item is None:
                return None
            val, exp = item
            if exp <= self._now():
                # истёк — удалим и вернём None
                self._data.pop(key, None)
                return None
            # LRU: переносим в конец как «последний использованный»
            self._data.move_to_end(key, last=True)
            return val

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl_eff = int(ttl if ttl and ttl > 0 else self.ttl)
        exp = self._now() + ttl_eff
        with self._lock:
            # если уже есть — перезапишем и перенесём в конец
            if key in self._data:
                self._data.move_to_end(key, last=True)
            self._data[key] = (value, exp)
            self._purge_expired()
            # LRU-вытеснение при переполнении
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired()
            return len(self._data)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None
