## `tests/unit/test_settings_load.py`
import os
from crypto_ai_bot.core.settings import Settings
def test_settings_load_defaults(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_SECRET", raising=False)
    s = Settings.load()
    d = s.as_dict()
    assert d["MODE"] in {"paper", "backtest", "live"}
    assert d["EXCHANGE"] == "gateio"