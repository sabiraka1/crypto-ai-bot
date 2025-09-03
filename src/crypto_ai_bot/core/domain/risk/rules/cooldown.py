from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import time

@dataclass(frozen=True)
class CooldownConfig:
    cooldown_sec: int = 0  # 0 = выключено

class CooldownRule:
    def __init__(self, cfg: CooldownConfig) -> None:
        self.cfg = cfg

    def _last_ts(self, trades_repo: Any, symbol: str) -> int | None:
        if hasattr(trades_repo, "last_trade_ts_ms"):
            try:
                return int(trades_repo.last_trade_ts_ms(symbol))
            except Exception:
                return None
        try:
            items = trades_repo.list_today(symbol)
            if not items:
                return None
            # предполагаем, что последний — в конце; иначе сортируем по ts
            def get_ts(x: Any) -> int:
                for k in ("ts", "timestamp", "time"):
                    v = getattr(x, k, None) if not isinstance(x, dict) else x.get(k)
                    if v is not None:
                        try:
                            return int(v)
                        except Exception:
                            continue
                return 0
            last = max(items, key=get_ts)
            ts = get_ts(last)
            return ts if ts > 0 else None
        except Exception:
            return None

    def check(self, *, symbol: str, trades_repo: Any) -> tuple[bool, str, dict]:
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
