import logging
from datetime import datetime
from typing import Optional, Dict
from config.settings import TradingConfig, TradingState
from core.state_manager import StateManager
from trading.exchange_client import ExchangeClient

class PositionManager:
    """Управление торговыми позициями"""
    
    def __init__(self, exchange_client: ExchangeClient, state_manager: StateManager):
        self.exchange = exchange_client
        self.state = state_manager
    
    def open_position(self, symbol: str, amount_usd: float) -> Optional[Dict]:
        """Открытие позиции"""
        try:
            if self.state.get_trading_state() != TradingState.WAITING:
                logging.warning("Cannot open position: not in WAITING state")
                return None
            
            # Проверка баланса
            balance = self.exchange.get_balance()
            usdt_balance = balance.get('USDT', {}).get('free', 0)
            
            if usdt_balance < amount_usd:
                logging.error(f"Insufficient balance: {usdt_balance} < {amount_usd}")
                return None
            
            # Создание ордера
            order = self.exchange.create_market_buy_order(symbol, amount_usd)
            
            # Обновление состояния
            current_price = self.exchange.get_current_price(symbol)
            position = {
                "symbol": symbol,
                "entry_price": current_price,
                "quantity": order.get('filled', 0),
                "entry_time": datetime.now().isoformat(),
                "entry_amount_usd": amount_usd,
                "order_id": order.get('id')
            }
            
            self.state.state["position"] = position
            self.state.set_trading_state(TradingState.IN_POSITION)
            
            logging.info(f"🎯 Position opened: {position['quantity']:.6f} {symbol} at ${current_price:.2f}")
            return position
            
        except Exception as e:
            logging.error(f"Failed to open position: {e}")
            return None
    
    def close_position(self, reason: str = "Manual close") -> Optional[Dict]:
        """Закрытие позиции"""
        try:
            if self.state.get_trading_state() != TradingState.IN_POSITION:
                logging.warning("Cannot close position: not in IN_POSITION state")
                return None
            
            position = self.state.state.get("position")
            if not position:
                logging.error("No position to close")
                return None
            
            # Создание ордера на продажу
            order = self.exchange.create_market_sell_order(
                position["symbol"], 
                position["quantity"]
            )
            
            # Расчет прибыли
            current_price = self.exchange.get_current_price(position["symbol"])
            profit_pct = ((current_price - position["entry_price"]) / position["entry_price"]) * 100
            profit_usd = (current_price - position["entry_price"]) * position["quantity"]
            
            # Обновление статистики
            self.state.state["total_trades"] += 1
            self.state.state["total_profit"] += profit_usd
            if profit_usd > 0:
                self.state.state["win_trades"] += 1
            
            # Очистка позиции и установка cooldown
            self.state.state["position"] = None
            self.state.state["last_trade_time"] = datetime.now().isoformat()
            self.state.set_trading_state(TradingState.COOLDOWN)
            self.state.start_cooldown()
            
            result = {
                "symbol": position["symbol"],
                "exit_price": current_price,
                "profit_pct": profit_pct,
                "profit_usd": profit_usd,
                "reason": reason,
                "exit_time": datetime.now().isoformat()
            }
            
            logging.info(f"💰 Position closed: {profit_pct:.2f}% (${profit_usd:.2f}) - {reason}")
            return result
            
        except Exception as e:
            logging.error(f"Failed to close position: {e}")
            return None
    
    def get_position_profit(self) -> float:
        """Получение текущей прибыли позиции в %"""
        try:
            position = self.state.state.get("position")
            if not position:
                return 0.0
            
            current_price = self.exchange.get_current_price(position["symbol"])
            profit_pct = ((current_price - position["entry_price"]) / position["entry_price"]) * 100
            return profit_pct
            
        except Exception as e:
            logging.error(f"Failed to calculate position profit: {e}")
            return 0.0