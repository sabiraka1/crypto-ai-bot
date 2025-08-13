# src/crypto_ai_bot/trading/exchange_client.py
from __future__ import annotations

import logging
import time
from typing import Any, Optional, List

from crypto_ai_bot.core.metrics import FETCH_OHLCV_LATENCY

logger = logging.getLogger(__name__)


class ExchangeClient:
    """
    Унифицированный клиент:
      - пробует ccxt (по умолчанию gateio)
      - если нет ccxt или не удалось создать клиента — публичный HTTP фолбэк (Binance)
    """

    def __init__(self, settings: Optional[Any] = None):
        self.settings = settings
        self.client = None  # ccxt клиент (если получится)

        # как называем биржу: settings.EXCHANGE_NAME или 'gateio'
        ex_name = None
        if settings and hasattr(settings, "EXCHANGE_NAME"):
            ex_name = getattr(settings, "EXCHANGE_NAME")
        if not ex_name:
            ex_name = "gateio"

        # пытаемся поднять ccxt
        try:
            import ccxt  # type: ignore

            if not hasattr(ccxt, ex_name):
                logger.warning(f"ccxt: exchange '{ex_name}' не найден, используем binance")
                ex_name = "binance"

            cls = getattr(ccxt, ex_name)
            kwargs = dict(enableRateLimit=True)
            # ключи не нужны для OHLCV, но если заданы — подключим
            if settings:
                key = getattr(settings, "API_KEY", None)
                sec = getattr(settings, "API_SECRET", None)
                if key and sec:
                    kwargs.update(apiKey=key, secret=sec)
            self.client = cls(kwargs)
            # некоторые реализации ccxt требуют .load_markets()
            if hasattr(self.client, "load_markets"):
                self.client.load_markets()
            logger.info(f"ccxt client ready: {ex_name}")
        except Exception as e:
            logger.warning(f"ccxt недоступен или не инициализировался ({e}). Включен HTTP фолбэк.")

    # --- публичный API бота ---------------------------------------------------
    def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List[list]:
        """
        Унифицированный метод получения OHLCV.
        Возвращает список: [[ts_ms, open, high, low, close, volume], ...]
        """
        try:
            # Путь 1: если у объекта есть свой fetch_ohlcv (ниже реализуем)
            fetch = getattr(self, "fetch_ohlcv", None)
            if callable(fetch):
                t0 = time.perf_counter()
                ohlcv = fetch(symbol, timeframe=timeframe, limit=limit)
                FETCH_OHLCV_LATENCY.observe(time.perf_counter() - t0)
                logger.debug(f"📊 Fetched {len(ohlcv)} candles for {symbol} via self.fetch_ohlcv")
                return ohlcv

            # Путь 2: если внутри есть реальный ccxt-клиент
            for attr in ("client", "api", "exchange"):
                obj = getattr(self, attr, None)
                fetch = getattr(obj, "fetch_ohlcv", None) if obj is not None else None
                if callable(fetch):
                    t0 = time.perf_counter()
                    ohlcv = fetch(symbol, timeframe=timeframe, limit=limit)
                    FETCH_OHLCV_LATENCY.observe(time.perf_counter() - t0)
                    logger.debug(f"📊 Fetched {len(ohlcv)} candles for {symbol} via self.{attr}.fetch_ohlcv")
                    return ohlcv

            # Если ни один путь не найден — это ошибка дизайна
            raise NotImplementedError(
                "ExchangeClient.get_ohlcv: implement .fetch_ohlcv() "
                "или предоставьте self.client/self.api/self.exchange с .fetch_ohlcv()."
            )
        except NotImplementedError:
            raise
        except Exception as e:
            logger.error(f"❌ OHLCV fetch failed for {symbol} {timeframe}: {e}")
            raise

    # --- реализация fetch_ohlcv с ccxt или HTTP фолбэком ---------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List[list]:
        """
        Сначала ccxt (если есть), иначе — публичный HTTP фолбэк (Binance).
        """
        # 1) ccxt
        if self.client is not None and hasattr(self.client, "fetch_ohlcv"):
            return self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

        # 2) HTTP фолбэк на Binance (без зависимостей)
        return self._fetch_ohlcv_http_binance(symbol, timeframe, limit)

    # --- Binance HTTP fallback ------------------------------------------------
    def _fetch_ohlcv_http_binance(self, symbol: str, timeframe: str, limit: int) -> List[list]:
        """
        Простая реализация через публичный REST Binance.
        Поддерживаются '15m'/'1h'/'4h' и формат символа 'BTC/USDT' -> 'BTCUSDT'.
        """
        try:
            import json
            from urllib.request import urlopen, Request
            from urllib.parse import urlencode

            sym = symbol.replace("/", "")
            params = urlencode({"symbol": sym, "interval": timeframe, "limit": limit})
            url = f"https://api.binance.com/api/v3/klines?{params}"

            req = Request(url, headers={"User-Agent": "crypto-ai-bot/1.0"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # Binance формат: [ openTime, o, h, l, c, v, closeTime, ... ]
            out: List[list] = []
            for k in data:
                ts = int(k[0])  # ms
                o = float(k[1]); h = float(k[2]); l = float(k[3]); c = float(k[4]); v = float(k[5])
                out.append([ts, o, h, l, c, v])

            if not out:
                raise RuntimeError("empty klines")
            logger.debug(f"📊 HTTP fallback fetched {len(out)} candles for {symbol}@{timeframe}")
            return out
        except Exception as e:
            raise RuntimeError(f"HTTP fallback failed: {e}") from e


# ── Исключения (оставляем твои типы) -----------------------------------------
class APIException(Exception):
    """Ошибка API биржи"""
    pass


class NetworkException(Exception):
    """Сетевая ошибка"""
    pass


__all__ = ["ExchangeClient", "APIException", "NetworkException"]
