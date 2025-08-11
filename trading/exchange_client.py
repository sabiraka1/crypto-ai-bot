# trading/exchange_client.py - UNIFIED CACHE VERSION (ЭТАП 4)

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

# ✅ ЭТАП 4: UNIFIED CACHE INTEGRATION
try:
    from utils.unified_cache import get_cache_manager, CacheNamespace
    UNIFIED_CACHE_AVAILABLE = True
    logging.info("🏦 Exchange Client: Unified Cache Manager loaded")
except ImportError:
    UNIFIED_CACHE_AVAILABLE = False
    logging.warning("🏦 Exchange Client: Unified Cache not available, using fallback")

class APIException(Exception):
    """Исключение для ошибок API биржи"""
    pass

# =============================================================================
# ✅ ЭТАП 4: ЗАМЕНА ExchangeCache НА UNIFIED CACHE
# =============================================================================

class ExchangeCacheCompat:
    """
    ✅ COMPATIBILITY LAYER: Адаптер для замены старого ExchangeCache
    
    Обеспечивает обратную совместимость со старым API, но использует
    unified cache под капотом с правильными namespace'ами:
    - PRICES → CacheNamespace.PRICES
    - OHLCV → CacheNamespace.OHLCV  
    - MARKET_INFO → CacheNamespace.MARKET_INFO
    """
    
    def __init__(self, 
                 price_ttl: int = 10,      # Цены кэшируем 10 сек
                 ohlcv_ttl: int = 60,      # OHLCV кэшируем 60 сек  
                 market_ttl: int = 3600,   # Информация о рынках - 1 час
                 max_entries: int = 100):  # Максимум записей (deprecated)
        
        self.price_ttl = price_ttl
        self.ohlcv_ttl = ohlcv_ttl  
        self.market_ttl = market_ttl
        self.max_entries = max_entries  # Для совместимости
        
        # ✅ Получаем unified cache manager
        self._unified_cache = self._get_unified_cache()
        
        # Статистика (для обратной совместимости)
        self._hits = 0
        self._misses = 0
        
        if self._unified_cache:
            logging.info("🏦 ExchangeCache: Using UNIFIED CACHE backend")
        else:
            logging.warning("🏦 ExchangeCache: Using FALLBACK backend")
    
    def _get_unified_cache(self):
        """Получить unified cache с fallback"""
        if UNIFIED_CACHE_AVAILABLE:
            try:
                return get_cache_manager()
            except Exception as e:
                logging.error(f"Failed to get unified cache: {e}")
        return None
    
    def _create_key(self, prefix: str, *args) -> str:
        """Создать ключ кэша (совместимость со старым API)"""
        key_str = f"{prefix}:" + ":".join(str(arg) for arg in args)
        return hashlib.md5(key_str.encode()).hexdigest()[:16]
    
    def get(self, key: str, ttl: int):
        """
        ✅ UNIFIED CACHE INTEGRATION: Получить из кэша
        
        Маппинг TTL → Namespace:
        - ttl == price_ttl → PRICES
        - ttl == ohlcv_ttl → OHLCV  
        - ttl == market_ttl → MARKET_INFO
        """
        if not self._unified_cache:
            self._misses += 1
            return None
        
        try:
            # ✅ Определяем namespace по TTL (для обратной совместимости)
            namespace = self._ttl_to_namespace(ttl)
            
            # ✅ Запрашиваем из unified cache
            result = self._unified_cache.get(key, namespace)
            
            if result is not None:
                self._hits += 1
                logging.debug(f"🏦 Cache HIT (unified): {key[:8]}... → {namespace.value}")
                return result
            else:
                self._misses += 1
                logging.debug(f"🏦 Cache MISS (unified): {key[:8]}... → {namespace.value}")
                return None
                
        except Exception as e:
            logging.error(f"Unified cache GET failed: {e}")
            self._misses += 1
            return None
    
    def set(self, key: str, data):
        """
        ✅ UNIFIED CACHE INTEGRATION: Сохранить в кэш
        
        Автоматически определяет namespace по префиксу ключа:
        - price: → PRICES
        - ohlcv: → OHLCV
        - market: → MARKET_INFO
        """
        if not self._unified_cache:
            return
        
        try:
            # ✅ Определяем namespace по префиксу ключа
            namespace = self._key_to_namespace(key)
            
            # ✅ Сохраняем в unified cache (TTL берется из конфигурации namespace)
            success = self._unified_cache.set(
                key, 
                data, 
                namespace,
                metadata={"source": "exchange_client", "timestamp": time.time()}
            )
            
            if success:
                logging.debug(f"🏦 Cache SET (unified): {key[:8]}... → {namespace.value}")
            else:
                logging.warning(f"🏦 Cache SET failed (unified): {key[:8]}...")
                
        except Exception as e:
            logging.error(f"Unified cache SET failed: {e}")
    
    def _ttl_to_namespace(self, ttl: int) -> CacheNamespace:
        """Маппинг TTL → Namespace для обратной совместимости"""
        if ttl == self.price_ttl:
            return CacheNamespace.PRICES
        elif ttl == self.ohlcv_ttl:
            return CacheNamespace.OHLCV
        elif ttl == self.market_ttl:
            return CacheNamespace.MARKET_INFO
        else:
            # Fallback для неизвестных TTL
            return CacheNamespace.MARKET_INFO
    
    def _key_to_namespace(self, key: str) -> CacheNamespace:
        """Определение namespace по префиксу ключа"""
        key_lower = key.lower()
        
        if key_lower.startswith('price:'):
            return CacheNamespace.PRICES
        elif key_lower.startswith('ohlcv:'):
            return CacheNamespace.OHLCV
        elif key_lower.startswith('market:'):
            return CacheNamespace.MARKET_INFO
        else:
            # Анализ содержимого ключа для автоопределения
            if 'ticker' in key_lower or 'last' in key_lower:
                return CacheNamespace.PRICES
            elif 'candle' in key_lower or 'ohlcv' in key_lower:
                return CacheNamespace.OHLCV
            else:
                return CacheNamespace.MARKET_INFO
    
    def clear(self):
        """✅ UNIFIED CACHE: Очистить все exchange кэши"""
        if not self._unified_cache:
            return
        
        try:
            # Очищаем все exchange namespace'ы
            for namespace in [CacheNamespace.PRICES, CacheNamespace.OHLCV, CacheNamespace.MARKET_INFO]:
                self._unified_cache.clear_namespace(namespace)
            
            logging.info("🏦 Exchange cache cleared (all unified namespaces)")
            
        except Exception as e:
            logging.error(f"Unified cache clear failed: {e}")
    
    def get_stats(self):
        """✅ UNIFIED CACHE: Статистика кэша"""
        if not self._unified_cache:
            return {
                "entries": 0,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_pct": 0,
                "unified_cache": False
            }
        
        try:
            # Получаем статистику из unified cache
            unified_stats = self._unified_cache.get_stats()
            
            # Агрегируем статистику по exchange namespace'ам
            exchange_namespaces = ["prices", "ohlcv", "market_info"]
            total_entries = 0
            total_memory = 0
            
            for ns_name in exchange_namespaces:
                ns_stats = unified_stats["namespaces"].get(ns_name, {})
                total_entries += ns_stats.get("entries", 0)
                total_memory += ns_stats.get("memory_mb", 0)
            
            # Обновляем локальную статистику из unified
            global_stats = unified_stats["global"]
            
            return {
                "entries": total_entries,
                "hits": global_stats.get("hits", self._hits),
                "misses": global_stats.get("misses", self._misses),
                "hit_rate_pct": global_stats.get("hit_rate_pct", 0),
                "memory_mb": round(total_memory, 2),
                "unified_cache": True,
                "namespaces": {
                    ns: unified_stats["namespaces"].get(ns, {}) 
                    for ns in exchange_namespaces
                }
            }
            
        except Exception as e:
            logging.error(f"Failed to get unified cache stats: {e}")
            return {
                "entries": 0,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_pct": 0,
                "unified_cache": False,
                "error": str(e)
            }


class ExchangeClient:
    """
    ✅ ЭТАП 4: Exchange Client с UNIFIED CACHE системой
    
    Изменения:
    - ExchangeCache заменен на ExchangeCacheCompat (unified backend)
    - Все кэширование через CacheNamespace.PRICES, OHLCV, MARKET_INFO
    - Сохранена обратная совместимость API
    - Улучшенная статистика и мониторинг
    """

    def __init__(self, api_key: str = None, api_secret: str = None, safe_mode: bool = True, csv_file: str = "trades.csv"):
        # Основные параметры
        self.safe_mode = safe_mode
        self.api_key = api_key or os.getenv("GATE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("GATE_API_SECRET", "")
        self.csv_file = csv_file
        self._lock = threading.RLock()
        
        # ✅ ЭТАП 4: Unified Cache система
        self.cache = ExchangeCacheCompat()
        
        # Legacy кэш для информации о рынках (будет постепенно мигрирован)
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
        cache_backend = "UNIFIED CACHE" if UNIFIED_CACHE_AVAILABLE else "FALLBACK"
        logging.info(f"🏦 Exchange client initialized in {mode_text} with {cache_backend}")

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

    # ==================== MARKET DATA (✅ UNIFIED CACHE) ====================

    def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List[List]:
        """✅ ЭТАП 4: OHLCV с unified кэшированием"""
        # ✅ Unified cache ключ
        cache_key = self.cache._create_key("ohlcv", symbol, timeframe, limit)
        
        # ✅ Проверяем unified cache (namespace OHLCV)
        cached_ohlcv = self.cache.get(cache_key, self.cache.ohlcv_ttl)
        if cached_ohlcv is not None:
            logging.debug(f"📈 OHLCV {symbol} {timeframe} from UNIFIED cache")
            return cached_ohlcv
        
        # Получаем с биржи
        try:
            if not self.exchange:
                self._init_exchange()

            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv:
                raise APIException(f"No OHLCV data received for {symbol}")

            # ✅ Сохраняем в unified cache (namespace OHLCV)
            self.cache.set(cache_key, ohlcv)
            
            logging.debug(f"📈 Fetched {len(ohlcv)} candles for {symbol} {timeframe} (from exchange, cached in UNIFIED)")
            return ohlcv

        except Exception as e:
            logging.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            raise APIException(f"OHLCV fetch failed: {e}")

    def get_last_price(self, symbol: str) -> float:
        """✅ ЭТАП 4: Цены с unified кэшированием"""
        # ✅ Unified cache ключ
        cache_key = self.cache._create_key("price", symbol)
        
        # ✅ Проверяем unified cache (namespace PRICES)
        cached_price = self.cache.get(cache_key, self.cache.price_ttl)
        if cached_price is not None:
            logging.debug(f"💰 Price {symbol} from UNIFIED cache: {cached_price:.6f}")
            return float(cached_price)
        
        # Получаем с биржи
        try:
            if not self.exchange:
                self._init_exchange()

            ticker = self.exchange.fetch_ticker(symbol)
            price = float(ticker.get('last', 0))

            if price <= 0:
                raise APIException(f"Invalid price received: {price}")

            # ✅ Сохраняем в unified cache (namespace PRICES)
            self.cache.set(cache_key, price)
            
            logging.debug(f"💰 Last price {symbol}: {price:.6f} (from exchange, cached in UNIFIED)")
            return price

        except Exception as e:
            logging.error(f"Failed to get last price for {symbol}: {e}")
            raise APIException(f"Price fetch failed: {e}")

    # ==================== TRADING OPERATIONS (без изменений) ====================

    def create_market_buy_order(self, symbol: str, amount: float) -> Dict[str, Any]:
        """Создание рыночного ордера на покупку"""
        
        with self._lock:
            try:
                # Получаем текущую цену (теперь с unified кэшированием)
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
                # Получаем текущую цену (теперь с unified кэшированием)
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

    # ==================== BALANCE MANAGEMENT (без изменений) ====================

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

    # ==================== MARKET INFO (✅ UNIFIED CACHE) ====================

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
        """✅ ЭТАП 4: Market info с unified кэшированием"""
        # ✅ Unified cache ключ
        cache_key = self.cache._create_key("market", symbol)
        
        # ✅ Проверяем unified cache (namespace MARKET_INFO)
        cached_info = self.cache.get(cache_key, self.cache.market_ttl)
        if cached_info is not None:
            logging.debug(f"📊 Market info {symbol} from UNIFIED cache")
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
            
            # ✅ Сохраняем в unified cache (namespace MARKET_INFO)
            self.cache.set(cache_key, market_info)
            logging.debug(f"📊 Market info {symbol} fetched and cached in UNIFIED")
            
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
            
            # ✅ Кэшируем дефолт в unified cache
            self.cache.set(cache_key, default_info)
            return default_info

    # ==================== ✅ ЭТАП 4: UNIFIED CACHE MANAGEMENT ====================

    def get_cache_stats(self) -> Dict[str, Any]:
        """✅ ЭТАП 4: Статистика unified кэша для exchange"""
        return self.cache.get_stats()

    def clear_cache(self):
        """✅ ЭТАП 4: Очистить unified cache (все exchange namespace'ы)"""
        self.cache.clear()

    def get_unified_cache_diagnostics(self) -> Dict[str, Any]:
        """✅ НОВОЕ: Диагностика unified cache интеграции"""
        if not UNIFIED_CACHE_AVAILABLE:
            return {
                "unified_cache_available": False,
                "fallback_mode": True
            }
        
        try:
            cache_manager = get_cache_manager()
            stats = cache_manager.get_stats()
            
            # Статистика по exchange namespace'ам
            exchange_namespaces = ["prices", "ohlcv", "market_info"]
            exchange_stats = {}
            
            for ns in exchange_namespaces:
                ns_stats = stats["namespaces"].get(ns, {})
                exchange_stats[ns] = ns_stats
                
                # Топ ключей для каждого namespace
                if ns_stats.get("entries", 0) > 0:
                    try:
                        top_keys = cache_manager.get_top_keys(
                            getattr(CacheNamespace, ns.upper()), 
                            limit=3
                        )
                        exchange_stats[ns]["top_keys"] = top_keys
                    except Exception:
                        pass
            
            return {
                "unified_cache_available": True,
                "exchange_namespaces": exchange_stats,
                "global_stats": stats["global"],
                "memory_pressure": stats["memory_pressure"],
                "cache_backend": "unified"
            }
            
        except Exception as e:
            return {
                "unified_cache_available": True,
                "error": str(e),
                "cache_backend": "unified_error"
            }

    def test_unified_cache_integration(self) -> Dict[str, Any]:
        """✅ НОВОЕ: Тестирование unified cache интеграции"""
        if not UNIFIED_CACHE_AVAILABLE:
            return {
                "test_passed": False,
                "reason": "Unified cache not available"
            }
        
        try:
            test_results = {}
            
            # Тест 1: PRICES namespace
            test_symbol = "BTC/USDT"
            test_price = 50000.0
            
            price_key = self.cache._create_key("price", test_symbol)
            self.cache.set(price_key, test_price)
            retrieved_price = self.cache.get(price_key, self.cache.price_ttl)
            
            test_results["prices"] = {
                "set_success": True,
                "get_success": retrieved_price == test_price,
                "data_integrity": retrieved_price == test_price
            }
            
            # Тест 2: OHLCV namespace
            test_ohlcv = [[1609459200000, 29000, 29500, 28800, 29200, 100]]
            ohlcv_key = self.cache._create_key("ohlcv", test_symbol, "1h", 100)
            self.cache.set(ohlcv_key, test_ohlcv)
            retrieved_ohlcv = self.cache.get(ohlcv_key, self.cache.ohlcv_ttl)
            
            test_results["ohlcv"] = {
                "set_success": True,
                "get_success": retrieved_ohlcv == test_ohlcv,
                "data_integrity": retrieved_ohlcv == test_ohlcv
            }
            
            # Тест 3: MARKET_INFO namespace
            test_market_info = {"precision": {"amount": 8, "price": 2}}
            market_key = self.cache._create_key("market", test_symbol)
            self.cache.set(market_key, test_market_info)
            retrieved_market = self.cache.get(market_key, self.cache.market_ttl)
            
            test_results["market_info"] = {
                "set_success": True,
                "get_success": retrieved_market == test_market_info,
                "data_integrity": retrieved_market == test_market_info
            }
            
            # Общий результат
            all_tests_passed = all(
                result["set_success"] and result["get_success"] and result["data_integrity"]
                for result in test_results.values()
            )
            
            # Очистка тестовых данных
            cache_manager = get_cache_manager()
            for namespace in [CacheNamespace.PRICES, CacheNamespace.OHLCV, CacheNamespace.MARKET_INFO]:
                cache_manager.delete(f"test_{namespace.value}", namespace)
            
            return {
                "test_passed": all_tests_passed,
                "individual_tests": test_results,
                "cache_stats": self.get_cache_stats()
            }
            
        except Exception as e:
            return {
                "test_passed": False,
                "error": str(e)
            }

    # ==================== UTILITY METHODS (без изменений) ====================

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
        """✅ ЭТАП 4: Сводка состояния с unified cache статистикой"""
        
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
        
        # ✅ Unified cache статистика
        cache_stats = self.get_cache_stats()
        cache_diagnostics = self.get_unified_cache_diagnostics()
            
        return {
            "mode": "SAFE" if self.safe_mode else "LIVE",
            "connected": self.check_connection(),
            "balances": balances,
            "csv_file": self.csv_file,
            "markets_cached": len(self._markets_cache),  # Legacy
            "last_cache_update": datetime.fromtimestamp(self._cache_timestamp).isoformat() if self._cache_timestamp else None,
            # ✅ ЭТАП 4: Unified cache статистика
            "cache_stats": cache_stats,
            "cache_backend": "unified" if UNIFIED_CACHE_AVAILABLE else "fallback",
            "unified_cache_diagnostics": cache_diagnostics
        }