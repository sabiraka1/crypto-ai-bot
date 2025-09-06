from crypto_ai_bot.core.domain.signals.timeframes import TFWeights

def test_weighted_average_ignores_missing_keys():
    w = TFWeights()
    values = {"15m": 1.0, "1h": 1.0}  # нет остальных ключей
    avg = w.weighted_average(values)
    # должен быть >0 и не обрушиться при недостающих ключах
    assert avg > 0
