# src/crypto_ai_bot/core/config/env_reader.py
from __future__ import annotations
import os
from typing import Mapping, Optional, Sequence, List

class EnvReader:
    """Thin wrapper around a mapping (default: os.environ).
    Allows tests to inject their own mapping without touching the process env.
    """
    def __init__(self, data: Optional[Mapping[str, str]] = None) -> None:
        self._data: Mapping[str, str] = data if data is not None else os.environ  # type: ignore[assignment]

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._data.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = (self._.get_raw(key)).lower()
        if val in ("1","true","yes","y","on"): return True
        if val in ("0","false","no","n","off"): return False
        return bool(default)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self._get_raw(key))
        except Exception:
            return int(default)

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self._get_raw(key))
        except Exception:
            return float(default)

    def get_list(self, key: str, default: Optional[Sequence[str]] = None, sep: str = ",") -> List[str]:
        raw = self._data.get(key)
        if raw is None:
            return list(default) if default is not None else []
        return [x.strip() for x in raw.split(sep) if x.strip()]

    def _get_raw(self, key: str) -> str:
        return (self._data.get(key) or "").strip()
