import ccxt
import os
import time
import logging
from datetime import datetime
from typing import Dict, Optional, Any, List

class APIException(Exception):
    pass

class ExchangeClient:
    """Gate.io spot client via ccxt with safe calls, precision handling, and logging."""
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.exchange = ccxt.gateio({
            'apiKey': api_key or os.getenv("GATE_API_KEY"),
            'secret': api_secret or os.getenv("GATE_API_SECRET"),
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        self.markets = None
        try:
            self.markets = self.exchange.load_markets()
            logging.info("✅ Exchange client initialized and markets loaded")
        except Exception as e:
            logging.error(f"❌ load_markets failed: {e}")

    # ---------- safe wrapper with retries ----------
    def _safe(self, fn, *args, **kwargs):
        for _ in range(3):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logging.error(f"⚠️ ccxt call failed: {e}")
                time.sleep(1.5)
        raise APIException("exchange call failed after retries")

    # ---------- OHLCV & ticker ----------
    def fetch_ohlcv(self, symbol: str, timeframe: str = '15m', limit: int = 200) -> List[List[Any]]:
        """CCXT OHLCV: [ts, open, high, low, close, volume]"""
        return self._safe(self.exchange.fetch_ohlcv, symbol, timeframe, None, limit)

    def ticker(self, symbol: str) -> Dict[str, Any]:
        """Ticker: {'last': ..., 'close': ...}"""
        return self._safe(self.exchange.fetch_ticker, symbol)

    def get_last_price(self, symbol: str) -> float:
        t = self.ticker(symbol)
        return float(t.get('last') or t.get('close'))

    # ---------- balance ----------
    def get_balance(self, asset: str) -> float:
        balance = self._safe(self.exchange.fetch_balance)
        return float(balance['free'].get(asset, 0))

    # ---------- precision & amount ----------
    def _amount_from_usd(self, symbol: str, usd: float, last_price: float) -> float:
        if last_price <= 0:
            return 0.0
        amt = usd / last_price
        try:
            if self.markets and symbol in self.markets:
                amt = float(self.exchange.amount_to_precision(symbol, amt))
                info = self.markets.get(symbol, {})
                limits = info.get('limits', {})
                min_amount = (limits.get('amount', {}) or {}).get('min')
                if min_amount and amt < float(min_amount):
                    amt = float(min_amount)
        except Exception as e:
            logging.warning(f"⚠️ amount precision/limit warning: {e}")
        return float(amt)

    def _apply_precision(self, symbol: str, amount: float) -> float:
        try:
            if self.markets and symbol in self.markets:
                amount = float(self.exchange.amount_to_precision(symbol, amount))
                min_amount = self.markets[symbol]['limits']['amount']['min']
                if float(amount) < min_amount:
                    amount = min_amount
        except Exception as e:
            logging.warning(f"⚠️ precision apply warning: {e}")
        return float(amount)

    # ---------- orders ----------
    def create_market_buy_order(self, symbol: str, usd: float):
        last = self.get_last_price(symbol)
        amount = self._amount_from_usd(symbol, usd, last)
        order = self._safe(self.exchange.create_order, symbol, 'market', 'buy', amount)
        self._log_trade("BUY", symbol, amount, last)
        return order

    def create_market_sell_order(self, symbol: str, amount: float):
        amount = self._apply_precision(symbol, amount)
        last = self.get_last_price(symbol)
        order = self._safe(self.exchange.create_order, symbol, 'market', 'sell', amount)
        self._log_trade("SELL", symbol, amount, last)
        return order

    # ---------- short aliases ----------
    def buy(self, symbol: str, amount_usd: float):
        return self.create_market_buy_order(symbol, amount_usd)

    def sell(self, symbol: str, amount: float):
        return self.create_market_sell_order(symbol, amount)

    # ---------- trade logging ----------
    def _log_trade(self, action: str, symbol: str, amount: float, price: float):
        msg = f"[TRADE] {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC | {action.upper()} {amount} {symbol} @ {price} USDT"
        logging.info(msg)
        try:
            with open("trades.log", "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception as e:
            logging.error(f"❌ write trades.log failed: {e}")
