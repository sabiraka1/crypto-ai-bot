# conftest.py
from __future__ import annotations

import asyncio
import os
import random
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from typing import Any, AsyncIterator, Dict, Iterable, Optional

import pytest

# ---------- PyTest / asyncio loop ----------

@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:
    """
    Session-scoped event loop (совместимо с pytest-asyncio).
    Нужен особенно на Windows, где default policy капризничает.
    """
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


# ---------- Decimal / randomness hygiene ----------

@pytest.fixture(autouse=True, scope="session")
def _decimal_global_precision() -> None:
    """
    Единая точность для всех тестов (меньше расхождений при расчетах).
    """
    ctx = getcontext()
    ctx.prec = 28  # совпадает с финанс. расчётами проекта
    ctx.rounding = "ROUND_HALF_EVEN"


@pytest.fixture(autouse=True)
def _reseed() -> None:
    random.seed(1337)


# ---------- Helpers: safe imports & stubs ----------

def _try_import(path: str, name: str) -> Any:
    """
    Импорт с мягким фолбэком: если модуля нет,
    возвращаем None и даём фикстуре решить, что делать.
    """
    try:
        module = __import__(path, fromlist=[name])
        return getattr(module, name)
    except Exception:
        return None


# Contracts (если есть)
BrokerPort = _try_import("crypto_ai_bot.core.application.ports", "BrokerPort")
EventBusPort = _try_import("crypto_ai_bot.core.application.ports", "EventBusPort")
MetricsPort = _try_import("crypto_ai_bot.core.application.ports", "MetricsPort")
TickerDTO = _try_import("crypto_ai_bot.core.application.ports", "TickerDTO")

Settings = _try_import("crypto_ai_bot.core.infrastructure.settings", "Settings")
create_broker = _try_import("crypto_ai_bot.core.infrastructure.brokers.factory", "create_broker")

Candle = _try_import("crypto_ai_bot.core.domain.signals.feature_pipeline", "Candle")
CCXTMarketData = _try_import("crypto_ai_bot.core.infrastructure.market_data.ccxt_market_data", "CCXTMarketData")


# ---------- Env helper ----------

@contextmanager
def _temp_env(**pairs: str) -> Any:
    prev: Dict[str, Optional[str]] = {}
    try:
        for k, v in pairs.items():
            prev[k] = os.environ.get(k)
            os.environ[k] = v
        yield
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------- Core fixtures ----------

@pytest.fixture(scope="session")
def settings() -> Any:
    """
    Тестовые настройки. Если есть Settings.load() — используем её,
    иначе собираем минимальный dataclass-аналог.
    """
    if Settings and hasattr(Settings, "load"):
        with _temp_env(
            MODE="paper",
            EXCHANGE="binance",
            API_KEY="test_key",
            API_SECRET="test_secret",
            SYMBOLS='["BTC/USDT","ETH/USDT"]',
        ):
            return Settings.load()  # type: ignore[no-any-return]
    # Фолбэк — лёгкая заглушка
    @dataclass
    class _S:
        MODE: str = "paper"
        EXCHANGE: str = "binance"
        API_KEY: str = "test_key"
        API_SECRET: str = "test_secret"
        SYMBOLS: list[str] = ("BTC/USDT", "ETH/USDT")
    return _S()


@pytest.fixture(scope="session")
def symbol(settings: Any) -> str:
    symbols = getattr(settings, "SYMBOLS", None) or ["BTC/USDT"]
    return symbols[0]


@pytest.fixture(scope="session")
def paper_broker(settings: Any, symbol: str) -> Any:
    """
    Бумажный брокер через фабрику, если доступна.
    Если фабрики/реализации нет — даём минимальный стаб, совместимый с BrokerPort.
    """
    if create_broker:
        try:
            return create_broker(settings, symbol)  # type: ignore[misc]
        except Exception:
            pass

    # ---- Stub BrokerPort ----
    class _StubBroker:
        exchange = "stub"
        symbol = symbol

        async def fetch_ticker(self, sym: str) -> Any:
            ts = datetime.now(timezone.utc)
            if TickerDTO:
                return TickerDTO(  # type: ignore[call-arg]
                    symbol=sym,
                    last=Decimal("30000"),
                    bid=Decimal("29995"),
                    ask=Decimal("30005"),
                    spread_pct=Decimal("0.033"),
                    volume_24h=Decimal("123.45"),
                    timestamp=ts,
                )
            return {
                "symbol": sym, "last": Decimal("30000"), "bid": Decimal("29995"),
                "ask": Decimal("30005"), "volume_24h": Decimal("123.45"), "timestamp": ts,
            }

        async def create_market_order(self, *args: Any, **kwargs: Any) -> dict:
            return {"id": "stub-order-1", "status": "filled", "filled": "1.0"}

    return _StubBroker()


@pytest.fixture(scope="session")
def market_data(paper_broker: Any) -> Any:
    """
    CCXTMarketData, если доступен; иначе — легкая заглушка с теми же методами.
    """
    if CCXTMarketData:
        try:
            return CCXTMarketData(broker=paper_broker, cache_ttl_sec=0.01)  # type: ignore[call-arg]
        except Exception:
            pass

    class _StubData:
        async def get_ticker(self, sym: str) -> Any:
            return await paper_broker.fetch_ticker(sym)

        async def get_ohlcv(self, sym: str, timeframe: str = "15m", limit: int = 100) -> list[Any]:
            return []  # тесты сами подставят свечи

    return _StubData()


# ---------- Event bus / metrics stubs ----------

@pytest.fixture
def fake_event_bus() -> Any:
    """
    Простая реализация EventBusPort: складывает опубликованные сообщения в память.
    """
    class _Bus:
        def __init__(self) -> None:
            self.messages: list[tuple[str, dict]] = []

        async def publish(self, topic: str, payload: dict) -> None:
            self.messages.append((topic, payload))

    return _Bus()


@pytest.fixture
def fake_metrics() -> Any:
    """
    Минимальные метрики c in-memory storage.
    """
    class _Metrics:
        def __init__(self) -> None:
            self.gauges: dict[str, float] = {}
            self.counters: dict[str, int] = {}

        def gauge(self, name: str, value: float) -> None:
            self.gauges[name] = float(value)

        def incr(self, name: str, value: int = 1) -> None:
            self.counters[name] = self.counters.get(name, 0) + int(value)

    return _Metrics()


# ---------- Test candles / features ----------

def _mk_candle(ts: datetime, o: float, h: float, l: float, c: float, v: float) -> Any:
    if Candle:
        return Candle(
            timestamp=ts,
            open=Decimal(str(o)),
            high=Decimal(str(h)),
            low=Decimal(str(l)),
            close=Decimal(str(c)),
            volume=Decimal(str(v)),
        )
    # Фолбэк — tuple CCXT-вида
    ms = int(ts.timestamp() * 1000)
    return [ms, o, h, l, c, v]


@pytest.fixture
def ohlcv_15m() -> list[Any]:
    """
    Небольшой набор свечей 15m (растущий тренд, лёгкая волатильность).
    Подходит для тестов индикаторов и стратегий.
    """
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    base = 30000.0
    out: list[Any] = []
    for i in range(120):
        t = now - timedelta(minutes=15 * (120 - i))
        close = base + i * 10.0 + (1 if i % 5 else -5)  # мягкий ап-тренд
        o = close - 5
        h = close + 15
        l = close - 25
        v = 100 + (i % 7) * 3
        out.append(_mk_candle(t, o, h, l, close, v))
    return out


@pytest.fixture
def ohlcv_1h() -> list[Any]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    base = 30000.0
    out: list[Any] = []
    for i in range(240):
        t = now - timedelta(hours=(240 - i))
        close = base + i * 40.0 + (10 if i % 6 else -30)
        o = close - 20
        h = close + 60
        l = close - 80
        v = 500 + (i % 5) * 10
        out.append(_mk_candle(t, o, h, l, close, v))
    return out


# ---------- Async helper for tests ----------

@pytest.fixture
def run_async(event_loop: asyncio.AbstractEventLoop):
    """
    Позволяет запускать корутины из синхронных тестов:
        result = run_async(coro())
    """
    def _run(coro: Any) -> Any:
        return event_loop.run_until_complete(coro)
    return _run
