from crypto_ai_bot.core.domain.signals.timeframes import TFWeights, AdaptiveTimeframeWeights

def test_tfweights_normalization_and_sum():
    w = TFWeights(w_15m=0.5, w_1h=0.5, w_4h=0.5, w_1d=0.0, w_1w=0.0).normalized()
    assert abs(sum(w.as_dict().values()) - 1.0) < 1e-6

def test_adaptive_by_atr_biases_more_volatile():
    base = TFWeights(w_15m=0.2, w_1h=0.2, w_4h=0.2, w_1d=0.2, w_1w=0.2)
    adapt = AdaptiveTimeframeWeights(base_weights=base, volatility_factor=0.5)
    w = adapt.calculate_weights({"15m": 10.0, "1h": 5.0, "4h": 2.0, "1d": 1.0, "1w": 0.5})
    d = w.as_dict()
    assert d["15m"] > d["1w"]           # более волатильный TF получил больший вес
    assert abs(sum(d.values()) - 1.0) < 1e-6
