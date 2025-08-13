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
from typing import Optional

def generate_price_chart(prices, title: str = "Price", width: int = 800, height: int = 400) -> bytes:
    """
    Генерирует PNG-картинку цен.
    Возвращает raw PNG bytes. Если matplotlib отсутствует — бросаем аккуратную ошибку.
    """
    if plt is None:
        raise RuntimeError(
            f"matplotlib недоступен: {_charts_import_error}. "
            f"Установи зависимости (matplotlib, pillow) и задеплой заново."
        )

    fig = plt.figure(figsize=(width / 100.0, height / 100.0), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot(prices)
    ax.set_title(title)
    ax.grid(True)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
