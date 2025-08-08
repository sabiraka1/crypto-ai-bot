import ccxt
import os
import time
import logging
from typing import Dict, Optional

class APIException(Exception):
    pass

class ExchangeClient:
    """Gate.io spot via ccxt with helpers."""
    def __init__(self, api_key: Optional[str]=None, api_secret: Optional[str]=None):
        self.exchange = ccxt.gateio({
            'apiKey': api_key or os.getenv("GATE_API_KEY"),
            'secret': api_secret or os.getenv("GATE_API_SECRET"),
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        self.markets = None
        try:
            self.markets = self.exchange.load_markets()
        except Exception as e:
            logging.error(f"load_markets failed: {e}")

    def _safe(self, fn, *args, **kwargs):
        for _ in range(3):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logging.error(f"ccxt call failed: {e}")
                time.sleep(2)
        raise APIException("exchange call failed after retries")

    def ticker(self, symbol: str) -> Dict:
        return self._safe(self.exchange.fetch_ticker, symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str = '15m', limit: int = 200):
        return self._safe(self.exchange.fetch_ohlcv, symbol, timeframe, None, limit)

    def _amount_from_usd(self, symbol: str, usd: float, last_price: float) -> float:
        if last_price <= 0:
            return 0.0
        amt = usd / last_price
        try:
            if self.markets and symbol in self.markets:
                amt = float(self.exchange.amount_to_precision(symbol, amt))
                # опционально проверим минималки
                info = self.markets.get(symbol, {})
                limits = info.get('limits', {})
                min_amount = (limits.get('amount', {}) or {}).get('min')
                if min_amount and amt < float(min_amount):
                    # округлим вверх до минимума
                    amt = float(min_amount)
        except Exception as e:
            logging.warning(f"amount precision/limit warning: {e}")
        return float(amt)

    def create_market_buy_order(self, symbol: str, usd: float):
        t = self.ticker(symbol)
        last = float(t.get('last') or t.get('close'))
        amount = self._amount_from_usd(symbol, usd, last)
        return self._safe(self.exchange.create_order, symbol, 'market', 'buy', amount)

    def create_market_sell_order(self, symbol: str, amount: float):
        return self._safe(self.exchange.create_order, symbol, 'market', 'sell', amount)
