from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any


@dataclass(frozen=True)
class CooldownConfig:
    cooldown_sec: int = 0  # 0 = disabled


class CooldownRule:
    def __init__(self, cfg: CooldownConfig) -> None:
        self.cfg = cfg

    def _last_ts(self, trades_repo: Any, symbol: str) -> int | None:
        """Возвращает timestamp последней сделки (мс)."""
        if hasattr(trades_repo, "last_trade_ts_ms"):
            try:
                res = trades_repo.last_trade_ts_ms(symbol)
                if res is not None:
                    return int(res)
            except Exception:
                pass

        # Фолбэк: ищем максимальный ts в list_today
        try:
            items = trades_repo.list_today(symbol)
            if not items:
                return None

            def get_ts(x: Any) -> int:
                for k in ("ts", "timestamp", "time", "ts_ms"):
                    v = getattr(x, k, None) if not isinstance(x, dict) else x.get(k)
                    if v is not None:
                        try:
                            return int(v)
                        except Exception:
                            continue
                return 0

            ts = max((get_ts(x) for x in items), default=0)
            return ts or None
        except Exception:
            return None

    def check(self, *, symbol: str, trades_repo: Any) -> tuple[bool, str, dict]:
        """Проверяет, прошла ли пауза после последней сделки."""
        if self.cfg.cooldown_sec <= 0:
            return True, "disabled", {}

        last = self._last_ts(trades_repo, symbol)
        if last is None:
            return True, "no_trades", {}

        now_ms = int(time.time() * 1000)
        delta_sec = (now_ms - last) / 1000.0

        if delta_sec < self.cfg.cooldown_sec:
            return False, "cooldown", {"delta_sec": int(delta_sec), "need_sec": self.cfg.cooldown_sec}

        return True, "ok", {}
