# src/crypto_ai_bot/core/risk/manager.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal

from . import rules as R


class RiskAssessment:
    def __init__(self, allow: bool, reasons: List[str], size_cap: Optional[Decimal] = None):
        self.allow = allow
        self.reasons = reasons
        self.size_cap = size_cap

    def to_dict(self) -> Dict[str, Any]:
        out = {"allow": self.allow, "reasons": list(self.reasons)}
        if self.size_cap is not None:
            out["size_cap"] = str(self.size_cap)
        return out


def assess(
    cfg: Any,
    broker: Any,
    repos: Any,
    *,
    symbol: str,
    side: str,
    size: Decimal,
) -> RiskAssessment:
    """
    Единая точка вызова правил риска. Возвращает «можно/нельзя» и причины.
    Если одно из правил «неизвестно» (нет данных/метода) — не блокируем.
    """
    reasons: List[str] = []
    ok_all = True

    # 1) Спред
    ok, why = R.check_spread(cfg, broker, symbol)
    ok_all &= ok
    reasons.append(f"spread:{why}")

    # 2) Торговые часы
    ok2, why2 = R.check_hours(cfg)
    ok_all &= ok2
    reasons.append(f"hours:{why2}")

    # 3) Просадка
    ok3, why3 = R.check_drawdown(cfg, repos.trades if hasattr(repos, "trades") else None)
    ok_all &= ok3
    reasons.append(f"drawdown:{why3}")

    # 4) Серия лоссов
    ok4, why4 = R.check_sequence_losses(cfg, repos.trades if hasattr(repos, "trades") else None)
    ok_all &= ok4
    reasons.append(f"seq_losses:{why4}")

    # 5) Экспозиция
    ok5, why5 = R.check_max_exposure(cfg, repos.positions if hasattr(repos, "positions") else None, broker, side, symbol)
    ok_all &= ok5
    reasons.append(f"exposure:{why5}")

    # (Опционально) Мягкое ограничение размера позиции
    size_cap = None
    max_pos_size = getattr(cfg, "RISK_MAX_POSITION_SIZE", None)
    try:
        if max_pos_size is not None:
            cap = Decimal(str(max_pos_size))
            if cap > 0 and size > cap:
                size_cap = cap
    except Exception:
        pass

    return RiskAssessment(bool(ok_all), reasons, size_cap)
