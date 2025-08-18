# tests/test_risk_rules.py
from crypto_ai_bot.core.risk import rules as R


class _FakeBroker:
    def __init__(self, bid, ask):
        self._bid = bid
        self._ask = ask
    def fetch_order_book(self, symbol, limit=10):
        return {"bids": [[self._bid, 1.0]], "asks": [[self._ask, 1.0]]}


class _FakeTradesRepo:
    def __init__(self, series):
        self._series = series
    def last_closed_pnls(self, n):
        return self._series[-n:]


def test_spread_ok_and_block():
    ok, code, _ = R.check_spread(_FakeBroker(99.9, 100.1), "BTC/USDT", max_spread_bps=50)
    assert ok and code == "spread_ok"

    ok, code, det = R.check_spread(_FakeBroker(99.0, 101.0), "BTC/USDT", max_spread_bps=50)
    assert not ok and code == "spread_too_wide"
    assert det["spread_bps"] > det["limit_bps"]

def test_sequence_losses_block():
    repo = _FakeTradesRepo(series=[+1.0, -0.5, -0.6, -0.7])
    ok, code, det = R.check_sequence_losses(repo, window=3, max_losses=3)
    assert not ok and code == "seq_losses_exceeded"
    assert det["tail_losses"] == 3
