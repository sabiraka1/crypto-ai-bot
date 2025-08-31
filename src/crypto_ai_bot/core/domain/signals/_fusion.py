## `core/signals/_fusion.py`
from __future__ import annotations

from crypto_ai_bot.utils.decimal import dec


def fuse_score(features: dict[str, object]) -> tuple[float, str]:
    """Простая эвристика: сравниваем last с SMA и EMA.
    Возвращает (score [0..1], explain).
    """
    try:
        last = dec(str(features.get("last", "0")))
        sma = dec(str(features.get("sma", "0")))
        ema = dec(str(features.get("ema", "0")))
        spread = float(features.get("spread_pct", 0.0))
    except Exception:
        return 0.0, "invalid_features"
    if last <= 0 or sma <= 0 or ema <= 0:
        return 0.0, "insufficient_data"
    dev_sma = float(((last - sma) / sma) * 100)
    dev_ema = float(((last - ema) / ema) * 100)
    raw = 0.5 + 0.25 * (dev_sma / 2.0) + 0.25 * (dev_ema / 2.0)  # мягкая шкала ~[-∞, +∞]
    raw -= min(spread / 100.0, 0.2)
    score = 1.0 / (1.0 + pow(2.71828, -raw))
    explain = f"dev_sma={dev_sma:.3f}%, dev_ema={dev_ema:.3f}%, spread={spread:.3f}%"
    return max(0.0, min(1.0, score)), explain
