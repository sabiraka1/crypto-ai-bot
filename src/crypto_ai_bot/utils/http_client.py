# src/crypto_ai_bot/utils/http_client.py
from __future__ import annotations

from typing import Optional

# Лёгкая фабрика HTTP-клиента без зависимости от core/settings.
# Вызывающий код сам решает, чем инициализировать timeout_sec (например, Settings.HTTP_TIMEOUT_SEC).
def create_http_client(*, timeout_sec: int = 30):
    # Сначала пробуем httpx (предпочтительно), иначе — aiohttp
    try:
        import httpx  # type: ignore
        return httpx.AsyncClient(timeout=timeout_sec)
    except Exception:
        pass

    try:
        import aiohttp  # type: ignore
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_sec))
    except Exception:
        # В крайнем случае отдаём заглушку, чтобы не падать при импорте
        class _Dummy:
            async def get(self, *a, **k): raise RuntimeError("no http client installed")
            async def post(self, *a, **k): raise RuntimeError("no http client installed")
            async def close(self): pass
        return _Dummy()
