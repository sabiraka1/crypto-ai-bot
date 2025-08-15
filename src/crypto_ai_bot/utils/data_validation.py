# src/crypto_ai_bot/utils/data_validation.py
from __future__ import annotations

from typing import Iterable, Sequence
import numpy as np
import pandas as pd


OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


class DataValidationError(ValueError):
    """Единое исключение для ошибок валидации рыночных данных."""


def ensure_ohlcv(df: pd.DataFrame, required: Sequence[str] = OHLCV_COLUMNS) -> None:
    """
    Проверяет базовую корректность OHLCV-данных:
    - есть нужные столбцы;
    - таблица не пустая;
    - столбцы числовые, без NaN/inf;
    - инварианты: low <= min(open, close) <= max(open, close) <= high.
    """
    if not isinstance(df, pd.DataFrame):
        raise DataValidationError("df must be a pandas.DataFrame")

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataValidationError(f"Missing OHLCV columns: {missing}")

    if df.empty:
        raise DataValidationError("Empty dataframe")

    # все требуемые колонки должны быть числовыми
    non_numeric = [c for c in required if not pd.api.types.is_numeric_dtype(df[c])]
    if non_numeric:
        raise DataValidationError(f"Non-numeric OHLCV columns: {non_numeric}")

    # NaN/inf не допускаются
    arr = df[list(required)].to_numpy(dtype="float64", copy=False)
    if not np.isfinite(arr).all():
        raise DataValidationError("OHLCV contains NaN or inf")

    # базовые ценовые инварианты
    if (df["low"] > df["high"]).any():
        raise DataValidationError("Found low > high")

    max_oc = df[["open", "close"]].max(axis=1)
    min_oc = df[["open", "close"]].min(axis=1)
    if (df["high"] < max_oc).any():
        raise DataValidationError("Found high < max(open, close)")
    if (df["low"] > min_oc).any():
        raise DataValidationError("Found low > min(open, close)")


def ensure_monotonic_index(df: pd.DataFrame) -> None:
    """Индекс должен идти по возрастанию (временные ряды)."""
    if not df.index.is_monotonic_increasing:
        raise DataValidationError("Index must be sorted ascending")


def coerce_numeric(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Мягко приводим указанные колонки к числам (строки → числа / NaN)."""
    out = df.copy()
    for c in columns:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def coerce_ohlcv(df: pd.DataFrame, required: Sequence[str] = OHLCV_COLUMNS) -> pd.DataFrame:
    """Приводим все OHLCV-колонки к числам."""
    return coerce_numeric(df, required)


def dropna_ohlcv(df: pd.DataFrame, required: Sequence[str] = OHLCV_COLUMNS) -> pd.DataFrame:
    """Удаляем строки с пропусками в любых OHLCV-колонках."""
    return df.dropna(subset=list(required))


def validate_ohlcv(
    df: pd.DataFrame,
    required: Sequence[str] = OHLCV_COLUMNS,
    min_rows: int = 1,
    check_index: bool = True,
) -> None:
    """
    Композитная валидация: базовая проверка, порядок индекса и минимальный размер.
    """
    ensure_ohlcv(df, required)
    if check_index:
        ensure_monotonic_index(df)
    if len(df) < min_rows:
        raise DataValidationError(f"Not enough rows: {len(df)} < {min_rows}")


def prepare_and_validate_ohlcv(
    df: pd.DataFrame,
    required: Sequence[str] = OHLCV_COLUMNS,
    min_rows: int = 1,
    check_index: bool = True,
) -> pd.DataFrame:
    """
    Удобный «всё-в-одном»: привести → дропнуть NaN → провалидировать.
    Возвращает очищенную копию df.
    """
    out = coerce_ohlcv(df, required)
    out = dropna_ohlcv(out, required)
    validate_ohlcv(out, required, min_rows=min_rows, check_index=check_index)
    return out


__all__ = [
    "DataValidationError",
    "OHLCV_COLUMNS",
    "ensure_ohlcv",
    "ensure_monotonic_index",
    "coerce_numeric",
    "coerce_ohlcv",
    "dropna_ohlcv",
    "validate_ohlcv",
    "prepare_and_validate_ohlcv",
]
