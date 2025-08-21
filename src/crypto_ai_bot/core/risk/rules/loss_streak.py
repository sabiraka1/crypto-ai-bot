from __future__ import annotations
from typing import Any, Dict, Tuple

class LossStreakRule:
    name = "loss_streak"

    def __init__(self, settings: Any, repos: Any) -> None:
        self.s = settings
        self.repos = repos

    async def allow(self, decision: str, symbol: str, ctx: Dict[str, Any]) -> Tuple[bool, str]:
        max_losses = int(getattr(self.s, "RISK_MAX_LOSSES", 0) or 0)
        if max_losses <= 0:
            return True, "disabled"

        repo = getattr(self.repos, "trades_repo", None)
        if repo and hasattr(repo, "loss_streak"):
            try:
                streak = int(repo.loss_streak(symbol=symbol))
                if streak >= max_losses:
                    return False, f"streak={streak}>={max_losses}"
                return True, f"streak={streak}<{max_losses}"
            except Exception:
                pass
        return True, "no_data"
