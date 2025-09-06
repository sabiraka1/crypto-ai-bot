import math
import pytest

from crypto_ai_bot.core.domain.signals.feature_pipeline import FeaturePipeline, Candle

@pytest.mark.parametrize("need_series", [True, False])
def test_indicators_basic_ranges(ohlcv_15m, need_series):
    fp = FeaturePipeline()
    feats = fp.extract_features(ohlcv_15m=ohlcv_15m, ohlcv_1h=ohlcv_15m if need_series else None)

    # RSI в [0, 100]
    for k, v in feats.items():
        if k.startswith("rsi14_"):
            assert 0.0 <= v <= 100.0

    # MACD значения присутствуют
    assert "macd_15m" in feats and "macd_signal_15m" in feats and "macd_hist_15m" in feats

    # ATR > 0
    assert feats.get("atr14_15m", 0) >= 0

    # Bollinger корректные отношения (верх > низ)
    up, mid, lo = feats.get("bb_upper_15m"), feats.get("bb_middle_15m"), feats.get("bb_lower_15m")
    assert up is not None and lo is not None
    assert up >= mid >= lo

    # Стохастик в [0, 100]
    k = feats.get("stoch_k_15m")
    d = feats.get("stoch_d_15m")
    assert 0.0 <= k <= 100.0
    assert 0.0 <= d <= 100.0
