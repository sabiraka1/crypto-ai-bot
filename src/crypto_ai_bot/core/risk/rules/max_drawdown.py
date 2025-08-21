from __future__ import annotations
from typing import Any, Dict, Tuple

class MaxDrawdownRule:
    name = "max_drawdown"

    def __init__(self, settings: Any, repos: Any) -> None:
        self.s = settings
        self.repos = repos

    async def allow(self, decision: str, symbol: str, ctx: Dict[str, Any]) -> Tuple[bool, str]:
        limit_pct = float(getattr(self.s, "RISK_MAX_DRAWDOWN_PCT", 0.0) or 0.0)
        if limit_pct <= 0:
            return True, "disabled"

        repo = getattr(self.repos, "trades_repo", None)
        if repo and hasattr(repo, "estimate_drawdown_pct"):
            try:
                dd = float(repo.estimate_drawdown_pct())
                if dd >= limit_pct:
                    return False, f"drawdown={dd:.2f}%>={limit_pct:.2f}%"
                return True, f"drawdown={dd:.2f}%<{limit_pct:.2f}%"
            except Exception:
                pass
        return True, "no_data"
