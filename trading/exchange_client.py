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
            'options': {
                'defaultType': 'spot',
                # ✅ покупаем по сумме (USDT), без передачи price
                'createMarketBuyOrderRequiresPrice': False,
                # ✅ ccxt будет автоматически корректировать дрифт времени
                'adjustForTimeDifference': True,
            }
        })

        self.markets = None
        try:
            # проверим, что ключи заданы (кинет исключение, если пустые)
            self.exchange.check_required_credentials()
        except Exception:
            # не падаем — позволяем работать и в режиме без ключей (чтение)
            pass

        try:
            # короткая попытка синхронизировать время (если биржа поддерживает)
            try:
                server_time = self.exchange.fetch_time()
                drift_ms = int(server_time) - int(time.time() * 1000)
                logging.info(f"⏱️ Gate.io time drift ~ {drift_ms} ms")
            except Exception:
                # не критично, просто логируем
                logging.debug("fetch_time not available")

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

    # ---------- diagnostics ----------
    def test_connection(self) -> bool:
        """Лёгкий тест авторизации: пробуем запросить баланс."""
        try:
            bal = self._safe(self.exchange.fetch_balance)
            # если ключи только для чтения — всё равно ок
            total = bal.get('total', {}) or {}
            logging.info(f"🔐 Auth OK, assets: {len(total)}")
            return True
        except Exception as e:
            logging.error(f"❌ Auth/Balance test failed: {e}")
            return False

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
        return float((balance.get('free') or {}).get(asset, 0))

    # ---------- orders ----------
    def create_market_buy_order(self, symbol: str, usd_amount: float):
        """
        Создаёт маркет-ордер на покупку по сумме в USDT (quote).
        CCXT + Gate.io примут это при createMarketBuyOrderRequiresPrice=False.
        """
        order = self._safe(
            self.exchange.create_order,
            symbol,
            'market',
            'buy',
            usd_amount,      # сумма в USDT
            None,            # price не нужен
            {'cost': usd_amount}  # дублируем стоимость явно
        )
        self._log_trade("BUY", symbol, usd_amount, self.get_last_price(symbol))
        return order

    def create_market_sell_order(self, symbol: str, amount: float):
        # для sell передаём количество базовой валюты
        order = self._safe(self.exchange.create_order, symbol, 'market', 'sell', amount)
        self._log_trade("SELL", symbol, amount, self.get_last_price(symbol))
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
