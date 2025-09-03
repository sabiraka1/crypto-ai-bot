from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any


@dataclass(frozen=True)
class MaxOrders5mConfig:
    limit: int = 0  # 0 = РІС‹РєР»СЋС‡РµРЅРѕ


class MaxOrders5mRule:
    def __init__(self, cfg: MaxOrders5mConfig) -> None:
        self.cfg = cfg

    def _count_last_minutes(self, trades_repo: Any, symbol: str, minutes: int) -> int | None:
        # Р±С‹СЃС‚СЂС‹Р№ РїСѓС‚СЊ
        if hasattr(trades_repo, "count_orders_last_minutes"):
            try:
                return int(trades_repo.count_orders_last_minutes(symbol, minutes))
            except Exception:
                return None
        # РґРµРіСЂР°РґР°С†РёСЏ: РїСЂРѕР±СѓРµРј list_today + С„РёР»СЊС‚СЂ РїРѕ РІСЂРµРјРµРЅРё
        try:
            items = trades_repo.list_today(symbol)
            if not items:
                return 0
            now_ms = int(time.time() * 1000)
            thr = now_ms - minutes * 60_000

            # РїС‹С‚Р°РµРјСЃСЏ РІС‹С‚Р°С‰РёС‚СЊ timestamp РёР· item.{ts, timestamp, time} РёР»Рё dict
            def get_ts(x: Any) -> int:
                for k in ("ts", "timestamp", "time"):
                    v = getattr(x, k, None) if not isinstance(x, dict) else x.get(k)
                    if v is not None:
                        try:
                            return int(v)
                        except Exception:
                            continue
                return 0

            return sum(1 for x in items if get_ts(x) >= thr)
        except Exception:
            return None

    def check(self, *, symbol: str, trades_repo: Any) -> tuple[bool, str, dict]:
        if self.cfg.limit <= 0:
            return True, "disabled", {}
        cnt = self._count_last_minutes(trades_repo, symbol, 5)
        if isinstance(cnt, int) and cnt >= self.cfg.limit > 0:
            return False, "max_orders_5m", {"count": cnt, "limit": self.cfg.limit}
        return True, "ok", {}
