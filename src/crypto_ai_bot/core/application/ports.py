from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SafetySwitchPort(Protocol):
    """
    ĞŸĞ¾Ñ€Ñ‚ Dead Man's Switch: ÑĞµÑ€Ğ²Ğ¸Ñ Ğ¾Ğ±ÑĞ·Ğ°Ğ½ Ğ¿ĞµÑ€Ğ¸Ğ¾Ğ´Ğ¸Ñ‡ĞµÑĞºĞ¸ Ğ²Ñ‹Ğ·Ñ‹Ğ²Ğ°Ñ‚ÑŒ ping()
    (Ğ½Ğ°Ğ¿Ñ€Ğ¸Ğ¼ĞµÑ€, Ñ€Ğ°Ğ· Ğ² N ÑĞµĞºÑƒĞ½Ğ´). Ğ•ÑĞ»Ğ¸ Ğ¿Ğ¸Ğ½Ğ³Ğ¾Ğ² Ğ½ĞµÑ‚ â€” Ğ²Ğ½ĞµÑˆĞ½ÑÑ ÑĞ¸ÑÑ‚ĞµĞ¼Ğ° Ğ¼Ğ¾Ğ¶ĞµÑ‚
    Ğ¾ÑÑ‚Ğ°Ğ½Ğ¾Ğ²Ğ¸Ñ‚ÑŒ Ñ‚Ğ¾Ñ€Ğ³Ğ¸/Ğ·Ğ°ĞºÑ€Ñ‹Ñ‚ÑŒ Ğ¿Ğ¾Ğ·Ğ¸Ñ†Ğ¸Ğ¸. Ğ’ Ğ½Ğ°ÑˆĞµĞ¼ ĞºĞ¾Ğ´Ğµ Ğ´Ğ¾Ğ¿ÑƒÑĞºĞ°ĞµÑ‚ÑÑ no-op.
    """
    async def start(self) -> None: ...
    async def ping(self) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class InstanceLockPort(Protocol):
    """
    ĞŸĞ¾Ñ€Ñ‚ ÑĞºÑĞºĞ»ÑĞ·Ğ¸Ğ²Ğ½Ğ¾Ğ³Ğ¾ Ğ»Ğ¾Ğº-Ğ¸Ğ½ÑÑ‚Ğ°Ğ½ÑĞ°: Ñ‡Ñ‚Ğ¾Ğ±Ñ‹ Ğ½Ğµ Ğ·Ğ°Ğ¿ÑƒÑÑ‚Ğ¸Ñ‚ÑŒ Ğ´Ğ²Ğ° Ñ€Ğ¾Ğ±Ğ¾Ñ‚Ğ° Ğ½Ğ° Ğ¾Ğ´Ğ¸Ğ½ ÑĞ¸Ğ¼Ğ²Ğ¾Ğ».
    """
    async def acquire(self) -> bool: ...
    async def release(self) -> None: ...


@runtime_checkable
class EventBusPort(Protocol):
    """ĞĞ±Ñ‰Ğ¸Ğ¹ Ğ¸Ğ½Ñ‚ĞµÑ€Ñ„ĞµĞ¹Ñ Ğ´Ğ»Ñ Ğ²ÑĞµÑ… event bus Ñ€ĞµĞ°Ğ»Ğ¸Ğ·Ğ°Ñ†Ğ¸Ğ¹."""
    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None: ...
    def on(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None: ...
    async def start(self) -> None: ...
    async def close(self) -> None: ...


@runtime_checkable
class BrokerPort(Protocol):
    """Ğ˜Ğ½Ñ‚ĞµÑ€Ñ„ĞµĞ¹Ñ Ğ´Ğ»Ñ Ğ±Ñ€Ğ¾ĞºĞµÑ€Ğ°."""
    async def fetch_ticker(self, symbol: str) -> Any: ...
    async def fetch_balance(self, symbol: str) -> Any: ...
    async def create_market_buy_quote(self, *, symbol: str, quote_amount: Any, client_order_id: str | None = None) -> Any: ...
    async def create_market_sell_base(self, *, symbol: str, base_amount: Any, client_order_id: str | None = None) -> Any: ...
    async def fetch_order(self, *, symbol: str, broker_order_id: str) -> Any: ...


@runtime_checkable
class StoragePort(Protocol):
    """Ğ˜Ğ½Ñ‚ĞµÑ€Ñ„ĞµĞ¹Ñ Ğ´Ğ»Ñ Ñ…Ñ€Ğ°Ğ½Ğ¸Ğ»Ğ¸Ñ‰Ğ°."""
    @property
    def trades(self) -> Any: ...
    @property
    def positions(self) -> Any: ...
    @property
    def idempotency(self) -> Any: ...


@runtime_checkable
class OrderLike(Protocol):
    """Ğ˜Ğ½Ñ‚ĞµÑ€Ñ„ĞµĞ¹Ñ Ğ´Ğ»Ñ Ğ¾Ñ€Ğ´ĞµÑ€Ğ°."""
    @property
    def filled(self) -> Any: ...
    @property
    def amount(self) -> Any: ...
    @property
    def side(self) -> str: ...
    @property
    def client_order_id(self) -> str: ...


# ---- Ğ‘ĞµĞ·Ğ¾Ğ¿Ğ°ÑĞ½Ñ‹Ğµ Ğ·Ğ°Ğ³Ğ»ÑƒÑˆĞºĞ¸ (Ğ¸ÑĞ¿Ğ¾Ğ»ÑŒĞ·ÑƒÑÑ‚ÑÑ, ĞºĞ¾Ğ³Ğ´Ğ° DMS/LOCK Ğ²Ñ‹ĞºĞ»ÑÑ‡ĞµĞ½Ñ‹) ----

class NoopSafetySwitch(SafetySwitchPort):
    async def start(self) -> None:
        return None

    async def ping(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class NoopInstanceLock(InstanceLockPort):
    async def acquire(self) -> bool:
        return True  # Ğ¿Ğ¾Ğ·Ğ²Ğ¾Ğ»ÑĞµĞ¼ Ğ·Ğ°Ğ¿ÑƒÑĞº (Ğ½ĞµÑ‚ Ñ„Ğ°ĞºÑ‚Ğ¸Ñ‡ĞµÑĞºĞ¾Ğ¹ Ğ±Ğ»Ğ¾ĞºĞ¸Ñ€Ğ¾Ğ²ĞºĞ¸)

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
