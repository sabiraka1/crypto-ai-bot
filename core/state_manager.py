import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from enum import Enum


class TradingState(Enum):
    WAITING = "waiting"
    ANALYZING = "analyzing"
    ENTERING = "entering"
    IN_POSITION = "in_position"
    EXITING = "exiting"
    COOLDOWN = "cooldown"
    PAUSED = "paused"


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
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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
            "updated_at": None,
            # управление позицией
            "last_manage_check": None,
            "entry_ts": None,
            "market_condition": None,
            "pattern": None,
            "order_id": None
        }


    def _derive_position_keys(self) -> set:
        """Определяем, какие ключи относятся к открытой позиции, исходя из _default_state().
        Поддерживает расширения без дублирования списков ключей.
        """
        defaults = self._default_state()
        # Ключи, которые НЕ относятся к позиции и не должны сбрасываться reset_position()
        non_position = {
            "trading_state",
            "position",
            "last_trade_time",
            "cooldown_until",
            "total_trades",
            "total_profit",
            "win_trades",
            "last_candle_ts",
            "updated_at",
            "last_signal_ts",
        }
        # Возвращаем только те ключи, которые существуют в defaults и не являются служебными
        return {k for k in defaults.keys() if k not in non_position}

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
        """Получение значения по ключу"""
        with self._lock:
            return self.state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Установка значения по ключу с автосохранением"""
        with self._lock:
            self.state[key] = value
            self._atomic_write(self.state)

    def update(self, data: Dict[str, Any]) -> None:
        """Обновление нескольких значений одновременно"""
        with self._lock:
            self.state.update(data)
            self._atomic_write(self.state)

    def get_all(self) -> Dict[str, Any]:
        """Получение всего состояния"""
        with self._lock:
            return dict(self.state)

    def flush(self) -> None:
        """Принудительная запись на диск (совместимость)."""
        with self._lock:
            self._atomic_write(self.state)

    # -------------------- Trading state API --------------------
    def get_trading_state(self) -> TradingState:
        """Получение состояния торговли"""
        with self._lock:
            state_value = self.state.get("trading_state", TradingState.WAITING.value)
            try:
                return TradingState(state_value)
            except ValueError:
                return TradingState.WAITING

    def set_trading_state(self, state: TradingState) -> None:
        """Установка состояния торговли"""
        with self._lock:
            self.state["trading_state"] = state.value
            self._atomic_write(self.state)

    # -------------------- Cooldown --------------------
    def is_in_cooldown(self) -> bool:
        """Проверка нахождения в кулдауне"""
        with self._lock:
            ts = self.state.get("cooldown_until")
            if not ts:
                return False
            try:
                cooldown_time = datetime.fromisoformat(ts)
                if cooldown_time.tzinfo is None:
                    cooldown_time = cooldown_time.replace(tzinfo=timezone.utc)
            except Exception:
                return False
            return datetime.now(timezone.utc) < cooldown_time

    def start_cooldown(self, seconds: Optional[int] = None) -> None:
        """
        Установить паузу после сделки. 
        Если seconds не задан — используем 60 минут по умолчанию.
        """
        with self._lock:
            if seconds is None:
                delta = timedelta(minutes=60)  # Стандартный кулдаун
            else:
                delta = timedelta(seconds=int(seconds))
            cooldown_time = datetime.now(timezone.utc) + delta
            self.state["cooldown_until"] = cooldown_time.isoformat()
            self._atomic_write(self.state)

    def clear_cooldown(self) -> None:
        """Очистка кулдауна"""
        with self._lock:
            self.state["cooldown_until"] = None
            self._atomic_write(self.state)

    # -------------------- Position helpers --------------------
    def reset_position(self) -> None:
        """Сброс всех полей открытой позиции (синхронизирован с _default_state)."""
        with self._lock:
            defaults = self._default_state()
            pos_keys = self._derive_position_keys()
            for k in pos_keys:
                self.state[k] = defaults.get(k)
            # отметим время обновления в UTC
            self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._atomic_write(self.state)

    def is_position_active(self) -> bool:
        """Проверка активности позиции"""
        with self._lock:
            return bool(self.state.get("in_position") or self.state.get("opening"))

    def get_position_info(self) -> Dict[str, Any]:
        """Получение информации о позиции"""
        with self._lock:
            if not self.is_position_active():
                return {"active": False}
            
            return {
                "active": True,
                "symbol": self.state.get("symbol"),
                "entry_price": self.state.get("entry_price"),
                "qty_usd": self.state.get("qty_usd"),
                "qty_base": self.state.get("qty_base"),
                "sl_price": self.state.get("sl_atr"),
                "tp1_price": self.state.get("tp1_atr"),
                "tp2_price": self.state.get("tp2_atr"),
                "partial_taken": self.state.get("partial_taken", False),
                "trailing_on": self.state.get("trailing_on", False),
                "entry_time": self.state.get("entry_ts"),
                "buy_score": self.state.get("buy_score"),
                "ai_score": self.state.get("ai_score"),
                "market_condition": self.state.get("market_condition"),
                "pattern": self.state.get("pattern")
            }

    # -------------------- Statistics --------------------
    def increment_trade_count(self) -> None:
        """Увеличение счетчика сделок"""
        with self._lock:
            self.state["total_trades"] = self.state.get("total_trades", 0) + 1
            self._atomic_write(self.state)

    def add_profit(self, profit: float) -> None:
        """Добавление прибыли к общей статистике"""
        with self._lock:
            self.state["total_profit"] = self.state.get("total_profit", 0.0) + float(profit)
            if profit > 0:
                self.state["win_trades"] = self.state.get("win_trades", 0) + 1
            self._atomic_write(self.state)

    def get_statistics(self) -> Dict[str, Any]:
        """Получение торговой статистики"""
        with self._lock:
            total_trades = self.state.get("total_trades", 0)
            win_trades = self.state.get("win_trades", 0)
            total_profit = self.state.get("total_profit", 0.0)
            
            win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
            
            return {
                "total_trades": total_trades,
                "win_trades": win_trades,
                "lose_trades": total_trades - win_trades,
                "win_rate": round(win_rate, 2),
                "total_profit": round(total_profit, 2)
            }

    # -------------------- Utilities --------------------
    def clear_all(self) -> None:
        """Полная очистка состояния"""
        with self._lock:
            self.state = self._default_state()
            self._atomic_write(self.state)

    def export_state(self) -> Dict[str, Any]:
        """Экспорт состояния для отладки"""
        with self._lock:
            return dict(self.state)

    def import_state(self, new_state: Dict[str, Any]) -> None:
        """Импорт состояния (осторожно!)"""
        with self._lock:
            # Проверяем что это валидный словарь
            if isinstance(new_state, dict):
                # мягкая валидация ключей, чтобы ловить опечатки
                defaults = self._default_state()
                unknown = set(new_state.keys()) - set(defaults.keys())
                if unknown:
                    import logging
                    logging.warning("import_state: unknown keys: %s", sorted(unknown))
                self.state = dict(new_state)
                self._ensure_defaults()
                self._atomic_write(self.state)