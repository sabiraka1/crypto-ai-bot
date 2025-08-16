# фрагмент: src/crypto_ai_bot/core/orchestrator.py
from __future__ import annotations
from .settings import Settings
from .brokers import create_broker, ExchangeInterface

class Orchestrator:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.broker: ExchangeInterface = create_broker(cfg)  # <-- единая фабрика
        # далее — планирование и lifecycle...
