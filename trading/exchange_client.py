import ccxt
import logging
import threading
import time
import os
import csv
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from decimal import Decimal, ROUND_DOWN
from dataclasses import dataclass


class APIException(Exception):
    """Исключение для ошибок API биржи"""
    pass


@dataclass
class CacheEntry:
    """Запись в кэше"""
    data: any
    timestamp: float
    access_count: int = 0


class ExchangeCache:
    """Кэширование для ExchangeClient"""
    
    def __init__(self, 
                 price_ttl: int = 10,      # Цены кэшируем 10 сек
                 ohlcv_ttl: int = 60,      # OHLCV кэшируем 60 сек  
                 market_ttl: int = 3600,   # Информация о рынках - 1 час
                 max_entries: int = 100):  # Максимум записей
        
        self.price_ttl = price_ttl
        self.ohlcv_ttl = ohlcv_ttl  
        self.market_ttl = market_ttl
        self.max_entries = max_entries
        
        self._cache = {}
        self._lock = threading.RLock()
        
        # Статистика
        self._hits = 0
        self._misses = 0
        
    def _create_key(self, prefix: str, *args) -> str:
        """Создать ключ кэша"""
        key_str = f"{prefix}:" + ":".join(str(arg) for arg in args)
        return hashlib.md5(key_str.encode()).hexdigest()[:16]
    
    def get(self, key: str, ttl: int):
        """Получить из кэша"""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
                
            entry = self._cache[key]
            
            # Проверяем свежесть
            if time.time() - entry.timestamp > ttl:
                del self._cache[key]
                self._misses += 1
                return None
            
            # Обновляем статистику
            entry.access_count += 1
            self._hits += 1
            
            logging.debug(f"📦 Cache HIT: {key[:8]}...")
            return entry.data
    
    def set(self, key: str, data):
        """Сохранить в кэш"""
        with self._lock:
            # Ограничиваем размер кэша
            if len(self._cache) >= self.max_entries:
                self._evict_old_entries()
            
            self._cache[key] = CacheEntry(
                data=data,
                timestamp=time.time(),
                access_count=1
            )
            
            logging.debug(f"📦 Cache SET: {key[:8]}...")
    
    def _evict_old_entries(self):
        """Удаление старых записей при переполнении"""
        # Удаляем 20% самых старых записей
        entries_to_remove = len(self._cache) // 5
        
        # Сортируем по времени последнего доступа
        sorted_items = sorted(
            self._cache.items(),
            key=lambda x: x[1].timestamp
        )
        
        for i in range(entries_to_remove):
            key, _ = sorted_items[i]
            del self._cache[key]
        
        logging.debug(f"📦 Evicted {entries_to_remove} old cache entries")
    
    def clear(self):
        """Очистить кэш"""
        with self._lock:
            self._cache.clear()
            logging.info("📦 Exchange cache cleared")
    
    def get_stats(self):
        """Статистика кэша"""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
            
            return {
                "entries": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_pct": round(hit_rate, 1),
                "max_entries": self.max_entries
            }


class ExchangeClient:
    """
    Полнофункциональный клиент для работы с Gate.io API.
    
    Особенности:
    - SAFE MODE: симуляция торговли с реальными ценами
    - LIVE MODE: реальная торговля 
    - Единый CSV для всех сделок с колонкой mode (SAFE/LIVE)
    - Автосоздание CSV файлов
    - Логирование открытых и закрытых позиций
    - Цены и анализ всегда с реального рынка
    - ✅ КЭШИРОВАНИЕ API запросов для производительности
    """

    def __init__(self, api_key: str = None, api_secret: str = None, safe_mode: bool = True, csv_file: str = "trades.csv"):
        # Основные параметры
        self.safe_mode = safe_mode
        self.api_key = api_key or os.getenv("GATE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("GATE_API_SECRET", "")
        self.csv_file = csv_file
        self._lock = threading.RLock()
        
        # ✅ НОВОЕ: Система кэширования
        self.cache = ExchangeCache()
        
        # Кэш для информации о рынках (старый, будет заменен)
        self._markets_cache = {}
        self._cache_timestamp = 0
        self._cache_ttl = 3600  # 1 час
        
        # Симуляция баланса для SAFE MODE
        self._paper_balances = {
            "USDT": 10000.0,  # Стартовый баланс в USDT
            "BTC": 0.0,
            "ETH": 0.0,
        }
        
        # Инициализация CSV
        self._init_csv()
        
        # Инициализация подключения к бирже
        self.exchange = None
        self._init_exchange()
        
        mode_text = "SAFE MODE (paper trading)" if self.safe_mode else "LIVE MODE (real trading)"
        logging.info(f"🏦 Exchange client initialized in {mode_text} with caching")

    def _init_csv(self):
        """Инициализация CSV файла с заголовками"""
        if not os.path.exists(self.csv_file):
            fieldnames = [
                "timestamp", "symbol", "side", "amount", "price", 
                "cost", "mode", "order_id", "status", "profit_pct", "profit_abs"
            ]
            with open(self.csv_file, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            logging.info(f"📄 Created CSV file: {self.csv_file}")

    def _init_exchange(self):
        """Инициализация подключения к бирже"""
        try:
            # Всегда создаем exchange для получения данных рынка
            self.exchange = ccxt.gateio({
                'apiKey': self.api_key if not self.safe_mode else "",
                'secret': self.api_secret if not self.safe_mode else "",
                'sandbox': False,
                'enableRateLimit': True,
                'timeout': 30000,
            })
            
            # Загружаем рынки
            self.exchange.load_markets()
            
            # Проверяем подключение только в LIVE режиме
            if not self.safe_mode and self.api_key and self.api_secret:
                # Тестовый запрос для проверки API ключей
                self.exchange.fetch_balance()
                logging.info("✅ Gate.io API connected successfully (LIVE MODE)")
            else:
                logging.info("✅ Gate.io market data connected (SAFE MODE)")
                
        except Exception as e:
            if not self.safe_mode:
                logging.error(f"❌ Failed to initialize Gate.io API: {e}")
                logging.warning("🔄 Falling back to SAFE MODE")
                self.safe_mode = True
            else:
                logging.warning(f"⚠️ Market data connection issues: {e}")

    def _log_trade(self, symbol: str, side: str, amount: float, price: float, 
                   cost: float = None, order_id: str = None, profit_pct: float = None, 
                   profit_abs: float = None):
        """Логирование сделки в CSV"""
        trade_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "cost": cost or (amount * price),
            "mode": "SAFE" if self.safe_mode else "LIVE",
            "order_id": order_id or f"{'sim' if self.safe_mode else 'real'}_{int(time.time()*1000)}",
            "status": "closed",
            "profit_pct": profit_pct or "",
            "profit_abs": profit_abs or ""
        }
        
        # Проверяем существование файла и создаем заголовки если нужно
        file_exists = os.path.isfile(self.csv_file)
        if not file_exists:
            self._init_csv()
            
        # Добавляем запись
        with open(self.csv_file, mode="a", newline="", encoding="utf-8") as file:
            fieldnames = list(trade_data.keys())
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writerow(trade_data)
        
        logging.debug(f"📊 Trade logged: {side} {amount:.8f} {symbol} @ {price:.6f}")

    # ==================== MARKET DATA (с кэшированием) ====================

    def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List[List]:
        """✅ КЭШИРОВАННАЯ версия - Получение OHLCV данных"""
        # Кэш ключ учитывает symbol, timeframe, limit
        cache_key = self.cache._create_key("ohlcv", symbol, timeframe, limit)
        
        # Проверяем кэш
        cached_ohlcv = self.cache.get(cache_key, self.cache.ohlcv_ttl)
        if cached_ohlcv is not None:
            logging.debug(f"📈 OHLCV {symbol} {timeframe} from cache")
            return cached_ohlcv
        
        # Получаем с биржи
        try:
            if not self.exchange:
                self._init_exchange()

            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv:
                raise APIException(f"No OHLCV data received for {symbol}")

            # Сохраняем в кэш
            self.cache.set(cache_key, ohlcv)
            
            logging.debug(f"📈 Fetched {len(ohlcv)} candles for {symbol} {timeframe} (from exchange)")
            return ohlcv

        except Exception as e:
            logging.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            raise APIException(f"OHLCV fetch failed: {e}")

    def get_last_price(self, symbol: str) -> float:
        """✅ КЭШИРОВАННАЯ версия - Получение последней цены"""
        cache_key = self.cache._create_key("price", symbol)
        
        # Проверяем кэш
        cached_price = self.cache.get(cache_key, self.cache.price_ttl)
        if cached_price is not None:
            logging.debug(f"💰 Price {symbol} from cache: {cached_price:.6f}")
            return float(cached_price)
        
        # Получаем с биржи
        try:
            if not self.exchange:
                self._init_exchange()

            ticker = self.exchange.fetch_ticker(symbol)
            price = float(ticker.get('last', 0))

            if price <= 0:
                raise APIException(f"Invalid price received: {price}")

            # Сохраняем в кэш
            self.cache.set(cache_key, price)
            
            logging.debug(f"💰 Last price {symbol}: {price:.6f} (from exchange)")
            return price

        except Exception as e:
            logging.error(f"Failed to get last price for {symbol}: {e}")
            raise APIException(f"Price fetch failed: {e}")

    # ==================== TRADING OPERATIONS ====================

    def create_market_buy_order(self, symbol: str, amount: float) -> Dict[str, Any]:
        """Создание рыночного ордера на покупку"""
        
        with self._lock:
            try:
                # Получаем текущую цену (теперь с кэшированием)
                price = self.get_last_price(symbol)
                cost = amount * price
                
                if self.safe_mode:
                    # SAFE MODE: Симуляция ордера
                    order_id = f"sim_buy_{int(time.time() * 1000)}"
                    
                    # Проверяем баланс USDT
                    usdt_balance = self._paper_balances.get("USDT", 0.0)
                    if cost > usdt_balance:
                        raise APIException(f"Insufficient USDT balance: {usdt_balance:.2f} < {cost:.2f}")
                    
                    # Обновляем бумажные балансы
                    base_currency = symbol.split('/')[0]
                    self._paper_balances["USDT"] -= cost
                    self._paper_balances[base_currency] = self._paper_balances.get(base_currency, 0.0) + amount
                    
                    order_result = {
                        "id": order_id,
                        "symbol": symbol,
                        "amount": amount,
                        "price": price,
                        "cost": cost,
                        "side": "buy",
                        "type": "market",
                        "status": "closed",
                        "timestamp": int(time.time() * 1000),
                        "datetime": datetime.now(timezone.utc).isoformat(),
                        "paper": True
                    }
                    
                    logging.info(f"📄 PAPER BUY: {symbol} {amount:.8f} @ {price:.6f} (cost: {cost:.2f} USDT)")
                    
                else:
                    # LIVE MODE: Реальный ордер
                    if not self.exchange:
                        raise APIException("Exchange not initialized")
                    
                    # Округляем количество согласно требованиям биржи
                    amount = self.round_amount(symbol, amount)
                    
                    # Проверяем минимальные требования
                    min_amount = self.market_min_amount(symbol)
                    min_cost = self.market_min_cost(symbol)
                    
                    if amount < min_amount:
                        raise APIException(f"Amount {amount} is below minimum {min_amount}")
                    if cost < min_cost:
                        raise APIException(f"Cost {cost:.2f} is below minimum {min_cost:.2f}")
                    
                    # Выполняем ордер
                    order_result = self.exchange.create_market_buy_order(symbol, amount)
                    
                    logging.info(f"✅ LIVE BUY: {symbol} {amount:.8f} @ {order_result.get('price', price):.6f}")

                # Логируем сделку
                self._log_trade(
                    symbol=symbol, 
                    side="buy", 
                    amount=amount, 
                    price=price, 
                    cost=cost,
                    order_id=order_result.get("id")
                )
                
                return order_result
                
            except Exception as e:
                logging.error(f"Failed to create buy order: {e}")
                raise APIException(f"Buy order failed: {e}")

    def create_market_sell_order(self, symbol: str, amount: float, entry_price: Optional[float] = None) -> Dict[str, Any]:
        """Создание рыночного ордера на продажу"""
        
        with self._lock:
            try:
                # Получаем текущую цену (теперь с кэшированием)
                price = self.get_last_price(symbol)
                cost = amount * price
                
                # Расчет прибыли если указана цена входа
                profit_pct = None
                profit_abs = None
                if entry_price and entry_price > 0:
                    profit_pct = round((price - entry_price) / entry_price * 100, 2)
                    profit_abs = round((price - entry_price) * amount, 4)
                
                if self.safe_mode:
                    # SAFE MODE: Симуляция ордера
                    order_id = f"sim_sell_{int(time.time() * 1000)}"
                    
                    # Проверяем баланс базовой валюты
                    base_currency = symbol.split('/')[0]
                    base_balance = self._paper_balances.get(base_currency, 0.0)
                    if amount > base_balance:
                        raise APIException(f"Insufficient {base_currency} balance: {base_balance:.8f} < {amount:.8f}")
                    
                    # Обновляем бумажные балансы
                    self._paper_balances[base_currency] -= amount
                    self._paper_balances["USDT"] += cost
                    
                    order_result = {
                        "id": order_id,
                        "symbol": symbol,
                        "amount": amount,
                        "price": price,
                        "cost": cost,
                        "side": "sell",
                        "type": "market",
                        "status": "closed",
                        "timestamp": int(time.time() * 1000),
                        "datetime": datetime.now(timezone.utc).isoformat(),
                        "paper": True
                    }
                    
                    profit_text = f" (PnL: {profit_pct:+.2f}%)" if profit_pct is not None else ""
                    logging.info(f"📄 PAPER SELL: {symbol} {amount:.8f} @ {price:.6f}{profit_text}")
                    
                else:
                    # LIVE MODE: Реальный ордер
                    if not self.exchange:
                        raise APIException("Exchange not initialized")
                    
                    # Округляем количество согласно требованиям биржи
                    amount = self.round_amount(symbol, amount)
                    
                    # Проверяем минимальные требования
                    min_amount = self.market_min_amount(symbol)
                    if amount < min_amount:
                        raise APIException(f"Amount {amount} is below minimum {min_amount}")
                    
                    # Выполняем ордер
                    order_result = self.exchange.create_market_sell_order(symbol, amount)
                    
                    profit_text = f" (PnL: {profit_pct:+.2f}%)" if profit_pct is not None else ""
                    logging.info(f"✅ LIVE SELL: {symbol} {amount:.8f} @ {order_result.get('price', price):.6f}{profit_text}")

                # Логируем сделку
                self._log_trade(
                    symbol=symbol, 
                    side="sell", 
                    amount=amount, 
                    price=price, 
                    cost=cost,
                    order_id=order_result.get("id"),
                    profit_pct=profit_pct,
                    profit_abs=profit_abs
                )
                
                return order_result
                
            except Exception as e:
                logging.error(f"Failed to create sell order: {e}")
                raise APIException(f"Sell order failed: {e}")

    # ==================== BALANCE MANAGEMENT ====================

    def get_balance(self, currency: str = "USDT") -> float:
        """Получение баланса по валюте"""
        
        try:
            if self.safe_mode:
                # SAFE MODE: Возвращаем симулированный баланс
                balance = self._paper_balances.get(currency, 0.0)
                logging.debug(f"📊 PAPER balance {currency}: {balance:.8f}")
                return balance
            
            # LIVE MODE: Реальный баланс
            if not self.exchange:
                raise APIException("Exchange not initialized")
                
            balance_info = self.exchange.fetch_balance()
            balance = float(balance_info.get('free', {}).get(currency, 0.0))
            logging.debug(f"💰 LIVE balance {currency}: {balance:.8f}")
            return balance
            
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

    def get_paper_balances(self) -> Dict[str, float]:
        """Получение всех симулированных балансов (только для SAFE MODE)"""
        if self.safe_mode:
            return dict(self._paper_balances)
        return {}

    def reset_paper_balances(self):
        """Сброс симулированных балансов к начальным значениям"""
        if self.safe_mode:
            self._paper_balances = {
                "USDT": 10000.0,
                "BTC": 0.0,
                "ETH": 0.0,
            }
            logging.info("🔄 Paper balances reset to default values")

    # ==================== MARKET INFO (с кэшированием) ====================

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
        """✅ КЭШИРОВАННАЯ версия - Получение информации о рынке"""
        cache_key = self.cache._create_key("market", symbol)
        
        # Проверяем кэш (длительное время жизни)
        cached_info = self.cache.get(cache_key, self.cache.market_ttl)
        if cached_info is not None:
            return cached_info
        
        # Получаем информацию о рынке
        try:
            if not self.exchange:
                # Дефолтная информация
                market_info = {
                    'precision': {'amount': 8, 'price': 6},
                    'limits': {
                        'amount': {'min': 0.00001, 'max': 10000},
                        'price': {'min': 0.01, 'max': 1000000},
                        'cost': {'min': 5.0, 'max': 1000000}
                    }
                }
            else:
                markets = self.exchange.load_markets()
                market_info = markets.get(symbol, {})
                
                if not market_info:
                    raise APIException(f"Market {symbol} not found")
            
            # Сохраняем в кэш (долго)
            self.cache.set(cache_key, market_info)
            
            return market_info
            
        except Exception as e:
            logging.error(f"Failed to get market info for {symbol}: {e}")
            # Возвращаем дефолтную информацию
            default_info = {
                'precision': {'amount': 8, 'price': 6},
                'limits': {
                    'amount': {'min': 0.00001},
                    'cost': {'min': 5.0}
                }
            }
            
            # Кэшируем дефолт на короткое время
            self.cache.set(cache_key, default_info)
            return default_info

    # ==================== CACHE MANAGEMENT ====================

    def get_cache_stats(self) -> Dict[str, Any]:
        """✅ НОВОЕ: Статистика кэша для мониторинга"""
        return self.cache.get_stats()

    def clear_cache(self):
        """✅ НОВОЕ: Очистить кэш (для /clear_cache endpoint)"""
        self.cache.clear()

    # ==================== UTILITY METHODS ====================

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
            if not self.exchange:
                return int(time.time() * 1000)
                
            return self.exchange.fetch_time()
            
        except Exception as e:
            logging.error(f"Failed to get server time: {e}")
            return int(time.time() * 1000)

    def get_trade_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Получение истории сделок из CSV"""
        
        try:
            if not os.path.exists(self.csv_file):
                return []
                
            with open(self.csv_file, mode="r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                trades = list(reader)
                
            # Возвращаем последние N сделок
            return trades[-limit:] if trades else []
            
        except Exception as e:
            logging.error(f"Failed to read trade history: {e}")
            return []

    def get_status_summary(self) -> Dict[str, Any]:
        """Получение сводки состояния клиента"""
        
        balances = {}
        try:
            if self.safe_mode:
                balances = self.get_paper_balances()
            else:
                # Получаем основные балансы
                for currency in ["USDT", "BTC", "ETH"]:
                    balances[currency] = self.get_balance(currency)
        except Exception:
            pass
            
        return {
            "mode": "SAFE" if self.safe_mode else "LIVE",
            "connected": self.check_connection(),
            "balances": balances,
            "csv_file": self.csv_file,
            "markets_cached": len(self._markets_cache),
            "last_cache_update": datetime.fromtimestamp(self._cache_timestamp).isoformat() if self._cache_timestamp else None,
            # ✅ НОВОЕ: Статистика кэша
            "cache_stats": self.get_cache_stats()
        }