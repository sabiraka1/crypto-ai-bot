# utils/csv_handler.py

import os
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

# Расширенная целевая схема (новые поля в конце)
SCHEMA: List[str] = [
    "timestamp",    # ISO UTC (время фиксации закрытия)
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
    # ---- новые, опциональные ----
    "entry_ts",         # ISO UTC (время входа)
    "exit_ts",          # ISO UTC (время закрытия, дубль timestamp)
    "duration_min",     # длительность сделки в минутах
    "market_condition", # strong_bull / weak_bull / sideways / weak_bear / strong_bear
    "pattern",          # паттерн/сетап, если передавался
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
    "entry_ts": "",
    "exit_ts": "",
    "duration_min": "",
    "market_condition": "",
    "pattern": "",
}


def _round_num(v: Any, ndigits: int) -> Any:
    try:
        if v is None or v == "":
            return v
        return round(float(v), ndigits)
    except Exception:
        return v


def _iso_utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_row(row: Dict[str, Any], schema_to_use: List[str]) -> Dict[str, Any]:
    """
    Нормализует одну запись под конкретную схему (может быть старой или новой).
    """
    # заполняем отсутствующие поля дефолтами (только те, что есть в целевой схеме записи)
    normalized = {k: row.get(k, DEFAULTS.get(k, "")) for k in schema_to_use}

    # timestamp → ISO
    if "timestamp" in schema_to_use:
        ts = normalized.get("timestamp")
        if not ts:
            normalized["timestamp"] = _iso_utc_now()
        else:
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    normalized["timestamp"] = dt.isoformat(timespec="seconds").replace("+00:00", "Z")
                else:
                    dt = pd.to_datetime(ts, utc=True, errors="coerce")
                    if pd.isna(dt):
                        normalized["timestamp"] = _iso_utc_now()
                    else:
                        normalized["timestamp"] = dt.isoformat(timespec="seconds").replace("+00:00", "Z")
            except Exception:
                normalized["timestamp"] = _iso_utc_now()

    # зеркалим exit_ts, если колонка есть, но не задана
    if "exit_ts" in schema_to_use:
        if not normalized.get("exit_ts"):
            normalized["exit_ts"] = normalized.get("timestamp", _iso_utc_now())

    # округления
    if "entry_price" in schema_to_use:
        normalized["entry_price"] = _round_num(normalized.get("entry_price"), 6)
    if "exit_price" in schema_to_use:
        normalized["exit_price"] = _round_num(normalized.get("exit_price"), 6)
    if "qty_usd" in schema_to_use:
        normalized["qty_usd"] = _round_num(normalized.get("qty_usd"), 2)
    if "pnl_pct" in schema_to_use:
        normalized["pnl_pct"] = _round_num(normalized.get("pnl_pct"), 4)
    if "pnl_abs" in schema_to_use:
        normalized["pnl_abs"] = _round_num(normalized.get("pnl_abs"), 2)

    # side/strings
    for key in ("symbol", "side", "reason", "market_condition", "pattern"):
        if key in schema_to_use:
            val = normalized.get(key)
            normalized[key] = "" if val is None else str(val).strip()

    # score-поля можно оставить пустыми строками или числами
    for key in ("buy_score", "ai_score", "final_score"):
        if key in schema_to_use:
            v = normalized.get(key)
            if v == "" or v is None:
                normalized[key] = ""
            else:
                try:
                    normalized[key] = _round_num(float(v), 4)
                except Exception:
                    normalized[key] = str(v)

    # duration_min — число (но не обязательно)
    if "duration_min" in schema_to_use:
        v = normalized.get("duration_min")
        try:
            if v == "" or v is None:
                normalized["duration_min"] = ""
            else:
                normalized["duration_min"] = _round_num(float(v), 2)
        except Exception:
            normalized["duration_min"] = ""

    # entry_ts / exit_ts → строки (если есть в схеме)
    for key in ("entry_ts", "exit_ts"):
        if key in schema_to_use:
            val = normalized.get(key)
            if not val:
                normalized[key] = ""
            else:
                try:
                    dt = pd.to_datetime(val, utc=True, errors="coerce")
                    if pd.isna(dt):
                        normalized[key] = ""
                    else:
                        normalized[key] = dt.isoformat(timespec="seconds").replace("+00:00", "Z")
                except Exception:
                    normalized[key] = ""

    return normalized


def _ensure_header(path: str, header: List[str]) -> None:
    """
    Создаёт файл с указанным заголовком, если файла нет или он пуст.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(",".join(header) + "\n")


def _read_file_schema(path: str) -> Optional[List[str]]:
    """
    Возвращает текущую схему (список колонок) из существующего CSV.
    Если файл отсутствует/пуст — None.
    """
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return None
        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if not first_line:
                return None
            cols = [c.strip() for c in first_line.split(",")]
            # фильтруем пустые хвосты
            cols = [c for c in cols if c != ""]
            return cols if cols else None
    except Exception:
        return None


def _acquire_lock(path: str, timeout: float = 5.0, poll: float = 0.05) -> str:
    """
    Примитивный межпроцессный лок на основе lock-файла с O_EXCL.
    """
    lock_path = f"{path}{LOCK_SUFFIX}"
    start = time.time()
    while True:
        try:
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
        Атомарная дозапись строки закрытой сделки в closed_trades.csv.
        ВАЖНО:
          - если файл уже существует со старой схемой — пишем только эти колонки (без миграции);
          - если файла нет/пуст — создаём с НОВОЙ расширенной схемой SCHEMA.
        """
        try:
            # выясняем активную схему файла
            file_schema = _read_file_schema(filepath)
            schema_to_use = file_schema if file_schema else SCHEMA

            # если файла нет/пуст — создаём с текущей (возможно расширенной) схемой
            _ensure_header(filepath, schema_to_use)

            normalized = _normalize_row(row, schema_to_use)

            lock_path = _acquire_lock(filepath)
            try:
                # гарантируем, что схема не изменилась с момента чтения
                current_schema = _read_file_schema(filepath) or schema_to_use
                if current_schema != schema_to_use:
                    # если внезапно поменялась (другой процесс создал по-другому) — подстроимся
                    schema_to_use = current_schema
                    normalized = _normalize_row(row, schema_to_use)

                # пишем строку в конец файла (строго по schema_to_use)
                line = ",".join([str(normalized.get(col, "")) for col in schema_to_use]) + "\n"
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
        Поддерживает как старую, так и новую схему.
        """
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return []

        try:
            # читаем без жёсткой схемы
            df = pd.read_csv(filepath, dtype=str)
            if df.empty:
                return []

            # добавим недостающие новые колонки (если файл старый)
            for col in SCHEMA:
                if col not in df.columns:
                    df[col] = ""

            # сортировка по timestamp (если возможно)
            try:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
                df = df.sort_values("timestamp", ascending=False)
            except Exception:
                df = df.iloc[::-1]  # fallback: просто перевернуть

            # отрезаем до лимита
            df = df[[c for c in df.columns if c in SCHEMA]].head(int(limit)).copy()

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
                item = {
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
                    # новые поля, если они вдруг есть
                    "entry_ts": r.get("entry_ts", ""),
                    "exit_ts": r.get("exit_ts", ""),
                    "duration_min": _fmt(r.get("duration_min"), 2) if str(r.get("duration_min", "")) != "" else "",
                    "market_condition": str(r.get("market_condition", "")),
                    "pattern": str(r.get("pattern", "")),
                }
                out.append(item)
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
        """
        Добавление новой строки в CSV (совместимость).
        Лучше использовать log_closed_trade().
        """
        try:
            # схема файла может быть старой — под неё и пишем
            file_schema = _read_file_schema(filepath)
            schema_to_use = file_schema if file_schema else SCHEMA
            _ensure_header(filepath, schema_to_use)

            normalized = _normalize_row(new_data, schema_to_use)

            lock_path = _acquire_lock(filepath)
            try:
                with open(filepath, "a", encoding="utf-8", newline="") as f:
                    line = ",".join([str(normalized.get(col, "")) for col in schema_to_use]) + "\n"
                    f.write(line)
            finally:
                _release_lock(lock_path)

            return True
        except Exception as e:
            logging.error(f"Failed to append to CSV {filepath}: {e}")
            return False
