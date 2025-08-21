## `tests/unit/test_validators.py`
import os
import pytest
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.validators.settings import validate_settings
from crypto_ai_bot.core.validators.dto import ensure_side, ensure_amount, ensure_symbol
from crypto_ai_bot.utils.exceptions import ValidationError
def test_settings_validate_live_requires_keys(monkeypatch):
    monkeypatch.setenv("MODE", "live")
    monkeypatch.setenv("API_KEY", "")
    monkeypatch.setenv("API_SECRET", "")
    with pytest.raises(ValidationError):
        Settings.load()
def test_dto_validators():
    assert ensure_side("BUY") == "buy"
    assert ensure_symbol("BTC/USDT") == "BTC/USDT"
    with pytest.raises(ValidationError):
        ensure_side("hold")
    with pytest.raises(ValidationError):
        ensure_symbol("BTCUSDT")
    amt = ensure_amount("1.23")
    assert amt > 0