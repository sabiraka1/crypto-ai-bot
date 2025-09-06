"""
Broker factory - creates appropriate broker based on mode and exchange.

Supports:
- paper mode: PaperBroker for testing
- live mode: CCXT-based LiveBroker with real exchange
"""
from __future__ import annotations

from typing import Optional

from crypto_ai_bot.core.application.ports import BrokerPort
from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


# ------------------------- helpers -------------------------

def _get_mode(settings: Settings) -> str:
    try:
        return str(getattr(settings, "MODE", "live")).lower()
    except Exception:
        return "live"


def _get_exchange(settings: Settings) -> str:
    try:
        return str(getattr(settings, "EXCHANGE", "binance")).lower()
    except Exception:
        return "binance"


def _pick_symbol(settings: Settings, symbol: Optional[str]) -> str:
    if symbol:
        return symbol
    try:
        syms = getattr(settings, "SYMBOLS", None) or []
        if isinstance(syms, (list, tuple)) and syms:
            return str(syms[0])
    except Exception:
        pass
    return "BTC/USDT"


# ------------------------- public API -------------------------

def create_broker(
    settings: Settings,
    symbol: Optional[str] = None,
) -> BrokerPort:
    """
    Create broker instance based on settings.

    Args:
        settings: System settings with mode and credentials
        symbol: Optional trading symbol

    Returns:
        BrokerPort implementation (PaperBroker or LiveBroker)

    Raises:
        ValueError: If mode or exchange is unsupported
    """
    mode = _get_mode(settings)
    exchange = _get_exchange(settings)
    sym = _pick_symbol(settings, symbol)

    _log.info(
        "broker_factory_create",
        extra={"mode": mode, "exchange": exchange, "symbol": sym},
    )

    if mode in ("paper", "test", "sim", "simulation"):
        return _create_paper_broker(settings, sym)

    if mode in ("live", "real", "prod", "production"):
        return _create_live_broker(settings, sym, exchange)

    raise ValueError(f"Unsupported MODE={mode}. Use 'paper' or 'live'.")


# ------------------------- paper -------------------------

def _create_paper_broker(
    settings: Settings,
    symbol: str,
) -> BrokerPort:
    """Create paper broker for testing."""
    try:
        from crypto_ai_bot.core.infrastructure.brokers.paper import PaperBroker

        _log.info("paper_broker_create", extra={"symbol": symbol})
        return PaperBroker(
            settings=settings,
            symbol=symbol,
            initial_balance={"USDT": 10_000.0},  # 10k USDT
            fee_rate=0.001,  # 0.1% fee
        )

    except ImportError as e:
        _log.error("paper_broker_import_failed", extra={"error": str(e)})
        raise ImportError("PaperBroker not found. Ensure paper.py is implemented.") from e


# ------------------------- live -------------------------

def _create_live_broker(
    settings: Settings,
    symbol: str,
    exchange: str = "gateio",
) -> BrokerPort:
    """Create live broker for real trading."""
    api_key = getattr(settings, "API_KEY", None)
    api_secret = getattr(settings, "API_SECRET", None)
    if not api_key or not api_secret:
        raise ValueError("API_KEY and API_SECRET are required for live trading.")

    # Prefer a curated mapping; fall back to generic CCXT id
    x = exchange.lower()
    if x in {"gateio", "gate"}:
        ccxt_id = "gateio"
    elif x in {"binance", "binanceus"}:
        ccxt_id = x
    elif x in {"coinbase", "coinbasepro"}:
        ccxt_id = "coinbasepro"
    elif x in {"kraken"}:
        ccxt_id = "kraken"
    elif x in {"okx", "okex"}:
        ccxt_id = "okx"
    else:
        ccxt_id = x

    return _create_ccxt_broker(settings, symbol, ccxt_id)


def _create_ccxt_broker(
    settings: Settings,
    symbol: str,
    exchange_id: str,
) -> BrokerPort:
    """Create CCXT-based LiveBroker (preferred) or fall back to CCXTAdapter."""
    try:
        # Preferred: our hardened LiveBroker wrapper
        from crypto_ai_bot.core.infrastructure.brokers.live import LiveBroker

        _log.info(
            "live_broker_create",
            extra={"exchange": exchange_id, "symbol": symbol},
        )
        return LiveBroker(
            exchange=exchange_id,
            api_key=getattr(settings, "API_KEY", None),
            api_secret=getattr(settings, "API_SECRET", None),
            api_password=getattr(settings, "API_PASSWORD", None),
            symbol=symbol,
            testnet=False,
            dry_run=False,
            mode="live",
            rate_limit=True,
            enable_rate_limit=True,
            verbose=False,
        )

    except ImportError:
        # Fallback: generic CCXTAdapter
        try:
            from crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter import CCXTAdapter

            _log.info(
                "ccxt_adapter_create",
                extra={"exchange": exchange_id, "symbol": symbol},
            )
            return CCXTAdapter(
                exchange=exchange_id,
                api_key=getattr(settings, "API_KEY", None),
                api_secret=getattr(settings, "API_SECRET", None),
                api_password=getattr(settings, "API_PASSWORD", None),
                symbol=symbol,
                testnet=False,
                dry_run=False,
                rate_limit=True,
                enable_rate_limit=True,
                verbose=False,
            )
        except ImportError as e:
            _log.error("ccxt_adapter_import_failed", extra={"error": str(e)})

    # Last resort: try to instantiate raw ccxt exchange and wrap it
    try:
        import ccxt

        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"Exchange '{exchange_id}' not supported by CCXT.")

        _log.warning("ccxt_raw_exchange_create", extra={"exchange": exchange_id})

        exchange_class = getattr(ccxt, exchange_id)
        exchange_instance = exchange_class({
            "apiKey": getattr(settings, "API_KEY", None),
            "secret": getattr(settings, "API_SECRET", None),
            "password": getattr(settings, "API_PASSWORD", None),
            "timeout": 30000,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

        from crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter import CCXTAdapter

        return CCXTAdapter(
            exchange=exchange_instance,  # type: ignore[arg-type]
            symbol=symbol,
        )

    except Exception as e2:
        _log.error("ccxt_raw_exchange_failed", extra={"exchange": exchange_id, "error": str(e2)})
        raise ImportError(f"Cannot create broker for exchange '{exchange_id}'.") from e2


# ------------------------- utils -------------------------

def validate_exchange_support(exchange: str) -> bool:
    """
    Check if exchange is supported by CCXT.

    Args:
        exchange: Exchange name

    Returns:
        True if supported
    """
    try:
        import ccxt
        return hasattr(ccxt, exchange.lower())
    except Exception:
        return False


def list_supported_exchanges() -> list[str]:
    """
    Get list of supported exchanges.

    Returns:
        List of exchange names
    """
    try:
        import ccxt
        return list(getattr(ccxt, "exchanges", []))
    except Exception:
        # Fallback to a conservative static set
        return [
            "gateio",
            "binance",
            "coinbasepro",
            "kraken",
            "okx",
            "bybit",
            "kucoin",
            "bitget",
            "mexc",
            "huobi",
        ]


# Export
__all__ = [
    "create_broker",
    "validate_exchange_support",
    "list_supported_exchanges",
]
