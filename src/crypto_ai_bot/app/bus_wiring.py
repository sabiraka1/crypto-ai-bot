# src/crypto_ai_bot/app/bus_wiring.py
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Tuple, List

try:
    from crypto_ai_bot.core.events.async_bus import AsyncEventBus
except Exception as e:  # pragma: no cover
    AsyncEventBus = None  # type: ignore

try:
    from crypto_ai_bot.events.factory import build_strategy_map
except Exception:
    def build_strategy_map(cfg): return {}


# --- простейшая статистика по p95/p99 (in-memory, небольшой буфер) ---
_LAT: Dict[str, List[float]] = {}
_LAT_MAX = 2000

def _record_latency(key: str, ms: float) -> None:
    arr = _LAT.setdefault(key, [])
    arr.append(float(ms))
    if len(arr) > _LAT_MAX:
        del arr[: len(arr) - _LAT_MAX]

def _percentile(xs: List[float], q: float) -> Optional[float]:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    if f == c:
        return xs[int(k)]
    d0 = xs[f] * (c - k)
    d1 = xs[c] * (k - f)
    return d0 + d1

def snapshot_quantiles() -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for k, arr in _LAT.items():
        p95 = _percentile(arr, 0.95)
        p99 = _percentile(arr, 0.99)
        d: Dict[str, float] = {}
        if p95 is not None:
            d["p95"] = float(p95)
        if p99 is not None:
            d["p99"] = float(p99)
        if d:
            out[k] = d
    return out


# --- журнал-прокси поверх AsyncEventBus ---
class _JournalProxy:
    def __init__(self, bus: Any, journal_repo: Optional[Any] = None) -> None:
        self._bus = bus
        self._jr = journal_repo

    # делегаты
    async def start(self) -> None:
        if hasattr(self._bus, "start"):
            await self._bus.start()

    async def stop(self) -> None:
        if hasattr(self._bus, "stop"):
            await self._bus.stop()

    def health(self) -> Dict[str, Any]:
        if hasattr(self._bus, "health"):
            return self._bus.health()
        return {}

    def dlq_dump(self, *, limit: int = 50) -> Any:
        if hasattr(self._bus, "dlq_dump"):
            return self._bus.dlq_dump(limit=limit)
        return []

    # публикация
    def publish(self, event: Dict[str, Any]) -> None:
        evt = dict(event or {})
        evt.setdefault("ts_ms", int(time.time() * 1000))
        if self._jr:
            try:
                self._jr.log_enqueued(evt)
            except Exception:
                pass
        self._bus.publish(evt)

    # подписка
    def subscribe(self, type_: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        def _wrap(e: Dict[str, Any]) -> Any:
            t0 = time.time()
            try:
                out = handler(e)
                if self._jr:
                    try:
                        self._jr.log_delivered(e)
                    except Exception:
                        pass
                return out
            except Exception as err:
                if self._jr:
                    try:
                        self._jr.log_error(e, err)
                    except Exception:
                        pass
                raise
            finally:
                try:
                    ts = int(e.get("ts_ms") or int(t0 * 1000))
                    dt_ms = max(0.0, (time.time() - (ts / 1000.0)) * 1000.0)
                    _record_latency(f"bus:{e.get('type','Unknown')}", dt_ms)
                except Exception:
                    pass

        self._bus.subscribe(type_, _wrap)


def build_bus(cfg: Any, repos: Any) -> Any:
    if AsyncEventBus is None:
        raise RuntimeError("AsyncEventBus is not available")
    smap = build_strategy_map(cfg)
    bus = AsyncEventBus(strategy_map=smap, dlq_max=int(getattr(cfg, "BUS_DLQ_MAX", 1000)))
    jr = getattr(repos, "journal", None)
    return _JournalProxy(bus, journal_repo=jr)
