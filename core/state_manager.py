import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from config.settings import TradingState, TradingConfig


class StateManager:
    """
    Управление состоянием торгового бота.
    - Потокобезопасно (RLock)
    - Атомарная запись файла (temp + replace)
    - Автобэкап битого JSON
    - Единые get/set/get_all
    - Совместимость: публичное поле `state` остаётся
    """

    def __init__(self, state_file: str = "bot_state.json"):
        self.state_file = state_file
        self._lock = threading.RLock()
        self.state: Dict[str, Any] = self._load_state()
        self._ensure_defaults()

    # -------------------- IO --------------------
    def _backup_file(self, src_path: str) -> Optional[str]:
        """Создать резервную копию повреждённого файла состояния."""
        try:
            if not os.path.exists(src_path):
                return None
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            bak_path = f"{src_path}.bak.{ts}"
            shutil.copy2(src_path, bak_path)
            return bak_path
        except Exception:
            return None

    def _safe_read_json(self, path: str) -> Optional[Dict[str, Any]]:
        """Безопасное чтение JSON; при ошибке возвращает None."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _load_state(self) -> Dict[str, Any]:
        """Загрузка состояния из файла; при проблемах — дефолты с автобэкапом."""
        if os.path.exists(self.state_file):
            data = self._safe_read_json(self.state_file)
            if isinstance(data, dict):
                return data
            # битый JSON: делаем бэкап и продолжаем с дефолтами
            self._backup_file(self.state_file)

        return self._default_state()

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        """Атомарная запись: сначала во временный файл, затем замена."""
        directory = os.path.dirname(os.path.abspath(self.state_file)) or "."
        os.makedirs(directory, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=directory, encoding="utf-8") as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, self.state_file)

    def save_state(self) -> None:
        """Сохранение состояния (потокобезопасно + атомарно)."""
        with self._lock:
            self._atomic_write(self.state)

    def load_state(self) -> None:
        """Принудительная перезагрузка состояния с диска (если нужно)."""
        with self._lock:
            self.state = self._load_state()
            self._ensure_defaults(write_if_changed=True)

    # -------------------- Defaults --------------------
    def _default_state(self) -> Dict[str, Any]:
        """Базовый скелет состояния (совместимый с PositionManager и main)."""
        return {
            "trading_state": TradingState.WAITING.value,
            "position": None,
            "last_trade_time": None,
            "cooldown_until": None,
            "total_trades": 0,
            "total_profit": 0.0,
            "win_trades": 0,
            # поля позиции
            "in_position": False,
            "opening": False,
            "symbol": None,
            "entry_price": 0.0,
            "qty_usd": 0.0,
            "qty_base": 0.0,
            "buy_score": None,
            "ai_score": None,
            "final_score": None,
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
            # цикл/свечи
            "last_candle_ts": None,
        }

    def _ensure_defaults(self, write_if_changed: bool = False) -> None:
        """Гарантирует наличие ключей, которые ожидают другие компоненты."""
        with self._lock:
            defaults = self._default_state()
            changed = False
            for k, v in defaults.items():
                if k not in self.state:
                    self.state[k] = v
                    changed = True
            if write_if_changed and changed:
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
            return dict(self.state)

    def flush(self) -> None:
        """Совместимость (запись уже атомарная)."""
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

    def start_cooldown(self, seconds: Optional[int] = None) -> None:
        """
        Установить паузу после сделки. Если seconds не задан —
        берём TradingConfig.POST_SALE_COOLDOWN (в минутах).
        """
        with self._lock:
            if seconds is None:
                minutes = getattr(TradingConfig, "POST_SALE_COOLDOWN", 0) or 0
                delta = timedelta(minutes=int(minutes))
            else:
                delta = timedelta(seconds=int(seconds))
            cooldown_time = datetime.now() + delta
            self.state["cooldown_until"] = cooldown_time.isoformat()
            self._atomic_write(self.state)

    # -------------------- Position helpers --------------------
    def reset_position(self) -> None:
        """Сброс всех полей открытой позиции."""
        with self._lock:
            self.state.update({
                "in_position": False,
                "opening": False,
                "symbol": None,
                "entry_price": 0.0,
                "qty_usd": 0.0,
                "qty_base": 0.0,
                "buy_score": None,
                "ai_score": None,
                "final_score": None,
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
            })
            self._atomic_write(self.state)
