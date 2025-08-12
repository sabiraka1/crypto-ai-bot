import importlib
import pytest
import time


def test_system_metrics_snapshot_basic():
    """Тест базовой функциональности SystemMetrics"""
    # Импортируем после conftest (где подставили psutil)
    monitoring = importlib.import_module("utils.monitoring")

    # Проверяем наличие экспортов
    assert hasattr(monitoring, "SystemMetrics")
    SM = monitoring.SystemMetrics

    # SystemMetrics это dataclass с обязательными параметрами
    # Создаем экземпляр с корректными параметрами
    sm = SM(
        timestamp=1640995200.0,
        memory_mb=1024.0,
        cpu_percent=12.3,
        threads_count=8,
        disk_usage_mb=200.0,
        uptime_seconds=3600.0
    )
    
    # Проверяем, что объект создался корректно
    assert sm.timestamp == 1640995200.0
    assert sm.memory_mb == 1024.0
    assert sm.cpu_percent == 12.3
    assert sm.threads_count == 8
    assert sm.disk_usage_mb == 200.0
    assert sm.uptime_seconds == 3600.0

    # Проверяем методы для совместимости
    assert hasattr(sm, "to_dict")
    dict_data = sm.to_dict()
    assert isinstance(dict_data, dict)
    assert dict_data["memory_mb"] == 1024.0

    # Проверяем создание из словаря
    sm2 = SM.from_dict(dict_data)
    assert sm2.memory_mb == sm.memory_mb


def test_get_system_metrics_function():
    """Тест функции get_system_metrics"""
    monitoring = importlib.import_module("utils.monitoring")
    
    # Проверяем что функция существует
    assert hasattr(monitoring, "get_system_metrics")
    assert callable(monitoring.get_system_metrics)
    
    # Вызываем функцию и проверяем результат
    metrics = monitoring.get_system_metrics()
    assert isinstance(metrics, monitoring.SystemMetrics)
    
    # Проверяем что все поля заполнены корректно
    assert isinstance(metrics.timestamp, (int, float))
    assert isinstance(metrics.memory_mb, (int, float))
    assert isinstance(metrics.cpu_percent, (int, float))
    assert isinstance(metrics.threads_count, int)
    assert isinstance(metrics.disk_usage_mb, (int, float))
    assert isinstance(metrics.uptime_seconds, (int, float))
    
    # Проверяем разумные границы значений
    assert metrics.memory_mb >= 0
    assert 0 <= metrics.cpu_percent <= 100
    assert metrics.threads_count >= 0
    assert metrics.disk_usage_mb >= 0
    assert metrics.uptime_seconds >= 0


def test_simple_monitor():
    """Тест класса SimpleMonitor"""
    monitoring = importlib.import_module("utils.monitoring")
    
    assert hasattr(monitoring, "SimpleMonitor")
    
    # Создаем экземпляр монитора
    monitor = monitoring.SimpleMonitor(check_interval=60)
    
    # Проверяем методы
    assert hasattr(monitor, "get_system_metrics")
    assert hasattr(monitor, "should_check")
    assert hasattr(monitor, "get_health_check")
    
    # Тестируем получение метрик
    metrics = monitor.get_system_metrics()
    assert isinstance(metrics, monitoring.SystemMetrics)
    
    # Тестируем проверку здоровья
    health = monitor.get_health_check()
    assert isinstance(health, dict)
    assert "ok" in health
    assert health["ok"] is True


def test_app_monitoring():
    """Тест класса AppMonitoring"""
    monitoring = importlib.import_module("utils.monitoring")
    
    assert hasattr(monitoring, "AppMonitoring")
    assert hasattr(monitoring, "app_monitoring")
    
    # Проверяем глобальный экземпляр
    app_mon = monitoring.app_monitoring
    assert isinstance(app_mon, monitoring.AppMonitoring)
    
    # Проверяем методы
    assert hasattr(app_mon, "get_health_response")
    assert hasattr(app_mon, "start_watchdog")
    assert hasattr(app_mon, "shutdown")
    
    # Тестируем получение ответа о здоровье
    health_response = app_mon.get_health_response()
    assert isinstance(health_response, dict)


def test_trading_metrics_dataclass():
    """Тест dataclass TradingMetrics"""
    monitoring = importlib.import_module("utils.monitoring")
    
    assert hasattr(monitoring, "TradingMetrics")
    TM = monitoring.TradingMetrics
    
    # Создаем экземпляр с тестовыми данными
    tm = TM(
        bot_active=True,
        position_active=False,
        last_signal_time="2024-01-01T12:00:00",
        total_trades=10,
        current_balance=1000.0,
        last_error=None
    )
    
    # Проверяем значения
    assert tm.bot_active is True
    assert tm.position_active is False
    assert tm.total_trades == 10
    assert tm.current_balance == 1000.0
    assert tm.last_error is None


def test_performance_monitor_compatibility():
    """Тест совместимости с PerformanceMonitor"""
    monitoring = importlib.import_module("utils.monitoring")
    
    # Проверяем что класс существует для совместимости
    if hasattr(monitoring, "PerformanceMonitor"):
        PM = monitoring.PerformanceMonitor
        pm = PM()
        
        assert hasattr(pm, "capture_metrics")
        metrics = pm.capture_metrics()
        assert isinstance(metrics, monitoring.SystemMetrics)


def test_resource_tracker():
    """Тест ResourceTracker если он существует"""
    monitoring = importlib.import_module("utils.monitoring")
    
    if hasattr(monitoring, "ResourceTracker"):
        RT = monitoring.ResourceTracker
        tracker = RT(max_history=10)
        
        assert hasattr(tracker, "record_metrics")
        assert hasattr(tracker, "get_average_metrics")
        
        # Записываем несколько метрик
        tracker.record_metrics()
        time.sleep(0.1)
        tracker.record_metrics()
        
        # Проверяем что история ведется
        assert len(tracker.history) >= 1
        
        # Проверяем получение средних значений
        avg_metrics = tracker.get_average_metrics()
        if avg_metrics:
            assert isinstance(avg_metrics, monitoring.SystemMetrics)


def test_app_monitoring_exports_exist():
    """Проверяем что модуль monitoring экспортирует основные функции"""
    monitoring = importlib.import_module("utils.monitoring")
    
    # Проверяем наличие основных экспортов
    assert hasattr(monitoring, "SystemMetrics")
    assert hasattr(monitoring, "SimpleMonitor")
    assert hasattr(monitoring, "app_monitoring")
    
    # Дополнительные проверки если функции существуют
    exports_to_check = [
        "get_system_metrics",
        "log_system_state", 
        "monitor_performance",
        "check_system_health"
    ]
    
    for export_name in exports_to_check:
        if hasattr(monitoring, export_name):
            attr = getattr(monitoring, export_name)
            assert callable(attr), f"{export_name} должно быть вызываемым"


def test_legacy_functions():
    """Тест legacy функций для обратной совместимости"""
    monitoring = importlib.import_module("utils.monitoring")
    
    # Проверяем legacy функцию monitor_resources
    if hasattr(monitoring, "monitor_resources"):
        result = monitoring.monitor_resources()
        assert isinstance(result, tuple)
        assert len(result) == 2
        cpu_percent, memory_mb = result
        assert isinstance(cpu_percent, (int, float))
        assert isinstance(memory_mb, (int, float))


def test_watchdog_class():
    """Тест SmartWatchdog класса"""
    monitoring = importlib.import_module("utils.monitoring")
    
    if hasattr(monitoring, "SmartWatchdog"):
        watchdog = monitoring.SmartWatchdog(check_interval=60)
        
        assert hasattr(watchdog, "start")
        assert hasattr(watchdog, "stop")
        assert watchdog.check_interval == 60
        assert watchdog._running is False