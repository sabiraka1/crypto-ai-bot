# utils/csv_handler.py

import os
import io
import time
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np

from core.exceptions import DataValidationException

# ── настройки и схема CSV ─────────────────────────────────────────────────────
DEFAULT_CSV_PATH = os.getenv("CLOSED_TRADES_CSV", "closed_trades.csv")
LOCK_SUFFIX = ".lock"

SCHEMA: List[str] = [
    "timestamp",    # ISO UTC
    "symbol",
    "side",         # LONG/SHORT/EXIT
    "entry_price",
    "exit_price",
    "qty_usd",
    "pnl_pct",
    "pnl_abs",
    "reason",
    "buy_score",
    "ai_score",
    "final_score",
]

# значения по умолчанию для отсутствующих ключей
DEFAULTS: Dict[str, Any] = {
    "timestamp": None,
    "symbol": "",
    "side": "",
    "entry_price": 0.0,
    "exit_price": 0.0,
    "qty_usd": 0.0,
    "pnl_pct": 0.0,
    "pnl_abs": 0.0,
    "reason": "",
    "buy_score": "",
    "ai_score": "",
    "final_score": "",
}


def _round_num(v: Any, ndigits: int) -> Any:
    try:
        if v is None or v == "":
            return v
        return round(float(v), ndigits)
    except Exception:
        return v


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    # заполняем отсутствующие поля дефолтами
    normalized = {k: row.get(k, DEFAULTS[k]) for k in SCHEMA}

    # timestamp
    ts = normalized.get("timestamp")
    if not ts:
        normalized["timestamp"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    else:
        # пробуем привести к ISO
        try:
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                normalized["timestamp"] = dt.isoformat(timespec="seconds").replace("+00:00", "Z")
            else:
                dt = pd.to_datetime(ts, utc=True, errors="coerce")
                if pd.isna(dt):
                    normalized["timestamp"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                else:
                    normalized["timestamp"] = dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        except Exception:
            normalized["timestamp"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    # округления
    normalized["entry_price"] = _round_num(normalized.get("entry_price"), 6)
    normalized["exit_price"]  = _round_num(normalized.get("exit_price"), 6)
    normalized["qty_usd"]     = _round_num(normalized.get("qty_usd"), 2)
    normalized["pnl_pct"]     = _round_num(normalized.get("pnl_pct"), 4)
    normalized["pnl_abs"]     = _round_num(normalized.get("pnl_abs"), 2)

    # side/strings
    for key in ("symbol", "side", "reason"):
        val = normalized.get(key)
        if val is None:
            normalized[key] = ""
        else:
            normalized[key] = str(val).strip()

    # score-поля можно оставить пустыми строками или числами
    for key in ("buy_score", "ai_score", "final_score"):
        v = normalized.get(key)
        if v == "" or v is None:
            normalized[key] = ""
        else:
            try:
                normalized[key] = _round_num(float(v), 4)
            except Exception:
                normalized[key] = str(v)

    return normalized


def _ensure_header(path: str) -> None:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        # создаём пустой CSV с заголовком
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(",".join(SCHEMA) + "\n")


def _acquire_lock(path: str, timeout: float = 5.0, poll: float = 0.05) -> str:
    """
    Примитивный межпроцессный лок на основе lock-файла с O_EXCL.
    """
    lock_path = f"{path}{LOCK_SUFFIX}"
    start = time.time()
    while True:
        try:
            # атомарное создание lock-файла
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return lock_path
        except FileExistsError:
            if time.time() - start > timeout:
                raise TimeoutError(f"Timeout acquiring lock for {path}")
            time.sleep(poll)


def _release_lock(lock_path: str) -> None:
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        pass


class CSVHandler:
    """Безопасная работа с CSV файлами + прикладные методы сделок"""

    # ── прикладные методы для сделок ──────────────────────────────────────────
    @staticmethod
    def log_closed_trade(row: Dict[str, Any], filepath: str = DEFAULT_CSV_PATH) -> bool:
        """
        Атомарная дозапись строки закрытой сделки в closed_trades.csv
        """
        try:
            normalized = _normalize_row(row)
            os.makedirs(os.path.dirname(filepath), exist_ok=True) if os.path.dirname(filepath) else None
            _ensure_header(filepath)

            lock_path = _acquire_lock(filepath)
            try:
                # пишем строку в конец файла
                line = ",".join([str(normalized.get(col, "")) for col in SCHEMA]) + "\n"
                with open(filepath, "a", encoding="utf-8", newline="") as f:
                    f.write(line)
            finally:
                _release_lock(lock_path)

            logging.info("✅ Closed trade logged")
            return True
        except Exception as e:
            logging.error(f"Failed to log closed trade: {e}")
            return False

    @staticmethod
    def read_last_trades(limit: int = 10, filepath: str = DEFAULT_CSV_PATH) -> List[Dict[str, Any]]:
        """
        Возвращает последние N строк как список словарей (самые свежие сверху).
        """
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return []

        try:
            # быстро читаем в pandas, с явной схемой колонок
            df = pd.read_csv(filepath, dtype=str)
            if df.empty:
                return []

            # гарантируем наличие колонок (если файл старого формата)
            for col in SCHEMA:
                if col not in df.columns:
                    df[col] = ""

            # сортировка по timestamp (если возможно)
            try:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
                df = df.sort_values("timestamp", ascending=False)
            except Exception:
                df = df.iloc[::-1]  # fallback: просто перевернуть

            df = df[SCHEMA].head(int(limit)).copy()

            # приведение типов/округление на выходе
            def _fmt(v, nd=None):
                try:
                    if v == "" or v is None or (isinstance(v, float) and np.isnan(v)):
                        return ""
                    if nd is None:
                        return v
                    return round(float(v), nd)
                except Exception:
                    return v

            out: List[Dict[str, Any]] = []
            for _, r in df.iterrows():
                out.append({
                    "timestamp": r.get("timestamp"),
                    "symbol": str(r.get("symbol", "")),
                    "side": str(r.get("side", "")),
                    "entry_price": _fmt(r.get("entry_price"), 6),
                    "exit_price": _fmt(r.get("exit_price"), 6),
                    "qty_usd": _fmt(r.get("qty_usd"), 2),
                    "pnl_pct": _fmt(r.get("pnl_pct"), 4),
                    "pnl_abs": _fmt(r.get("pnl_abs"), 2),
                    "reason": str(r.get("reason", "")),
                    "buy_score": _fmt(r.get("buy_score"), 4) if str(r.get("buy_score", "")) != "" else "",
                    "ai_score": _fmt(r.get("ai_score"), 4) if str(r.get("ai_score", "")) != "" else "",
                    "final_score": _fmt(r.get("final_score"), 4) if str(r.get("final_score", "")) != "" else "",
                })
            return out
        except Exception as e:
            logging.error(f"Failed to read last trades: {e}")
            return []

    # ── базовые безопасные операции с CSV (оставлены для обратной совместимости)
    @staticmethod
    def read_csv_safe(filepath: str, expected_columns: list = None) -> Optional[pd.DataFrame]:
        """Безопасное чтение CSV с валидацией"""
        try:
            read_params = [
                {"sep": ",", "encoding": "utf-8"},
                {"sep": ",", "encoding": "cp1251"},
                {"sep": ",", "encoding": "windows-1251"},
                {"sep": ",", "encoding": "latin-1"},
                {"sep": ";", "encoding": "utf-8"},
                {"sep": "\t", "encoding": "utf-8"},
            ]
            df = None
            for params in read_params:
                try:
                    df = pd.read_csv(filepath, **params, on_bad_lines="skip")
                    if len(df.columns) >= 3:
                        break
                except Exception:
                    continue

            if df is None or df.empty:
                raise DataValidationException("Could not read CSV file")

            df = CSVHandler._validate_and_clean(df, expected_columns)
            logging.info(f"✅ CSV loaded: {len(df)} rows, {len(df.columns)} columns")
            return df

        except Exception as e:
            logging.error(f"Failed to read CSV {filepath}: {e}")
            return None

    @staticmethod
    def _validate_and_clean(df: pd.DataFrame, expected_columns: list = None) -> pd.DataFrame:
        """Валидация и очистка данных"""
        try:
            df = df.dropna(how="all").drop_duplicates()

            if expected_columns:
                missing_cols = set(expected_columns) - set(df.columns)
                if missing_cols:
                    logging.warning(f"Missing columns: {missing_cols}")

            if "timestamp" in df.columns:
                df = df.dropna(subset=["timestamp"])

            for col in df.columns:
                if col in [
                    "open", "high", "low", "close", "volume", "price", "rsi",
                    "macd", "macd_signal", "macd_histogram", "total_score",
                    "ai_score", "confidence",
                ]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                elif col in ("timestamp", "datetime"):
                    df[col] = pd.to_datetime(df[col], errors="coerce")
                elif col == "main_reason":
                    df[col] = df[col].astype(str).replace({"?": "", "nan": "Unknown"}, regex=True)

            critical_cols = ["open", "high", "low", "close"] if "close" in df.columns else []
            if critical_cols:
                df = df.dropna(subset=critical_cols)

            return df.reset_index(drop=True)

        except Exception as e:
            logging.error(f"Data validation failed: {e}")
            raise DataValidationException(f"Data validation failed: {e}")

    @staticmethod
    def save_csv_safe(df: pd.DataFrame, filepath: str) -> bool:
        """Безопасное сохранение CSV"""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True) if os.path.dirname(filepath) else None
            df.to_csv(filepath, index=False, encoding="utf-8")
            logging.info(f"✅ CSV saved: {filepath}")
            return True
        except Exception as e:
            logging.error(f"Failed to save CSV {filepath}: {e}")
            return False

    @staticmethod
    def append_to_csv(new_data: dict, filepath: str) -> bool:
        """Добавление новой строки в CSV (совместимость). Рекомендуется log_closed_trade()."""
        try:
            normalized = {**DEFAULTS, **new_data}
            os.makedirs(os.path.dirname(filepath), exist_ok=True) if os.path.dirname(filepath) else None
            _ensure_header(filepath)

            lock_path = _acquire_lock(filepath)
            try:
                df = pd.read_csv(filepath) if os.path.exists(filepath) else pd.DataFrame(columns=SCHEMA)
                # приводим к схеме
                for col in SCHEMA:
                    if col not in df.columns:
                        df[col] = ""
                new_row = {k: normalized.get(k, "") for k in SCHEMA}
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                df.to_csv(filepath, index=False, encoding="utf-8")
            finally:
                _release_lock(lock_path)

            return True
        except Exception as e:
            logging.error(f"Failed to append to CSV {filepath}: {e}")
            return False
