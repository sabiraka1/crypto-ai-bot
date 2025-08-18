# src/crypto_ai_bot/backtest/csv_loader.py
from __future__ import annotations

import csv
from typing import Iterable, List, Sequence, Tuple, Optional

_OHLCV_IDX = {
    "timestamp": {"timestamp", "time", "ts", "date", "datetime"},
    "open": {"open", "o"},
    "high": {"high", "h"},
    "low": {"low", "l"},
    "close": {"close", "c"},
    "volume": {"volume", "vol", "v"},
}


def _norm_header(cols: Sequence[str]) -> dict:
    m: dict[str, int] = {}
    for i, name in enumerate(cols):
        key = name.strip().lower()
        for k, aliases in _OHLCV_IDX.items():
            if key in aliases and k not in m:
                m[k] = i
    return m


def _to_float(x: str) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _to_int(x: str) -> int:
    try:
        v = int(float(x))
        # эвристика: если это секунды, умножим до миллисекунд (>= 10^10 — уже ms)
        if v < 10_000_000_000:
            v *= 1000
        return v
    except Exception:
        return 0


def load_ohlcv_csv(path: str) -> List[List[float]]:
    """
    Читает CSV и возвращает список OHLCV:
    [ [ts_ms, open, high, low, close, volume], ... ] отсортированный по времени.
    Поддерживает заголовки: timestamp|time|date|datetime, open, high, low, close, volume (в любом регистре).
    """
    rows: List[List[float]] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        cols = next(reader, None)
        if not cols:
            return rows
        idx = _norm_header(cols)
        # обязательные поля
        req = {"timestamp", "open", "high", "low", "close"}
        if not req.issubset(set(idx.keys())):
            raise ValueError(f"CSV missing columns: required {sorted(req)}, got {sorted(idx.keys())}")
        ivol = idx.get("volume")

        for r in reader:
            ts = _to_int(r[idx["timestamp"]])
            o = _to_float(r[idx["open"]])
            h = _to_float(r[idx["high"]])
            l = _to_float(r[idx["low"]])
            c = _to_float(r[idx["close"]])
            v = _to_float(r[ivol]) if ivol is not None else 0.0
            if ts <= 0:
                continue
            rows.append([float(ts), float(o), float(h), float(l), float(c), float(v)])

    rows.sort(key=lambda x: x[0])
    return rows
