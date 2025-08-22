## `core/monitoring/health_checker.py`
from __future__ import annotations
import asyncio
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Any, Dict, Optional
from ..events.bus import AsyncEventBus, Event
from ..events import topics
from ..brokers.base import IBroker
from ..brokers.symbols import market_info_from_ccxt
from ..storage.facade import Storage
from ...utils.time import now_ms
from ...utils.ids import make_correlation_id
from ...utils.logging import get_logger
from ...utils.exceptions import ValidationError

# Локальные исключения для preflight
class BrokerError(Exception):
    pass

class TransientError(Exception):
    pass

_log = get_logger("monitoring.health")

@dataclass(frozen=True)
class HealthReport:
    ok: bool
    db_ok: bool
    migrations_ok: bool
    broker_ok: bool
    bus_ok: bool
    clock_drift_ms: Optional[int]
    details: Dict[str, Any]
    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

class HealthChecker:
    """Агрегированный health: DB, миграции, брокер, EventBus, clock drift.
    Примечание: проверка шины отправляет и ожидает loopback‑событие в тему `HEALTH_STATUS`.
    """
    def __init__(self, *, storage: Storage, broker: IBroker, bus: Optional[AsyncEventBus] = None):
        self.storage = storage
        self.broker = broker
        self.bus = bus

    async def check(self, *, symbol: str, timeout_ms: int = 1500, clock_drift_ms: Optional[int] = None) -> HealthReport:
        details: Dict[str, Any] = {}
        db_ok = self._check_db(details)
        migrations_ok = self._check_migrations(details)
        broker_ok = await self._check_broker(symbol, details, timeout_ms)
        bus_ok = await self._check_bus(details, timeout_ms) if self.bus else True
        details["clock_drift_ms"] = clock_drift_ms
        ok = all([db_ok, migrations_ok, broker_ok, bus_ok])
        return HealthReport(
            ok=ok,
            db_ok=db_ok,
            migrations_ok=migrations_ok,
            broker_ok=broker_ok,
            bus_ok=bus_ok,
            clock_drift_ms=clock_drift_ms,
            details=details,
        )

    async def preflight(self, *, symbol: str, fixed_quote_amount: Decimal, broker) -> dict:
        """
        Быстрый набор проверок перед MODE=live.
        Ничего не размещает.
        """
        ts = now_ms()
        checks = {"api_keys": True}  # если до сюда дошли, ключи хотя бы заданы
        ok = True
        err: str = ""

        # 1) Балансы
        try:
            await broker.fetch_balance()
            checks["balance"] = True
        except (TransientError, BrokerError, Exception) as e:
            checks["balance"] = False
            ok = False
            err = f"balance: {e}"

        # 2) Маркет-инфо (precision/limits). Если метод недоступен — считаем пройденным.
        try:
            mi_raw = getattr(broker, "fetch_market_info", None)
            if callable(mi_raw):
                m = await broker.fetch_market_info(symbol)
                _ = market_info_from_ccxt(symbol, m)  # парс проверяет наличие ключевых полей
                checks["market_info"] = True
            else:
                checks["market_info"] = True
        except Exception as e:
            checks["market_info"] = False
            ok = False
            err = err or f"market_info: {e}"

        # 3) Тикер (цена живая, ask/bid > 0)
        try:
            t = await broker.fetch_ticker(symbol)
            checks["ticker"] = bool(t and (t.ask > 0 or t.last > 0))
            ok = ok and checks["ticker"]
        except Exception as e:
            checks["ticker"] = False
            ok = False
            err = err or f"ticker: {e}"

        # 4) Достаточность FIXED_AMOUNT по minNotional (если есть market_info)
        try:
            if callable(getattr(broker, "fetch_market_info", None)):
                m = await broker.fetch_market_info(symbol)
                mi = market_info_from_ccxt(symbol, m)
                # берём ask как оценку цены
                t = await broker.fetch_ticker(symbol)
                price = Decimal(str(t.ask or t.last or t.bid or 0))
                if mi.min_notional_quote and price > 0:
                    checks["notional_ok"] = Decimal(str(fixed_quote_amount)) >= mi.min_notional_quote
                    ok = ok and checks["notional_ok"]
                else:
                    checks["notional_ok"] = True
            else:
                checks["notional_ok"] = True
        except Exception as e:
            checks["notional_ok"] = False
            ok = False
            err = err or f"notional: {e}"

        return {"ok": bool(ok), "checks": checks, "ts_ms": ts, **({"error": err} if err else {})}

    def _check_db(self, details: Dict[str, Any]) -> bool:
        try:
            self.storage.conn.execute("SELECT 1;")
            details["db"] = "ok"
            return True
        except Exception as exc:
            details["db"] = f"error: {exc}"
            return False

    def _check_migrations(self, details: Dict[str, Any]) -> bool:
        try:
            cur = self.storage.conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            )
            present = bool(cur.fetchone()[0])
            details["migrations_table"] = present
            return present
        except Exception as exc:
            details["migrations_table"] = f"error: {exc}"
            return False

    async def _check_broker(self, symbol: str, details: Dict[str, Any], timeout_ms: int) -> bool:
        try:
            async def _run():
                t = await self.broker.fetch_ticker(symbol)
                return bool(t and t.timestamp)
            return await asyncio.wait_for(_run(), timeout=timeout_ms / 1000.0)
        except Exception as exc:
            details["broker"] = f"error: {exc}"
            return False

    async def _check_bus(self, details: Dict[str, Any], timeout_ms: int) -> bool:
        try:
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            cid = make_correlation_id()
            async def _probe(evt: Event):  # type: ignore[valid-type]
                if evt.payload.get("cid") == cid:
                    try:
                        self.bus.unsubscribe(topics.HEALTH_STATUS, _probe)  # type: ignore[arg-type]
                    except Exception:
                        pass
                    if not fut.done():
                        fut.set_result(True)
            self.bus.subscribe(topics.HEALTH_STATUS, _probe)  # type: ignore[arg-type]
            await self.bus.publish(topics.HEALTH_STATUS, {"ts": now_ms(), "cid": cid}, key="health")
            ok = await asyncio.wait_for(fut, timeout=timeout_ms / 1000.0)
            details["bus_loopback"] = ok
            return bool(ok)
        except Exception as exc:
            details["bus_loopback"] = f"error: {exc}"
            return False