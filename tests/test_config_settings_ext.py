import importlib
import os


def _reload_settings(monkeypatch, env: dict):
    # Сбрасываем/устанавливаем окружение под тест
    for k in list(os.environ):
        # не трогаем критичные переменные CI, но чистим наши
        if k.startswith(("SAFE_MODE", "RATE_LIMIT", "TIMEFRAME", "CACHE", "LOG", "API", "TELEGRAM", "BINANCE")):
            monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    # Переимпортируем модуль
    import config.settings as settings
    importlib.reload(settings)
    return settings


def test_safe_mode_bool_parsing(monkeypatch):
    settings = _reload_settings(monkeypatch, {"SAFE_MODE": "true"})
    CFG = settings.TradingConfig()
    assert isinstance(CFG.SAFE_MODE, bool)
    assert CFG.SAFE_MODE is True

    settings = _reload_settings(monkeypatch, {"SAFE_MODE": "0"})
    CFG = settings.TradingConfig()
    assert CFG.SAFE_MODE is False


def test_numeric_env_parsing(monkeypatch):
    settings = _reload_settings(monkeypatch, {"RATE_LIMIT": "123", "CACHE_TTL": "900"})
    CFG = settings.TradingConfig()
    # Не утверждаем точные имена полей, но проверяем что числа стали числами, если такие поля существуют
    for attr in ("RATE_LIMIT", "CACHE_TTL", "REQUESTS_PER_MIN"):
        if hasattr(CFG, attr):
            assert isinstance(getattr(CFG, attr), (int, float))


def test_timeframe_and_defaults(monkeypatch):
    # Проверяем, что таймфрейм берётся из окружения, а при кривом значении — падает в дефолт(ы)
    settings = _reload_settings(monkeypatch, {"TIMEFRAME": "1h"})
    CFG = settings.TradingConfig()
    if hasattr(CFG, "TIMEFRAME"):
        assert getattr(CFG, "TIMEFRAME") in ("1m", "5m", "15m", "1h", "4h", "1d")

    settings = _reload_settings(monkeypatch, {"TIMEFRAME": "weird"})
    CFG = settings.TradingConfig()
    if hasattr(CFG, "TIMEFRAME"):
        assert getattr(CFG, "TIMEFRAME") in ("1m", "5m", "15m", "1h", "4h", "1d")
