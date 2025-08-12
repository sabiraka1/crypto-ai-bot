import types
from types import SimpleNamespace
import pytest

# Тестируем utils.monitoring, но ВСЁ внешнее мокируем
import importlib


@pytest.fixture
def monitoring():
    mod = importlib.import_module("utils.monitoring")
    return mod


def test_should_check_interval(monkeypatch, monitoring):
    # time.time -> управляемая последовательность вызовов
    now_values = iter([1000.0, 1005.0, 1011.0])
    monkeypatch.setattr(monitoring.time, "time", lambda: next(now_values))

    m = monitoring.SimpleMonitor(check_interval=10)
    # при первом вызове прошло >= 10s (1000 - 0), поэтому True
    assert m.should_check() is True
    # 1005 - 1000 < 10 -> False
    assert m.should_check() is False
    # 1011 - 1000 >= 10 -> True
    assert m.should_check() is True


def test_get_system_metrics_and_alerts(monkeypatch, monitoring):
    # Пороговые значения делаем пониже, чтобы сработали алерты
    monkeypatch.setenv("MEMORY_ALERT_MB", "100")   # 100 MB
    monkeypatch.setenv("CPU_ALERT_PCT", "50")      # 50%

    # Мокаем psutil.Process и disk_usage
    class _FakeMem:  # process.memory_info()
        rss = 200 * 1024 * 1024  # 200 MB

    class _FakeProc:
        def memory_info(self):
            return _FakeMem()

        def cpu_percent(self, interval=0.1):
            return 60.0  # 60%

        def num_threads(self):
            return 7

    fake_psutil = SimpleNamespace(
        Process=lambda pid=None: _FakeProc(),
        disk_usage=lambda path: SimpleNamespace(used=123 * 1024 * 1024),  # 123 MB
    )
    monkeypatch.setattr(monitoring, "psutil", fake_psutil, raising=True)

    # time.time нужен для аптайма (делаем стабильным)
    start = 1_000_000.0
    monkeypatch.setattr(monitoring.time, "time", lambda: start + 120.0)  # uptime ~120s

    m = monitoring.SimpleMonitor(check_interval=1)
    m._start_time = start  # фиксируем начало

    metrics = m.get_system_metrics()
    assert metrics.memory_mb == pytest.approx(200.0, rel=0.01)
    assert metrics.cpu_percent == pytest.approx(60.0)
    assert metrics.threads_count == 7
    assert metrics.disk_usage_mb == pytest.approx(123.0, rel=0.01)
    assert metrics.uptime_seconds == pytest.approx(120.0, rel=0.01)

    alerts = m.check_alerts(metrics)
    # Оба алерта должны сработать при сниженных порогах
    assert any("High memory usage" in a for a in alerts)
    assert any("High CPU usage" in a for a in alerts)
    # Логика и поля соответствуют описанию методов. 


def test_app_monitoring_health_response_paths(monkeypatch, monitoring):
    app = monitoring.AppMonitoring()

    # Сценарий 1: should_check -> True -> get_full_status
    called = {"full": False, "health": False}
    app.monitor.should_check = lambda: True
    app.monitor.get_full_status = lambda trading_bot=None: (called.__setitem__("full", True) or {"system": {}, "trading": {}, "alerts": []})
    app.monitor.get_health_check = lambda: (called.__setitem__("health", True) or {"ok": True})

    resp = app.get_health_response(trading_bot=None)
    assert "system" in resp and "trading" in resp
    assert called["full"] and not called["health"]

    # Сценарий 2: should_check -> False -> get_health_check
    called = {"full": False, "health": False}
    app.monitor.should_check = lambda: False
    app.monitor.get_full_status = lambda trading_bot=None: (called.__setitem__("full", True) or {})
    app.monitor.get_health_check = lambda: (called.__setitem__("health", True) or {"ok": True})

    resp = app.get_health_response(trading_bot=None)
    assert resp.get("ok") is True
    assert called["health"] and not called["full"]
    # В точности повторяет логику метода. :contentReference[oaicite:4]{index=4}


def test_watchdog_attempt_restart_respects_cooldown(monkeypatch, monitoring):
    wd = monitoring.SmartWatchdog(check_interval=60)

    # Подменяем телеграм-модуль, чтобы не ходить наружу
    fake_tg = types.ModuleType("telegram.api_utils")
    fake_tg.send_message = lambda *_args, **_kwargs: None
    # Впихиваем в sys.modules
    monkeypatch.syspath_prepend("")  # чтобы модуль был доступен
    monkeypatch.setitem(
        __import__("sys").modules, "telegram.api_utils", fake_tg
    )

    # Тайм: сначала можно рестартить, потом — в периоде cooldown
    t = {"now": 10_000.0}
    monkeypatch.setattr(monitoring.time, "time", lambda: t["now"])

    called = {"cnt": 0}

    def restart_func():
        called["cnt"] += 1

    # Первый вызов — должен перезапустить
    wd._attempt_restart(restart_func)  # nosec - приватный, но безопасен в тесте
    assert called["cnt"] == 1
    assert wd._restart_attempts == 1
    first = wd._last_restart

    # Через 5 секунд — кулдаун ещё активен, не должен рестартить
    t["now"] = first + 5.0
    wd._attempt_restart(restart_func)
    assert called["cnt"] == 1  # без изменений
    # Проверяем контракт и защиту перезапуска. :contentReference[oaicite:5]{index=5}
