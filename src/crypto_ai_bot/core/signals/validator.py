# src/crypto_ai_bot/core/signals/validator.py
# Back-compat: экспортируем validate_features из актуального агрегатора сигналов
from crypto_ai_bot.trading.signals.sinyal_skorlayici import validate_features  # noqa: F401
