# src/crypto_ai_bot/app/__init__.py
"""
App-слой (FastAPI и адаптеры).

Важно: не импортируем server.app напрямую на уровне модуля,
чтобы избежать побочных эффектов при импортировании пакета.
Используйте get_app() для ленивого получения экземпляра FastAPI.
"""
from __future__ import annotations

from typing import Any

__all__ = ["get_app"]


def get_app() -> Any:
    """Ленивый доступ к FastAPI приложению (избегает побочных импортов)."""
    from .server import app  # локальный импорт
    return app
