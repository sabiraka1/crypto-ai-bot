import importlib
import sys
from types import SimpleNamespace
import time


def _install_stub(module_name: str, obj):
    """РЈРґРѕР±РЅС‹Р№ РїРѕРјРѕС‰РЅРёРє: Р·Р°СЃСѓРЅСѓС‚СЊ Р·Р°РіР»СѓС€РєСѓ РІ sys.modules РїРѕ РїСѓС‚Рё РІРёРґР° 'a.b.c'."""
    parts = module_name.split(".")
    base = ""
    for i, p in enumerate(parts):
        base = p if i == 0 else base + "." + p
        if base not in sys.modules:
            sys.modules[base] = SimpleNamespace()
    sys.modules[module_name] = obj


def test_integration_check_happy_path(monkeypatch):
    """
    Р­РјСѓР»РёСЂСѓРµРј РЅР°Р»РёС‡РёРµ analysis.* Рё utils.monitoring С‚Р°Рє, С‡С‚РѕР±С‹ check_integration() РїСЂРѕС€С‘Р» РїРѕ РІРµС‚РєР°Рј OK.
    Р­С‚Рѕ РїРѕРєСЂС‹РІР°РµС‚ СЃСЂР°Р·Сѓ РЅРµСЃРєРѕР»СЊРєРѕ Р±Р»РѕРєРѕРІ РІ utils/integration_check.py.
    """
    # --- technical_indicators.calculate_all_indicators
    ti_stub = SimpleNamespace(
        calculate_all_indicators=lambda prices: {
            "sma": [sum(prices) / len(prices)] if prices else [],
            "ema": [sum(prices) / len(prices)] if prices else [],
        }
    )
    _install_stub("crypto_ai_bot.core.indicators.unified", ti_stub)

    # --- market_analyzer.MarketAnalyzer
    class MarketAnalyzerStub:
        def __init__(self):
            self.called = True

        def analyze(self, *args, **kwargs):
            return {"signal": "hold", "score": 0.0}

        def report(self, *args, **kwargs):
            return "OK"

    ma_stub = SimpleNamespace(MarketAnalyzer=MarketAnalyzerStub)
    _install_stub("analysis.market_analyzer", ma_stub)

    # --- scoring_engine.ScoringEngine
    class ScoringEngineStub:
        # РѕСЃС‚Р°РІР»СЏРµРј С‚РѕР»СЊРєРѕ evaluate (С‡С‚РѕР± unified_interface == True)
        def evaluate(self, *args, **kwargs):
            return {"buy": 0.0, "sell": 0.0}

    se_stub = SimpleNamespace(ScoringEngine=ScoringEngineStub)
    _install_stub("analysis.scoring_engine", se_stub)

    # --- utils.monitoring.SimpleMonitor & app_monitoring.get_health_response
    class Metrics:
        def __init__(self):
            self.memory_mb = 123.0
            self.cpu_percent = 7.0
            self.threads_count = 3
            self.disk_usage_mb = 42.0
            self.uptime_seconds = 1
            self.timestamp = time.time()

    class SimpleMonitorStub:
        def get_system_metrics(self):
            return Metrics()

    app_mon_stub = SimpleNamespace(get_health_response=lambda: {"timestamp": time.time()})
    mon_pkg = SimpleNamespace(SimpleMonitor=SimpleMonitorStub, app_monitoring=app_mon_stub)
    _install_stub("utils.monitoring", mon_pkg)

    ic = importlib.import_module("utils.integration_check")
    res = ic.check_integration()

    assert isinstance(res, dict)
    # С‚РµС…РЅРёС‡РµСЃРєРёРµ РёРЅРґРёРєР°С‚РѕСЂС‹
    assert res.get("technical_indicators", {}).get("status") == "OK"
    # РјРѕРЅРёС‚РѕСЂРёРЅРі
    assert res.get("monitoring", {}).get("status") == "OK"
    assert res["monitoring"]["metrics_working"] is True
    assert res["monitoring"]["health_working"] is True
    # СЃРєРѕСЂРёРЅРі (РїСЂРѕРІРµСЂСЏРµРј unified_interface)
    assert res.get("scoring_engine", {}).get("status") == "OK"
    assert res["scoring_engine"]["unified_interface"] is True


def test_integration_check_errors_when_modules_missing(monkeypatch):
    """
    РџСЂРѕРІРµСЂСЏРµРј РІРµС‚РєРё РѕС€РёР±РѕРє: СѓР±РёСЂР°РµРј analysis.* Рё monitoring РёР· sys.modules
    Рё СѓР±РµР¶РґР°РµРјСЃСЏ, С‡С‚Рѕ check_integration() РІРѕР·РІСЂР°С‰Р°РµС‚ СЃС‚Р°С‚СѓСЃ ERROR РїРѕ СЌС‚РёРј РїСѓРЅРєС‚Р°Рј.
    """
    for k in list(sys.modules.keys()):
        if k.startswith("analysis.") or k == "utils.monitoring":
            sys.modules.pop(k, None)

    ic = importlib.import_module("utils.integration_check")
    res = ic.check_integration()

    # РљР°Рє РјРёРЅРёРјСѓРј СЌС‚Рё РєР»СЋС‡Рё РґРѕР»Р¶РЅС‹ РїСЂРёСЃСѓС‚СЃС‚РІРѕРІР°С‚СЊ Рё РёРјРµС‚СЊ СЃС‚Р°С‚СѓСЃ ERROR
    assert "technical_indicators" in res
    assert "monitoring" in res
    assert res["technical_indicators"]["status"] in ("ERROR", "SKIPPED", "WARNING")
    assert res["monitoring"]["status"] in ("ERROR", "SKIPPED", "WARNING")


def test_print_integration_report_smoke(capsys):
    """
    Р‘С‹СЃС‚СЂР°СЏ РґС‹РјРѕРІР°СЏ РїСЂРѕРІРµСЂРєР° СѓРґРѕР±РЅРѕРіРѕ РїСЂРёРЅС‚РµСЂР° РѕС‚С‡С‘С‚Р° вЂ” РЅРµ Р»РѕРјР°РµС‚ stdout.
    """
    ic = importlib.import_module("utils.integration_check")
    # РїРѕРґСЃС‚Р°РІРёРј РјРёРЅРёРјР°Р»СЊРЅС‹Р№ СЂРµР·СѓР»СЊС‚Р°С‚
    sample = {
        "technical_indicators": {"status": "OK"},
        "monitoring": {"status": "ERROR", "error": "missing"},
    }
    ic.print_integration_report(sample)
    out = capsys.readouterr().out
    assert "technical_indicators" in out
    assert "monitoring" in out






