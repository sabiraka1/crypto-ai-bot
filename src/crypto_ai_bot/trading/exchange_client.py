# src/crypto_ai_bot/trading/exchange_client.py

import logging
import time

from crypto_ai_bot.core.metrics import FETCH_OHLCV_LATENCY

logger = logging.getLogger(__name__)


class ExchangeClient:
    # ... твой существующий код (__init__, auth и т.п.) ...

    def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200):
        """
        Унифицированный метод получения OHLCV.
        Возвращает CCXT-совместимый список: [[ts, open, high, low, close, volume], ...]
        """
        try:
            # 1) Если у самого объекта есть ccxt-совместный метод
            fetch = getattr(self, "fetch_ohlcv", None)
            if callable(fetch):
                t0 = time.perf_counter()
                ohlcv = fetch(symbol, timeframe=timeframe, limit=limit)
                FETCH_OHLCV_LATENCY.observe(time.perf_counter() - t0)
                logger.debug(f"📊 Fetched {len(ohlcv)} candles for {symbol} via self.fetch_ohlcv")
                return ohlcv

            # 2) Если внутри хранится реальный ccxt-клиент
            for attr in ("client", "api", "exchange"):
                obj = getattr(self, attr, None)
                fetch = getattr(obj, "fetch_ohlcv", None) if obj is not None else None
                if callable(fetch):
                    t0 = time.perf_counter()
                    ohlcv = fetch(symbol, timeframe=timeframe, limit=limit)
                    FETCH_OHLCV_LATENCY.observe(time.perf_counter() - t0)
                    logger.debug(f"📊 Fetched {len(ohlcv)} candles for {symbol} via self.{attr}.fetch_ohlcv")
                    return ohlcv

            # 3) Если не нашли, явно сигнализируем
            raise NotImplementedError(
                "ExchangeClient.get_ohlcv: implement .fetch_ohlcv() "
                "или предоставьте self.client/self.api/self.exchange с .fetch_ohlcv()."
            )

        except NotImplementedError:
            # Re-raise implementation errors без дополнительного логирования
            raise
        except Exception as e:
            logger.error(f"❌ OHLCV fetch failed for {symbol} {timeframe}: {e}")
            # Re-raise для сохранения стека вызовов
            raise


# ── Опциональные исключения для лучшей диагностики ──────────────────────────
class APIException(Exception):
    """Ошибка API биржи"""
    pass


class NetworkException(Exception):
    """Сетевая ошибка"""
    pass


# ── Экспорт ──────────────────────────────────────────────────────────────────
__all__ = ["ExchangeClient", "APIException", "NetworkException"]
