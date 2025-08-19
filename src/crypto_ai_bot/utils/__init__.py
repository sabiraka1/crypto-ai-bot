# src/crypto_ai_bot/utils/__init__.py

from . import metrics  # noqa: F401
from .logging import get_logger, setup_json_logging  # noqa: F401

# Совместимость со старым API:
# старое имя init -> новое setup_json_logging
init = setup_json_logging  # noqa: F401

def set_level(level: str) -> None:  # noqa: F401
    """
    Backward-compat shim. Раньше могли вызывать utils.set_level(...).
    Теперь просто меняем уровень root-логгера.
    """
    import logging
    logging.getLogger().setLevel(level)

# (Остальные экспорты, если они у вас нужны)
try:
    from .cache import GLOBAL_CACHE, TTLCache  # noqa: F401
except Exception:
    GLOBAL_CACHE = None  # type: ignore
    TTLCache = None  # type: ignore

try:
    from .charts import render_price_spark_svg, render_profit_curve_svg  # noqa: F401
except Exception:
    def render_price_spark_svg(*_a, **_k):  # type: ignore
        return ""
    def render_profit_curve_svg(*_a, **_k):  # type: ignore
        return ""

__all__ = [
    "metrics",
    "get_logger",
    "setup_json_logging",
    "init",
    "set_level",
    "GLOBAL_CACHE",
    "TTLCache",
    "render_price_spark_svg",
    "render_profit_curve_svg",
]
