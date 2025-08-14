import importlib
import pytest
import time


def test_system_metrics_snapshot_basic():
    """РўРµСЃС‚ Р±Р°Р·РѕРІРѕР№ С„СѓРЅРєС†РёРѕРЅР°Р»СЊРЅРѕСЃС‚Рё SystemMetrics"""
    # РРјРїРѕСЂС‚РёСЂСѓРµРј РїРѕСЃР»Рµ conftest (РіРґРµ РїРѕРґСЃС‚Р°РІРёР»Рё psutil)
    monitoring = importlib.import_module("utils.monitoring")

    # РџСЂРѕРІРµСЂСЏРµРј РЅР°Р»РёС‡РёРµ СЌРєСЃРїРѕСЂС‚РѕРІ
    assert hasattr(monitoring, "SystemMetrics")
    SM = monitoring.SystemMetrics

    # SystemMetrics СЌС‚Рѕ dataclass СЃ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹РјРё РїР°СЂР°РјРµС‚СЂР°РјРё
    # РЎРѕР·РґР°РµРј СЌРєР·РµРјРїР»СЏСЂ СЃ РєРѕСЂСЂРµРєС‚РЅС‹РјРё РїР°СЂР°РјРµС‚СЂР°РјРё
    sm = SM(
        timestamp=1640995200.0,
        memory_mb=1024.0,
        cpu_percent=12.3,
        threads_count=8,
        disk_usage_mb=200.0,
        uptime_seconds=3600.0
    )
    
    # РџСЂРѕРІРµСЂСЏРµРј, С‡С‚Рѕ РѕР±СЉРµРєС‚ СЃРѕР·РґР°Р»СЃСЏ РєРѕСЂСЂРµРєС‚РЅРѕ
    assert sm.timestamp == 1640995200.0
    assert sm.memory_mb == 1024.0
    assert sm.cpu_percent == 12.3
    assert sm.threads_count == 8
    assert sm.disk_usage_mb == 200.0
    assert sm.uptime_seconds == 3600.0

    # РџСЂРѕРІРµСЂСЏРµРј РјРµС‚РѕРґС‹ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё
    assert hasattr(sm, "to_dict")
    dict_data = sm.to_dict()
    assert isinstance(dict_data, dict)
    assert dict_data["memory_mb"] == 1024.0

    # РџСЂРѕРІРµСЂСЏРµРј СЃРѕР·РґР°РЅРёРµ РёР· СЃР»РѕРІР°СЂСЏ
    sm2 = SM.from_dict(dict_data)
    assert sm2.memory_mb == sm.memory_mb


def test_get_system_metrics_function():
    """РўРµСЃС‚ С„СѓРЅРєС†РёРё get_system_metrics"""
    monitoring = importlib.import_module("utils.monitoring")
    
    # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ С„СѓРЅРєС†РёСЏ СЃСѓС‰РµСЃС‚РІСѓРµС‚
    assert hasattr(monitoring, "get_system_metrics")
    assert callable(monitoring.get_system_metrics)
    
    # Р’С‹Р·С‹РІР°РµРј С„СѓРЅРєС†РёСЋ Рё РїСЂРѕРІРµСЂСЏРµРј СЂРµР·СѓР»СЊС‚Р°С‚
    metrics = monitoring.get_system_metrics()
    assert isinstance(metrics, monitoring.SystemMetrics)
    
    # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РІСЃРµ РїРѕР»СЏ Р·Р°РїРѕР»РЅРµРЅС‹ РєРѕСЂСЂРµРєС‚РЅРѕ
    assert isinstance(metrics.timestamp, (int, float))
    assert isinstance(metrics.memory_mb, (int, float))
    assert isinstance(metrics.cpu_percent, (int, float))
    assert isinstance(metrics.threads_count, int)
    assert isinstance(metrics.disk_usage_mb, (int, float))
    assert isinstance(metrics.uptime_seconds, (int, float))
    
    # РџСЂРѕРІРµСЂСЏРµРј СЂР°Р·СѓРјРЅС‹Рµ РіСЂР°РЅРёС†С‹ Р·РЅР°С‡РµРЅРёР№
    assert metrics.memory_mb >= 0
    assert 0 <= metrics.cpu_percent <= 100
    assert metrics.threads_count >= 0
    assert metrics.disk_usage_mb >= 0
    assert metrics.uptime_seconds >= 0


def test_simple_monitor():
    """РўРµСЃС‚ РєР»Р°СЃСЃР° SimpleMonitor"""
    monitoring = importlib.import_module("utils.monitoring")
    
    assert hasattr(monitoring, "SimpleMonitor")
    
    # РЎРѕР·РґР°РµРј СЌРєР·РµРјРїР»СЏСЂ РјРѕРЅРёС‚РѕСЂР°
    monitor = monitoring.SimpleMonitor(check_interval=60)
    
    # РџСЂРѕРІРµСЂСЏРµРј РјРµС‚РѕРґС‹
    assert hasattr(monitor, "get_system_metrics")
    assert hasattr(monitor, "should_check")
    assert hasattr(monitor, "get_health_check")
    
    # РўРµСЃС‚РёСЂСѓРµРј РїРѕР»СѓС‡РµРЅРёРµ РјРµС‚СЂРёРє
    metrics = monitor.get_system_metrics()
    assert isinstance(metrics, monitoring.SystemMetrics)
    
    # РўРµСЃС‚РёСЂСѓРµРј РїСЂРѕРІРµСЂРєСѓ Р·РґРѕСЂРѕРІСЊСЏ
    health = monitor.get_health_check()
    assert isinstance(health, dict)
    assert "ok" in health
    assert health["ok"] is True


def test_app_monitoring():
    """РўРµСЃС‚ РєР»Р°СЃСЃР° AppMonitoring"""
    monitoring = importlib.import_module("utils.monitoring")
    
    assert hasattr(monitoring, "AppMonitoring")
    assert hasattr(monitoring, "app_monitoring")
    
    # РџСЂРѕРІРµСЂСЏРµРј РіР»РѕР±Р°Р»СЊРЅС‹Р№ СЌРєР·РµРјРїР»СЏСЂ
    app_mon = monitoring.app_monitoring
    assert isinstance(app_mon, monitoring.AppMonitoring)
    
    # РџСЂРѕРІРµСЂСЏРµРј РјРµС‚РѕРґС‹
    assert hasattr(app_mon, "get_health_response")
    assert hasattr(app_mon, "start_watchdog")
    assert hasattr(app_mon, "shutdown")
    
    # РўРµСЃС‚РёСЂСѓРµРј РїРѕР»СѓС‡РµРЅРёРµ РѕС‚РІРµС‚Р° Рѕ Р·РґРѕСЂРѕРІСЊРµ
    health_response = app_mon.get_health_response()
    assert isinstance(health_response, dict)


def test_trading_metrics_dataclass():
    """РўРµСЃС‚ dataclass TradingMetrics"""
    monitoring = importlib.import_module("utils.monitoring")
    
    assert hasattr(monitoring, "TradingMetrics")
    TM = monitoring.TradingMetrics
    
    # РЎРѕР·РґР°РµРј СЌРєР·РµРјРїР»СЏСЂ СЃ С‚РµСЃС‚РѕРІС‹РјРё РґР°РЅРЅС‹РјРё
    tm = TM(
        bot_active=True,
        position_active=False,
        last_signal_time="2024-01-01T12:00:00",
        total_trades=10,
        current_balance=1000.0,
        last_error=None
    )
    
    # РџСЂРѕРІРµСЂСЏРµРј Р·РЅР°С‡РµРЅРёСЏ
    assert tm.bot_active is True
    assert tm.position_active is False
    assert tm.total_trades == 10
    assert tm.current_balance == 1000.0
    assert tm.last_error is None


def test_performance_monitor_compatibility():
    """РўРµСЃС‚ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё СЃ PerformanceMonitor"""
    monitoring = importlib.import_module("utils.monitoring")
    
    # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РєР»Р°СЃСЃ СЃСѓС‰РµСЃС‚РІСѓРµС‚ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё
    if hasattr(monitoring, "PerformanceMonitor"):
        PM = monitoring.PerformanceMonitor
        pm = PM()
        
        assert hasattr(pm, "capture_metrics")
        metrics = pm.capture_metrics()
        assert isinstance(metrics, monitoring.SystemMetrics)


def test_resource_tracker():
    """РўРµСЃС‚ ResourceTracker РµСЃР»Рё РѕРЅ СЃСѓС‰РµСЃС‚РІСѓРµС‚"""
    monitoring = importlib.import_module("utils.monitoring")
    
    if hasattr(monitoring, "ResourceTracker"):
        RT = monitoring.ResourceTracker
        tracker = RT(max_history=10)
        
        assert hasattr(tracker, "record_metrics")
        assert hasattr(tracker, "get_average_metrics")
        
        # Р—Р°РїРёСЃС‹РІР°РµРј РЅРµСЃРєРѕР»СЊРєРѕ РјРµС‚СЂРёРє
        tracker.record_metrics()
        time.sleep(0.1)
        tracker.record_metrics()
        
        # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РёСЃС‚РѕСЂРёСЏ РІРµРґРµС‚СЃСЏ
        assert len(tracker.history) >= 1
        
        # РџСЂРѕРІРµСЂСЏРµРј РїРѕР»СѓС‡РµРЅРёРµ СЃСЂРµРґРЅРёС… Р·РЅР°С‡РµРЅРёР№
        avg_metrics = tracker.get_average_metrics()
        if avg_metrics:
            assert isinstance(avg_metrics, monitoring.SystemMetrics)


def test_app_monitoring_exports_exist():
    """РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ РјРѕРґСѓР»СЊ monitoring СЌРєСЃРїРѕСЂС‚РёСЂСѓРµС‚ РѕСЃРЅРѕРІРЅС‹Рµ С„СѓРЅРєС†РёРё"""
    monitoring = importlib.import_module("utils.monitoring")
    
    # РџСЂРѕРІРµСЂСЏРµРј РЅР°Р»РёС‡РёРµ РѕСЃРЅРѕРІРЅС‹С… СЌРєСЃРїРѕСЂС‚РѕРІ
    assert hasattr(monitoring, "SystemMetrics")
    assert hasattr(monitoring, "SimpleMonitor")
    assert hasattr(monitoring, "app_monitoring")
    
    # Р”РѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Рµ РїСЂРѕРІРµСЂРєРё РµСЃР»Рё С„СѓРЅРєС†РёРё СЃСѓС‰РµСЃС‚РІСѓСЋС‚
    exports_to_check = [
        "get_system_metrics",
        "log_system_state", 
        "monitor_performance",
        "check_system_health"
    ]
    
    for export_name in exports_to_check:
        if hasattr(monitoring, export_name):
            attr = getattr(monitoring, export_name)
            assert callable(attr), f"{export_name} РґРѕР»Р¶РЅРѕ Р±С‹С‚СЊ РІС‹Р·С‹РІР°РµРјС‹Рј"


def test_legacy_functions():
    """РўРµСЃС‚ legacy С„СѓРЅРєС†РёР№ РґР»СЏ РѕР±СЂР°С‚РЅРѕР№ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё"""
    monitoring = importlib.import_module("utils.monitoring")
    
    # РџСЂРѕРІРµСЂСЏРµРј legacy С„СѓРЅРєС†РёСЋ monitor_resources
    if hasattr(monitoring, "monitor_resources"):
        result = monitoring.monitor_resources()
        assert isinstance(result, tuple)
        assert len(result) == 2
        cpu_percent, memory_mb = result
        assert isinstance(cpu_percent, (int, float))
        assert isinstance(memory_mb, (int, float))


def test_watchdog_class():
    """РўРµСЃС‚ SmartWatchdog РєР»Р°СЃСЃР°"""
    monitoring = importlib.import_module("utils.monitoring")
    
    if hasattr(monitoring, "SmartWatchdog"):
        watchdog = monitoring.SmartWatchdog(check_interval=60)
        
        assert hasattr(watchdog, "start")
        assert hasattr(watchdog, "stop")
        assert watchdog.check_interval == 60
        assert watchdog._running is False
