from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

# =========================
#  Сервисные порты/контракты
# =========================


@runtime_checkable
class SafetySwitchPort(Protocol):
    """
    Dead Man's Switch: сервис, который обязан периодически получать ping().
    Если пинги не приходят N секунд — внешний сторож может остановить торговлю/закрыть позиции.
    В базовой реализации может быть no-op.
    """

    async def start(self) -> None: ...
    async def ping(self) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class InstanceLockPort(Protocol):
    """
    Эксклюзивный lock-инстанса: чтобы не запустить два бота на один символ.
    Вернул True при acquire() — значит, мы единственные владельцы.
    """

    async def acquire(self) -> bool: ...
    async def release(self) -> None: ...


@runtime_checkable
class EventBusPort(Protocol):
    """Общий интерфейс для event-bus реализаций."""

    async def publish(self, topic: str, payload: dict[str, Any], key: str | None = None) -> None: ...
    def on(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None: ...
    async def start(self) -> None: ...
    async def close(self) -> None: ...


# =========================
#  Порт брокера (биржи)
# =========================


@dataclass(frozen=True)
class TickerDTO:
    """Опциональный удобный контейнер для тикера (можно продолжать возвращать dict)."""

    last: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    symbol: str | None = None
    timestamp: int | None = None


@runtime_checkable
class BrokerPort(Protocol):
    """
    Интерфейс для адаптеров брокера. Разрешаем возвращать dict (как у ccxt),
    чтобы не ломать существующий код. Если используешь TickerDTO — тоже ок.
    """

    async def fetch_ticker(self, symbol: str) -> Any: ...
    async def fetch_balance(self, symbol: str) -> Any: ...
    async def create_market_buy_quote(
        self, *, symbol: str, quote_amount: Any, client_order_id: str | None = None
    ) -> Any: ...
    async def create_market_sell_base(
        self, *, symbol: str, base_amount: Any, client_order_id: str | None = None
    ) -> Any: ...
    async def fetch_open_orders(self, symbol: str) -> Any: ...
    async def fetch_order(self, *, symbol: str, broker_order_id: str) -> Any: ...


# =========================
#  Порт хранилища (storage)
# =========================


@runtime_checkable
class StoragePort(Protocol):
    """
    Высокоуровневый контракт хранилища. Конкретные репозитории — атрибуты.
    Никаких сигнатур тут не навязываем, чтобы не ломать существующие реализации.
    """

    @property
    def trades(self) -> Any: ...
    @property
    def positions(self) -> Any: ...
    @property
    def idempotency(self) -> Any: ...


# =========================
#  Утилитарный контракт
# =========================


@runtime_checkable
class OrderLike(Protocol):
    """Минимальный контракт «похожего на ордер» объекта для обработчиков."""

    @property
    def filled(self) -> Any: ...
    @property
    def amount(self) -> Any: ...
    @property
    def side(self) -> str: ...
    @property
    def client_order_id(self) -> str: ...


# =========================
#  Базовые no-op реализации
# =========================


class NoopSafetySwitch(SafetySwitchPort):
    async def start(self) -> None:
        return None

    async def ping(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class NoopInstanceLock(InstanceLockPort):
    async def acquire(self) -> bool:
        # Позволяем запуститься (нет фактической блокировки)
        return True

    async def release(self) -> None:
        return None


__all__ = [
    # сервисы
    "SafetySwitchPort",
    "InstanceLockPort",
    "EventBusPort",
    "NoopSafetySwitch",
    "NoopInstanceLock",
    # брокер
    "BrokerPort",
    "TickerDTO",
    # storage / утилиты
    "StoragePort",
    "OrderLike",
]
