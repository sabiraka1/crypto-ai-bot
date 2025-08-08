import json
import os
from datetime import datetime, timedelta
from config.settings import TradingState, TradingConfig

class StateManager:
    """Управление состоянием торгового бота"""
    
    def __init__(self, state_file: str = "bot_state.json"):
        self.state_file = state_file
        self.state = self._load_state()
    
    def _load_state(self) -> dict:
        """Загрузка состояния из файла"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        return {
            "trading_state": TradingState.WAITING.value,
            "position": None,
            "last_trade_time": None,
            "cooldown_until": None,
            "total_trades": 0,
            "total_profit": 0.0,
            "win_trades": 0
        }
    
    def save_state(self):
        """Сохранение состояния в файл"""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def get_trading_state(self) -> TradingState:
        return TradingState(self.state["trading_state"])
    
    def set_trading_state(self, state: TradingState):
        self.state["trading_state"] = state.value
        self.save_state()
    
    def is_in_cooldown(self) -> bool:
        if not self.state.get("cooldown_until"):
            return False
        
        cooldown_time = datetime.fromisoformat(self.state["cooldown_until"])
        return datetime.now() < cooldown_time
    
    def start_cooldown(self):
        cooldown_time = datetime.now() + timedelta(minutes=TradingConfig.POST_SALE_COOLDOWN)
        self.state["cooldown_until"] = cooldown_time.isoformat()
        self.save_state()