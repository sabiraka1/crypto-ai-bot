# src/crypto_ai_bot/core/validators/__init__.py
from __future__ import annotations
from .config import validate_config  # re-export единственной каноничной функции

__all__ = ["validate_config"]
