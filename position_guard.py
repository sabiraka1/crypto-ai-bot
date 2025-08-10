# position_guard.py
# Дополнительная защита от множественных позиций

import logging
import threading
import time
from typing import Optional
from datetime import datetime, timezone

class PositionGuard:
    """
    Глобальная защита от множественных позиций на уровне приложения.
    Работает как дополнительный слой защиты к PositionManager.
    """
    
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(PositionGuard, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._position_lock = threading.RLock()
        self._last_entry_time = None
        self._min_entry_interval = 60  # Минимум 60 секунд между входами
        self._active_symbol = None
        self._entry_in_progress = False
        self._initialized = True
        
        logging.info("🛡️ PositionGuard initialized")
    
    def can_open_position(self, symbol: str, state_manager) -> tuple[bool, str]:
        """
        Проверяет можно ли открыть позицию.
        Возвращает (разрешено, причина_отказа)
        """
        with self._position_lock:
            now = datetime.now(timezone.utc)
            
            # 1. Проверяем что нет входа в процессе
            if self._entry_in_progress:
                return False, "entry_already_in_progress"
            
            # 2. Проверяем состояние в state_manager
            try:
                st = state_manager.state
                if st.get("in_position") or st.get("opening"):
                    return False, "position_active_in_state"
            except Exception as e:
                logging.error(f"Error checking state manager: {e}")
                return False, "state_check_error"
            
            # 3. Проверяем временной интервал
            if self._last_entry_time:
                time_since = (now - self._last_entry_time).total_seconds()
                if time_since < self._min_entry_interval:
                    return False, f"too_soon_{int(self._min_entry_interval - time_since)}s"
            
            # 4. Проверяем что не пытаемся открыть другой символ
            if self._active_symbol and self._active_symbol != symbol:
                return False, f"different_symbol_{self._active_symbol}"
            
            return True, "allowed"
    
    def begin_entry(self, symbol: str) -> bool:
        """
        Начинает процесс входа. Возвращает True если успешно захватили блокировку.
        """
        with self._position_lock:
            if self._entry_in_progress:
                logging.warning(f"🛡️ Entry already in progress for {self._active_symbol}")
                return False
            
            self._entry_in_progress = True
            self._active_symbol = symbol
            self._last_entry_time = datetime.now(timezone.utc)
            
            logging.info(f"🛡️ Entry lock acquired for {symbol}")
            return True
    
    def complete_entry(self, symbol: str, success: bool):
        """
        Завершает процесс входа.
        """
        with self._position_lock:
            if not self._entry_in_progress or self._active_symbol != symbol:
                logging.warning(f"🛡️ Complete entry called for wrong symbol: {symbol} vs {self._active_symbol}")
                return
            
            self._entry_in_progress = False
            
            if not success:
                # При неудаче сбрасываем активный символ
                self._active_symbol = None
                # И время последнего входа (разрешаем повторить быстрее)
                self._last_entry_time = None
                logging.info(f"🛡️ Entry failed, lock released for {symbol}")
            else:
                logging.info(f"🛡️ Entry successful, position active for {symbol}")
    
    def position_closed(self, symbol: str):
        """
        Уведомляет о закрытии позиции.
        """
        with self._position_lock:
            if self._active_symbol == symbol:
                self._active_symbol = None
                self._entry_in_progress = False
                logging.info(f"🛡️ Position closed, guard reset for {symbol}")
    
    def force_reset(self):
        """
        Принудительно сбрасывает все блокировки. Только для экстренных случаев.
        """
        with self._position_lock:
            old_symbol = self._active_symbol
            self._entry_in_progress = False
            self._active_symbol = None
            self._last_entry_time = None
            logging.warning(f"🛡️ Force reset executed, was tracking: {old_symbol}")
    
    def get_status(self) -> dict:
        """
        Возвращает текущий статус guard'а для диагностики.
        """
        with self._position_lock:
            return {
                "entry_in_progress": self._entry_in_progress,
                "active_symbol": self._active_symbol,
                "last_entry_time": self._last_entry_time.isoformat() if self._last_entry_time else None,
                "min_entry_interval": self._min_entry_interval
            }

# Глобальный экземпляр
position_guard = PositionGuard()