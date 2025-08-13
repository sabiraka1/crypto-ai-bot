# src/crypto_ai_bot/telegram/charts.py

# Безголовый рендер графиков для серверов (Railway)
try:
    import matplotlib
    matplotlib.use("Agg")  # важный момент: headless backend
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

# Опциональные зависимости (не обязательны для импорта модуля)
try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # noqa: N816

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # noqa: N816

# Флаг готовности графиков (для мягких фолбэков в командах)
CHARTS_READY = plt is not None


def _to_series(prices: Any) -> Iterable[float]:
    """
    Приводит вход к одномерной последовательности float.
    Поддерживает: list/tuple/np.array/pd.Series/pd.DataFrame (берём колонку 'close' если есть).
    """
    # pandas DataFrame
    if pd is not None and isinstance(prices, pd.DataFrame):
        if "close" in prices.columns:
            series = prices["close"].astype(float).tolist()
        else:
            # берём первую числовую колонку
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

    # обычные python-последовательности
    if isinstance(prices, (list, tuple)):
        return [float(x) for x in prices]

    # неизвестный тип
    try:
        return list(prices)  # последняя попытка
    except Exception:
        return []


def generate_price_chart_png(prices: Any,
                             title: str = "Price",
                             width: int = 800,
                             height: int = 400) -> bytes:
    """
    Генерирует PNG-картинку цен и возвращает raw bytes.
    Если matplotlib отсутствует — бросаем аккуратную ошибку.
    """
    if plt is None:
        raise RuntimeError(
            f"matplotlib недоступен: {_charts_import_error}. "
            f"Установи зависимости (matplotlib, pillow) и задеплой заново."
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
    Совместимая обёртка: строит график и сохраняет PNG в файл.
    Возвращает путь к файлу (или None, если matplotlib недоступен).
    Если outfile не задан — создаёт временный файл и возвращает его путь.
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
