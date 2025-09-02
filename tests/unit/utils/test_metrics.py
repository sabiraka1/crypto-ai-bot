from crypto_ai_bot.utils import metrics

def test_histogram_singleton_and_sanitized():
    metrics.observe("broker.request.ms", 10.0, {"fn":"fetch_balance"})
    metrics.observe("broker.request.ms", 15.0, {"fn":"fetch_balance"})
    # If no exception raised, duplicate timeseries avoided and name sanitized
    metrics.inc("orders.created", exchange="gateio")
