# src/crypto_ai_bot/core/risk/manager.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from crypto_ai_bot.core.risk import rules as R


class RiskManager:
    """
    Агрегирует проверки риска. Возвращает структуру:
    {
      "ok": bool,
      "blocked_by": ["code1", ...],   # только error-коды
      "checks": {
         "time_sync": {...},
         "hours": {...},
         "spread": {...},
         "exposure": {...},
         "drawdown": {...},
         "sequence_losses": {...},
      }
    }
    """

    def __init__(self, cfg: Any, *, broker: Any, positions_repo: Any, trades_repo: Any, http: Any = None) -> None:
        self.cfg = cfg
        self.broker = broker
        self.positions = positions_repo
        self.trades = trades_repo
        self.http = http

    def evaluate(self, *, symbol: str, action: str) -> Dict[str, Any]:
        """
        Блокирующие правила:
         - time_sync (error)
         - hours (error)
         - spread (error) — только для действий buy/sell
         - exposure (error) — ограничение на число открытых позиций, блокирует только buy
         - drawdown (error)
         - sequence_losses (error)
        warn-статусы не блокируют, но возвращаются в checks.
        """
        checks: Dict[str, Dict[str, Any]] = {}
        blocked: List[str] = []

        # 1) time sync
        chk = R.check_time_sync(self.cfg, self.http)
        checks["time_sync"] = chk
        if chk["status"] == "error":
            blocked.append(chk["code"])

        # 2) hours
        chk = R.check_hours(self.cfg)
        checks["hours"] = chk
        if chk["status"] == "error":
            blocked.append(chk["code"])

        # 3) spread (только если action реальное)
        a = (action or "").lower()
        if a in ("buy", "sell"):
            max_bps = int(getattr(self.cfg, "MAX_SPREAD_BPS", 25) or 25)
            chk = R.check_spread(self.broker, symbol=symbol, max_spread_bps=max_bps)
            checks["spread"] = chk
            if chk["status"] == "error":
                blocked.append(chk["code"])

        # 4) exposure (имеет смысл блокировать только buy)
        if a == "buy":
            max_pos = int(getattr(self.cfg, "MAX_POSITIONS", 1) or 1)
            chk = R.check_max_exposure(self.positions, max_positions=max_pos)
            checks["exposure"] = chk
            if chk["status"] == "error":
                blocked.append(chk["code"])

        # 5) drawdown (по последним сделкам)
        lookback_days = int(getattr(self.cfg, "RISK_LOOKBACK_DAYS", 7) or 7)
        dd_limit = float(getattr(self.cfg, "RISK_MAX_DRAWDOWN_PCT", 10.0) or 10.0)
        chk = R.check_drawdown(self.trades, lookback_days=lookback_days, max_drawdown_pct=dd_limit)
        checks["drawdown"] = chk
        if chk["status"] == "error":
            blocked.append(chk["code"])

        # 6) sequence losses
        seq_win = int(getattr(self.cfg, "RISK_SEQUENCE_WINDOW", 3) or 3)
        seq_max = int(getattr(self.cfg, "RISK_MAX_LOSSES", 3) or 3)
        chk = R.check_sequence_losses(self.trades, window=seq_win, max_losses=seq_max)
        checks["sequence_losses"] = chk
        if chk["status"] == "error":
            blocked.append(chk["code"])

        ok = len(blocked) == 0
        return {"ok": ok, "blocked_by": blocked, "checks": checks}
