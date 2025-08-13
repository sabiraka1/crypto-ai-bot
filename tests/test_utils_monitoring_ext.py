import importlib
import sys
import types
import time
from dataclasses import asdict


def _make_fake_csv_handler(monkeypatch, count=7):
    # Подменяем модуль utils.csv_handler (только то, что нужно monitoring)
    fake = types.ModuleType("utils.csv_handler")
    class CSVHandler:
        @staticmethod
        def get_trade_stats():
            return {"count": count}
    fake.CSVHandler = CSVHandler
    monkeypatch.setitem(sys.modules, "utils.csv_handler", fake)


def test_alert_thresholds_and_dedup(monkeypatch):
    mon = importlib.import_module("utils.monitoring")
    m = mon.SimpleMonitor(check_interval=0)
    # занижаем пороги, чтобы алерты сработали
    m.thresholds["memory_mb"] = 10.0
    m.thresholds["cpu_percent"] = 5.0

    # первое срабатывание — 2 алерта
    metrics = mon.SystemMetrics(
        timestamp=time.time(),
        memory_mb=500.0,
        cpu_percent=90.0,
        threads_count=10,
        disk_usage_mb=1000.0,
        uptime_seconds=60.0,
    )
    alerts1 = m.check_alerts(metrics)
    assert any("High memory" in a for a in alerts1)
    assert any("High CPU" in a for a in alerts1)

    # повтор — должны задедуплироваться, алертов не прибавится
    alerts2 = m.check_alerts(metrics)
    assert alerts2 == []

    # наполняем сэт, чтобы сработал авто-reset (>10)
    m._alerts_sent = {f"k{i}" for i in range(12)}
    _ = m.check_alerts(metrics)
    # после вызова множество очищается (по коду, когда >10)
    assert len(m._alerts_sent) == 0


def test_get_full_status_with_trading_bot(monkeypatch):
    mon = importlib.import_module("utils.monitoring")
    _make_fake_csv_handler(monkeypatch, count=11)

    class Bot:
        def __init__(self):
            self.state = types.SimpleNamespace(get=lambda key, default=None: True)
            self.pm = object()
            self.exchange = types.SimpleNamespace(get_balance=lambda sym: 1234.56)

    m = mon.SimpleMonitor(check_interval=0)
    # установим предыдущее измерение, чтобы health_check показывал memory_mb
    m._last_metrics = mon.SystemMetrics(time.time(), 42.0, 1.0, 5, 100.0, 10.0)

    status = m.get_full_status(Bot())
    assert status["system"]["memory_mb"] >= 0
    assert status["trading"]["bot_active"] is True
    assert status["trading"]["position_active"] in (True, False)
    assert status["trading"]["total_trades"] == 11
    assert status["trading"]["current_balance"] == 1234.56
    assert "alerts" in status

    hc = m.get_health_check()
    assert "ok" in hc and "uptime" in hc and "last_check" in hc


def test_should_check_throttle(monkeypatch):
    mon = importlib.import_module("utils.monitoring")
    m = mon.SimpleMonitor(check_interval=10)
    # имитируем время
    base = time.time()
    monkeypatch.setattr(time, "time", lambda: base)

    assert m.should_check() is True   # первый проход
    assert m.should_check() is False  # слишком быстро

    # прошло 10 секунд
    monkeypatch.setattr(time, "time", lambda: base + 10.01)
    assert m.should_check() is True


def test_watchdog_start_stop_does_not_crash(monkeypatch):
    mon = importlib.import_module("utils.monitoring")
    wd = mon.SmartWatchdog(check_interval=0)

    # заглушки
    restart_calls = {"n": 0}
    def restart():
        restart_calls["n"] += 1

    class DummyBot:
        pass

    # старт/стоп потоков без зависаний
    wd.start(DummyBot(), restart)
    wd.stop()
    # никаких строгих ассертов по количеству рестартов, важно что не падает и корректно останавливается
