"""
Live broker implementation - wrapper for CCXT in production mode.

Forces live trading mode with real API keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any

from crypto_ai_bot.core.application.ports import BrokerPort
from crypto_ai_bot.core.infrastructure.brokers.ccxt_adapter import CCXTAdapter
from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


@dataclass
class LiveBroker(CCXTAdapter):
    """
    Live trading broker - forces production mode.

    Extends CCXTAdapter with:
    - Forced live mode (dry_run=False)
    - API credentials validation
    - Additional safety checks
    """

    def __post_init__(self) -> None:
        """Initialize live broker with production settings."""
        # Force live flags before parent init (work with frozen dataclasses too)
        try:
            object.__setattr__(self, "dry_run", False)
            object.__setattr__(self, "mode", "live")
            object.__setattr__(self, "testnet", False)
            object.__setattr__(self, "enable_rate_limit", True)
        except (AttributeError, TypeError):
            # Fallback for non-frozen dataclasses
            self.dry_run = False  # type: ignore[assignment]
            self.mode = "live"  # type: ignore[assignment]
            self.testnet = False  # type: ignore[assignment]
            self.enable_rate_limit = True  # type: ignore[assignment]

        # Initialize parent CCXTAdapter
        super().__post_init__()

        # Validate credentials & environment
        self._validate_credentials()

        # Final sanity: warn if settings/environment looks non-live
        self._warn_if_non_live_context()

        _log.info(
            "live_broker_initialized",
            extra={
                "exchange": getattr(self, "exchange", "unknown"),
                "symbol": getattr(self, "symbol", "ALL"),
                "mode": "LIVE",
                "has_api_key": bool(getattr(self, "api_key", None)),
                "has_api_secret": bool(getattr(self, "api_secret", None)),
                "rate_limit": bool(getattr(self, "enable_rate_limit", True)),
            },
        )

    # ------------- overrides with extra logging -------------

    async def create_market_order(self, *args: Any, **kwargs: Any) -> Any:
        """Create LIVE market order with extra audit logging."""
        self._ensure_live_ready()
        _log.info(
            "live_order_market_create",
            extra={
                "symbol": kwargs.get("symbol"),
                "side": kwargs.get("side"),
                "amount": kwargs.get("amount"),
                "client_order_id": kwargs.get("client_order_id"),
            },
        )

        result = await super().create_market_order(*args, **kwargs)

        _log.info(
            "live_order_market_created",
            extra={
                "order_id": getattr(result, "id", None),
                "status": getattr(getattr(result, "status", None), "value", getattr(result, "status", None)),
                "filled": str(getattr(result, "filled", "")),
            },
        )
        return result

    async def create_limit_order(self, *args: Any, **kwargs: Any) -> Any:
        """Create LIVE limit order with extra audit logging."""
        self._ensure_live_ready()
        _log.info(
            "live_order_limit_create",
            extra={
                "symbol": kwargs.get("symbol"),
                "side": kwargs.get("side"),
                "amount": kwargs.get("amount"),
                "price": kwargs.get("price"),
                "client_order_id": kwargs.get("client_order_id"),
            },
        )

        result = await super().create_limit_order(*args, **kwargs)

        _log.info(
            "live_order_limit_created",
            extra={
                "order_id": getattr(result, "id", None),
                "status": getattr(getattr(result, "status", None), "value", getattr(result, "status", None)),
            },
        )
        return result

    async def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
        """Cancel LIVE order with extra audit logging."""
        self._ensure_live_ready()
        _log.info(
            "live_order_cancel",
            extra={
                "order_id": kwargs.get("order_id"),
                "symbol": kwargs.get("symbol"),
            },
        )

        result = await super().cancel_order(*args, **kwargs)

        _log.info(
            "live_order_cancelled",
            extra={
                "order_id": getattr(result, "id", None),
                "status": getattr(getattr(result, "status", None), "value", getattr(result, "status", None)),
            },
        )
        return result

    # ------------- safety checks -------------

    def _validate_credentials(self) -> None:
        """Validate that API credentials are present for live trading."""
        api_key = getattr(self, "api_key", None)
        api_secret = getattr(self, "api_secret", None)

        if not api_key:
            _log.error("live_missing_api_key", extra={"exchange": getattr(self, "exchange", "unknown")})
            raise ValueError(f"API_KEY is required for live trading on {getattr(self, 'exchange', 'exchange')}")

        if not api_secret:
            _log.error("live_missing_api_secret", extra={"exchange": getattr(self, "exchange", "unknown")})
            raise ValueError(f"API_SECRET is required for live trading on {getattr(self, 'exchange', 'exchange')}")

        # Warn if using suspicious keys
        low = str(api_key).lower()
        if "test" in low or "demo" in low or "paper" in low:
            _log.warning(
                "live_api_key_suspicious",
                extra={"exchange": getattr(self, "exchange", "unknown")},
            )

    def _warn_if_non_live_context(self) -> None:
        """Warn if adapter still looks like test/sandbox."""
        # testnet or dry_run mistakenly enabled?
        if bool(getattr(self, "dry_run", False)) or bool(getattr(self, "testnet", False)):
            _log.warning(
                "live_flags_inconsistent",
                extra={"dry_run": getattr(self, "dry_run", None), "testnet": getattr(self, "testnet", None)},
            )

    def _ensure_live_ready(self) -> None:
        """Runtime assertion before placing/cancelling live orders."""
        if getattr(self, "dry_run", False) or getattr(self, "testnet", False):
            _log.error("live_mode_violation", extra={"dry_run": self.dry_run, "testnet": self.testnet})
            raise RuntimeError("Live orders are not allowed when dry_run/testnet is enabled.")

        if not getattr(self, "api_key", None) or not getattr(self, "api_secret", None):
            _log.error("live_missing_credentials_runtime")
            raise RuntimeError("Missing API credentials for live trading.")

    # ------------- factory -------------

def create_live_broker(
    settings: Settings,
    symbol: Optional[str] = None,
) -> BrokerPort:
    """
    Factory to create live broker instance.

    Args:
        settings: System settings with API credentials
        symbol: Optional trading symbol to focus on

    Returns:
        Configured LiveBroker instance

    Raises:
        ValueError: If API credentials are missing
    """
    if getattr(settings, "MODE", "live") != "live":
        _log.warning("live_broker_non_live_mode", extra={"MODE": getattr(settings, "MODE", None)})

    return LiveBroker(
        exchange=getattr(settings, "EXCHANGE", "binance"),
        api_key=getattr(settings, "API_KEY", None),
        api_secret=getattr(settings, "API_SECRET", None),
        symbol=(symbol or (settings.SYMBOLS[0] if getattr(settings, "SYMBOLS", []) else "BTC/USDT")),
        dry_run=False,            # Always False for live
        mode="live",
        testnet=False,            # Never testnet for live
        rate_limit=True,          # Always respect rate limits in live
        enable_rate_limit=True,
        verbose=False,            # Less verbose in production
    )


# Export
__all__ = [
    "LiveBroker",
    "create_live_broker",
]
