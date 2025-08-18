# src/crypto_ai_bot/core/risk/manager.py
from __future__ import annotations

from typing import Any, Dict, List

from . import rules as R


class RiskManager:
    """
    Композитный риск-менеджер.
    Вызывает набор правил и возвращает {"ok": bool, "blocks": [...], "checks": {...}}.
    """

    def __init__(self, cfg: Any, *, broker: Any, positions_repo: Any, trades_repo: Any, http: Any) -> None:
        self.cfg = cfg
        self.broker = broker
        self.positions_repo = positions_repo
        self.trades_repo = trades_repo
        self.http = http

    def evaluate(self, *, symbol: str, action: str) -> Dict[str, Any]:
        """
        Если action == hold — считаем ok без проверок.
        Иначе прогоняем правила.
        """
        action = (action or "").lower().strip()
        if action not in ("buy", "sell"):
            return {"ok": True, "blocks": [], "checks": {"skipped": True}}

        cfg = self.cfg
        checks: Dict[str, Any] = {}

        # 1) время (NTP-drift)
        checks["time_sync"] = R.check_time_sync(cfg, self.http)

        # 2) торговые часы
        checks["hours"] = R.check_hours(cfg)

        # 3) спред
        checks["spread"] = R.check_spread(
            self.broker,
            symbol=symbol,
            max_spread_bps=int(getattr(cfg, "MAX_SPREAD_BPS", 25)),
        )

        # 4) экспозиция
        checks["exposure"] = R.check_max_exposure(
            self.positions_repo,
            max_positions=int(getattr(cfg, "MAX_POSITIONS", 1)),
        )

        # 5) просадка
        checks["drawdown"] = R.check_drawdown(
            self.trades_repo,
            lookback_days=int(getattr(cfg, "RISK_LOOKBACK_DAYS", 7)),
            max_drawdown_pct=float(getattr(cfg, "RISK_MAX_DRAWDOWN_PCT", 10)),
        )

        # 6) последовательность убыточных
        checks["seq_losses"] = R.check_sequence_losses(
            self.trades_repo,
            window=int(getattr(cfg, "RISK_SEQUENCE_WINDOW", 3)),
            max_losses=int(getattr(cfg, "RISK_MAX_LOSSES", 3)),
        )

        blocks = [k for k, v in checks.items() if isinstance(v, dict) and v.get("status") == "error"]
        return {"ok": len(blocks) == 0, "blocks": blocks, "checks": checks}
