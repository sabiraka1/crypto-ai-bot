# utils/monitoring.py - РќРћР’Р«Р™ Р¤РђР™Р›

import os
import time
import threading
import logging
import psutil
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

# =============================================================================
# РЈРџР РћР©Р•РќРќРђРЇ РЎРРЎРўР•РњРђ РњРћРќРРўРћР РРќР“Рђ
# =============================================================================

@dataclass
class SystemMetrics:
    """РњРµС‚СЂРёРєРё СЃРёСЃС‚РµРјС‹"""
    timestamp: float
    memory_mb: float
    cpu_percent: float
    threads_count: int
    disk_usage_mb: float
    uptime_seconds: float
    
    def to_dict(self) -> Dict[str, Any]:
        """РџСЂРµРѕР±СЂР°Р·РѕРІР°РЅРёРµ РІ СЃР»РѕРІР°СЂСЊ РґР»СЏ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё СЃ С‚РµСЃС‚Р°РјРё"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SystemMetrics':
        """РЎРѕР·РґР°РЅРёРµ СЌРєР·РµРјРїР»СЏСЂР° РёР· СЃР»РѕРІР°СЂСЏ"""
        return cls(**data)

@dataclass
class TradingMetrics:
    """РњРµС‚СЂРёРєРё С‚РѕСЂРіРѕРІР»Рё"""
    bot_active: bool
    position_active: bool
    last_signal_time: Optional[str]
    total_trades: int
    current_balance: float
    last_error: Optional[str]

class SimpleMonitor:
    """РЈРїСЂРѕС‰РµРЅРЅР°СЏ СЃРёСЃС‚РµРјР° РјРѕРЅРёС‚РѕСЂРёРЅРіР° Р±РµР· РёР·Р±С‹С‚РѕС‡РЅРѕСЃС‚Рё"""
    
    def __init__(self, check_interval: int = 300):
        self.check_interval = check_interval  # 5 РјРёРЅСѓС‚
        self._last_check = 0
        self._last_metrics: Optional[SystemMetrics] = None
        self._start_time = time.time()
        self._alerts_sent = set()  # Р”Р»СЏ РїСЂРµРґРѕС‚РІСЂР°С‰РµРЅРёСЏ СЃРїР°РјР°
        
        # РџРѕСЂРѕРіРё РґР»СЏ Р°Р»РµСЂС‚РѕРІ
        self.thresholds = {
            "memory_mb": float(os.getenv("MEMORY_ALERT_MB", "1000")),  # 1GB
            "cpu_percent": float(os.getenv("CPU_ALERT_PCT", "85")),   # 85%
            "disk_usage_mb": float(os.getenv("DISK_ALERT_MB", "5000")) # 5GB
        }
        
    def should_check(self) -> bool:
        """РќСѓР¶РЅР° Р»Рё РїСЂРѕРІРµСЂРєР° РјРµС‚СЂРёРє"""
        now = time.time()
        if now - self._last_check >= self.check_interval:
            self._last_check = now
            return True
        return False
    
    def get_system_metrics(self) -> SystemMetrics:
        """РџРѕР»СѓС‡РёС‚СЊ СЃРёСЃС‚РµРјРЅС‹Рµ РјРµС‚СЂРёРєРё"""
        try:
            process = psutil.Process(os.getpid())
            
            # Р‘Р°Р·РѕРІС‹Рµ РјРµС‚СЂРёРєРё
            memory_mb = process.memory_info().rss / (1024 * 1024)
            cpu_percent = process.cpu_percent(interval=0.1)
            threads_count = process.num_threads()
            
            # Р”РёСЃРєРѕРІРѕРµ РїСЂРѕСЃС‚СЂР°РЅСЃС‚РІРѕ (С‚РµРєСѓС‰Р°СЏ РґРёСЂРµРєС‚РѕСЂРёСЏ)
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
        """РџРѕР»СѓС‡РёС‚СЊ С‚РѕСЂРіРѕРІС‹Рµ РјРµС‚СЂРёРєРё"""
        try:
            bot_active = trading_bot is not None
            position_active = False
            last_signal_time = None
            total_trades = 0
            current_balance = 0.0
            last_error = None
            
            if trading_bot:
                try:
                    # РџСЂРѕРІРµСЂСЏРµРј РїРѕР·РёС†РёСЋ
                    if hasattr(trading_bot, 'state'):
                        position_active = bool(trading_bot.state.get("in_position"))
                        
                    # РџРѕР»СѓС‡Р°РµРј СЃС‚Р°С‚РёСЃС‚РёРєСѓ СЃРґРµР»РѕРє
                    if hasattr(trading_bot, 'pm'):
                        try:
                            from utils.csv_handler import CSVHandler
                            stats = CSVHandler.get_trade_stats()
                            total_trades = stats.get("count", 0)
                        except Exception:
                            pass
                            
                    # Р‘Р°Р»Р°РЅСЃ РёР· exchange client
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
        """РџСЂРѕРІРµСЂРёС‚СЊ РїРѕСЂРѕРіРё Р°Р»РµСЂС‚РѕРІ"""
        alerts = []
        
        # РџСЂРѕРІРµСЂСЏРµРј РїР°РјСЏС‚СЊ
        if metrics.memory_mb > self.thresholds["memory_mb"]:
            alert_key = f"memory_{int(metrics.memory_mb//100)}"
            if alert_key not in self._alerts_sent:
                alerts.append(f"High memory usage: {metrics.memory_mb:.1f} MB")
                self._alerts_sent.add(alert_key)
        
        # РџСЂРѕРІРµСЂСЏРµРј CPU
        if metrics.cpu_percent > self.thresholds["cpu_percent"]:
            alert_key = f"cpu_{int(metrics.cpu_percent//10)}"
            if alert_key not in self._alerts_sent:
                alerts.append(f"High CPU usage: {metrics.cpu_percent:.1f}%")
                self._alerts_sent.add(alert_key)
        
        # РћС‡РёС‰Р°РµРј СЃС‚Р°СЂС‹Рµ Р°Р»РµСЂС‚С‹ (РєР°Р¶РґС‹Рµ 30 РјРёРЅСѓС‚)
        if len(self._alerts_sent) > 10:
            self._alerts_sent.clear()
        
        return alerts
    
    def get_full_status(self, trading_bot=None) -> Dict[str, Any]:
        """РџРѕР»РЅС‹Р№ СЃС‚Р°С‚СѓСЃ СЃРёСЃС‚РµРјС‹"""
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
        """Р‘С‹СЃС‚СЂР°СЏ РїСЂРѕРІРµСЂРєР° Р·РґРѕСЂРѕРІСЊСЏ"""
        return {
            "ok": True,
            "timestamp": time.time(),
            "uptime": round(time.time() - self._start_time, 2),
            "last_check": self._last_check,
            "memory_mb": self._last_metrics.memory_mb if self._last_metrics else 0
        }

# =============================================================================
# SMART WATCHDOG - РЈРњРќР«Р™ РЎРўРћР РћР–
# =============================================================================

class SmartWatchdog:
    """РЈРјРЅС‹Р№ СЃС‚РѕСЂРѕР¶ Р±РµР· РёР·Р±С‹С‚РѕС‡РЅС‹С… РїСЂРѕРІРµСЂРѕРє"""
    
    def __init__(self, check_interval: int = 300):
        self.check_interval = check_interval
        self._running = False
        self._thread = None
        self._restart_attempts = 0
        self._max_restarts = 3
        self._last_restart = 0
        self._restart_cooldown = 1800  # 30 РјРёРЅСѓС‚
        
    def start(self, trading_bot_ref, restart_func):
        """Р—Р°РїСѓСЃС‚РёС‚СЊ СЃС‚РѕСЂРѕР¶Р°"""
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
        logging.info("рџђ• Smart watchdog started")
    
    def stop(self):
        """РћСЃС‚Р°РЅРѕРІРёС‚СЊ СЃС‚РѕСЂРѕР¶Р°"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _watch_loop(self, trading_bot_ref, restart_func):
        """РћСЃРЅРѕРІРЅРѕР№ С†РёРєР» СЃС‚РѕСЂРѕР¶Р°"""
        consecutive_failures = 0
        
        while self._running:
            try:
                time.sleep(self.check_interval)
                
                if not self._running:
                    break
                
                # РџСЂРѕРІРµСЂСЏРµРј С‚РѕСЂРіРѕРІРѕРіРѕ Р±РѕС‚Р°
                bot_ok = self._check_trading_bot(trading_bot_ref)
                
                if bot_ok:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logging.warning(f"рџђ• Trading bot check failed #{consecutive_failures}")
                    
                    # РџРѕРїС‹С‚РєР° РїРµСЂРµР·Р°РїСѓСЃРєР° РїСЂРё РєСЂРёС‚РёС‡РµСЃРєРёС… РїСЂРѕР±Р»РµРјР°С…
                    if consecutive_failures >= 3:
                        self._attempt_restart(restart_func)
                        consecutive_failures = 0
                        
            except Exception as e:
                logging.error(f"рџђ• Watchdog error: {e}")
                time.sleep(60)  # РџР°СѓР·Р° РїСЂРё РѕС€РёР±РєР°С…
    
    def _check_trading_bot(self, bot_ref) -> bool:
        """РџСЂРѕРІРµСЂРёС‚СЊ СЃРѕСЃС‚РѕСЏРЅРёРµ С‚РѕСЂРіРѕРІРѕРіРѕ Р±РѕС‚Р°"""
        try:
            # РџСЂРѕРІРµСЂСЏРµРј С‡С‚Рѕ Р±РѕС‚ СЃСѓС‰РµСЃС‚РІСѓРµС‚
            if callable(bot_ref):
                bot = bot_ref()
            else:
                bot = bot_ref
                
            if bot is None:
                return False
            
            # РџСЂРѕРІРµСЂСЏРµРј РїРѕС‚РѕРє С‚РѕСЂРіРѕРІР»Рё
            trading_threads = [
                t for t in threading.enumerate() 
                if t.name == "TradingLoop" and t.is_alive()
            ]
            
            return len(trading_threads) > 0
            
        except Exception as e:
            logging.debug(f"Bot check error: {e}")
            return False
    
    def _attempt_restart(self, restart_func):
        """РџРѕРїС‹С‚РєР° РїРµСЂРµР·Р°РїСѓСЃРєР°"""
        now = time.time()
        
        # РџСЂРѕРІРµСЂСЏРµРј РєСѓР»РґР°СѓРЅ Рё Р»РёРјРёС‚ РїРµСЂРµР·Р°РїСѓСЃРєРѕРІ
        if (now - self._last_restart < self._restart_cooldown or 
            self._restart_attempts >= self._max_restarts):
            logging.warning("рџђ• Restart skipped: cooldown or max attempts reached")
            return
        
        try:
            logging.warning("рџђ• Attempting to restart trading bot...")
            
            # РћС‚РїСЂР°РІР»СЏРµРј СѓРІРµРґРѕРјР»РµРЅРёРµ
            try:
                from telegram.api_utils import send_message
                send_message("рџ”„ Watchdog restarting trading bot due to failures")
            except Exception:
                pass
            
            # Р’С‹Р·С‹РІР°РµРј С„СѓРЅРєС†РёСЋ РїРµСЂРµР·Р°РїСѓСЃРєР°
            if callable(restart_func):
                restart_func()
                
            self._restart_attempts += 1
            self._last_restart = now
            
            logging.info("рџђ• Restart attempt completed")
            
        except Exception as e:
            logging.error(f"рџђ• Restart failed: {e}")

# =============================================================================
# РРќРўР•Р“Р РђР¦РРЇ Р”Р›РЇ APP.PY
# =============================================================================

class AppMonitoring:
    """РРЅС‚РµРіСЂР°С†РёСЏ РјРѕРЅРёС‚РѕСЂРёРЅРіР° РґР»СЏ app.py"""
    
    def __init__(self):
        self.monitor = SimpleMonitor(check_interval=300)
        self.watchdog = SmartWatchdog(check_interval=300)
        
    def get_health_response(self, trading_bot=None):
        """РћС‚РІРµС‚ РґР»СЏ /health endpoint"""
        if self.monitor.should_check():
            return self.monitor.get_full_status(trading_bot)
        else:
            return self.monitor.get_health_check()
    
    def start_watchdog(self, bot_ref, restart_func):
        """Р—Р°РїСѓСЃС‚РёС‚СЊ СЃС‚РѕСЂРѕР¶Р°"""
        self.watchdog.start(bot_ref, restart_func)
    
    def shutdown(self):
        """РљРѕСЂСЂРµРєС‚РЅРѕРµ Р·Р°РІРµСЂС€РµРЅРёРµ"""
        self.watchdog.stop()
        logging.info("рџ”§ Monitoring system shutdown")

# Р“Р»РѕР±Р°Р»СЊРЅС‹Р№ СЌРєР·РµРјРїР»СЏСЂ РґР»СЏ app.py
app_monitoring = AppMonitoring()

# =============================================================================
# Р”РћРџРћР›РќРРўР•Р›Р¬РќР«Р• Р¤РЈРќРљР¦РР Р”Р›РЇ РЎРћР’РњР•РЎРўРРњРћРЎРўР РЎ РўР•РЎРўРђРњР
# =============================================================================

class PerformanceMonitor:
    """РљР»Р°СЃСЃ РґР»СЏ РјРѕРЅРёС‚РѕСЂРёРЅРіР° РїСЂРѕРёР·РІРѕРґРёС‚РµР»СЊРЅРѕСЃС‚Рё (СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ СЃ С‚РµСЃС‚Р°РјРё)"""
    
    def __init__(self):
        self.start_time = time.time()
        self.metrics_history = []
        self.alerts = []
        
    def capture_metrics(self) -> SystemMetrics:
        """Р—Р°С…РІР°С‚ С‚РµРєСѓС‰РёС… СЃРёСЃС‚РµРјРЅС‹С… РјРµС‚СЂРёРє"""
        monitor = SimpleMonitor()
        return monitor.get_system_metrics()


def get_system_metrics() -> SystemMetrics:
    """РџРѕР»СѓС‡РµРЅРёРµ С‚РµРєСѓС‰РёС… СЃРёСЃС‚РµРјРЅС‹С… РјРµС‚СЂРёРє (СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚СЊ СЃ С‚РµСЃС‚Р°РјРё)"""
    monitor = SimpleMonitor()
    return monitor.get_system_metrics()


def log_system_state(output_file: Optional[str] = None) -> Dict[str, Any]:
    """Р›РѕРіРёСЂРѕРІР°РЅРёРµ С‚РµРєСѓС‰РµРіРѕ СЃРѕСЃС‚РѕСЏРЅРёСЏ СЃРёСЃС‚РµРјС‹"""
    metrics = get_system_metrics()
    
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "system_metrics": metrics.to_dict(),
        "app_info": {
            "python_version": "3.13.6",
            "process_id": os.getpid(),
        }
    }
    
    if output_file:
        try:
            import json
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(log_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"РћС€РёР±РєР° Р·Р°РїРёСЃРё Р»РѕРіР°: {e}")
    
    return log_data


def monitor_performance(duration_seconds: int = 60, interval_seconds: int = 5) -> list:
    """РњРѕРЅРёС‚РѕСЂРёРЅРі РїСЂРѕРёР·РІРѕРґРёС‚РµР»СЊРЅРѕСЃС‚Рё РІ С‚РµС‡РµРЅРёРµ Р·Р°РґР°РЅРЅРѕРіРѕ РІСЂРµРјРµРЅРё"""
    metrics_list = []
    monitor = SimpleMonitor()
    
    start_time = time.time()
    
    while time.time() - start_time < duration_seconds:
        metrics = monitor.get_system_metrics()
        metrics_list.append(metrics)
        time.sleep(interval_seconds)
    
    return metrics_list


def check_system_health() -> Dict[str, Any]:
    """РџСЂРѕРІРµСЂРєР° СЃРѕСЃС‚РѕСЏРЅРёСЏ СЃРёСЃС‚РµРјС‹ Рё РІРѕР·РІСЂР°С‰РµРЅРёРµ СЂРµРєРѕРјРµРЅРґР°С†РёР№"""
    metrics = get_system_metrics()
    
    health_status = {
        "overall_status": "healthy",
        "warnings": [],
        "recommendations": [],
        "metrics": metrics.to_dict()
    }
    
    # РџСЂРѕРІРµСЂРєР° РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ РїР°РјСЏС‚Рё
    if metrics.memory_mb > 8000:  # > 8GB
        health_status["warnings"].append("Р’С‹СЃРѕРєРѕРµ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ РїР°РјСЏС‚Рё")
        health_status["recommendations"].append("Р Р°СЃСЃРјРѕС‚СЂРёС‚Рµ РІРѕР·РјРѕР¶РЅРѕСЃС‚СЊ СѓРІРµР»РёС‡РµРЅРёСЏ RAM")
        health_status["overall_status"] = "warning"
    
    # РџСЂРѕРІРµСЂРєР° CPU
    if metrics.cpu_percent > 80:
        health_status["warnings"].append("Р’С‹СЃРѕРєР°СЏ Р·Р°РіСЂСѓР·РєР° CPU")
        health_status["recommendations"].append("РћРїС‚РёРјРёР·РёСЂСѓР№С‚Рµ РЅР°РіСЂСѓР·РєСѓ РЅР° РїСЂРѕС†РµСЃСЃРѕСЂ")
        health_status["overall_status"] = "warning"
    
    # РџСЂРѕРІРµСЂРєР° РґРёСЃРєРѕРІРѕРіРѕ РїСЂРѕСЃС‚СЂР°РЅСЃС‚РІР°
    if metrics.disk_usage_mb > 50000:  # > 50GB
        health_status["warnings"].append("Р’С‹СЃРѕРєРѕРµ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ РґРёСЃРєР°")
        health_status["recommendations"].append("РћС‡РёСЃС‚РёС‚Рµ РІСЂРµРјРµРЅРЅС‹Рµ С„Р°Р№Р»С‹")
        health_status["overall_status"] = "warning"
    
    return health_status


class ResourceTracker:
    """РљР»Р°СЃСЃ РґР»СЏ РѕС‚СЃР»РµР¶РёРІР°РЅРёСЏ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ СЂРµСЃСѓСЂСЃРѕРІ РІРѕ РІСЂРµРјРµРЅРё"""
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.history = []
        self.lock = threading.Lock()
    
    def record_metrics(self) -> None:
        """Р—Р°РїРёСЃСЊ С‚РµРєСѓС‰РёС… РјРµС‚СЂРёРє РІ РёСЃС‚РѕСЂРёСЋ"""
        metrics = get_system_metrics()
        
        with self.lock:
            self.history.append(metrics)
            
            # РћРіСЂР°РЅРёС‡РёРІР°РµРј СЂР°Р·РјРµСЂ РёСЃС‚РѕСЂРёРё
            if len(self.history) > self.max_history:
                self.history = self.history[-self.max_history:]
    
    def get_average_metrics(self, last_n: Optional[int] = None) -> Optional[SystemMetrics]:
        """РџРѕР»СѓС‡РµРЅРёРµ СЃСЂРµРґРЅРёС… РјРµС‚СЂРёРє Р·Р° РїРѕСЃР»РµРґРЅРёРµ N Р·Р°РїРёСЃРµР№"""
        with self.lock:
            if not self.history:
                return None
            
            data = self.history[-last_n:] if last_n else self.history
            
            if not data:
                return None
            
            # Р’С‹С‡РёСЃР»СЏРµРј СЃСЂРµРґРЅРёРµ Р·РЅР°С‡РµРЅРёСЏ
            avg_memory = sum(m.memory_mb for m in data) / len(data)
            avg_cpu = sum(m.cpu_percent for m in data) / len(data)
            avg_threads = sum(m.threads_count for m in data) / len(data)
            avg_disk = sum(m.disk_usage_mb for m in data) / len(data)
            avg_uptime = sum(m.uptime_seconds for m in data) / len(data)
            
            return SystemMetrics(
                timestamp=time.time(),
                memory_mb=avg_memory,
                cpu_percent=avg_cpu,
                threads_count=int(avg_threads),
                disk_usage_mb=avg_disk,
                uptime_seconds=avg_uptime
            )
    
    def export_history(self, filename: str) -> bool:
        """Р­РєСЃРїРѕСЂС‚ РёСЃС‚РѕСЂРёРё РјРµС‚СЂРёРє РІ С„Р°Р№Р»"""
        try:
            import json
            with self.lock:
                data = [metrics.to_dict() for metrics in self.history]
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    "export_time": datetime.now().isoformat(),
                    "total_records": len(data),
                    "metrics": data
                }, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            logging.error(f"РћС€РёР±РєР° СЌРєСЃРїРѕСЂС‚Р° РёСЃС‚РѕСЂРёРё: {e}")
            return False


# Р“Р»РѕР±Р°Р»СЊРЅС‹Р№ СЌРєР·РµРјРїР»СЏСЂ С‚СЂРµРєРµСЂР° СЂРµСЃСѓСЂСЃРѕРІ
_resource_tracker = ResourceTracker()


def start_background_monitoring(interval_seconds: int = 30) -> threading.Thread:
    """Р—Р°РїСѓСЃРє С„РѕРЅРѕРІРѕРіРѕ РјРѕРЅРёС‚РѕСЂРёРЅРіР° СЂРµСЃСѓСЂСЃРѕРІ"""
    def monitoring_loop():
        while True:
            try:
                _resource_tracker.record_metrics()
                time.sleep(interval_seconds)
            except Exception as e:
                logging.error(f"РћС€РёР±РєР° РІ С„РѕРЅРѕРІРѕРј РјРѕРЅРёС‚РѕСЂРёРЅРіРµ: {e}")
                time.sleep(interval_seconds)
    
    thread = threading.Thread(target=monitoring_loop, daemon=True)
    thread.start()
    return thread


def get_resource_summary() -> Dict[str, Any]:
    """РџРѕР»СѓС‡РµРЅРёРµ СЃРІРѕРґРєРё РїРѕ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЋ СЂРµСЃСѓСЂСЃРѕРІ"""
    current = get_system_metrics()
    average = _resource_tracker.get_average_metrics(last_n=10)  # РїРѕСЃР»РµРґРЅРёРµ 10 Р·Р°РїРёСЃРµР№
    
    return {
        "current": current.to_dict(),
        "average_last_10": average.to_dict() if average else None,
        "history_count": len(_resource_tracker.history),
        "psutil_available": True
    }

# =============================================================================
# Р­РљРЎРџРћР Рў Р РЎРћР’РњР•РЎРўРРњРћРЎРўР¬
# =============================================================================

# Р¤СѓРЅРєС†РёРё РґР»СЏ РѕР±СЂР°С‚РЅРѕР№ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё
def monitor_resources():
    """Legacy С„СѓРЅРєС†РёСЏ - С‚РµРїРµСЂСЊ РёСЃРїРѕР»СЊР·СѓРµС‚ SimpleMonitor"""
    monitor = SimpleMonitor()
    metrics = monitor.get_system_metrics()
    return metrics.cpu_percent, metrics.memory_mb

def send_telegram_alert(message):
    """Legacy С„СѓРЅРєС†РёСЏ РѕС‚РїСЂР°РІРєРё Р°Р»РµСЂС‚РѕРІ"""
    try:
        from telegram.api_utils import send_message
        send_message(f"рџљЁ {message}")
    except Exception as e:
        logging.error(f"Alert send failed: {e}")

__all__ = [
    'SimpleMonitor',
    'SmartWatchdog', 
    'AppMonitoring',
    'app_monitoring',
    'SystemMetrics',
    'TradingMetrics',
    'PerformanceMonitor',
    'ResourceTracker',
    'get_system_metrics',
    'log_system_state',
    'monitor_performance',
    'check_system_health',
    'start_background_monitoring',
    'get_resource_summary'
]

