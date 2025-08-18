# src/crypto_ai_bot/core/brokers/base.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class ExchangeInterface(Protocol):
    """
    Минимальный протокол, на который опирается приложение/юзкейсы.
    Реализации: CCXTExchange (live), PaperExchange (paper), BacktestExchange (backtest).
    """
    # --- market data ---
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]: ...

    # --- trading ---
    def create_order(
        self,
        symbol: str,
        type: str,            # 'market' | 'limit'
        side: str,            # 'buy' | 'sell'
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]: ...

    def cancel_order(
        self,
        id: str,
        symbol: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]: ...

    def fetch_order(
        self,
        id: str,
        symbol: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]: ...

    def fetch_open_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]: ...

    # опционально, но полезно для health
    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...


def _mode(settings: Any) -> str:
    m = str(getattr(settings, "MODE", "paper") or "paper").strip().lower()
    # допускаем синонимы
    return {
        "live": "live",
        "prod": "live",
        "production": "live",
        "paper": "paper",
        "papertrading": "paper",
        "sim": "paper",
        "sandbox": "paper",
        "backtest": "backtest",
        "bt": "backtest",
    }.get(m, "paper")


def _exchange_name(settings: Any) -> str:
    # по умолчанию идём в Gate.io (как ты и планируешь)
    return str(getattr(settings, "EXCHANGE", "gateio") or "gateio").strip().lower()


def create_broker(settings: Any, bus: Any = None) -> ExchangeInterface:
    """
    Единая фабрика брокера с явной поддержкой Gate.io через CCXT.
    MODE:   live | paper | backtest
    EXCHANGE: gateio | binance | okx | bybit | ...
    """
    mode = _mode(settings)
    exchange_name = _exchange_name(settings)

    if mode == "live":
        # Основная реализация: CCXT-адаптер.
        # Важно: передаём exchange_name (Gate.io, Binance и т.д.)
        from .ccxt_impl import CCXTExchange
        # избегаем именованных параметров, чтобы не наткнуться на старые сигнатуры
        return CCXTExchange(settings, bus=bus, exchange_name=exchange_name)  # type: ignore[call-arg]

    if mode == "paper":
        # Бумажная торговля (если есть). Иначе — безопасный фоллбек на CCXT в "read-only" режимах.
        try:
            from .paper_exchange import PaperExchange  # твоя реализация, если присутствует
            return PaperExchange(settings, bus=bus, exchange_name=exchange_name)  # type: ignore[call-arg]
        except Exception:
            # Фоллбек: создадим CCXT-адаптер (методы ордеров можно «заглушить» в настройках)
            from .ccxt_impl import CCXTExchange
            return CCXTExchange(settings, bus=bus, exchange_name=exchange_name)  # type: ignore[call-arg]

    if mode == "backtest":
        # Бэктест-адаптер (если есть)
        try:
            from .backtest_exchange import BacktestExchange
            return BacktestExchange(settings, bus=bus, exchange_name=exchange_name)  # type: ignore[call-arg]
        except Exception as e:
            raise RuntimeError("Backtest mode requested but BacktestExchange not available") from e

    # если пришёл неизвестный режим — безопасно отвалимся в paper
    try:
        from .paper_exchange import PaperExchange
        return PaperExchange(settings, bus=bus, exchange_name=exchange_name)  # type: ignore[call-arg]
    except Exception:
        from .ccxt_impl import CCXTExchange
        return CCXTExchange(settings, bus=bus, exchange_name=exchange_name)  # type: ignore[call-arg]
