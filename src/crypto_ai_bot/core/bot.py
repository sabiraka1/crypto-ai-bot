# фрагмент: src/crypto_ai_bot/core/bot.py
from __future__ import annotations
from typing import Optional
from .settings import Settings
from .brokers import create_broker, ExchangeInterface
from .storage.sqlite_adapter import create_repositories  # фабрика репозиториев

class Bot:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.broker: ExchangeInterface = create_broker(cfg)  # <-- ЕДИНАЯ точка
        self.repos = create_repositories(cfg.DB_PATH)        # интерфейсы через контейнер
        self._last_decision: Optional[dict] = None

    # ... evaluate/execute/get_status остаются без изменения публичного контракта
