# src/crypto_ai_bot/telegram/charts.py

# Р‘РµР·РіРѕР»РѕРІС‹Р№ СЂРµРЅРґРµСЂ РіСЂР°С„РёРєРѕРІ РґР»СЏ СЃРµСЂРІРµСЂРѕРІ (Railway)
try:
    import matplotlib
    matplotlib.use("Agg")  # РІР°Р¶РЅС‹Р№ РјРѕРјРµРЅС‚: headless backend
    import matplotlib.pyplot as plt
except Exception as e:
    plt = None
    _charts_import_error = e
else:
    _charts_import_error = None

import io
import os
import tempfile
from typing import Optional, Iterable, Any

# РћРїС†РёРѕРЅР°Р»СЊРЅС‹Рµ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё (РЅРµ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹ РґР»СЏ РёРјРїРѕСЂС‚Р° РјРѕРґСѓР»СЏ)
try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # noqa: N816

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # noqa: N816

# Р¤Р»Р°Рі РіРѕС‚РѕРІРЅРѕСЃС‚Рё РіСЂР°С„РёРєРѕРІ (РґР»СЏ РјСЏРіРєРёС… С„РѕР»Р±СЌРєРѕРІ РІ РєРѕРјР°РЅРґР°С…)
CHARTS_READY = plt is not None


def _to_series(prices: Any) -> Iterable[float]:
    """
    РџСЂРёРІРѕРґРёС‚ РІС…РѕРґ Рє РѕРґРЅРѕРјРµСЂРЅРѕР№ РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅРѕСЃС‚Рё float.
    РџРѕРґРґРµСЂР¶РёРІР°РµС‚: list/tuple/np.array/pd.Series/pd.DataFrame (Р±РµСЂС‘Рј РєРѕР»РѕРЅРєСѓ 'close' РµСЃР»Рё РµСЃС‚СЊ).
    """
    # pandas DataFrame
    if pd is not None and isinstance(prices, pd.DataFrame):
        if "close" in prices.columns:
            series = prices["close"].astype(float).tolist()
        else:
            # Р±РµСЂС‘Рј РїРµСЂРІСѓСЋ С‡РёСЃР»РѕРІСѓСЋ РєРѕР»РѕРЅРєСѓ
            for c in prices.columns:
                try:
                    series = prices[c].astype(float).tolist()
                    break
                except Exception:
                    continue
            else:
                series = []
        return series

    # pandas Series
    if pd is not None and isinstance(prices, pd.Series):
        try:
            return prices.astype(float).tolist()
        except Exception:
            return prices.tolist()

    # numpy array
    if np is not None and isinstance(prices, np.ndarray):
        return prices.astype(float).tolist()

    # РѕР±С‹С‡РЅС‹Рµ python-РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅРѕСЃС‚Рё
    if isinstance(prices, (list, tuple)):
        return [float(x) for x in prices]

    # РЅРµРёР·РІРµСЃС‚РЅС‹Р№ С‚РёРї
    try:
        return list(prices)  # РїРѕСЃР»РµРґРЅСЏСЏ РїРѕРїС‹С‚РєР°
    except Exception:
        return []


def generate_price_chart_png(prices: Any,
                             title: str = "Price",
                             width: int = 800,
                             height: int = 400) -> bytes:
    """
    Р“РµРЅРµСЂРёСЂСѓРµС‚ PNG-РєР°СЂС‚РёРЅРєСѓ С†РµРЅ Рё РІРѕР·РІСЂР°С‰Р°РµС‚ raw bytes.
    Р•СЃР»Рё matplotlib РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚ вЂ” Р±СЂРѕСЃР°РµРј Р°РєРєСѓСЂР°С‚РЅСѓСЋ РѕС€РёР±РєСѓ.
    """
    if plt is None:
        raise RuntimeError(
            f"matplotlib РЅРµРґРѕСЃС‚СѓРїРµРЅ: {_charts_import_error}. "
            f"РЈСЃС‚Р°РЅРѕРІРё Р·Р°РІРёСЃРёРјРѕСЃС‚Рё (matplotlib, pillow) Рё Р·Р°РґРµРїР»РѕР№ Р·Р°РЅРѕРІРѕ."
        )

    series = _to_series(prices)

    fig = plt.figure(figsize=(width / 100.0, height / 100.0), dpi=100)
    ax = fig.add_subplot(111)
    if series:
        ax.plot(series)
    ax.set_title(title)
    ax.grid(True)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def generate_price_chart(prices: Any,
                         title: str = "Price",
                         outfile: Optional[str] = None,
                         width: int = 800,
                         height: int = 400) -> Optional[str]:
    """
    РЎРѕРІРјРµСЃС‚РёРјР°СЏ РѕР±С‘СЂС‚РєР°: СЃС‚СЂРѕРёС‚ РіСЂР°С„РёРє Рё СЃРѕС…СЂР°РЅСЏРµС‚ PNG РІ С„Р°Р№Р».
    Р’РѕР·РІСЂР°С‰Р°РµС‚ РїСѓС‚СЊ Рє С„Р°Р№Р»Сѓ (РёР»Рё None, РµСЃР»Рё matplotlib РЅРµРґРѕСЃС‚СѓРїРµРЅ).
    Р•СЃР»Рё outfile РЅРµ Р·Р°РґР°РЅ вЂ” СЃРѕР·РґР°С‘С‚ РІСЂРµРјРµРЅРЅС‹Р№ С„Р°Р№Р» Рё РІРѕР·РІСЂР°С‰Р°РµС‚ РµРіРѕ РїСѓС‚СЊ.
    """
    if not CHARTS_READY:
        return None

    png = generate_price_chart_png(prices, title=title, width=width, height=height)

    if outfile:
        path = outfile
    else:
        fd, path = tempfile.mkstemp(prefix="chart_", suffix=".png")
        os.close(fd)

    with open(path, "wb") as f:
        f.write(png)

    return path








