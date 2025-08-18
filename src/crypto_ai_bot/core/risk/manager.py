# src/crypto_ai_bot/core/risk/manager.py
from __future__ import annotations

from typing import Any, Dict, List

from crypto_ai_bot.utils import metrics
from . import rules as R


class RiskManager:
    """
    Агрегирует результат правил. Возвращает словарь:
    {
      "ok": bool,
      "blocked_by": [codes...],
      "details": {"rule_code": {...}}
    }
    """

    def __init__(self, cfg: Any, *, broker: Any, positions_repo: Any, trades_repo: Any, http: Any = None) -> None:
        self.cfg = cfg
        self.broker = broker
        self.pos = positions_repo
        self.trades = trades_repo
        self.http = http

    def evaluate(self, *, symbol: str, action: str) -> Dict[str, Any]:
        """
        Оценивает набор правил. Для action='sell' часть правил считается «пропускными» (не блокируем выход).
        """
        res: Dict[str, Any] = {"ok": True, "blocked_by": [], "details": {}}
        blocked: List[str] = []

        # --- time sync ---
        ok, code, details = R.check_time_sync(self.cfg, self.http)
        res["details"][code] = details
        if not ok:
            blocked.append(code)

        # --- hours window ---
        ok, code, details = R.check_hours(self.cfg)
        res["details"][code] = details
        if not ok:
            blocked.append(code)

        # --- spread ---
        max_spread = getattr(self.cfg, "MAX_SPREAD_BPS", None)
        ok, code, details = R.check_spread(self.broker, symbol, max_spread_bps=max_spread)
        res["details"][code] = details
        if not ok:
            blocked.append(code)

        # --- drawdown ---
        dd_days = getattr(self.cfg, "RISK_LOOKBACK_DAYS", None)
        dd_limit = getattr(self.cfg, "RISK_MAX_DRAWDOWN_PCT", None)
        ok, code, details = R.check_drawdown(self.trades, lookback_days=dd_days, max_drawdown_pct=dd_limit)
        res["details"][code] = details
        if not ok:
            blocked.append(code)

        # --- sequence losses ---
        win = getattr(self.cfg, "RISK_SEQUENCE_WINDOW", None)
        cap = getattr(self.cfg, "RISK_MAX_LOSSES", None)
        ok, code, details = R.check_sequence_losses(self.trades, window=win, max_losses=cap)
        res["details"][code] = details
        if not ok:
            blocked.append(code)

        # --- exposure ---
        max_pos = getattr(self.cfg, "MAX_POSITIONS", None)
        ok, code, details = R.check_max_exposure(self.pos, max_positions=max_pos)
        res["details"][code] = details
        if not ok and str(action).lower() == "buy":
            # ПОКУПКИ ограничиваем; продажу не блокируем экспозицией
            blocked.append(code)

        res["blocked_by"] = blocked
        res["ok"] = len(blocked) == 0

        if not res["ok"]:
            for reason in blocked:
                metrics.inc("risk_block_total", {"reason": reason})
        else:
            metrics.inc("risk_pass_total")

        return res
