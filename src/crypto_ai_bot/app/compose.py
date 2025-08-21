# src/crypto_ai_bot/app/compose.py
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

from crypto_ai_bot.core.events.bus import AsyncEventBus
from crypto_ai_bot.core.storage.facade import Storage
from crypto_ai_bot.core.brokers.base import IBroker
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.utils.logging import get_logger


@dataclass
class Container:
    settings: Settings
    db: sqlite3.Connection | None
    bus: AsyncEventBus

    # ленивые билдеры, чтобы не ломать фундамент пока нет реализаций
    _storage_builder: Callable[[], Storage]
    _broker_builder: Callable[[], IBroker]

    _storage: Optional[Storage] = None
    _broker: Optional[IBroker] = None

    @property
    def storage(self) -> Storage:
        if self._storage is None:
            self._storage = self._storage_builder()
        return self._storage

    @property
    def broker(self) -> IBroker:
        if self._broker is None:
            self._broker = self._broker_builder()
        return self._broker


def _connect_db(path: str) -> sqlite3.Connection:
    # Минимальный SQLite-коннект с безопасными PRAGMA; миграции добавим на этапе Storage impl
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)  # autocommit
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.close()
    return conn


def _make_storage_builder(db_conn: sqlite3.Connection) -> Callable[[], Storage]:
    def _builder() -> Storage:
        # Делегируем создание в фасад; он подцепит конкретные репозитории, когда они появятся
        return Storage.from_connection(db_conn)
    return _builder


def _make_broker_builder(settings: Settings) -> Callable[[], IBroker]:
    def _builder() -> IBroker:
        # Подхватываем реализацию динамически, чтобы не тащить зависимость раньше времени
        if settings.MODE == "paper":
            mod_name = "crypto_ai_bot.core.brokers.backtest_exchange"
            cls_name = "BacktestBroker"
        else:
            mod_name = "crypto_ai_bot.core.brokers.ccxt_exchange"
            cls_name = "CCXTBroker"

        mod = __import__(mod_name, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        return cls(settings)  # type: ignore[no-any-return]
    return _builder


def build_container() -> Container:
    """Собирает зависимости в правильном порядке: settings → db → storage/broker → event bus."""
    log = get_logger("compose")
    settings = Settings.load()
    db = _connect_db(settings.DB_PATH)
    bus = AsyncEventBus()
    log.info("container: settings/db/bus инициализированы")

    return Container(
        settings=settings,
        db=db,
        bus=bus,
        _storage_builder=_make_storage_builder(db),
        _broker_builder=_make_broker_builder(settings),
    )
