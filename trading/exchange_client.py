import os
import ccxt
import time
import logging
from datetime import datetime
from typing import Dict, Optional, Any, List

class APIException(Exception):
    pass

class ExchangeClient:
    """
    Gate.io spot client via ccxt with:
      - SAFE_MODE (paper) support
      - min_notional (min cost) check & auto-adjust
      - retry policy (non-retryable errors are not retried)
      - buy by QUOTE amount (USDT) using params={'cost': ...}
      - structured logging
    """
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.safe_mode = str(os.getenv("SAFE_MODE", "0")).strip().lower() in ("1", "true", "yes", "on")
        self.exchange = ccxt.gateio({
            "apiKey": api_key or os.getenv("GATE_API_KEY"),
            "secret": api_secret or os.getenv("GATE_API_SECRET"),
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot",
                # Позволяет указывать стоимость покупки через params.cost
                "createMarketBuyOrderRequiresPrice": False,
                "adjustForTimeDifference": True,
            }
        })

        self.markets: Dict[str, Any] = {}
        try:
            self.exchange.check_required_credentials()
        except Exception:
            # не фейлим, если только паблик-методы нужны
            pass

        # Диагностика времени + загрузка рынков
        try:
            try:
                server_time = self.exchange.fetch_time()
                drift_ms = int(server_time) - int(time.time() * 1000)
                logging.info(f"⏱️ Gate.io time drift ~ {drift_ms} ms")
            except Exception:
                logging.debug("fetch_time not available")

            self.markets = self.exchange.load_markets()
            logging.info("✅ Exchange client initialized and markets loaded")
        except Exception as e:
            logging.error(f"❌ load_markets failed: {e}")

    # --------------------- helpers ---------------------
    def market_min_cost(self, symbol: str) -> Optional[float]:
        """
        Возвращает минимальную допустимую стоимость ордера (USDT) для символа,
        если биржа предоставляет это в markets[symbol]['limits']['cost']['min'].
        """
        try:
            m = self.markets.get(symbol) or {}
            limits = m.get("limits") or {}
            cost = limits.get("cost") or {}
            mn = cost.get("min")
            return float(mn) if mn is not None else None
        except Exception:
            return None

    def _is_retryable(self, e: Exception) -> bool:
        """
        Рассортируем ошибки: не ретраим явные бизнес-ошибки
        (микро-сумма, недостаточно средств, неверные параметры).
        """
        msg = str(e).upper()
        non_retry_signals = [
            "INVALID_PARAM_VALUE",
            "BALANCE_NOT_ENOUGH",
            "INSUFFICIENT",
            "MIN_TRADE_REQUIREMENT",
            "MIN_NOTIONAL",
            "COST_MIN",
        ]
        return not any(s in msg for s in non_retry_signals)

    # --------------------- safe wrapper ---------------------
    def _safe(self, fn, *args, **kwargs):
        last_exc = None
        for attempt in range(3):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_exc = e
                # Для не-ретраибл — прекращаем сразу
                if not self._is_retryable(e):
                    logging.error(f"⚠️ ccxt call failed (non-retryable): {e}")
                    break
                logging.warning(f"⚠️ ccxt call failed (retryable, attempt {attempt+1}/3): {e}")
                time.sleep(1.5)
        raise APIException(f"exchange call failed after retries: {last_exc}")

    # --------------------- diagnostics ---------------------
    def test_connection(self) -> bool:
        """Лёгкий тест авторизации: пробуем запросить баланс."""
        try:
            bal = self._safe(self.exchange.fetch_balance)
            total = bal.get("total", {}) or {}
            logging.info(f"🔐 Auth OK, assets: {len(total)}")
            return True
        except Exception as e:
            logging.error(f"❌ Auth/Balance test failed: {e}")
            return False

    # --------------------- market data ---------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 200) -> List[List[Any]]:
        return self._safe(self.exchange.fetch_ohlcv, symbol, timeframe, None, limit)

    def ticker(self, symbol: str) -> Dict[str, Any]:
        return self._safe(self.exchange.fetch_ticker, symbol)

    def get_last_price(self, symbol: str) -> float:
        t = self.ticker(symbol)
        return float(t.get("last") or t.get("close"))

    # --------------------- balance ---------------------
    def get_balance(self, asset: str) -> float:
        balance = self._safe(self.exchange.fetch_balance)
        return float((balance.get("free") or {}).get(asset, 0))

    # --------------------- trading ---------------------
    def create_market_buy_order(self, symbol: str, amount_usd: float):
        """
        Создаёт маркет BUY ордер по **сумме в USDT**.
        - Учитывает min_notional: auto-bump до минимума
        - SAFE_MODE: paper-ордер без обращения к бирже
        """
        # min_notional guard
        min_cost = self.market_min_cost(symbol) or 0.0
        final_cost = max(float(amount_usd), float(min_cost))
        if final_cost > amount_usd:
            logging.info(f"🧩 amount bumped to min_notional: requested={amount_usd:.2f}, min={min_cost:.2f}, final={final_cost:.2f}")

        if self.safe_mode:
            order = {
                "id": f"paper-{int(time.time()*1000)}",
                "symbol": symbol,
                "side": "buy",
                "type": "market",
                "status": "filled",
                "cost_usd": final_cost,
                "paper": True,
            }
            self._log_trade("BUY[PAPER]", symbol, final_cost, self.get_last_price(symbol))
            return order

        # На Gate.io покупка по 'cost' (quote-amount). amount(None) + params.cost
        order = self._safe(
            self.exchange.create_order,
            symbol,
            "market",
            "buy",
            None,             # amount не обязателен (стоимость зададим через cost)
            None,
            {"cost": final_cost}
        )
        self._log_trade("BUY", symbol, final_cost, self.get_last_price(symbol))
        return order

    def create_market_sell_order(self, symbol: str, amount_base: float):
        """
        Маркет SELL по количеству базовой валюты.
        SAFE_MODE: paper-ордер без обращения к бирже.
        """
        if self.safe_mode:
            order = {
                "id": f"paper-{int(time.time()*1000)}",
                "symbol": symbol,
                "side": "sell",
                "type": "market",
                "status": "filled",
                "amount": float(amount_base),
                "paper": True,
            }
            self._log_trade("SELL[PAPER]", symbol, float(amount_base), self.get_last_price(symbol))
            return order

        order = self._safe(self.exchange.create_order, symbol, "market", "sell", float(amount_base))
        self._log_trade("SELL", symbol, float(amount_base), self.get_last_price(symbol))
        return order

    # --------------------- aliases ---------------------
    def buy(self, symbol: str, amount_usd: float):
        return self.create_market_buy_order(symbol, amount_usd)

    def sell(self, symbol: str, amount: float):
        return self.create_market_sell_order(symbol, amount)

    # --------------------- trade logging ---------------------
    def _log_trade(self, action: str, symbol: str, amount: float, price: float):
        msg = (
            f"[TRADE] {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC | "
            f"{action} {symbol} amount={amount:.8f} @ {price:.2f} USDT"
        )
        logging.info(msg)
        try:
            with open("trades.log", "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception as e:
            logging.error(f"❌ write trades.log failed: {e}")
