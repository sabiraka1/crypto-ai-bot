# src/crypto_ai_bot/backtest/dataloader.py
from __future__ import annotations
import csv
from typing import Iterable, List
from crypto_ai_bot.backtest.engine import Candle

def _to_ts(v: str) -> int:
    v = v.strip()
    if not v:
        return 0
    # число? секунды или миллисекунды
    try:
        n = int(float(v))
        if n > 2_000_000_000_000:  # явно ms
            return n
        if n < 10_000_000_000:     # секунды
            return n * 1000
        return n
    except Exception:
        # ISO8601?
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(v.replace("Z","").replace("z",""))
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0

def load_csv(path: str) -> Iterable[Candle]:
    """
    Поддерживаем любые заголовки: time|timestamp, open, high, low, close, volume.
    Разделитель — по умолчанию запятая.
    """
    with open(path, "r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        # нормализуем имена
        hdr = {k.lower().strip(): k for k in r.fieldnames or []}
        t_key = hdr.get("timestamp") or hdr.get("time") or list(hdr.values())[0]
        o_key = hdr.get("open")
        h_key = hdr.get("high")
        l_key = hdr.get("low")
        c_key = hdr.get("close")
        v_key = hdr.get("volume") or hdr.get("vol") or hdr.get("amount")

        for row in r:
            try:
                ts = _to_ts(str(row[t_key]))
                o = float(row[o_key]); h = float(row[h_key]); l = float(row[l_key]); c = float(row[c_key])
                v = float(row[v_key]) if v_key in row and row[v_key] not in ("", None) else 0.0
                yield Candle(ts=ts, open=o, high=h, low=l, close=c, volume=v)
            except Exception:
                continue
