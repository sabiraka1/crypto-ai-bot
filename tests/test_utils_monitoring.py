# tests/test_utils_monitoring.py
import importlib
import types

def test_system_metrics_snapshot_basic():
    # Импортируем после conftest (где подставили psutil)
    monitoring = importlib.import_module("utils.monitoring")

    # Проверяем наличие экспортов (не жёстко привязываемся к конкретной реализации)
    assert hasattr(monitoring, "SystemMetrics")
    SM = monitoring.SystemMetrics

    sm = SM()
    snap = sm.snapshot() if hasattr(sm, "snapshot") else sm()  # на случай callble
    assert isinstance(snap, dict)
    assert len(snap) > 0

def test_app_monitoring_exports_exist():
    monitoring = importlib.import_module("utils.monitoring")

    # Эти имена объявлены в __all__ модуля — просто проверим, что они доступны.
    for name in ("AppMonitoring", "app_monitoring"):
        assert hasattr(monitoring, name), f"{name} should be exported"

    # Не дергаем фоновые потоки, чтобы тесты оставались детерминированными
