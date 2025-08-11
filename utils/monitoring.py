# utils/monitoring.py - НОВЫЙ ФАЙЛ

import os
import time
import threading
import logging
import psutil
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

# =============================================================================
# УПРОЩЕННАЯ СИСТЕМА МОНИТОРИНГА
# =============================================================================

@dataclass
class SystemMetrics:
    """Метрики системы"""
    timestamp: float
    memory_mb: float
    cpu_percent: float
    threads_count: int
    disk_usage_mb: float
    uptime_seconds: float

@dataclass
class TradingMetrics:
    """Метрики торговли"""
    bot_active: bool
    position_active: bool
    last_signal_time: Optional[str]
    total_trades: int
    current_balance: float
    last_error: Optional[str]

class SimpleMonitor:
    """Упрощенная система мониторинга без избыточности"""
    
    def __init__(self, check_interval: int = 300):
        self.check_interval = check_interval  # 5 минут
        self._last_check = 0
        self._last_metrics: Optional[SystemMetrics] = None
        self._start_time = time.time()
        self._alerts_sent = set()  # Для предотвращения спама
        
        # Пороги для алертов
        self.thresholds = {
            "memory_mb": float(os.getenv("MEMORY_ALERT_MB", "1000")),  # 1GB
            "cpu_percent": float(os.getenv("CPU_ALERT_PCT", "85")),   # 85%
            "disk_usage_mb": float(os.getenv("DISK_ALERT_MB", "5000")) # 5GB
        }
        
    def should_check(self) -> bool:
        """Нужна ли проверка метрик"""
        now = time.time()
        if now - self._last_check >= self.check_interval:
            self._last_check = now
            return True
        return False
    
    def get_system_metrics(self) -> SystemMetrics:
        """Получить системные метрики"""
        try:
            process = psutil.Process(os.getpid())
            
            # Базовые метрики
            memory_mb = process.memory_info().rss / (1024 * 1024)
            cpu_percent = process.cpu_percent(interval=0.1)
            threads_count = process.num_threads()
            
            # Дисковое пространство (текущая директория)
            disk_usage = psutil.disk_usage('.')
            disk_usage_mb = disk_usage.used / (1024 * 1024)
            
            uptime = time.time() - self._start_time
            
            metrics = SystemMetrics(
                timestamp=time.time(),
                memory_mb=round(memory_mb, 2),
                cpu_percent=round(cpu_percent, 2),
                threads_count=threads_count,
                disk_usage_mb=round(disk_usage_mb, 2),
                uptime_seconds=round(uptime, 2)
            )
            
            self._last_metrics = metrics
            return metrics
            
        except Exception as e:
            logging.error(f"Failed to get system metrics: {e}")
            return SystemMetrics(
                timestamp=time.time(),
                memory_mb=0.0, cpu_percent=0.0, 
                threads_count=0, disk_usage_mb=0.0, 
                uptime_seconds=0.0
            )
    
    def get_trading_metrics(self, trading_bot=None) -> TradingMetrics:
        """Получить торговые метрики"""
        try:
            bot_active = trading_bot is not None
            position_active = False
            last_signal_time = None
            total_trades = 0
            current_balance = 0.0
            last_error = None
            
            if trading_bot:
                try:
                    # Проверяем позицию
                    if hasattr(trading_bot, 'state'):
                        position_active = bool(trading_bot.state.get("in_position"))
                        
                    # Получаем статистику сделок
                    if hasattr(trading_bot, 'pm'):
                        try:
                            from utils.csv_handler import CSVHandler
                            stats = CSVHandler.get_trade_stats()
                            total_trades = stats.get("count", 0)
                        except Exception:
                            pass
                            
                    # Баланс из exchange client
                    if hasattr(trading_bot, 'exchange'):
                        try:
                            current_balance = trading_bot.exchange.get_balance("USDT")
                        except Exception:
                            pass
                            
                except Exception as e:
                    last_error = str(e)[:100]
            
            return TradingMetrics(
                bot_active=bot_active,
                position_active=position_active,
                last_signal_time=last_signal_time,
                total_trades=total_trades,
                current_balance=round(current_balance, 2),
                last_error=last_error
            )
            
        except Exception as e:
            logging.error(f"Failed to get trading metrics: {e}")
            return TradingMetrics(
                bot_active=False, position_active=False,
                last_signal_time=None, total_trades=0,
                current_balance=0.0, last_error=str(e)[:100]
            )
    
    def check_alerts(self, metrics: SystemMetrics) -> list:
        """Проверить пороги алертов"""
        alerts = []
        
        # Проверяем память
        if metrics.memory_mb > self.thresholds["memory_mb"]:
            alert_key = f"memory_{int(metrics.memory_mb//100)}"
            if alert_key not in self._alerts_sent:
                alerts.append(f"High memory usage: {metrics.memory_mb:.1f} MB")
                self._alerts_sent.add(alert_key)
        
        # Проверяем CPU
        if metrics.cpu_percent > self.thresholds["cpu_percent"]:
            alert_key = f"cpu_{int(metrics.cpu_percent//10)}"
            if alert_key not in self._alerts_sent:
                alerts.append(f"High CPU usage: {metrics.cpu_percent:.1f}%")
                self._alerts_sent.add(alert_key)
        
        # Очищаем старые алерты (каждые 30 минут)
        if len(self._alerts_sent) > 10:
            self._alerts_sent.clear()
        
        return alerts
    
    def get_full_status(self, trading_bot=None) -> Dict[str, Any]:
        """Полный статус системы"""
        system_metrics = self.get_system_metrics()
        trading_metrics = self.get_trading_metrics(trading_bot)
        alerts = self.check_alerts(system_metrics)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "system": asdict(system_metrics),
            "trading": asdict(trading_metrics),
            "alerts": alerts,
            "uptime_hours": round(system_metrics.uptime_seconds / 3600, 2)
        }
    
    def get_health_check(self) -> Dict[str, Any]:
        """Быстрая проверка здоровья"""
        return {
            "ok": True,
            "timestamp": time.time(),
            "uptime": round(time.time() - self._start_time, 2),
            "last_check": self._last_check,
            "memory_mb": self._last_metrics.memory_mb if self._last_metrics else 0
        }

# =============================================================================
# SMART WATCHDOG - УМНЫЙ СТОРОЖ
# =============================================================================

class SmartWatchdog:
    """Умный сторож без избыточных проверок"""
    
    def __init__(self, check_interval: int = 300):
        self.check_interval = check_interval
        self._running = False
        self._thread = None
        self._restart_attempts = 0
        self._max_restarts = 3
        self._last_restart = 0
        self._restart_cooldown = 1800  # 30 минут
        
    def start(self, trading_bot_ref, restart_func):
        """Запустить сторожа"""
        if self._running:
            return
            
        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            args=(trading_bot_ref, restart_func),
            daemon=True,
            name="SmartWatchdog"
        )
        self._thread.start()
        logging.info("🐕 Smart watchdog started")
    
    def stop(self):
        """Остановить сторожа"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _watch_loop(self, trading_bot_ref, restart_func):
        """Основной цикл сторожа"""
        consecutive_failures = 0
        
        while self._running:
            try:
                time.sleep(self.check_interval)
                
                if not self._running:
                    break
                
                # Проверяем торгового бота
                bot_ok = self._check_trading_bot(trading_bot_ref)
                
                if bot_ok:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logging.warning(f"🐕 Trading bot check failed #{consecutive_failures}")
                    
                    # Попытка перезапуска при критических проблемах
                    if consecutive_failures >= 3:
                        self._attempt_restart(restart_func)
                        consecutive_failures = 0
                        
            except Exception as e:
                logging.error(f"🐕 Watchdog error: {e}")
                time.sleep(60)  # Пауза при ошибках
    
    def _check_trading_bot(self, bot_ref) -> bool:
        """Проверить состояние торгового бота"""
        try:
            # Проверяем что бот существует
            if callable(bot_ref):
                bot = bot_ref()
            else:
                bot = bot_ref
                
            if bot is None:
                return False
            
            # Проверяем поток торговли
            trading_threads = [
                t for t in threading.enumerate() 
                if t.name == "TradingLoop" and t.is_alive()
            ]
            
            return len(trading_threads) > 0
            
        except Exception as e:
            logging.debug(f"Bot check error: {e}")
            return False
    
    def _attempt_restart(self, restart_func):
        """Попытка перезапуска"""
        now = time.time()
        
        # Проверяем кулдаун и лимит перезапусков
        if (now - self._last_restart < self._restart_cooldown or 
            self._restart_attempts >= self._max_restarts):
            logging.warning("🐕 Restart skipped: cooldown or max attempts reached")
            return
        
        try:
            logging.warning("🐕 Attempting to restart trading bot...")
            
            # Отправляем уведомление
            try:
                from telegram.bot_handler import send_message
                send_message("🔄 Watchdog restarting trading bot due to failures")
            except Exception:
                pass
            
            # Вызываем функцию перезапуска
            if callable(restart_func):
                restart_func()
                
            self._restart_attempts += 1
            self._last_restart = now
            
            logging.info("🐕 Restart attempt completed")
            
        except Exception as e:
            logging.error(f"🐕 Restart failed: {e}")

# =============================================================================
# ИНТЕГРАЦИЯ ДЛЯ APP.PY
# =============================================================================

class AppMonitoring:
    """Интеграция мониторинга для app.py"""
    
    def __init__(self):
        self.monitor = SimpleMonitor(check_interval=300)
        self.watchdog = SmartWatchdog(check_interval=300)
        
    def get_health_response(self, trading_bot=None):
        """Ответ для /health endpoint"""
        if self.monitor.should_check():
            return self.monitor.get_full_status(trading_bot)
        else:
            return self.monitor.get_health_check()
    
    def start_watchdog(self, bot_ref, restart_func):
        """Запустить сторожа"""
        self.watchdog.start(bot_ref, restart_func)
    
    def shutdown(self):
        """Корректное завершение"""
        self.watchdog.stop()
        logging.info("🔧 Monitoring system shutdown")

# Глобальный экземпляр для app.py
app_monitoring = AppMonitoring()

# =============================================================================
# ЭКСПОРТ И СОВМЕСТИМОСТЬ
# =============================================================================

# Функции для обратной совместимости
def monitor_resources():
    """Legacy функция - теперь использует SimpleMonitor"""
    monitor = SimpleMonitor()
    metrics = monitor.get_system_metrics()
    return metrics.cpu_percent, metrics.memory_mb

def send_telegram_alert(message):
    """Legacy функция отправки алертов"""
    try:
        from telegram.bot_handler import send_message
        send_message(f"🚨 {message}")
    except Exception as e:
        logging.error(f"Alert send failed: {e}")

__all__ = [
    'SimpleMonitor',
    'SmartWatchdog', 
    'AppMonitoring',
    'app_monitoring',
    'SystemMetrics',
    'TradingMetrics'
]