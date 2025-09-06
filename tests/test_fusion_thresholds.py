from crypto_ai_bot.core.domain.signals.fusion import SignalFusion, FusionConfig
from crypto_ai_bot.core.domain.macro.types import RegimeState

def test_fusion_passes_in_risk_on():
    fu = SignalFusion()
    s = fu.fuse_signals(technical_score=80, ai_score=70, regime=RegimeState.RISK_ON)
    assert s.passed is True and s.direction.value == "long"

def test_fusion_blocks_in_neutral():
    fu = SignalFusion()
    s = fu.fuse_signals(technical_score=99, ai_score=99, regime=RegimeState.NEUTRAL)
    assert s.passed is False

def test_ai_abstain_zone_is_ignored_and_threshold_raised():
    cfg = FusionConfig(ai_abstain_low=45, ai_abstain_high=55)
    fu = SignalFusion(config=cfg)
    s = fu.fuse_signals(technical_score=65, ai_score=50, regime=RegimeState.RISK_SMALL)  # ai в зоне
    assert s.metadata["ai_abstain_applied"] is True
