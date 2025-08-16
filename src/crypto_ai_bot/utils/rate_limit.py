from __future__ import annotations
import time
from typing import Callable, Dict, Any, Optional

class RateLimitState:
    def __init__(self, *, rate_per_min: int, burst: Optional[int] = None) -> None:
        self.rate_per_sec = max(1, rate_per_min) / 60.0
        self.burst = float(burst if burst is not None else max(1, rate_per_min))
        self._state: Dict[str, tuple[float, float]] = {}

    def consume(self, key: str) -> tuple[bool, float]:
        now = time.monotonic()
        tokens, last_ts = self._state.get(key, (self.burst, now))
        delta = max(0.0, now - last_ts)
        tokens = min(self.burst, tokens + delta * self.rate_per_sec)
        if tokens < 1.0:
            need = 1.0 - tokens
            retry_in = need / self.rate_per_sec if self.rate_per_sec > 0 else 1.0
            self._state[key] = (tokens, now)
            return False, retry_in
        tokens -= 1.0
        self._state[key] = (tokens, now)
        return True, 0.0

_GLOBAL_LIMITERS: Dict[str, RateLimitState] = {}

def rate_limit(*, name: str, key_fn: Optional[Callable[..., str]] = None, rate_per_min: int = 60, burst: Optional[int] = None):
    lim = _GLOBAL_LIMITERS.get(name)
    if lim is None:
        lim = RateLimitState(rate_per_min=rate_per_min, burst=burst)
        _GLOBAL_LIMITERS[name] = lim
    def _decorator(fn):
        def _wrapper(*args, **kwargs):
            cfg = kwargs.get("cfg") or (args[0] if args else None)
            r = getattr(cfg, f"RATE_LIMIT_{name.upper()}_PER_MIN", rate_per_min) if cfg else rate_per_min
            b = getattr(cfg, f"RATE_BURST_{name.upper()}", burst if burst is not None else r)
            lim.rate_per_sec = max(1, int(r)) / 60.0
            lim.burst = float(b if b is not None else r)
            key = key_fn(*args, **kwargs) if key_fn else "global"
            ok, retry_in = lim.consume(key)
            if not ok:
                return {"status": "rate_limited", "limiter": name, "retry_in": round(retry_in, 3)}
            return fn(*args, **kwargs)
        return _wrapper
    return _decorator