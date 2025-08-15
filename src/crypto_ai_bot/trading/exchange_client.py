# src/crypto_ai_bot/trading/exchange_client.py
from __future__ import annotations

import logging
import time
from typing import Any, Optional, List

from crypto_ai_bot.core.metrics import FETCH_OHLCV_LATENCY

logger = logging.getLogger(__name__)


class ExchangeClient:
    """
    РЈРЅРёС„РёС†РёСЂРѕРІР°РЅРЅС‹Р№ РєР»РёРµРЅС‚:
      - РїСЂРѕР±СѓРµС‚ ccxt (РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ gateio)
      - РµСЃР»Рё РЅРµС‚ ccxt РёР»Рё РЅРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР·РґР°С‚СЊ РєР»РёРµРЅС‚Р° вЂ” РїСѓР±Р»РёС‡РЅС‹Р№ HTTP С„РѕР»Р±СЌРє (Binance)
    """

    def __init__(self, settings: Optional[Any] = None):
        self.settings = settings
        self.client = None  # ccxt РєР»РёРµРЅС‚ (РµСЃР»Рё РїРѕР»СѓС‡РёС‚СЃСЏ)

        # РєР°Рє РЅР°Р·С‹РІР°РµРј Р±РёСЂР¶Сѓ: settings.EXCHANGE_NAME РёР»Рё 'gateio'
        ex_name = None
        if settings and hasattr(settings, "EXCHANGE_NAME"):
            ex_name = getattr(settings, "EXCHANGE_NAME")
        if not ex_name:
            ex_name = "gateio"

        # РїС‹С‚Р°РµРјСЃСЏ РїРѕРґРЅСЏС‚СЊ ccxt
        try:
            import ccxt  # type: ignore

            if not hasattr(ccxt, ex_name):
                logger.warning(f"ccxt: exchange '{ex_name}' РЅРµ РЅР°Р№РґРµРЅ, РёСЃРїРѕР»СЊР·СѓРµРј binance")
                ex_name = "binance"

            cls = getattr(ccxt, ex_name)
            kwargs = dict(enableRateLimit=True)
            # РєР»СЋС‡Рё РЅРµ РЅСѓР¶РЅС‹ РґР»СЏ OHLCV, РЅРѕ РµСЃР»Рё Р·Р°РґР°РЅС‹ вЂ” РїРѕРґРєР»СЋС‡РёРј
            if settings:
                key = getattr(settings, "API_KEY", None)
                sec = getattr(settings, "API_SECRET", None)
                if key and sec:
                    kwargs.update(apiKey=key, secret=sec)
            self.client = cls(kwargs)
            # РЅРµРєРѕС‚РѕСЂС‹Рµ СЂРµР°Р»РёР·Р°С†РёРё ccxt С‚СЂРµР±СѓСЋС‚ .load_markets()
            if hasattr(self.client, "load_markets"):
                self.client.load_markets()
            logger.info(f"ccxt client ready: {ex_name}")
        except Exception as e:
            logger.warning(f"ccxt РЅРµРґРѕСЃС‚СѓРїРµРЅ РёР»Рё РЅРµ РёРЅРёС†РёР°Р»РёР·РёСЂРѕРІР°Р»СЃСЏ ({e}). Р’РєР»СЋС‡РµРЅ HTTP С„РѕР»Р±СЌРє.")

    # --- РїСѓР±Р»РёС‡РЅС‹Р№ API Р±РѕС‚Р° ---------------------------------------------------
    def get_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List[list]:
        """
        РЈРЅРёС„РёС†РёСЂРѕРІР°РЅРЅС‹Р№ РјРµС‚РѕРґ РїРѕР»СѓС‡РµРЅРёСЏ OHLCV.
        Р’РѕР·РІСЂР°С‰Р°РµС‚ СЃРїРёСЃРѕРє: [[ts_ms, open, high, low, close, volume], ...]
        """
        try:
            # РџСѓС‚СЊ 1: РµСЃР»Рё Сѓ РѕР±СЉРµРєС‚Р° РµСЃС‚СЊ СЃРІРѕР№ fetch_ohlcv (РЅРёР¶Рµ СЂРµР°Р»РёР·СѓРµРј)
            fetch = getattr(self, "fetch_ohlcv", None)
            if callable(fetch):
                t0 = time.perf_counter()
                ohlcv = fetch(symbol, timeframe=timeframe, limit=limit)
                FETCH_OHLCV_LATENCY.observe(time.perf_counter() - t0)
                logger.debug(f"рџ“Љ Fetched {len(ohlcv)} candles for {symbol} via self.fetch_ohlcv")
                return ohlcv

            # РџСѓС‚СЊ 2: РµСЃР»Рё РІРЅСѓС‚СЂРё РµСЃС‚СЊ СЂРµР°Р»СЊРЅС‹Р№ ccxt-РєР»РёРµРЅС‚
            for attr in ("client", "api", "exchange"):
                obj = getattr(self, attr, None)
                fetch = getattr(obj, "fetch_ohlcv", None) if obj is not None else None
                if callable(fetch):
                    t0 = time.perf_counter()
                    ohlcv = fetch(symbol, timeframe=timeframe, limit=limit)
                    FETCH_OHLCV_LATENCY.observe(time.perf_counter() - t0)
                    logger.debug(f"рџ“Љ Fetched {len(ohlcv)} candles for {symbol} via self.{attr}.fetch_ohlcv")
                    return ohlcv

            # Р•СЃР»Рё РЅРё РѕРґРёРЅ РїСѓС‚СЊ РЅРµ РЅР°Р№РґРµРЅ вЂ” СЌС‚Рѕ РѕС€РёР±РєР° РґРёР·Р°Р№РЅР°
            raise NotImplementedError(
                "ExchangeClient.get_ohlcv: implement .fetch_ohlcv() "
                "РёР»Рё РїСЂРµРґРѕСЃС‚Р°РІСЊС‚Рµ self.client/self.api/self.exchange СЃ .fetch_ohlcv()."
            )
        except NotImplementedError:
            raise
        except Exception as e:
            logger.error(f"вќЊ OHLCV fetch failed for {symbol} {timeframe}: {e}")
            raise

    # --- СЂРµР°Р»РёР·Р°С†РёСЏ fetch_ohlcv СЃ ccxt РёР»Рё HTTP С„РѕР»Р±СЌРєРѕРј ---------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List[list]:
        """
        РЎРЅР°С‡Р°Р»Р° ccxt (РµСЃР»Рё РµСЃС‚СЊ), РёРЅР°С‡Рµ вЂ” РїСѓР±Р»РёС‡РЅС‹Р№ HTTP С„РѕР»Р±СЌРє (Binance).
        """
        # 1) ccxt
        if self.client is not None and hasattr(self.client, "fetch_ohlcv"):
            return self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

        # 2) HTTP С„РѕР»Р±СЌРє РЅР° Binance (Р±РµР· Р·Р°РІРёСЃРёРјРѕСЃС‚РµР№)
        return self._fetch_ohlcv_http_binance(symbol, timeframe, limit)

    # --- Binance HTTP fallback ------------------------------------------------
    def _fetch_ohlcv_http_binance(self, symbol: str, timeframe: str, limit: int) -> List[list]:
        """
        РџСЂРѕСЃС‚Р°СЏ СЂРµР°Р»РёР·Р°С†РёСЏ С‡РµСЂРµР· РїСѓР±Р»РёС‡РЅС‹Р№ REST Binance.
        РџРѕРґРґРµСЂР¶РёРІР°СЋС‚СЃСЏ '15m'/'1h'/'4h' Рё С„РѕСЂРјР°С‚ СЃРёРјРІРѕР»Р° 'BTC/USDT' -> 'BTCUSDT'.
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

            # Binance С„РѕСЂРјР°С‚: [ openTime, o, h, l, c, v, closeTime, ... ]
            out: List[list] = []
            for k in data:
                ts = int(k[0])  # ms
                o = float(k[1]); h = float(k[2]); l = float(k[3]); c = float(k[4]); v = float(k[5])
                out.append([ts, o, h, l, c, v])

            if not out:
                raise RuntimeError("empty klines")
            logger.debug(f"рџ“Љ HTTP fallback fetched {len(out)} candles for {symbol}@{timeframe}")
            return out
        except Exception as e:
            raise RuntimeError(f"HTTP fallback failed: {e}") from e


# в”Ђв”Ђ РСЃРєР»СЋС‡РµРЅРёСЏ (РѕСЃС‚Р°РІР»СЏРµРј С‚РІРѕРё С‚РёРїС‹) -----------------------------------------
class APIException(Exception):
    """РћС€РёР±РєР° API Р±РёСЂР¶Рё"""
    pass


class NetworkException(Exception):
    """РЎРµС‚РµРІР°СЏ РѕС€РёР±РєР°"""
    pass


__all__ = ["ExchangeClient", "APIException", "NetworkException"]







