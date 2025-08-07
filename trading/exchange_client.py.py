import ccxt
import logging
from typing import Dict, Optional
from core.decorators import retry, log_execution
from core.exceptions import APIException
from config.settings import TradingConfig

class ExchangeClient:
    """Клиент для работы с биржей Gate.io"""
    
    def __init__(self):
        self.exchange = ccxt.gateio({
            'apiKey': TradingConfig.GATE_API_KEY,
            'secret': TradingConfig.GATE_API_SECRET,
            'sandbox': False,
            'enableRateLimit': True,
        })
    
    @retry(max_attempts=3, delay=1.0)
    @log_execution
    def get_balance(self) -> Dict:
        """Получение баланса"""
        try:
            balance = self.exchange.fetch_balance()
            return balance
        except Exception as e:
            logging.error(f"Failed to get balance: {e}")
            raise APIException(f"Balance fetch failed: {e}")
    
    @retry(max_attempts=3, delay=1.0)
    @log_execution
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> list:
        """Получение OHLCV данных"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return ohlcv
        except Exception as e:
            logging.error(f"Failed to fetch OHLCV: {e}")
            raise APIException(f"OHLCV fetch failed: {e}")
    
    @retry(max_attempts=3, delay=2.0)
    @log_execution
    def create_market_buy_order(self, symbol: str, amount_usd: float) -> Dict:
        """Создание рыночного ордера на покупку"""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            quantity = amount_usd / current_price
            
            order = self.exchange.create_market_buy_order(symbol, quantity)
            logging.info(f"✅ Buy order created: {quantity:.6f} at ~${current_price:.2f}")
            return order
            
        except Exception as e:
            logging.error(f"Failed to create buy order: {e}")
            raise APIException(f"Buy order failed: {e}")
    
    @retry(max_attempts=3, delay=2.0)
    @log_execution
    def create_market_sell_order(self, symbol: str, quantity: float) -> Dict:
        """Создание рыночного ордера на продажу"""
        try:
            order = self.exchange.create_market_sell_order(symbol, quantity)
            logging.info(f"✅ Sell order created: {quantity:.6f}")
            return order
            
        except Exception as e:
            logging.error(f"Failed to create sell order: {e}")
            raise APIException(f"Sell order failed: {e}")
    
    @log_execution
    def get_current_price(self, symbol: str) -> float:
        """Получение текущей цены"""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            logging.error(f"Failed to get current price: {e}")
            raise APIException(f"Price fetch failed: {e}")