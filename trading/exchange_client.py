import ccxt
import logging
import threading
import time
import os
from datetime import datetime
from typing import Optional, Dict, Any, List
from decimal import Decimal, ROUND_DOWN


class APIException(Exception):
    """Исключение для ошибок API биржи"""
    pass


class ExchangeClient:
    # Safe Mode блокирует реальные сделки, но пишет виртуальные в основной CSV
    # В CSV добавляется колонка mode (SAFE / LIVE)
    # Цены и анализ всегда с реального рынка
    """
    Упрощенный клиент для работы с Gate.io API.
    Поддерживает безопасный режим для тестирования.
    """

    def __init__(self, api_key: str = None, api_secret: str = None, safe_mode: bool = True):
        self.safe_mode = getattr(config, 'SAFE_MODE', True)  # Safe mode flag
        self.api_key = api_key or os.getenv("GATE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("GATE_API_SECRET", "")
        self.safe_mode = safe_mode
        self._lock = threading.RLock()
        
        # Кэш для информации о рынках
        self._markets_cache = {}
        self._cache_timestamp = 0
        self._cache_ttl = 3600  # 1 час
        
        # Инициализация exchange для реального режима
        self.exchange = None
        if not self.safe_mode and self.api_key and self.api_secret:
            try:
                self.exchange = ccxt.gateio({
                    'apiKey': self.api_key,
                    'secret': self.api_secret,
                    'sandbox': False,
                    'enableRateLimit': True,
                    'timeout': 30000,
                })
                # Проверяем подключение
                self.exchange.load_markets()
                logging.info("✅ Gate.io API connected successfully")
            except Exception as e:
                logging.error(f"❌ Failed to initialize Gate.io API: {e}")
                self.safe_mode = True
                self.exchange = None
        
        if self.safe_mode:
            logging.info("📄 Exchange client running in SAFE MODE (paper trading)")

    def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List[List]:
    """Получение OHLCV данных - всегда с реального рынка"""
    try:
        if not self.exchange:
            self.exchange = ccxt.gateio({
                'enableRateLimit': True,
                'timeout': 30000,
            })
            self.exchange.load_markets()

        ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv:
            raise APIException(f"No OHLCV data received for {symbol}")

        return ohlcv

    except Exception as e:
        logging.error(f"Failed to fetch OHLCV for {symbol}: {e}")
        raise APIException(f"OHLCV fetch failed: {e}")

def get_last_price(self, symbol: str) -> float:
    """Получение последней цены - всегда с реального рынка"""
    try:
        if not self.exchange:
            try:
                self.exchange = ccxt.gateio({
                    'enableRateLimit': True,
                    'timeout': 30000,
                })
                self.exchange.load_markets()
            except Exception as e:
                raise APIException(f"Failed to init exchange for price fetch: {e}")

        ticker = self.exchange.fetch_ticker(symbol)
        price = float(ticker.get('last', 0))

        if price <= 0:
            raise APIException(f"Invalid price received: {price}")

        return price

    except Exception as e:
        logging.error(f"Failed to get last price for {symbol}: {e}")
        raise APIException(f"Price fetch failed: {e}")

def create_market_buy_order(self, symbol: str, amount: float) -> Dict[str, Any]:
        """Создание рыночного ордера на покупку"""
        
        with self._lock:
            try:
                if self.safe_mode:
                    # Симуляция ордера
                    price = self.get_last_price(symbol)
                    order_id = f"sim_buy_{int(time.time() * 1000)}"
                    
                    return {
                        "id": order_id,
                        "symbol": symbol,
                        "amount": amount,
                        "price": price,
                        "cost": amount * price,
                        "side": "buy",
                        "type": "market",
                        "status": "closed",
                        "timestamp": int(time.time() * 1000),
                        "datetime": datetime.utcnow().isoformat(),
                        "paper": True
                    }
                
                if not self.exchange:
                    raise APIException("Exchange not initialized")
                
                # Округляем количество согласно требованиям биржи
                amount = self.round_amount(symbol, amount)
                
                # Проверяем минимальные требования
                min_amount = self.market_min_amount(symbol)
                if amount < min_amount:
                    raise APIException(f"Amount {amount} is below minimum {min_amount}")
                
                # Выполняем ордер
                order = self.exchange.create_market_buy_order(symbol, amount)
                
                logging.info(f"✅ BUY order executed: {symbol} {amount} @ {order.get('price', 'market')}")
                return order
                
            except Exception as e:
                logging.error(f"Failed to create buy order: {e}")
                raise APIException(f"Buy order failed: {e}")

    def create_market_sell_order(self, symbol: str, amount: float) -> Dict[str, Any]:
        """Создание рыночного ордера на продажу"""
        
        with self._lock:
            try:
                if self.safe_mode:
                    # Симуляция ордера
                    price = self.get_last_price(symbol)
                    order_id = f"sim_sell_{int(time.time() * 1000)}"
                    
                    return {
                        "id": order_id,
                        "symbol": symbol,
                        "amount": amount,
                        "price": price,
                        "cost": amount * price,
                        "side": "sell",
                        "type": "market",
                        "status": "closed",
                        "timestamp": int(time.time() * 1000),
                        "datetime": datetime.utcnow().isoformat(),
                        "paper": True
                    }
                
                if not self.exchange:
                    raise APIException("Exchange not initialized")
                
                # Округляем количество согласно требованиям биржи
                amount = self.round_amount(symbol, amount)
                
                # Проверяем минимальные требования
                min_amount = self.market_min_amount(symbol)
                if amount < min_amount:
                    raise APIException(f"Amount {amount} is below minimum {min_amount}")
                
                # Выполняем ордер
                order = self.exchange.create_market_sell_order(symbol, amount)
                
                logging.info(f"✅ SELL order executed: {symbol} {amount} @ {order.get('price', 'market')}")
                return order
                
            except Exception as e:
                logging.error(f"Failed to create sell order: {e}")
                raise APIException(f"Sell order failed: {e}")

    def get_balance(self, currency: str = "USDT") -> float:
        """Получение баланса по валюте"""
        
        try:
            if self.safe_mode:
                # Симуляция баланса
                return 1000.0 if currency == "USDT" else 0.1
            
            if not self.exchange:
                raise APIException("Exchange not initialized")
                
            balance = self.exchange.fetch_balance()
            return float(balance.get('free', {}).get(currency, 0.0))
            
        except Exception as e:
            logging.error(f"Failed to get balance for {currency}: {e}")
            return 0.0

    def get_free_base(self, symbol: str) -> float:
        """Получение свободного баланса базовой валюты"""
        
        try:
            base_currency = symbol.split('/')[0]  # BTC из BTC/USDT
            return self.get_balance(base_currency)
        except Exception as e:
            logging.error(f"Failed to get free base for {symbol}: {e}")
            return 0.0

    def market_min_cost(self, symbol: str) -> float:
        """Минимальная стоимость ордера в USDT"""
        
        try:
            market_info = self._get_market_info(symbol)
            return float(market_info.get('limits', {}).get('cost', {}).get('min', 5.0))
        except Exception:
            return 5.0  # Дефолтное значение для Gate.io

    def market_min_amount(self, symbol: str) -> float:
        """Минимальное количество для ордера"""
        
        try:
            market_info = self._get_market_info(symbol)
            return float(market_info.get('limits', {}).get('amount', {}).get('min', 0.00001))
        except Exception:
            return 0.00001  # Дефолтное значение

    def round_amount(self, symbol: str, amount: float) -> float:
        """Округление количества согласно требованиям биржи"""
        
        try:
            market_info = self._get_market_info(symbol)
            precision = market_info.get('precision', {}).get('amount', 8)
            
            # Используем Decimal для точного округления
            decimal_amount = Decimal(str(amount))
            rounded = decimal_amount.quantize(Decimal('0.1') ** precision, rounding=ROUND_DOWN)
            
            return float(rounded)
            
        except Exception as e:
            logging.error(f"Failed to round amount for {symbol}: {e}")
            return round(amount, 8)

    def round_price(self, symbol: str, price: float) -> float:
        """Округление цены согласно требованиям биржи"""
        
        try:
            market_info = self._get_market_info(symbol)
            precision = market_info.get('precision', {}).get('price', 6)
            
            return round(price, precision)
            
        except Exception as e:
            logging.error(f"Failed to round price for {symbol}: {e}")
            return round(price, 6)

    def _get_market_info(self, symbol: str) -> Dict[str, Any]:
        """Получение информации о рынке с кэшированием"""
        
        current_time = time.time()
        
        # Проверяем кэш
        if (symbol in self._markets_cache and 
            current_time - self._cache_timestamp < self._cache_ttl):
            return self._markets_cache[symbol]
        
        try:
            if self.safe_mode:
                # Дефолтная информация для безопасного режима
                market_info = {
                    'id': symbol,
                    'symbol': symbol,
                    'base': symbol.split('/')[0],
                    'quote': symbol.split('/')[1],
                    'active': True,
                    'type': 'spot',
                    'precision': {
                        'amount': 8,
                        'price': 6
                    },
                    'limits': {
                        'amount': {'min': 0.00001, 'max': 10000},
                        'price': {'min': 0.01, 'max': 1000000},
                        'cost': {'min': 5.0, 'max': 1000000}
                    }
                }
            else:
                if not self.exchange:
                    raise APIException("Exchange not initialized")
                    
                markets = self.exchange.load_markets()
                market_info = markets.get(symbol, {})
                
                if not market_info:
                    raise APIException(f"Market {symbol} not found")
            
            # Обновляем кэш
            self._markets_cache[symbol] = market_info
            self._cache_timestamp = current_time
            
            return market_info
            
        except Exception as e:
            logging.error(f"Failed to get market info for {symbol}: {e}")
            # Возвращаем дефолтную информацию
            return {
                'precision': {'amount': 8, 'price': 6},
                'limits': {
                    'amount': {'min': 0.00001},
                    'cost': {'min': 5.0}
                }
            }

    def _generate_synthetic_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List]:
        """Генерация синтетических OHLCV данных для тестирования"""
        
        import random
        
        # Базовая цена в зависимости от символа
        if "BTC" in symbol:
            base_price = 43000.0
            volatility = 200.0
        elif "ETH" in symbol:
            base_price = 2500.0
            volatility = 50.0
        else:
            base_price = 100.0
            volatility = 5.0
        
        # Интервал в миллисекундах
        timeframe_ms = {
            '1m': 60 * 1000,
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '1h': 60 * 60 * 1000,
            '4h': 4 * 60 * 60 * 1000,
            '1d': 24 * 60 * 60 * 1000
        }.get(timeframe, 15 * 60 * 1000)
        
        # Генерируем данные
        current_time = int(time.time() * 1000)
        ohlcv_data = []
        
        price = base_price
        
        for i in range(limit):
            timestamp = current_time - (limit - i - 1) * timeframe_ms
            
            # Генерируем случайные изменения
            change = random.uniform(-volatility * 0.02, volatility * 0.02)
            price += change
            
            # OHLC вокруг цены закрытия
            close = price
            open_price = close + random.uniform(-volatility * 0.01, volatility * 0.01)
            high = max(open_price, close) + random.uniform(0, volatility * 0.01)
            low = min(open_price, close) - random.uniform(0, volatility * 0.01)
            volume = random.uniform(100, 1000)
            
            ohlcv_data.append([timestamp, open_price, high, low, close, volume])
        
        return ohlcv_data

    def get_trading_fees(self, symbol: str) -> Dict[str, float]:
        """Получение торговых комиссий"""
        
        try:
            if self.safe_mode:
                return {'maker': 0.002, 'taker': 0.002}  # 0.2% для Gate.io
            
            if not self.exchange:
                raise APIException("Exchange not initialized")
                
            fees = self.exchange.fetch_trading_fees()
            symbol_fees = fees.get('trading', {}).get(symbol, {})
            
            return {
                'maker': float(symbol_fees.get('maker', 0.002)),
                'taker': float(symbol_fees.get('taker', 0.002))
            }
            
        except Exception as e:
            logging.error(f"Failed to get trading fees for {symbol}: {e}")
            return {'maker': 0.002, 'taker': 0.002}

    def check_connection(self) -> bool:
        """Проверка соединения с биржей"""
        
        try:
            if self.safe_mode:
                return True
            
            if not self.exchange:
                return False
                
            # Простая проверка через получение времени сервера
            self.exchange.fetch_time()
            return True
            
        except Exception as e:
            logging.error(f"Connection check failed: {e}")
            return False

    def get_server_time(self) -> int:
        """Получение времени сервера"""
        
        try:
            if self.safe_mode:
                return int(time.time() * 1000)
            
            if not self.exchange:
                raise APIException("Exchange not initialized")
                
            return self.exchange.fetch_time()
            
        except Exception as e:
            logging.error(f"Failed to get server time: {e}")
            return int(time.time() * 1000)

# ===== ДОРАБОТКИ SAFE/LIVE И CSV ЛОГИРОВАНИЯ =====
import csv
import os
import ccxt
import logging
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from decimal import Decimal, ROUND_DOWN

class APIException(Exception):
    """Исключение для ошибок API биржи"""
    pass

class ExchangeClient:
    """Клиент для работы с Gate.io API с поддержкой SAFE/LIVE режима и логированием сделок"""
    
    def __init__(self, api_key: str = None, api_secret: str = None, safe_mode: bool = True, csv_file: str = "trades.csv"):
        self.safe_mode = safe_mode
        self.api_key = api_key or os.getenv("GATE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("GATE_API_SECRET", "")
        self.csv_file = csv_file
        self._lock = threading.RLock()
        self._markets_cache = {}
        self._cache_timestamp = 0
        self._cache_ttl = 3600

        self._init_csv()
        
        self.exchange = None
        try:
            self.exchange = ccxt.gateio({
                'apiKey': self.api_key,
                'secret': self.api_secret,
                'sandbox': False,
                'enableRateLimit': True,
                'timeout': 30000,
            })
            self.exchange.load_markets()
            logging.info("✅ Gate.io API connected successfully")
        except Exception as e:
            logging.error(f"❌ Failed to initialize Gate.io API: {e}")
            self.safe_mode = True
            self.exchange = None

        if self.safe_mode:
            logging.info("📄 Running in SAFE MODE (paper trading)")

    def _init_csv(self):
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["timestamp", "symbol", "side", "amount", "price", "mode", "profit"])
                writer.writeheader()

    def _log_trade(self, symbol, side, amount, price, profit=None):
        trade_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "mode": "SAFE" if self.safe_mode else "LIVE",
            "profit": profit if profit is not None else ""
        }
        file_exists = os.path.isfile(self.csv_file)
        with open(self.csv_file, mode="a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["timestamp", "symbol", "side", "amount", "price", "mode", "profit"])
            if not file_exists:
                writer.writeheader()
            writer.writerow(trade_data)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List[List]:
        """Получение OHLCV данных с реального рынка"""
        try:
            if not self.exchange:
                self.exchange = ccxt.gateio({'enableRateLimit': True, 'timeout': 30000})
                self.exchange.load_markets()
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv:
                raise APIException(f"No OHLCV data for {symbol}")
            return ohlcv
        except Exception as e:
            logging.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            raise APIException(str(e))

    def get_last_price(self, symbol: str) -> float:
        """Последняя цена с реального рынка"""
        try:
            if not self.exchange:
                self.exchange = ccxt.gateio({'enableRateLimit': True, 'timeout': 30000})
                self.exchange.load_markets()
            ticker = self.exchange.fetch_ticker(symbol)
            price = float(ticker.get('last', 0))
            if price <= 0:
                raise APIException(f"Invalid price {price}")
            return price
        except Exception as e:
            logging.error(f"Failed to get last price for {symbol}: {e}")
            raise APIException(str(e))

    def create_market_buy_order(self, symbol: str, amount: float) -> Dict[str, Any]:
        with self._lock:
            try:
                price = self.get_last_price(symbol)
                if self.safe_mode:
                    order_id = f"sim_buy_{int(time.time()*1000)}"
                    self._log_trade(symbol, "buy", amount, price)
                    return {"id": order_id, "symbol": symbol, "amount": amount, "price": price, "side": "buy", "status": "closed", "paper": True}
                if not self.exchange:
                    raise APIException("Exchange not initialized")
                amount = self.round_amount(symbol, amount)
                order = self.exchange.create_market_buy_order(symbol, amount)
                self._log_trade(symbol, "buy", amount, order.get("price", price))
                return order
            except Exception as e:
                logging.error(f"Failed to create buy order: {e}")
                raise APIException(str(e))

    def create_market_sell_order(self, symbol: str, amount: float, entry_price: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                price = self.get_last_price(symbol)
                profit = None
                if entry_price:
                    profit = round((price - entry_price) / entry_price * 100, 2)
                if self.safe_mode:
                    order_id = f"sim_sell_{int(time.time()*1000)}"
                    self._log_trade(symbol, "sell", amount, price, profit)
                    return {"id": order_id, "symbol": symbol, "amount": amount, "price": price, "side": "sell", "status": "closed", "paper": True}
                if not self.exchange:
                    raise APIException("Exchange not initialized")
                amount = self.round_amount(symbol, amount)
                order = self.exchange.create_market_sell_order(symbol, amount)
                self._log_trade(symbol, "sell", amount, order.get("price", price), profit)
                return order
            except Exception as e:
                logging.error(f"Failed to create sell order: {e}")
                raise APIException(str(e))

    def round_amount(self, symbol: str, amount: float) -> float:
        try:
            market_info = self._get_market_info(symbol)
            precision = market_info.get('precision', {}).get('amount', 8)
            decimal_amount = Decimal(str(amount))
            rounded = decimal_amount.quantize(Decimal('0.1') ** precision, rounding=ROUND_DOWN)
            return float(rounded)
        except Exception:
            return round(amount, 8)

    def _get_market_info(self, symbol: str) -> Dict[str, Any]:
        current_time = time.time()
        if symbol in self._markets_cache and current_time - self._cache_timestamp < self._cache_ttl:
            return self._markets_cache[symbol]
        if not self.exchange:
            return {'precision': {'amount': 8, 'price': 6}}
        markets = self.exchange.load_markets()
        market_info = markets.get(symbol, {})
        self._markets_cache[symbol] = market_info
        self._cache_timestamp = current_time
        return market_info