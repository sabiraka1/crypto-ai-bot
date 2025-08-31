from __future__ import annotations

from typing import Protocol, runtime_checkable, Any, Callable, Awaitable


@runtime_checkable
class SafetySwitchPort(Protocol):
    """
    Порт Dead Man's Switch: сервис обязан периодически вызывать ping()
    (например, раз в N секунд). Если пингов нет — внешняя система может
    остановить торги/закрыть позиции. В нашем коде допускается no-op.
    """
    async def start(self) -> None: ...
    async def ping(self) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class InstanceLockPort(Protocol):
    """
    Порт эксклюзивного лок-инстанса: чтобы не запустить два робота на один символ.
    """
    async def acquire(self) -> bool: ...
    async def release(self) -> None: ...


@runtime_checkable
class EventBusPort(Protocol):
    """Общий интерфейс для всех event bus реализаций."""
    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None: ...
    def on(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None: ...
    async def start(self) -> None: ...
    async def close(self) -> None: ...


@runtime_checkable
class BrokerPort(Protocol):
    """Интерфейс для брокера."""
    async def fetch_ticker(self, symbol: str) -> Any: ...
    async def fetch_balance(self, symbol: str) -> Any: ...
    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Any, client_order_id: str | None = None) -> Any: ...
    async def create_market_sell_base(self, *, symbol: str, base_amount: Any, client_order_id: str | None = None) -> Any: ...
    async def fetch_order(self, *, symbol: str, broker_order_id: str) -> Any: ...


@runtime_checkable  
class StoragePort(Protocol):
    """Интерфейс для хранилища."""
    @property
    def trades(self) -> Any: ...
    @property
    def positions(self) -> Any: ...
    @property
    def idempotency(self) -> Any: ...


@runtime_checkable
class OrderLike(Protocol):
    """Интерфейс для ордера."""
    @property
    def filled(self) -> Any: ...
    @property
    def amount(self) -> Any: ...
    @property
    def side(self) -> str: ...
    @property
    def client_order_id(self) -> str: ...


# ---- Безопасные заглушки (используются, когда DMS/LOCK выключены) ----

class NoopSafetySwitch(SafetySwitchPort):
    async def start(self) -> None:
        return None

    async def ping(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class NoopInstanceLock(InstanceLockPort):
    async def acquire(self) -> bool:
        return True  # позволяем запуск (нет фактической блокировки)

    async def release(self) -> None:
        return None


__all__ = [
    "InstanceLockPort",
    "NoopInstanceLock",
    "NoopSafetySwitch",
    "SafetySwitchPort",
    "EventBusPort",
    "BrokerPort",
    "StoragePort",
    "OrderLike",
]