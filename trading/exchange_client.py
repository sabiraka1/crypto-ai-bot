import ccxt
import os
import logging
from datetime import datetime

class ExchangeClient:
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key or os.getenv('GATE_API_KEY')
        self.api_secret = api_secret or os.getenv('GATE_API_SECRET')
        self.exchange = ccxt.gateio({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True
        })
        self.markets = self.exchange.load_markets()
        logging.info("✅ Exchange client initialized and markets loaded")

    def _log_trade(self, action, symbol, amount, price):
        """Логирование сделки в файл и консоль"""
        msg = f"[TRADE] {datetime.utcnow()} UTC | {action.upper()} {amount} {symbol} @ {price} USDT"
        logging.info(msg)
        with open("trades.log", "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def get_balance(self, asset):
        balance = self.exchange.fetch_balance()
        return balance['free'].get(asset, 0)

    def get_last_price(self, symbol):
        ticker = self.exchange.fetch_ticker(symbol)
        return ticker['last']

    def _apply_precision(self, symbol, amount):
        """Применяем точность и проверяем минимальный объём"""
        amount = self.exchange.amount_to_precision(symbol, amount)
        min_amount = self.markets[symbol]['limits']['amount']['min']
        if float(amount) < min_amount:
            amount = min_amount
        return float(amount)

    def buy(self, symbol, amount_usd):
        """Маркет-покупка на указанную сумму в USD"""
        last_price = self.get_last_price(symbol)
        amount = amount_usd / last_price
        amount = self._apply_precision(symbol, amount)
        order = self.exchange.create_market_buy_order(symbol, amount)
        self._log_trade("buy", symbol, amount, last_price)
        return order

    def sell(self, symbol, amount):
        """Маркет-продажа"""
        amount = self._apply_precision(symbol, amount)
        last_price = self.get_last_price(symbol)
        order = self.exchange.create_market_sell_order(symbol, amount)
        self._log_trade("sell", symbol, amount, last_price)
        return order
