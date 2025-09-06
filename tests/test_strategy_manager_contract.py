import pytest

try:
    from crypto_ai_bot.core.domain.strategies.strategy_manager import StrategyManager  # ожидаемый путь
    from crypto_ai_bot.core.domain.strategies.interfaces import Strategy, StrategyResult, Direction
except Exception:
    StrategyManager = None

@pytest.mark.xfail(StrategyManager is None, reason="strategy_manager не реализован", strict=False)
def test_strategy_manager_aggregates_scores(ohlcv_15m):
    from crypto_ai_bot.core.domain.signals.feature_pipeline import FeaturePipeline
    fp = FeaturePipeline()
    feats = fp.extract_features(ohlcv_15m=ohlcv_15m)

    class DummyStrat:
        name = "dummy"
        def evaluate(self, feats):
            return StrategyResult(name=self.name, direction=Direction.LONG, score=70.0, meta={})

    sm = StrategyManager(strategies=[DummyStrat()])
    tech_score, results = sm.evaluate(feats)
    assert 0.0 <= tech_score <= 100.0
    assert results and results[0].name == "dummy"
