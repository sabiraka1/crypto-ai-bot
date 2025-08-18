# src/crypto_ai_bot/core/types/base.py
from __future__ import annotations
from typing import NewType

ID = NewType("ID", str)
Millis = NewType("Millis", int)
Symbol = NewType("Symbol", str)
Timeframe = NewType("Timeframe", str)
