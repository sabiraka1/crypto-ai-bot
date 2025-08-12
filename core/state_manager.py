import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from config.settings import TradingState


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