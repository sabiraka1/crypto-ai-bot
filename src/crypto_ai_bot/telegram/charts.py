import logging
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def generate_price_chart(df: pd.DataFrame, symbol: str, filename: str = "chart.png") -> Optional[str]:
    """Генерирует график цены и сохраняет его в файл.

    Returns путь к файлу, если успешно, иначе None.
    """
    try:
        plt.figure(figsize=(10, 6))
        df["close"].plot(title=f"{symbol} Price Chart", color="blue")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(filename, dpi=150, bbox_inches="tight")
        plt.close()
        return filename
    except Exception as e:
        logging.error(f"Chart creation failed: {e}")
        return None
