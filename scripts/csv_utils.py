# src/crypto_ai_bot/scripts/csv_utils.py
from __future__ import annotations

import csv
import datetime as dt
from typing import List, Sequence, Optional


def _parse_ts(val: str) -> int:
    """
    Поддерживает:
      - миллисекунды (число)
      - секунды (<= 10^11)
      - ISO8601 (UTC ожидается; смещение в строке учитывается)
    Возвращает epoch-ms.
    """
    s = (val or "").strip()
    if not s:
        return 0
    # numeric?
    if s.isdigit():
        x = int(s)
        # эвристика: если похоже на миллисекунды
        return x if x > 10_000_000_000 else x * 1000
    # ISO 8601
    try:
        # с учётом смещений +/-HH:MM
        dt_obj = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return int(dt_obj.timestamp() * 1000)
    except Exception:
        pass
    # last resort: strptime нескольких популярных форматов
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            dt_obj = dt.datetime.strptime(s, fmt)
            dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
            return int(dt_obj.timestamp() * 1000)
        except Exception:
            continue
    return 0


def load_ohlcv_csv(path: str, *, ts_col: str = "timestamp",
                   open_col: str = "open", high_col: str = "high",
                   low_col: str = "low", close_col: str = "close",
                   volume_col: str = "volume") -> List[Sequence[float]]:
    """
    Унифицированный CSV→OHLCV загрузчик (формат ccxt: [ms, o, h, l, c, v]).
    Не требует pandas.
    """
    out: List[Sequence[float]] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            try:
                ms = _parse_ts(str(row.get(ts_col, "")))
                o = float(row.get(open_col, 0.0) or 0.0)
                h = float(row.get(high_col, 0.0) or 0.0)
                l = float(row.get(low_col, 0.0) or 0.0)
                c = float(row.get(close_col, 0.0) or 0.0)
                v = float(row.get(volume_col, 0.0) or 0.0)
                if ms and o and h and l and c:
                    out.append([ms, o, h, l, c, v])
            except Exception:
                continue
    # сортировка по времени на всякий случай
    out.sort(key=lambda r: r[0])
    return out
