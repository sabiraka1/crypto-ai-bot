from __future__ import annotations

from typing import Optional
from crypto_ai_bot.core.infrastructure.settings import Settings

def create_http_client(*, settings: Optional[Settings] = None, timeout_override: Optional[int] = None):
    """Создает HTTP клиент с настройками из Settings."""
    s = settings or Settings.load()
    timeout_sec = timeout_override or s.HTTP_TIMEOUT_SEC
    
    try:
        import httpx
        return httpx.AsyncClient(timeout=timeout_sec)
    except ImportError:
        try:
            import aiohttp
            return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_sec))
        except ImportError:
            raise RuntimeError("Neither httpx nor aiohttp is available")

# Для обратной совместимости с существующим кодом
def get_timeout_sec(settings: Optional[Settings] = None) -> int:
    """Получить timeout из настроек."""
    s = settings or Settings.load()
    return s.HTTP_TIMEOUT_SEC