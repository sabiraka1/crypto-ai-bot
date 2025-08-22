import time
from crypto_ai_bot.utils.metrics import inc, observe, timer, snapshot

def test_metrics_snapshot_basic():
    # counters
    inc("orders_placed_total", {"symbol": "BTC/USDT"})
    inc("orders_placed_total", {"symbol": "BTC/USDT"}, value=2)

    # histograms: manual
    observe("latency_seconds", 0.01, {"uc": "decide"})
    observe("latency_seconds", 0.02, {"uc": "decide"})

    # histograms: timer
    with timer("eval_tick_seconds", {"loop": "eval"}):
        time.sleep(0.001)

    snap = snapshot()

    # counters present and aggregated
    ctrs = snap["counters"]["orders_placed_total"]
    total_for_btc = [s for s in ctrs if s["labels"].get("symbol") == "BTC/USDT"][0]["value"]
    assert total_for_btc == 3.0

    # histograms present
    lat_series = snap["histograms"]["latency_seconds"]
    decide = [s for s in lat_series if s["labels"].get("uc") == "decide"][0]
    assert decide["count"] == 2.0 and 0.02 <= decide["sum"] <= 0.04

    # timer produced something
    assert "eval_tick_seconds" in snap["histograms"]
