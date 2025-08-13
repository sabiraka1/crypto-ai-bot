import importlib
import sys
from types import SimpleNamespace
import time


def _install_stub(module_name: str, obj):
    """Удобный помощник: засунуть заглушку в sys.modules по пути вида 'a.b.c'."""
    parts = module_name.split(".")
    base = ""
    for i, p in enumerate(parts):
        base = p if i == 0 else base + "." + p
        if base not in sys.modules:
            sys.modules[base] = SimpleNamespace()
    sys.modules[module_name] = obj


def test_integration_check_happy_path(monkeypatch):
    """
    Эмулируем наличие analysis.* и utils.monitoring так, чтобы check_integration() прошёл по веткам OK.
    Это покрывает сразу несколько блоков в utils/integration_check.py.
    """
    # --- technical_indicators.calculate_all_indicators
    ti_stub = SimpleNamespace(
        calculate_all_indicators=lambda prices: {
            "sma": [sum(prices) / len(prices)] if prices else [],
            "ema": [sum(prices) / len(prices)] if prices else [],
        }
    )
    _install_stub("analysis.technical_indicators", ti_stub)

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
        # оставляем только evaluate (чтоб unified_interface == True)
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
    # технические индикаторы
    assert res.get("technical_indicators", {}).get("status") == "OK"
    # мониторинг
    assert res.get("monitoring", {}).get("status") == "OK"
    assert res["monitoring"]["metrics_working"] is True
    assert res["monitoring"]["health_working"] is True
    # скоринг (проверяем unified_interface)
    assert res.get("scoring_engine", {}).get("status") == "OK"
    assert res["scoring_engine"]["unified_interface"] is True


def test_integration_check_errors_when_modules_missing(monkeypatch):
    """
    Проверяем ветки ошибок: убираем analysis.* и monitoring из sys.modules
    и убеждаемся, что check_integration() возвращает статус ERROR по этим пунктам.
    """
    for k in list(sys.modules.keys()):
        if k.startswith("analysis.") or k == "utils.monitoring":
            sys.modules.pop(k, None)

    ic = importlib.import_module("utils.integration_check")
    res = ic.check_integration()

    # Как минимум эти ключи должны присутствовать и иметь статус ERROR
    assert "technical_indicators" in res
    assert "monitoring" in res
    assert res["technical_indicators"]["status"] in ("ERROR", "SKIPPED", "WARNING")
    assert res["monitoring"]["status"] in ("ERROR", "SKIPPED", "WARNING")


def test_print_integration_report_smoke(capsys):
    """
    Быстрая дымовая проверка удобного принтера отчёта — не ломает stdout.
    """
    ic = importlib.import_module("utils.integration_check")
    # подставим минимальный результат
    sample = {
        "technical_indicators": {"status": "OK"},
        "monitoring": {"status": "ERROR", "error": "missing"},
    }
    ic.print_integration_report(sample)
    out = capsys.readouterr().out
    assert "technical_indicators" in out
    assert "monitoring" in out
