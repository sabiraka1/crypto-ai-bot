from crypto_ai_bot.core.infrastructure.settings import Settings


def test_settings_load_minimal_env(monkeypatch):
    monkeypatch.setenv("MODE", "paper")
    monkeypatch.setenv("EXCHANGE", "gateio")
    monkeypatch.setenv("SYMBOL", "BTC/USDT")
    s = Settings.load()
    assert s.MODE.lower() == "paper"
    assert s.EXCHANGE.lower() == "gateio"
    assert s.SYMBOL == "BTC/USDT"


def test_settings_telegram_fields_do_not_cross_fill(monkeypatch):
    # В текущей реализации TELEGRAM_CHAT_ID не берётся из ALERT_CHAT_ID
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_ALERT_CHAT_ID", "999")
    s = Settings.load()
    assert getattr(s, "TELEGRAM_CHAT_ID", "") in ("", None)
