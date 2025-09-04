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
        """Get timestamp of last trade."""
        # Try fast path first
        if hasattr(trades_repo, "last_trade_ts_ms"):
            try:
                result = trades_repo.last_trade_ts_ms(symbol)
                if result is not None:
                    return int(result)
            except Exception:
                pass

        # Fallback to list_today
        try:
            items = trades_repo.list_today(symbol)
            if not items:
                return None

            # Find the trade with maximum timestamp
            def get_ts(x: Any) -> int:
                timestamp_keys = ["ts", "timestamp", "time", "ts_ms"]
                for key in timestamp_keys:
                    value = None
                    if isinstance(x, dict):
                        value = x.get(key)
                    else:
                        value = getattr(x, key, None)

                    if value is not None:
                        try:
                            return int(value)
                        except Exception:
                            continue
                return 0

            last = max(items, key=get_ts)
            ts = get_ts(last)
            return ts if ts > 0 else None
        except Exception:
            return None

    def check(self, *, symbol: str, trades_repo: Any) -> tuple[bool, str, dict]:
        """Check if cooldown period has passed."""
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
