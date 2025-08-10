import ccxt
import logging
import threading
import time
import json
import os
from datetime import datetime
from decimal import Decimal

# ===============================
# Exchange Client
# ===============================

class ExchangeClient:
    def __init__(self, api_key, api_secret, safe_mode=True, log_dir="logs"):
        self.safe_mode = bool(int(safe_mode))
        self.api_key = api_key
        self.api_secret = api_secret
        self.trailing_stops = {}
        self.trailing_threads = {}
        self.lock = threading.RLock()

        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        self.log_file = os.path.join(log_dir, "trades.log")
        self.csv_file = os.path.join(log_dir, "trades.csv")

        if not self.safe_mode:
            self.exchange = ccxt.gateio({
                'apiKey': self.api_key,
                'secret': self.api_secret
            })
        else:
            self.exchange = None

    # ===============================
    # Logging utilities
    # ===============================
    def log_trade(self, action, symbol, amount, price, extra=""):
        log_entry = f"{datetime.utcnow().isoformat()} | {action} | {symbol} | amount={amount} | price={price} | {extra}"
        logging.info(log_entry)

        with open(self.log_file, "a") as f:
            f.write(log_entry + "\n")

        with open(self.csv_file, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()},{action},{symbol},{amount},{price},{extra}\n")

    # ===============================
    # Order Execution
    # ===============================
    def create_market_buy_order(self, symbol, amount):
        if self.safe_mode:
            self.log_trade("BUY_SIM", symbol, amount, "market")
            return {"status": "simulated"}
        order = self.exchange.create_market_buy_order(symbol, amount)
        self.log_trade("BUY", symbol, amount, order['price'])
        return order

    def create_market_sell_order(self, symbol, amount):
        if self.safe_mode:
            self.log_trade("SELL_SIM", symbol, amount, "market")
            return {"status": "simulated"}
        order = self.exchange.create_market_sell_order(symbol, amount)
        self.log_trade("SELL", symbol, amount, order['price'])
        return order

    # ===============================
    # Partial Sell
    # ===============================
    def sell_partial(self, symbol, fraction, price=None):
        """Sell a fraction (0.0 - 1.0) of current position"""
        with self.lock:
            if fraction <= 0 or fraction > 1:
                raise ValueError("Fraction must be between 0 and 1")

            position_amount = self.get_position_amount(symbol)
            sell_amount = Decimal(position_amount) * Decimal(fraction)

            if sell_amount <= 0:
                logging.warning(f"No position to sell for {symbol}")
                return None

            if self.safe_mode:
                self.log_trade("SELL_PARTIAL_SIM", symbol, sell_amount, price or "market", f"{fraction*100}%")
                return {"status": "simulated"}

            if price:
                order = self.exchange.create_limit_sell_order(symbol, float(sell_amount), price)
            else:
                order = self.exchange.create_market_sell_order(symbol, float(sell_amount))

            self.log_trade("SELL_PARTIAL", symbol, sell_amount, price or order.get('price', 'market'), f"{fraction*100}%")
            return order

    # ===============================
    # Position / Balance Helpers
    # ===============================
    def get_position_amount(self, symbol):
        if self.safe_mode:
            return 1.0  # simulate 1 unit for testing
        balance = self.exchange.fetch_balance()
        base_currency = symbol.split("/")[0]
        return balance['free'].get(base_currency, 0)

    def get_market_price(self, symbol):
        if self.safe_mode:
            return 100.0
        ticker = self.exchange.fetch_ticker(symbol)
        return ticker['last']

    # ===============================
    # Trailing Stop
    # ===============================
    def start_trailing_stop(self, symbol, entry_price, trailing_percent, check_interval=5):
        """Start a trailing stop that closes the position if price drops more than trailing_percent from peak"""
        with self.lock:
            if symbol in self.trailing_threads:
                logging.warning(f"Trailing stop already active for {symbol}")
                return

            self.trailing_stops[symbol] = {
                "peak_price": entry_price,
                "trailing_percent": trailing_percent,
                "active": True
            }

            def monitor():
                logging.info(f"Started trailing stop for {symbol} ({trailing_percent}%)")
                while self.trailing_stops[symbol]["active"]:
                    current_price = self.get_market_price(symbol)
                    if current_price > self.trailing_stops[symbol]["peak_price"]:
                        self.trailing_stops[symbol]["peak_price"] = current_price

                    drop_percent = ((self.trailing_stops[symbol]["peak_price"] - current_price) / self.trailing_stops[symbol]["peak_price"]) * 100

                    if drop_percent >= trailing_percent:
                        logging.info(f"Trailing stop triggered for {symbol} at {current_price} (drop {drop_percent:.2f}%)")
                        self.create_market_sell_order(symbol, self.get_position_amount(symbol))
                        self.trailing_stops[symbol]["active"] = False
                        break

                    time.sleep(check_interval)

            t = threading.Thread(target=monitor, daemon=True)
            self.trailing_threads[symbol] = t
            t.start()

    def stop_trailing_stop(self, symbol):
        with self.lock:
            if symbol in self.trailing_stops:
                self.trailing_stops[symbol]["active"] = False
                logging.info(f"Trailing stop stopped for {symbol}")

