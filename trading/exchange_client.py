import os
import ccxt
import time
import math
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any, List, Tuple


class APIException(Exception):
    pass


class ExchangeClient:
    """
    Gate.io spot client via ccxt with:
      - SAFE_MODE (paper) support с виртуальными балансами
      - min_notional (min cost) check & auto-adjust
      - balance checks (skipped in SAFE_MODE)
      - precision-aware rounding for sell amounts
      - retry policy
      - buy by QUOTE amount (USDT) using params={'cost': ...}
      - structured logging
      - Улучшенная обработка продажи с текущей ценой
    """
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self.safe_mode = str(os.getenv("SAFE_MODE", "0")).strip().lower() in ("1", "true", "yes", "on")
        
        # Добавляем виртуальный баланс для SAFE_MODE
        self._virtual_balances = {}
        if self.safe_mode:
            # Инициализируем виртуальные балансы
            self._virtual_balances = {
                "USDT": 10000.0,  # 10,000 USDT
                "BTC": 0.0,       # 0 BTC изначально
            }
            logging.info("💰 SAFE_MODE enabled: Virtual balances initialized")
        
        self.exchange = ccxt.gateio({
            "apiKey": api_key or os.getenv("GATE_API_KEY"),
            "secret": api_secret or os.getenv("GATE_API_SECRET"),
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot",
                "createMarketBuyOrderRequiresPrice": False,  # allow params.cost
                "adjustForTimeDifference": True,
            },
            "timeout": 20000,
        })

        self.markets: Dict[str, Any] = {}
        try:
            if not self.safe_mode:
                self.exchange.check_required_credentials()
        except Exception:
            # public calls can still work
            pass

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

    # --------------------- market helpers ---------------------
    def market_min_cost(self, symbol: str) -> Optional[float]:
        try:
            m = self.markets.get(symbol) or {}
            limits = m.get("limits") or {}
            cost = limits.get("cost") or {}
            mn = cost.get("min")
            return float(mn) if mn is not None else None
        except Exception:
            return None

    def market_min_amount(self, symbol: str) -> Optional[float]:
        try:
            m = self.markets.get(symbol) or {}
            limits = m.get("limits") or {}
            amt = limits.get("amount") or {}
            mn = amt.get("min")
            return float(mn) if mn is not None else None
        except Exception:
            return None

    def _split_symbol(self, symbol: str) -> Tuple[str, str]:
        # ccxt symbols look like "BTC/USDT"
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            return base, quote
        return symbol, "USDT"

    def get_precisions(self, symbol: str) -> Tuple[Optional[int], Optional[int], Optional[float]]:
        """
        Returns (amount_decimals, price_decimals, amount_step)
        Some exchanges provide decimals in precision, some provide step in limits.amount.step
        """
        m = self.markets.get(symbol) or {}
        prec = m.get("precision") or {}
        amount_decimals = prec.get("amount")
        price_decimals = prec.get("price")
        amount_step = None
        try:
            step = (m.get("limits") or {}).get("amount", {}).get("step")
            amount_step = float(step) if step is not None else None
        except Exception:
            amount_step = None
        return amount_decimals, price_decimals, amount_step

    def round_amount(self, symbol: str, amount: float) -> float:
        if amount <= 0:
            return 0.0
        amount_decimals, _price_decimals, amount_step = self.get_precisions(symbol)
        try:
            if amount_step and amount_step > 0:
                # round down to nearest step
                return math.floor(amount / amount_step) * amount_step
            if amount_decimals is not None:
                # round down by decimals
                factor = 10 ** int(amount_decimals)
                return math.floor(amount * factor) / factor
        except Exception:
            pass
        # fallback: 8 decimals
        return math.floor(amount * 1e8) / 1e8

    def check_min_notional(self, symbol: str, cost: float) -> float:
        mn = self.market_min_cost(symbol) or 0.0
        return max(float(cost), float(mn))

    # --------------------- retry policy ---------------------
    def _is_retryable(self, e: Exception) -> bool:
        msg = str(e).upper()
        non_retry_signals = [
            "INVALID_PARAM_VALUE",
            "BALANCE_NOT_ENOUGH",
            "INSUFFICIENT",
            "MIN_TRADE_REQUIREMENT",
            "MIN_NOTIONAL",
            "COST_MIN",
            "CANNOT_PLACE_ORDER",
        ]
        return not any(s in msg for s in non_retry_signals)

    def _safe(self, fn, *args, **kwargs):
        last_exc = None
        for attempt in range(3):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if not self._is_retryable(e):
                    logging.error(f"⚠️ ccxt call failed (non-retryable): {e}")
                    break
                logging.warning(f"⚠️ ccxt call failed (retryable, attempt {attempt+1}/3): {e}")
                time.sleep(1.25 * (attempt + 1))
        raise APIException(f"exchange call failed after retries: {last_exc}")

    # --------------------- diagnostics ---------------------
    def test_connection(self) -> bool:
        if self.safe_mode:
            logging.info("🔐 SAFE_MODE: Connection test skipped")
            return True
            
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
        try:
            t = self.ticker(symbol)
            last = t.get("last") or t.get("close") or t.get("ask") or t.get("bid")
            return float(last)
        except Exception:
            return 0.0

    # --------------------- virtual balance helpers ---------------------
    def _update_virtual_balance(self, asset: str, delta: float):
        """Обновляет виртуальный баланс в SAFE_MODE"""
        if self.safe_mode:
            current = self._virtual_balances.get(asset, 0.0)
            self._virtual_balances[asset] = max(0.0, current + delta)
            logging.info(f"💰 Virtual balance updated: {asset} {current:.8f} → {self._virtual_balances[asset]:.8f} (Δ{delta:+.8f})")

    # --------------------- balance ---------------------
    def get_balance(self, asset: str) -> float:
        if self.safe_mode:
            # Возвращаем виртуальный баланс в paper режиме
            return float(self._virtual_balances.get(asset, 0.0))
        
        # Реальный режим
        balance = self._safe(self.exchange.fetch_balance)
        return float((balance.get("free") or {}).get(asset, 0))

    def get_free_quote(self, symbol: str) -> float:
        _base, quote = self._split_symbol(symbol)
        try:
            return self.get_balance(quote)
        except Exception:
            return 0.0

    def get_free_base(self, symbol: str) -> float:
        base, _quote = self._split_symbol(symbol)
        try:
            return self.get_balance(base)
        except Exception:
            return 0.0

    def calculate_base_amount_from_usd(self, symbol: str, usd_amount: float, current_price: float = None) -> float:
        """
        Рассчитывает количество базовой валюты исходя из USD суммы и текущей цены
        Учитывает точность и минимальные требования биржи
        """
        if current_price is None:
            current_price = self.get_last_price(symbol)
        
        if current_price <= 0:
            raise APIException("Invalid current price for calculation")
        
        # Базовое количество
        base_amount = float(usd_amount) / float(current_price)
        
        # Округляем согласно точности биржи
        base_amount = self.round_amount(symbol, base_amount)
        
        # Проверяем минимальное количество
        min_amount = self.market_min_amount(symbol) or 0.0
        if base_amount < min_amount and min_amount > 0:
            logging.info(f"🧩 base amount bumped to min_amount: from {base_amount:.8f} to {min_amount:.8f}")
            base_amount = min_amount
        
        return base_amount

    # --------------------- trading ---------------------
    def create_market_buy_order(self, symbol: str, amount_usd: float):
        """
        Create MARKET BUY by quote amount (USDT) via params={'cost': ...}
        - SAFE_MODE: виртуальные балансы с проверками
        - non-SAFE: checks free quote balance
        - auto-bumps to min_notional
        """
        requested = float(amount_usd)
        min_cost = self.market_min_cost(symbol) or 0.0

        if self.safe_mode:
            # Проверяем виртуальный баланс USDT
            base, quote = self._split_symbol(symbol)
            free_quote = self.get_free_quote(symbol)
            
            final_cost = max(requested, min_cost)
            if final_cost > free_quote:
                raise APIException(f"Insufficient virtual {quote} balance: need {final_cost:.2f}, have {free_quote:.2f}")
            
            if final_cost > requested:
                logging.info(f'🧩 amount bumped to min_notional (SAFE_MODE): requested={requested:.2f}, min={min_cost:.2f}, final={final_cost:.2f}')
            
            current_price = self.get_last_price(symbol)
            base_amount = self.calculate_base_amount_from_usd(symbol, final_cost, current_price)
            
            # Обновляем виртуальные балансы
            self._update_virtual_balance(quote, -final_cost)  # Уменьшаем USDT
            self._update_virtual_balance(base, +base_amount)  # Увеличиваем BTC
            
            order = {
                "id": f"paper-{int(time.time()*1000)}",
                "symbol": symbol,
                "side": "buy",
                "type": "market",
                "status": "filled",
                "cost": final_cost,
                "filled": base_amount,
                "amount": base_amount,
                "avg": current_price,
                "paper": True,
            }
            self._log_trade("BUY[PAPER]", symbol, final_cost, current_price)
            return order

        # Реальный режим без изменений
        free_quote = self.get_free_quote(symbol)
        if free_quote <= 0:
            raise APIException("No free quote balance to buy")

        planned = min(requested, free_quote)
        final_cost = max(planned, min_cost)

        if final_cost > free_quote:
            raise APIException(f"Insufficient quote balance: need {final_cost:.2f}, have {free_quote:.2f}")

        if final_cost > requested:
            logging.info(
                f"🧩 amount bumped to min_notional: requested={requested:.2f}, "
                f"min={min_cost:.2f}, final={final_cost:.2f}"
            )

        order = self._safe(
            self.exchange.create_order,
            symbol,
            "market",
            "buy",
            None,             # amount is omitted; we use cost
            None,
            {"cost": final_cost}
        )
        self._log_trade("BUY", symbol, final_cost, self.get_last_price(symbol))
        return order

    def create_market_sell_order(self, symbol: str, amount_base: float):
        """
        MARKET SELL by base amount with precision rounding.
        - SAFE_MODE: обновляет виртуальные балансы
        - non-SAFE: checks free base balance
        - Enforces min amount where applicable
        """
        amt = float(amount_base)
        
        # Сначала округляем
        amt = self.round_amount(symbol, amt)
        
        # Проверяем минимум
        min_amt = self.market_min_amount(symbol) or 0.0
        if min_amt > 0 and amt < min_amt:
            if self.safe_mode:
                # В бумажном режиме продаем минимум если размер меньше
                logging.info(f"🧩 SAFE_MODE: sell amount bumped to min_amount: from {amt:.8f} to {min_amt:.8f}")
                amt = float(min_amt)
            else:
                # В реальном режиме пытаемся продать все доступное
                free_base = self.get_free_base(symbol)
                if free_base >= min_amt:
                    logging.info(f"🧩 sell amount too small, using available balance: from {amt:.8f} to {free_base:.8f}")
                    amt = self.round_amount(symbol, free_base)
                else:
                    raise APIException(f"Sell amount {amt:.8f} is below minimum {min_amt:.8f} and insufficient balance {free_base:.8f}")

        if amt <= 0:
            raise APIException("Sell amount after rounding is zero")

        if self.safe_mode:
            # Проверяем виртуальный баланс базовой валюты
            base, quote = self._split_symbol(symbol)
            free_base = self.get_free_base(symbol)
            
            if amt > free_base:
                if free_base >= min_amt:
                    logging.info(f"🧩 SAFE_MODE: adjusting sell amount to available balance: from {amt:.8f} to {free_base:.8f}")
                    amt = self.round_amount(symbol, free_base)
                else:
                    raise APIException(f"Insufficient virtual {base} balance: need {amt:.8f}, have {free_base:.8f}")
            
            current_price = self.get_last_price(symbol)
            cost_received = float(amt) * current_price
            
            # Обновляем виртуальные балансы
            self._update_virtual_balance(base, -amt)          # Уменьшаем BTC
            self._update_virtual_balance(quote, +cost_received) # Увеличиваем USDT
            
            order = {
                "id": f"paper-{int(time.time()*1000)}",
                "symbol": symbol,
                "side": "sell",
                "type": "market",
                "status": "filled",
                "amount": float(amt),
                "filled": float(amt),
                "avg": current_price,
                "cost": cost_received,
                "paper": True,
            }
            self._log_trade("SELL[PAPER]", symbol, float(amt), current_price)
            return order

        # Реальный режим без изменений
        free_base = self.get_free_base(symbol)
        
        # Если пытаемся продать больше чем есть, продаем все что есть
        if amt > free_base:
            if free_base >= min_amt:
                logging.info(f"🧩 adjusting sell amount to available balance: from {amt:.8f} to {free_base:.8f}")
                amt = self.round_amount(symbol, free_base)
            else:
                raise APIException(f"Insufficient base balance: need {amt:.8f}, have {free_base:.8f}")

        order = self._safe(self.exchange.create_order, symbol, "market", "sell", float(amt))
        self._log_trade("SELL", symbol, float(amt), self.get_last_price(symbol))
        return order

    def sell_all_base(self, symbol: str) -> dict:
        """
        Продает ВСЕ доступные базовые активы по символу
        Полезно для полного закрытия позиции
        """
        try:
            free_base = self.get_free_base(symbol)
            if free_base <= 0:
                raise APIException("No base balance to sell")
            
            # Округляем доступный баланс
            amt_to_sell = self.round_amount(symbol, free_base)
            
            # Проверяем минимум
            min_amt = self.market_min_amount(symbol) or 0.0
            if amt_to_sell < min_amt:
                if self.safe_mode:
                    # В SAFE_MODE продаем весь доступный баланс
                    amt_to_sell = free_base
                    logging.info(f"🧩 SAFE_MODE: selling all available {amt_to_sell:.8f} (below min)")
                else:
                    raise APIException(f"Available balance {amt_to_sell:.8f} is below minimum {min_amt:.8f}")
            
            return self.create_market_sell_order(symbol, amt_to_sell)
            
        except Exception as e:
            logging.error(f"sell_all_base failed: {e}")
            raise

    # --------------------- aliases ---------------------
    def buy(self, symbol: str, amount_usd: float):
        return self.create_market_buy_order(symbol, amount_usd)

    def sell(self, symbol: str, amount: float):
        return self.create_market_sell_order(symbol, amount)

    # --------------------- trade logging ---------------------
    def _log_trade(self, action: str, symbol: str, amount: float, price: float):
        ts = datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        msg = f"[TRADE] {ts} | {action} {symbol} amount={amount:.8f} @ {price:.6f}"
        logging.info(msg)
        try:
            with open("trades.log", "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception as e:
            logging.error(f"❌ write trades.log failed: {e}")