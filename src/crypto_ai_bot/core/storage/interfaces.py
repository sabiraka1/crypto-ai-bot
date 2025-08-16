# src/crypto_ai_bot/core/storage/interfaces.py
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable, Iterable, Any


# ---------- Ошибки/исключения хранилища ----------
class StorageError(Exception): ...
class ConflictError(StorageError): ...
class NotFoundError(StorageError): ...


# ---------- Общая транзакция/контейнер ----------
class Transaction(AbstractContextManager):
    """База для контекстного менеджера транзакций (BEGIN..COMMIT/ROLLBACK)."""
    def __exit__(self, exc_type, exc, tb) -> bool:  # pragma: no cover
        return False


class Repositories(Protocol):
    """
    Контейнер с репозиториями и (опционально) транзакцией.
    Реализация (например, sqlite_adapter) должна предоставить эти атрибуты.
    """
    # обязательные репозитории:
    idempotency: "IdempotencyRepository"
    trades: "TradeRepository"           # реализуй по своему контракту
    positions: "PositionRepository"     # реализуй по своему контракту
    audit: "AuditRepository"

    # опционально:
    def transaction(self) -> Transaction: ...
    # либо атрибут txn/contextmanager, если так удобнее в твоём адаптере


# ---------- Идемпотентность ----------
@dataclass(frozen=True)
class IdemStatus:
    key: str
    state: str   # "claimed" | "committed"
    ttl_seconds: int

@runtime_checkable
class IdempotencyRepository(Protocol):
    """
    Репозиторий идемпотентности на уровне приложения.
    Семантика:
      - claim(key, ttl): если ключ свободен или истёк → занять, вернуть True.
                         если уже активен → False (дубликат).
      - commit(key): помечает «успешно завершено», чтобы повтор не выполнялся.
      - release(key): освобождает ключ (например, при ошибке).
      - exists_active(key): активен ли ключ (claimed/committed и не истёк).
      - purge_expired(): удалить протухшие записи, вернуть кол-во.
    """
    def claim(self, key: str, ttl_seconds: int, payload: dict | None = None) -> bool: ...
    def commit(self, key: str) -> None: ...
    def release(self, key: str) -> None: ...
    def exists_active(self, key: str) -> bool: ...
    def purge_expired(self) -> int: ...
    def get(self, key: str) -> IdemStatus | None: ...


# ---------- Простейшие контракты доменных репозиториев ----------
# Ниже — легкие заглушки интерфейсов, чтобы use_cases не зависел от конкретной реализации.

@runtime_checkable
class AuditRepository(Protocol):
    def log_event(self, event_type: str, data: dict) -> None: ...

@runtime_checkable
class TradeRepository(Protocol):
    def insert_raw_order(self, order: dict) -> None: ...
    # добавляй методы под свою доменную модель

@runtime_checkable
class PositionRepository(Protocol):
    def upsert_position(self, pos: dict) -> None: ...
    # добавляй методы под свою доменную модель
