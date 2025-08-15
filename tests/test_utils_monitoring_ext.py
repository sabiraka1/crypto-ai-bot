import importlib
import sys
import types
import time
from dataclasses import asdict


def _make_fake_csv_handler(monkeypatch, count=7):
    # РџРѕРґРјРµРЅСЏРµРј РјРѕРґСѓР»СЊ utils.csv_handler (С‚РѕР»СЊРєРѕ С‚Рѕ, С‡С‚Рѕ РЅСѓР¶РЅРѕ monitoring)
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
    # Р·Р°РЅРёР¶Р°РµРј РїРѕСЂРѕРіРё, С‡С‚РѕР±С‹ Р°Р»РµСЂС‚С‹ СЃСЂР°Р±РѕС‚Р°Р»Рё
    m.thresholds["memory_mb"] = 10.0
    m.thresholds["cpu_percent"] = 5.0

    # РїРµСЂРІРѕРµ СЃСЂР°Р±Р°С‚С‹РІР°РЅРёРµ вЂ” 2 Р°Р»РµСЂС‚Р°
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

    # РїРѕРІС‚РѕСЂ вЂ” РґРѕР»Р¶РЅС‹ Р·Р°РґРµРґСѓРїР»РёСЂРѕРІР°С‚СЊСЃСЏ, Р°Р»РµСЂС‚РѕРІ РЅРµ РїСЂРёР±Р°РІРёС‚СЃСЏ
    alerts2 = m.check_alerts(metrics)
    assert alerts2 == []

    # РЅР°РїРѕР»РЅСЏРµРј СЃСЌС‚, С‡С‚РѕР±С‹ СЃСЂР°Р±РѕС‚Р°Р» Р°РІС‚Рѕ-reset (>10)
    m._alerts_sent = {f"k{i}" for i in range(12)}
    _ = m.check_alerts(metrics)
    # РїРѕСЃР»Рµ РІС‹Р·РѕРІР° РјРЅРѕР¶РµСЃС‚РІРѕ РѕС‡РёС‰Р°РµС‚СЃСЏ (РїРѕ РєРѕРґСѓ, РєРѕРіРґР° >10)
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
    # СѓСЃС‚Р°РЅРѕРІРёРј РїСЂРµРґС‹РґСѓС‰РµРµ РёР·РјРµСЂРµРЅРёРµ, С‡С‚РѕР±С‹ health_check РїРѕРєР°Р·С‹РІР°Р» memory_mb
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
    # РёРјРёС‚РёСЂСѓРµРј РІСЂРµРјСЏ
    base = time.time()
    monkeypatch.setattr(time, "time", lambda: base)

    assert m.should_check() is True   # РїРµСЂРІС‹Р№ РїСЂРѕС…РѕРґ
    assert m.should_check() is False  # СЃР»РёС€РєРѕРј Р±С‹СЃС‚СЂРѕ

    # РїСЂРѕС€Р»Рѕ 10 СЃРµРєСѓРЅРґ
    monkeypatch.setattr(time, "time", lambda: base + 10.01)
    assert m.should_check() is True


def test_watchdog_start_stop_does_not_crash(monkeypatch):
    mon = importlib.import_module("utils.monitoring")
    wd = mon.SmartWatchdog(check_interval=0)

    # Р·Р°РіР»СѓС€РєРё
    restart_calls = {"n": 0}
    def restart():
        restart_calls["n"] += 1

    class DummyBot:
        pass

    # СЃС‚Р°СЂС‚/СЃС‚РѕРї РїРѕС‚РѕРєРѕРІ Р±РµР· Р·Р°РІРёСЃР°РЅРёР№
    wd.start(DummyBot(), restart)
    wd.stop()
    # РЅРёРєР°РєРёС… СЃС‚СЂРѕРіРёС… Р°СЃСЃРµСЂС‚РѕРІ РїРѕ РєРѕР»РёС‡РµСЃС‚РІСѓ СЂРµСЃС‚Р°СЂС‚РѕРІ, РІР°Р¶РЅРѕ С‡С‚Рѕ РЅРµ РїР°РґР°РµС‚ Рё РєРѕСЂСЂРµРєС‚РЅРѕ РѕСЃС‚Р°РЅР°РІР»РёРІР°РµС‚СЃСЏ




