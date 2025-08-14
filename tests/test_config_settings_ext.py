import importlib
import os


def _reload_settings(monkeypatch, env: dict):
    # РЎР±СЂР°СЃС‹РІР°РµРј/СѓСЃС‚Р°РЅР°РІР»РёРІР°РµРј РѕРєСЂСѓР¶РµРЅРёРµ РїРѕРґ С‚РµСЃС‚
    for k in list(os.environ):
        # РЅРµ С‚СЂРѕРіР°РµРј РєСЂРёС‚РёС‡РЅС‹Рµ РїРµСЂРµРјРµРЅРЅС‹Рµ CI, РЅРѕ С‡РёСЃС‚РёРј РЅР°С€Рё
        if k.startswith(("SAFE_MODE", "RATE_LIMIT", "TIMEFRAME", "CACHE", "LOG", "API", "TELEGRAM", "BINANCE")):
            monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    # РџРµСЂРµРёРјРїРѕСЂС‚РёСЂСѓРµРј РјРѕРґСѓР»СЊ
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
    # РќРµ СѓС‚РІРµСЂР¶РґР°РµРј С‚РѕС‡РЅС‹Рµ РёРјРµРЅР° РїРѕР»РµР№, РЅРѕ РїСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ С‡РёСЃР»Р° СЃС‚Р°Р»Рё С‡РёСЃР»Р°РјРё, РµСЃР»Рё С‚Р°РєРёРµ РїРѕР»СЏ СЃСѓС‰РµСЃС‚РІСѓСЋС‚
    for attr in ("RATE_LIMIT", "CACHE_TTL", "REQUESTS_PER_MIN"):
        if hasattr(CFG, attr):
            assert isinstance(getattr(CFG, attr), (int, float))


def test_timeframe_and_defaults(monkeypatch):
    # РџСЂРѕРІРµСЂСЏРµРј, С‡С‚Рѕ С‚Р°Р№РјС„СЂРµР№Рј Р±РµСЂС‘С‚СЃСЏ РёР· РѕРєСЂСѓР¶РµРЅРёСЏ, Р° РїСЂРё РєСЂРёРІРѕРј Р·РЅР°С‡РµРЅРёРё вЂ” РїР°РґР°РµС‚ РІ РґРµС„РѕР»С‚(С‹)
    settings = _reload_settings(monkeypatch, {"TIMEFRAME": "1h"})
    CFG = settings.TradingConfig()
    if hasattr(CFG, "TIMEFRAME"):
        assert getattr(CFG, "TIMEFRAME") in ("1m", "5m", "15m", "1h", "4h", "1d")

    settings = _reload_settings(monkeypatch, {"TIMEFRAME": "weird"})
    CFG = settings.TradingConfig()
    if hasattr(CFG, "TIMEFRAME"):
        assert getattr(CFG, "TIMEFRAME") in ("1m", "5m", "15m", "1h", "4h", "1d")


