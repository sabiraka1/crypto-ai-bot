"""
Шлюз для совместимости: маппим crypto_ai_bot.utils.* на верхнеуровневые utils.*,
пока модули физически лежат в корне репозитория.

Рекомендуемый следующий шаг: перенести utils/*.py в src/crypto_ai_bot/utils/*.py
и удалить этот мост.
"""
import importlib
import sys

for _name in ("ids", "time", "logging", "metrics", "exceptions"):
    try:
        mod = importlib.import_module(f"utils.{_name}")
        sys.modules[f"{__name__}.{_name}"] = mod
    except Exception:
        # модуль может отсутствовать — тогда просто пропускаем
        pass
