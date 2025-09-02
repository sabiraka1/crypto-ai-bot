from __future__ import annotations
import logging
from typing import Any, Dict

try:
    from crypto_ai_bot.utils.logging import get_logger as _get_logger
    from crypto_ai_bot.utils.metrics import inc as _inc
    def get_logger(name: str, *, level: int = logging.INFO) -> logging.Logger:
        return _get_logger(name=name, level=level)
    def inc(name: str, **labels: Any) -> None:
        _inc(name, **labels)
except Exception:
    def get_logger(name: str, *, level: int = logging.INFO) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        return logger
    def inc(name: str, **labels: Any) -> None:
        return None


class HealthChecker:
    """Health checker for monitoring system components."""
    
    def __init__(
        self,
        storage: Any,
        broker: Any,
        bus: Any,
        settings: Any
    ) -> None:
        self.storage = storage
        self.broker = broker
        self.bus = bus
        self.settings = settings
        self._log = get_logger("health_checker")
        self._last_check_results: Dict[str, Any] = {}
        
    async def check(self) -> Dict[str, Any]:
        """Check health of all components."""
        results = {
            "storage": False,
            "broker": False,
            "bus": False,
            "healthy": False
        }
        
        # Check storage
        try:
            if hasattr(self.storage, "conn"):
                self.storage.conn.execute("SELECT 1")
                results["storage"] = True
        except Exception as e:
            self._log.error(f"Storage health check failed: {e}")
            
        # Check broker
        try:
            if hasattr(self.broker, "exchange"):
                results["broker"] = True
        except Exception as e:
            self._log.error(f"Broker health check failed: {e}")
            
        # Check bus
        try:
            if hasattr(self.bus, "publish"):
                results["bus"] = True
        except Exception as e:
            self._log.error(f"Bus health check failed: {e}")
            
        # Overall health
        results["healthy"] = all([
            results["storage"],
            results["broker"],
            results["bus"]
        ])
        
        self._last_check_results = results
        return results
    
    async def tick(self, symbol: str, **kwargs: Any) -> Dict[str, Any]:
        """Periodic health check tick - accepts any kwargs for compatibility."""
        # Игнорируем дополнительные параметры типа dms
        if not self._last_check_results:
            await self.check()
        
        return {
            "healthy": self._last_check_results.get("healthy", True),
            "symbol": symbol
        }