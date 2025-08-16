# src/crypto_ai_bot/core/brokers/base.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable, Any, Iterable

# ---- Исключения брокера -----------------------------------------------------


class ExchangeError(Exception):
    """Базовая ошибка брокера."""


class TransientExchangeError(ExchangeError):
    """Временная ошибка (retry имеет смысл)."""


class PermanentExchangeError(ExchangeError):
    """Фатальная ошибка (retry не поможет)."""


# ---- Контракт брокера --------------------------------------------------------


@runtime_checkable
class ExchangeInterface(Protocol):
    """
    Единый контракт брокера для live/paper/backtest реализаций.

    ВАЖНО:
    - Деньги/объёмы: Decimal
    - Время: UTC-aware datetime в данных, где применимо
    - Символы/таймфреймы НОРМАЛИЗУЕМ заранее (brokers/symbols.py)
    """

    # Маркет-данные
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list[float]]:
        """Возвращает [[ts_ms, open, high, low, close, volume], ...] длиной <= limit."""

    def fetch_ticker(self, symbol: str) -> dict:
        """Возвращает текущие котировки/спред/прочее в словаре."""

    # Торговля
    def create_order(
        self,
        symbol: str,
        type_: str,  # "market" | "limit"
        side: str,   # "buy" | "sell"
        amount: Decimal,
        price: Decimal | None = None,
        *,
        idempotency_key: str | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        """Создаёт ордер и возвращает нормализованный ответ биржи."""

    def cancel_order(self, order_id: str, *, symbol: str | None = None) -> dict:
        """Отмена ордера."""

    def fetch_balance(self) -> dict:
        """Баланс по аккаунту/валютам."""

    # Ресурсы
    def close(self) -> None:
        """Освобождение сетевых/IO ресурсов клиента."""


# ---- Вспомогательные типы ----------------------------------------------------


@dataclass(frozen=True)
class BrokerInfo:
    name: str         # 'binance', 'bybit', 'paper', 'backtest', ...
    mode: str         # 'live' | 'paper' | 'backtest'


# ---- Фабрика брокеров --------------------------------------------------------


def create_broker(cfg: "Settings") -> ExchangeInterface:
    """
    Единая точка создания брокера по режиму (cfg.MODE).
    Не импортируем реализации на модульном уровне, чтобы исключить циклы и ускорить cold start.
    """
    mode = (getattr(cfg, "MODE", "paper") or "paper").lower()

    if mode == "live":
        from .ccxt_exchange import CcxtExchange
        return CcxtExchange.from_settings(cfg)
    elif mode == "paper":
        from .paper_exchange import PaperExchange
        return PaperExchange.from_settings(cfg)
    elif mode == "backtest":
        from .backtest_exchange import BacktestExchange
        return BacktestExchange.from_settings(cfg)
    else:
        raise ValueError(f"Unknown MODE={cfg.MODE!r}. Expected 'live' | 'paper' | 'backtest'.")


__all__ = [
    "ExchangeError",
    "TransientExchangeError",
    "PermanentExchangeError",
    "ExchangeInterface",
    "BrokerInfo",
    "create_broker",
]
