from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import time
from typing import Any


@dataclass(frozen=True)
class MaxTurnover5mConfig:
    limit_quote: Decimal = Decimal("0")


class MaxTurnover5mRule:
    def __init__(self, cfg: MaxTurnover5mConfig) -> None:
        self.cfg = cfg

    def _turnover_last_minutes(self, trades_repo: Any, symbol: str, minutes: int) -> Decimal | None:
        if hasattr(trades_repo, "turnover_last_minutes"):
            try:
                return Decimal(str(trades_repo.turnover_last_minutes(symbol, minutes)))
            except Exception:
                return None
        try:
            items = trades_repo.list_today(symbol)
            if not items:
                return Decimal("0")
            now_ms = int(time.time() * 1000)
            thr = now_ms - minutes * 60_000

            def get_ts(x: Any) -> int:
                for k in ("ts", "timestamp", "time"):
                    v = getattr(x, k, None) if not isinstance(x, dict) else x.get(k)
                    if v is not None:
                        try:
                            return int(v)
                        except Exception:
                            continue
                return 0

            def get_quote(x: Any) -> Decimal:
                for k in ("quote", "quote_amount", "filled_quote", "amount_quote"):
                    v = getattr(x, k, None) if not isinstance(x, dict) else x.get(k)
                    if v is not None:
                        try:
                            return Decimal(str(v))
                        except Exception:
                            continue
                return Decimal("0")

            s = Decimal("0")
            for it in items:
                if get_ts(it) >= thr:
                    s += abs(get_quote(it))
            return s
        except Exception:
            return None

    def check(self, *, symbol: str, trades_repo: Any) -> tuple[bool, str, dict]:
        lim = self.cfg.limit_quote
        if lim <= 0:
            return True, "disabled", {}
        val = self._turnover_last_minutes(trades_repo, symbol, 5)
        if val is not None and val >= lim:
            return False, "max_turnover_5m", {"turnover": str(val), "limit": str(lim)}
        return True, "ok", {}
