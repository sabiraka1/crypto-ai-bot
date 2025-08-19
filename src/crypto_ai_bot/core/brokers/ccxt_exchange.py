# src/crypto_ai_bot/core/brokers/ccxt_exchange.py
from __future__ import annotations

import logging
import time
import random
import string
from typing import Any, Dict, List, Optional, Tuple

from crypto_ai_bot.utils.circuit_breaker import CircuitBreaker

logger = logging.getLogger("brokers.ccxt_exchange")

# --- optional imports (graceful fallback) ---
try:
    from crypto_ai_bot.utils.metrics import inc, observe_histogram
except Exception:  # no metrics – provide stubs
    def inc(*args, **kwargs): return None
    def observe_histogram(*args, **kwargs): return None

try:
    from crypto_ai_bot.utils.rate_limit import MultiLimiter, TokenBucket  # optional
except Exception:
    MultiLimiter = None
    TokenBucket = None

# --- ccxt imports ---
try:
    import ccxt
    from ccxt.base.errors import (
        DDoSProtection, RateLimitExceeded, ExchangeNotAvailable, NetworkError,
        RequestTimeout, AuthenticationError, PermissionDenied,
        InvalidOrder, InsufficientFunds, OrderNotFound
    )
except Exception as e:  # pragma: no cover
    ccxt = None
    # Оставляем импорт ошибок пустым — пробросим generic Exception при использовании.

# -------------------------
# helpers
# -------------------------

def _kind_from_exc(e: Exception) -> str:
    if isinstance(e, (RateLimitExceeded, DDoSProtection)):
        return "rate_limit"
    if isinstance(e, (NetworkError, ExchangeNotAvailable, RequestTimeout)):
        return "network"
    if isinstance(e, (AuthenticationError, PermissionDenied)):
        return "auth"
    if isinstance(e, (InvalidOrder, InsufficientFunds, OrderNotFound)):
        return "order"
    return "unknown"


def _safe_get(d: Dict[str, Any], *keys, default=None):
    cur = d or {}
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _now_ms() -> int:
    return int(time.time() * 1000)


# -------------------------
# Per-endpoint limiter (fallback)
# -------------------------

class _LocalTokenBucket:
    """Простой токен-бакет, если нет utils.rate_limit."""
    def __init__(self, capacity: int, interval_s: float) -> None:
        self.capacity = max(1, int(capacity))
        self.tokens = float(self.capacity)
        self.interval_s = float(interval_s)
        self.last = time.monotonic()

    def try_acquire(self, tokens: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last
        # пополнение токенов
        self.tokens = min(self.capacity, self.tokens + (self.capacity * (elapsed / self.interval_s)))
        self.last = now
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


class _GateIOLimiter:
    """
    Per-endpoint buckets: orders / market_data / account.
    Если в проекте есть MultiLimiter/TokenBucket — используем их.
    Иначе – локальная fallback-реализация.
    """
    def __init__(self) -> None:
        if TokenBucket and MultiLimiter:
            self.buckets = {
                "orders": TokenBucket(100, 10.0),       # 100 calls / 10s
                "market_data": TokenBucket(600, 10.0),  # 600 calls / 10s
                "account": TokenBucket(300, 10.0),      # 300 calls / 10s
            }
        else:
            self.buckets = {
                "orders": _LocalTokenBucket(100, 10.0),
                "market_data": _LocalTokenBucket(600, 10.0),
                "account": _LocalTokenBucket(300, 10.0),
            }

    def try_acquire(self, endpoint: str, tokens: float = 1.0) -> bool:
        bucket = self.buckets.get(endpoint) or self.buckets["orders"]
        return bucket.try_acquire(tokens)


# -------------------------
# CCXT wrapper
# -------------------------

class CCXTExchange:
    """
    Тонкая обёртка CCXT с:
      - CircuitBreaker + экспоненциальные ретраи
      - Per-endpoint rate limits
      - Централизованный clientOrderId (Gate `text`)
    """

    def __init__(self, settings: Any, bus: Optional[Any] = None) -> None:
        if ccxt is None:  # pragma: no cover
            raise RuntimeError("ccxt is not installed")

        name = str(getattr(settings, "EXCHANGE", "gateio")).lower()
        klass = getattr(ccxt, name, None)
        if klass is None:
            raise RuntimeError(f"Unsupported exchange: {name}")

        self.ccxt = klass({
            "apiKey": getattr(settings, "API_KEY", None),
            "secret": getattr(settings, "API_SECRET", None),
            "enableRateLimit": True,
            # можно добавить таймауты/прокси по нужде
        })
        self.bus = bus
        self.settings = settings

        self.cb = CircuitBreaker(name=f"ccxt:{name}")
        self.limiter = _GateIOLimiter()

        # загрузка маркетов один раз
        try:
            self.ccxt.load_markets()
            self.cb.record_success()
        except Exception as e:
            self.cb.record_error(_kind_from_exc(e), e)
            raise

        self.exchange_id = self.ccxt.id

    # ---------- private ----------

    async def _sleep(self, seconds: float) -> None:
        # делаем локальный async sleep, чтобы не тянуть asyncio тут
        # этот метод может быть заменён на asyncio.sleep в async-обвязках
        time.sleep(seconds)

    def _rl(self, endpoint: str) -> None:
        if not self.limiter.try_acquire(endpoint):
            # backoff ~50-100ms пока не появится токен
            # (CCXT всё равно держит свой enableRateLimit, мы просто сглаживаем пики)
            time.sleep(0.05)

    def _with_retries(self, endpoint: str, fn, *args, **kwargs):
        """
        Ретраи с CB и небольшим экспоненциальным backoff + jitter.
        """
        if not self.cb.allow():
            inc("ccxt_circuit_open_total", {"endpoint": endpoint})
            raise RateLimitExceeded("circuit_open")

        attempts = int(getattr(self.settings, "EXCHANGE_MAX_ATTEMPTS", 4))
        base = float(getattr(self.settings, "EXCHANGE_RETRY_BASE_S", 0.1))
        last_exc: Optional[Exception] = None

        for i in range(1, attempts + 1):
            try:
                self._rl(endpoint)
                t0 = time.perf_counter()
                res = fn(*args, **kwargs)
                dt = (time.perf_counter() - t0) * 1000.0
                observe_histogram("ccxt_latency_ms", dt, {"endpoint": endpoint})
                self.cb.record_success()
                return res
            except Exception as e:
                kind = _kind_from_exc(e)
                self.cb.record_error(kind, e)
                last_exc = e
                inc("ccxt_errors_total", {"endpoint": endpoint, "kind": kind})

                # Не ретраим логические ошибки
                if isinstance(e, (InvalidOrder, InsufficientFunds, AuthenticationError, PermissionDenied)):
                    raise

                # backoff
                if i < attempts:
                    # экспонента + джиттер
                    sleep_s = base * (2 ** (i - 1))
                    sleep_s *= (0.85 + random.random() * 0.3)  # +-15%
                    time.sleep(min(1.0, sleep_s))
                else:
                    break

        # все попытки исчерпаны
        raise last_exc if last_exc else RuntimeError("ccxt call failed")

    def _gate_text_from(self, *, symbol: str, side: str) -> str:
        """
        Строгое формирование clientOrderId для Gate.io (param: text).
        Требования Gate: начинаться с 't-', <= 28 bytes, [A-Za-z0-9._-]
        """
        # Минимальная энтропия и привязка к операции
        ts = int(time.time() * 1000) % 10_000_000
        base = f"{symbol}:{side}:{ts}"
        # простой base36+резка
        base36 = "".join([(c if c.isalnum() else "-") for c in base])
        text = f"t-{base36}"[:28]
        return text

    # ---------- public ----------
    # NB: Сигнатуры оставлены совместимыми с ccxt

    def fetch_ticker(self, symbol: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._with_retries("market_data", self.ccxt.fetch_ticker, symbol, params or {})

    def fetch_balance(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._with_retries("account", self.ccxt.fetch_balance, params or {})

    def fetch_open_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return self._with_retries("orders", self.ccxt.fetch_open_orders, symbol, since, limit, params or {})

    def fetch_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._with_retries("orders", self.ccxt.fetch_order, id, symbol, params or {})

    def cancel_order(self, id: str, symbol: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._with_retries("orders", self.ccxt.cancel_order, id, symbol, params or {})

    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Централизованная точка создания ордеров:
          - per-endpoint rate limit
          - clientOrderId для Gate (param: text)
          - корректная обработка MARKET BUY для Gate (amount = QUOTE)
        """
        p = dict(params or {})

        # Gate.io: обязательный client id (text). Если не задан — ставим тут.
        if (self.exchange_id == "gateio") and ("text" not in p):
            # NB: генерим здесь ЕДИНЫЙ clientOrderId → не дублировать в верхних слоях
            p["text"] = self._gate_text_from(symbol=symbol, side=side)

            # Для MARKET BUY Gate может требовать отключение "requires price" флага
            if type.lower() == "market" and side.lower() == "buy":
                # если верхний уровень уже проставил — оставим; иначе – установим
                p.setdefault("createMarketBuyOrderRequiresPrice", False)

        # Основной вызов
        return self._with_retries("orders", self.ccxt.create_order, symbol, type, side, amount, price, p)
