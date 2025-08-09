import json
import os
import tempfile
import threading
from datetime import datetime, timedelta
from typing import Any, Dict

from config.settings import TradingState, TradingConfig


class StateManager:
    """
    Управление состоянием торгового бота.
    - Потокобезопасно (RLock)
    - Атомарная запись файла (через temp + replace)
    - Единые get/set/get_all
    - Совместимость: публичное поле `state` остаётся (но изменять его руками не нужно)
    """

    def __init__(self, state_file: str = "bot_state.json"):
        self.state_file = state_file
        self._lock = threading.RLock()
        self.state: Dict[str, Any] = self._load_state()
        self._ensure_defaults()

    # -------------------- IO --------------------
    def _load_state(self) -> dict:
        """Загрузка состояния из файла (если нет — базовые значения)."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass

        # Базовый скелет состояния
        return {
            "trading_state": TradingState.WAITING.value,
            "position": None,
            "last_trade_time": None,
            "cooldown_until": None,
            "total_trades": 0,
            "total_profit": 0.0,
            "win_trades": 0,
            # поля позиции (для совместимости с PositionManager)
            "in_position": False,
            "opening": False,
            "symbol": None,
            "entry_price": 0.0,
            "qty_usd": 0.0,
            "qty_base": 0.0,
            "buy_score": None,
            "ai_score": None,
            "amount_frac": None,
            "tp_price_pct": 0.0,
            "sl_price_pct": 0.0,
            "tp1_atr": 0.0,
            "tp2_atr": 0.0,
            "sl_atr": 0.0,
            "trailing_on": False,
            "partial_taken": False,
            "close_price": None,
            "last_reason": None,
        }

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        """Атомарная запись: сначала во временный файл, затем замена."""
        directory = os.path.dirname(os.path.abspath(self.state_file)) or "."
        with tempfile.NamedTemporaryFile("w", delete=False, dir=directory, encoding="utf-8") as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, self.state_file)

    def save_state(self) -> None:
        """Сохранение состояния (потокобезопасно + атомарно)."""
        with self._lock:
            self._atomic_write(self.state)

    # -------------------- Defaults --------------------
    def _ensure_defaults(self) -> None:
        """Гарантирует наличие ключей, которые ожидают другие компоненты."""
        with self._lock:
            defaults = {
                "trading_state": TradingState.WAITING.value,
                "position": None,
                "last_trade_time": None,
                "cooldown_until": None,
                "total_trades": 0,
                "total_profit": 0.0,
                "win_trades": 0,
                "in_position": False,
                "opening": False,
                "symbol": None,
                "entry_price": 0.0,
                "qty_usd": 0.0,
                "qty_base": 0.0,
                "buy_score": None,
                "ai_score": None,
                "amount_frac": None,
                "tp_price_pct": 0.0,
                "sl_price_pct": 0.0,
                "tp1_atr": 0.0,
                "tp2_atr": 0.0,
                "sl_atr": 0.0,
                "trailing_on": False,
                "partial_taken": False,
                "close_price": None,
                "last_reason": None,
            }
            changed = False
            for k, v in defaults.items():
                if k not in self.state:
                    self.state[k] = v
                    changed = True
            if changed:
                self._atomic_write(self.state)

    # -------------------- Generic API --------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self.state[key] = value
            self._atomic_write(self.state)

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            # возвращаем копию, чтобы снаружи не модифицировали напрямую
            return dict(self.state)

    def flush(self) -> None:
        """Совместимость с интерфейсами repo: здесь запись идёт сразу, так что no-op."""
        # Оставлено для совместимости
        pass

    # -------------------- Trading state API --------------------
    def get_trading_state(self) -> TradingState:
        with self._lock:
            return TradingState(self.state["trading_state"])

    def set_trading_state(self, state: TradingState) -> None:
        with self._lock:
            self.state["trading_state"] = state.value
            self._atomic_write(self.state)

    # -------------------- Cooldown --------------------
    def is_in_cooldown(self) -> bool:
        with self._lock:
            ts = self.state.get("cooldown_until")
            if not ts:
                return False
            try:
                cooldown_time = datetime.fromisoformat(ts)
            except Exception:
                return False
            return datetime.now() < cooldown_time

    def start_cooldown(self) -> None:
        with self._lock:
            cooldown_time = datetime.now() + timedelta(minutes=TradingConfig.POST_SALE_COOLDOWN)
            self.state["cooldown_until"] = cooldown_time.isoformat()
            self._atomic_write(self.state)
