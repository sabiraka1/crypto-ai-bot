from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, DefaultDict
from collections import defaultdict

from ..storage.facade import Storage
from ..brokers.base import IBroker
from ...utils.logging import get_logger

_log = get_logger("risk.manager")


@dataclass
class RiskConfig:
    cooldown_sec: int = 60
    max_spread_pct: float = 0.3                     # % (0.3 = 0.3%)
    max_position_base: float = 0.02                 # base qty
    max_orders_per_hour: int = 6
    daily_loss_limit_quote: float = 100.0


@dataclass
class RiskManager:
    storage: Storage
    config: RiskConfig

    # in-memory state (персист не обязателен для первой версии)
    _last_exec_ms: Dict[str, int] = field(default_factory=dict, init=False)
    _orders_hist_ms: DefaultDict[str, List[int]] = field(default_factory=lambda: defaultdict(list), init=False)

    async def check(self, *, symbol: str, action: str, evaluation: Dict[str, Any]) -> Dict[str, Any]:
        """
        ЕДИНЫЙ формат ответа:
          {"ok": bool, "reasons": [str, ...], "limits": {...}}
        Где reasons пуст, если ok=True. Исключения не бросаем.
        """
        reasons: List[str] = []
        limits: Dict[str, Any] = {
            "cooldown_sec": self.config.cooldown_sec,
            "max_spread_pct": self.config.max_spread_pct,
            "max_position_base": self.config.max_position_base,
            "max_orders_per_hour": self.config.max_orders_per_hour,
            "daily_loss_limit_quote": self.config.daily_loss_limit_quote,
        }

        now_ms = int(time.time() * 1000)

        # --- 1) Cooldown -------------------------------------------------------
        last = self._last_exec_ms.get(symbol)
        if last is not None:
            if (now_ms - last) < self.config.cooldown_sec * 1000:
                reasons.append("cooldown")

        # --- 2) Spread limit ---------------------------------------------------
        try:
            ctx = evaluation.get("ctx") if isinstance(evaluation, dict) else None
            spread = float(ctx.get("spread", 0.0)) if isinstance(ctx, dict) else 0.0
            if spread > float(self.config.max_spread_pct):
                reasons.append(f"spread>{self.config.max_spread_pct}%")
        except Exception:
            # контекст стратегии не обязателен
            pass

        # --- 3) Max position base (long-only) ---------------------------------
        try:
            pos = self.storage.positions.get_position(symbol)
            base_qty = float(pos.base_qty or 0.0)
            if base_qty > float(self.config.max_position_base) and action == "buy":
                reasons.append("position_limit")
        except Exception:
            # если позиции нет/ошибка чтения — не блокируем по этому пункту
            pass

        # --- 4) Orders per hour ------------------------------------------------
        try:
            window_ms = 60 * 60 * 1000
            hist = self._orders_hist_ms[symbol]
            # сбросить старые записи
            hist[:] = [ts for ts in hist if (now_ms - ts) < window_ms]
            if len(hist) >= int(self.config.max_orders_per_hour):
                reasons.append("rate_limit_hour")
        except Exception:
            pass

        # --- 5) Daily loss limit (по операциям SELL как фиксациям) ------------
        try:
            trades = self.storage.trades.list_today(symbol)
            realized = Decimal("0")
            for t in trades:
                # convention: SELL фиксирует результат в quote; BUY — расход
                side = str(t.get("side") or "").lower()
                cost = Decimal(str(t.get("cost") or "0"))
                if side == "sell":
                    realized += cost
                elif side == "buy":
                    realized -= cost
            # если ушли за минус лимита
            if realized < Decimal(str(-abs(self.config.daily_loss_limit_quote))):
                reasons.append("daily_loss_limit")
        except Exception:
            pass

        ok = (len(reasons) == 0)

        # если ок, то готовим запись для cooldown/rate
        if ok:
            self._last_exec_ms[symbol] = now_ms
            self._orders_hist_ms[symbol].append(now_ms)

        return {"ok": ok, "reasons": reasons, "limits": limits}
