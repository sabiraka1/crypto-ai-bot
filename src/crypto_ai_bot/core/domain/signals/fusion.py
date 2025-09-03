from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from .macro import MacroContext, macro_coeff

Regime = Literal["bull", "neutral", "bear"]

@dataclass(frozen=True)
class FusionThresholds:
    ind_bull: float = 60.0
    ai_bull: float = 65.0
    ind_neutral: float = 65.0
    ai_neutral: float = 65.0
    ind_bear: float = 70.0
    ai_bear: float = 70.0
    abstain_low: float = 45.0
    abstain_high: float = 55.0

def pass_thresholds(ind_score: float,
                    ai_score: float | None,
                    regime: Regime,
                    macro: MacroContext | None = None,
                    thr: FusionThresholds | None = None) -> tuple[bool, dict]:
    thr = thr or FusionThresholds()
    coeff = macro_coeff(macro)
    if regime == "bull":
        need_ind = thr.ind_bull * coeff
        need_ai = thr.ai_bull * coeff
    elif regime == "bear":
        need_ind = thr.ind_bear * coeff
        need_ai = thr.ai_bear * coeff
    else:
        need_ind = thr.ind_neutral * coeff
        need_ai = thr.ai_neutral * coeff
    if ai_score is not None and thr.abstain_low < thr.abstain_high:
        if thr.abstain_low <= ai_score <= thr.abstain_high:
            return False, {"reason": "ai_abstain_zone", "ai": ai_score}
    if ai_score is None:
        ok = ind_score >= (need_ind + 5.0)
        return ok, {"need_ind": need_ind + 5.0, "ind": ind_score, "ai": None, "coeff": coeff}
    ok = (ind_score >= need_ind) and (ai_score >= need_ai)
    return ok, {"need_ind": need_ind, "need_ai": need_ai, "ind": ind_score, "ai": ai_score, "coeff": coeff}
