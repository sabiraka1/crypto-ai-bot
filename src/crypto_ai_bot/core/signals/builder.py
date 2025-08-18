# src/crypto_ai_bot/core/signals/builder.py
from __future__ import annotations

# Единая точка: старая логика иногда звала build_signals, новая — build.
# Делаем совместимость: оба имени указывают на одну функцию.
try:
    from ._build import build as build
except Exception:
    # Если переименуете обратно — не забудьте обновить импорт
    from .build import build as build  # fallback

# Старое имя, на которое могли ссылаться прежние модули:
build_signals = build
