import types
from types import SimpleNamespace
import pandas as pd
import pytest
import importlib
import sys


@pytest.fixture(autouse=True)
def fake_dependencies(monkeypatch):
    # 1) analysis.technical_indicators
    tech = types.ModuleType("analysis.technical_indicators")

    def calc_all_ind(df, use_cache=True):
        out = df.copy()
        out["ema"] = [101, 102, 103]  # добавим один индикатор
        return out

    tech.calculate_all_indicators = calc_all_ind
    tech.get_cache_stats = lambda: {"size": 1}
    monkeypatch.setitem(sys.modules, "analysis.technical_indicators", tech)

    # 2) utils.csv_handler
    csv_mod = types.ModuleType("utils.csv_handler")

    class CSVHandler:
        @staticmethod
        def start():
            return None

        @staticmethod
        def log_signal_snapshot(_):
            return None

    def get_csv_system_stats():
        return {"batch_writer": {"buffer_size": 0}, "read_cache": []}

    csv_mod.CSVHandler = CSVHandler
    csv_mod.get_csv_system_stats = get_csv_system_stats
    monkeypatch.setitem(sys.modules, "utils.csv_handler", csv_mod)

    # 3) utils.monitoring
    mon_mod = types.ModuleType("utils.monitoring_fake_for_integration")
    # но сам utils.monitoring настоящим остаётся — нам лишь нужен app_monitorинг совместимого интерфейса
    real_mon = importlib.import_module("utils.monitoring")

    class _AppMon:
        @staticmethod
        def get_health_response(trading_bot=None):
            return {"timestamp": "ok"}

    monkeypatch.setitem(sys.modules, "utils.monitoring", real_mon)          # чтобы импорт прошёл
    monkeypatch.setattr(real_mon, "app_monitoring", _AppMon(), raising=True)

    # 4) analysis.scoring_engine
    se = types.ModuleType("analysis.scoring_engine")

    class ScoringEngine:
        def evaluate(self, *_a, **_kw):
            return {"ok": True}

    se.ScoringEngine = ScoringEngine
    monkeypatch.setitem(sys.modules, "analysis.scoring_engine", se)

    yield

    # tearDown — ничего особенного


def test_check_integration_structure_and_status():
    ic = importlib.import_module("utils.integration_check")
    res = ic.check_integration()
    assert isinstance(res, dict)
    # Все ключевые блоки есть и в статусе OK
    for key in ("technical_indicators", "csv_handler", "monitoring", "scoring_engine"):
        assert key in res, f"missing block {key}"
        assert res[key].get("status") == "OK"


def test_print_integration_report_no_crash(capsys):
    ic = importlib.import_module("utils.integration_check")
    ic.print_integration_report()
    out = capsys.readouterr().out
    assert "ОТЧЕТ ОБ ИНТЕГРАЦИИ" in out
    assert "ОБЩИЙ СТАТУС" in out
    # Покрываем оба публичных интерфейса модуля. 
