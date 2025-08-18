# src/crypto_ai_bot/__init__.py
"""
Корневой пакет crypto_ai_bot.

Здесь лишь метаданные и удобные хелперы — без побочных импортов.
Не читаем ENV (правило архитектуры).
"""
from __future__ import annotations

from typing import Final

# Пытаемся взять версию из установленных дистрибутивов (если проект установлен),
# иначе — безопасный дефолт.
try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError  # type: ignore
    try:
        __version__: Final[str] = _pkg_version("crypto-ai-bot")  # имя пакета при установке
    except PackageNotFoundError:
        __version__ = "0.0.0"
except Exception:
    __version__ = "0.0.0"

__all__ = ["__version__", "get_version"]


def get_version() -> str:
    """Возвращает строку версии пакета (без побочных эффектов)."""
    return __version__
