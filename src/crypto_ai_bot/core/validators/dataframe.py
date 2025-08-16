# src/crypto_ai_bot/core/validators/dataframe.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


CANON_COLS = ["ts", "open", "high", "low", "close", "volume"]

# Допускаем разные варианты имён колонок (регистр/алиасы)
_COL_ALIASES = {
    "ts": {"t", "ts", "time", "timestamp", "datetime", "date"},
    "open": {"o", "open"},
    "high": {"h", "high"},
    "low": {"l", "low"},
    "close": {"c", "close", "price", "last"},
    "volume": {"v", "vol", "volume"},
}


@dataclass(frozen=True)
class OhlcvSpec:
    require_sorted: bool = True
    require_unique_ts: bool = True
    min_len: int | None = None
    drop_non_finite: bool = True
    coerce_seconds_to_ms: bool = True


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # приводим имена к нижнему регистру, убираем пробелы
    cols = {c: str(c).strip().lower() for c in df.columns}
    df = df.rename(columns=cols)

    # карту: найденное имя → каноническое
    mapping: dict[str, str] = {}
    for canon, aliases in _COL_ALIASES.items():
        for col in df.columns:
            if col in aliases:
                mapping[col] = canon

    # если одно и то же канон-имя попадает из нескольких колонок — оставляем первую
    seen: set[str] = set()
    new_cols: dict[str, str] = {}
    for col, canon in mapping.items():
        if canon not in seen:
            new_cols[col] = canon
            seen.add(canon)

    df = df.rename(columns=new_cols)
    return df


def _ensure_required_columns(df: pd.DataFrame) -> None:
    missing = [c for c in CANON_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV missing required columns: {missing}; got={list(df.columns)}")


def _coerce_types(df: pd.DataFrame) -> pd.DataFrame:
    # ts → int64 (мс)
    if not np.issubdtype(df["ts"].dtype, np.integer):
        df["ts"] = pd.to_numeric(df["ts"], errors="coerce").astype("Int64").astype("int64")

    # цены/объёмы → float64
    for col in ("open", "high", "low", "close", "volume"):
        if not np.issubdtype(df[col].dtype, np.floating):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df


def _maybe_seconds_to_ms(df: pd.DataFrame) -> pd.DataFrame:
    # эвристика: если ts < 10^12, вероятно это секунды → умножим на 1000
    if df["ts"].dropna().empty:
        return df
    max_ts = df["ts"].max()
    if max_ts < 10**12:  # ~ Sat Sep 09 2001 в мс
        df["ts"] = (df["ts"] * 1000).astype("int64")
    return df


def _drop_non_finite_rows(df: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    mask = np.ones(len(df), dtype=bool)
    for c in cols:
        x = df[c].to_numpy(dtype="float64", copy=False)
        mask &= np.isfinite(x)
    if (~mask).any():
        df = df.loc[mask].copy()
    return df


def _ensure_sorted_unique(df: pd.DataFrame, *, require_sorted: bool, require_unique: bool) -> pd.DataFrame:
    if require_sorted and not df["ts"].is_monotonic_increasing:
        df = df.sort_values("ts", kind="mergesort", ignore_index=True)
    if require_unique:
        # оставим последнюю запись для дубликатов ts
        df = df.drop_duplicates(subset=["ts"], keep="last", ignore_index=True)
    return df


def require_ohlcv(
    data: pd.DataFrame | Sequence[Sequence[float]] | Mapping | Iterable[Mapping],
    *,
    spec: OhlcvSpec | None = None,
) -> pd.DataFrame:
    """
    Приводит любой разумный ввод к канонической OHLCV-таблице с колонками:
    ['ts','open','high','low','close','volume'].
    - ts: миллисекунды UTC (int64)
    - цены/объёмы: float64
    Политики контроля задаются через OhlcvSpec.
    """
    spec = spec or OhlcvSpec()

    # 1) собрать DataFrame
    if isinstance(data, pd.DataFrame):
        df = data.copy()
    else:
        df = pd.DataFrame(data)

    if df.empty:
        raise ValueError("OHLCV is empty")

    # 2) нормализовать имена, проверить обязательные колонки
    df = _normalize_columns(df)
    _ensure_required_columns(df)

    # 3) типы и миллисекунды
    df = _coerce_types(df)
    if spec.coerce_seconds_to_ms:
        df = _maybe_seconds_to_ms(df)

    # 4) удалить строки с NaN/inf при необходимости
    if spec.drop_non_finite:
        df = _drop_non_finite_rows(df, ("open", "high", "low", "close", "volume"))

    # 5) отсортировать / убрать дубликаты ts
    df = _ensure_sorted_unique(df, require_sorted=spec.require_sorted, require_unique=spec.require_unique_ts)

    # 6) минимальная длина
    if spec.min_len is not None and len(df) < spec.min_len:
        raise ValueError(f"OHLCV length={len(df)} < min_len={spec.min_len}")

    return df[CANON_COLS].reset_index(drop=True)


def assert_min_len(df: pd.DataFrame, n: int) -> None:
    if len(df) < n:
        raise ValueError(f"OHLCV expected at least {n} rows, got {len(df)}")


def drop_non_finite(s: pd.Series) -> pd.Series:
    return s.replace([np.inf, -np.inf], np.nan).dropna()


# Удобные шорткаты (опционально экспортируем их в __init__.py):
def require_ohlcv_min(data, min_len: int) -> pd.DataFrame:
    return require_ohlcv(data, spec=OhlcvSpec(min_len=min_len))
