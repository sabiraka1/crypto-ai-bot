# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations
import binascii
import re
from typing import Any, Dict, Optional

from crypto_ai_bot.utils.logging import get_logger
from crypto_ai_bot.utils.metrics import inc
from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker  # ваш класс
# предполагается, что self.limiter поддерживает .try_acquire(endpoint)

logger = get_logger(__name__)
_ALLOWED = re.compile(r"[A-Za-z0-9._-]+")

def _gateio_text_from(seed: str) -> str:
    """
    Генерация clientOrderId (Gate: поле text). Должно начинаться с 't-' и <= 28 байт.
    """
    crc = binascii.crc32(seed.encode("utf-8")) & 0xFFFFFFFF
    base = f"t-{crc:08x}"
    # на всякий случай фильтруем
    base = "".join(ch for ch in base if _ALLOWED.match(ch))
    return base[:28]

class CCXTExchange:
    def __init__(self, *, ccxt, settings, limiter: Optional[Any] = None) -> None:
        self.ccxt = ccxt
        self.settings = settings
        self.limiter = limiter
        self.cb = CircuitBreaker(
            name="ccxt_broker",
            fail_threshold=int(getattr(settings, "CB_FAIL_THRESHOLD", 5)),
            open_timeout_sec=float(getattr(settings, "CB_OPEN_TIMEOUT_SEC", 30.0)),
            half_open_max_calls=int(getattr(settings, "CB_HALF_OPEN_CALLS", 1)),
            window_sec=float(getattr(settings, "CB_WINDOW_SEC", 60.0)),
        )
        if hasattr(self.ccxt, "options"):
            self.ccxt.options["createMarketBuyOrderRequiresPrice"] = False

    # --- market meta ---

    def get_market_meta(self, symbol: str) -> Dict[str, Any]:
        m = self.ccxt.market(symbol)
        prec = m.get("precision", {})
        limits = m.get("limits", {}) or {}
        amount_step = limits.get("amount", {}).get("step", None) or 0
        min_amount = limits.get("amount", {}).get("min", None) or 0
        return {
            "amount_step": amount_step,
            "min_amount": min_amount,
            "price_precision": prec.get("price", None),
        }

    # --- basic ops ---

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        self._rl("market_data")
        return self.ccxt.fetch_ticker(symbol)

    async def fetch_open_orders(self, *, symbol: str):
        # оставляем API async-friendly для оркестратора (он вызовет через to_thread)
        self._rl("orders")
        return self.ccxt.fetch_open_orders(symbol)

    def create_order(self, *, symbol: str, type: str, side: str, amount: float, params: Optional[Dict[str, Any]] = None):
        self._rl("orders")
        if not params:
            params = {}
        # clientOrderId / text — здесь, единообразно
        try:
            seed = f"{symbol}:{side}:{amount}"
            params.setdefault("text", _gateio_text_from(seed))
        except Exception:
            pass
        od = self.ccxt.create_order(symbol=symbol, type=type, side=side, amount=amount, params=params)
        inc("broker_create_order_total", {"side": side})
        return od

    # --- helpers ---

    def _rl(self, endpoint: str) -> None:
        if self.limiter and not self.limiter.try_acquire(endpoint):
            raise RuntimeError(f"rate_limit_exceeded:{endpoint}")
