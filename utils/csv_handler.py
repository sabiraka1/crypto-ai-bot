# utils/csv_handler.py

import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np

from core.exceptions import DataValidationException

# ── пути по умолчанию ─────────────────────────────────────────────────────────
DEFAULT_CLOSED_TRADES_CSV = os.getenv("CLOSED_TRADES_CSV", "closed_trades.csv")
DEFAULT_SIGNALS_CSV       = os.getenv("SIGNALS_CSV",       "signals_snapshots.csv")
LOCK_SUFFIX = ".lock"

# ── схема закрытых сделок (расширенная; при существующем файле ничего не мигрируем) ──
TRADES_SCHEMA: List[str] = [
    "timestamp",        # ISO UTC (момент фиксации закрытия)
    "symbol",
    "side",             # LONG/SHORT/EXIT
    "entry_price",
    "exit_price",
    "qty_usd",
    "pnl_pct",
    "pnl_abs",
    "reason",
    "buy_score",
    "ai_score",
    "final_score",
    # новые (опц.)
    "entry_ts",
    "exit_ts",
    "duration_min",
    "market_condition",
    "pattern",
]

TRADES_DEFAULTS: Dict[str, Any] = {
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

# ── схема снапшотов сигналов/рынка ────────────────────────────────────────────
SIGNALS_SCHEMA: List[str] = [
    "timestamp",        # ISO UTC времени свечи/цикла
    "symbol",
    "timeframe",
    "close",
    "rsi",
    "macd",
    "macd_signal",
    "macd_hist",
    "ema_20",
    "ema_50",
    "sma_20",
    "sma_50",
    "atr_14",
    "price_change_1",
    "price_change_3",
    "price_change_5",
    "vol_change",
    "buy_score",
    "ai_score",
    "market_condition",
    "decision",         # hold|enter|exit
    "reason",           # краткое пояснение
]

SIGNALS_DEFAULTS: Dict[str, Any] = {k: "" for k in SIGNALS_SCHEMA}
SIGNALS_DEFAULTS.update({
    "close": 0.0, "rsi": "", "macd": "", "macd_signal": "", "macd_hist": "",
    "ema_20": "", "ema_50": "", "sma_20": "", "sma_50": "",
    "atr_14": "", "price_change_1": "", "price_change_3": "", "price_change_5": "",
    "vol_change": "", "buy_score": "", "ai_score": "",
})

# ── утилиты ───────────────────────────────────────────────────────────────────
def _iso_utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def _round_num(v: Any, ndigits: int) -> Any:
    try:
        if v is None or v == "":
            return v
        return round(float(v), ndigits)
    except Exception:
        return v

def _ensure_header(path: str, header: List[str]) -> None:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(",".join(header) + "\n")

def _read_file_schema(path: str) -> Optional[List[str]]:
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return None
        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if not first_line:
                return None
            cols = [c.strip() for c in first_line.split(",")]
            cols = [c for c in cols if c != ""]
            return cols if cols else None
    except Exception:
        return None

def _acquire_lock(path: str, timeout: float = 5.0, poll: float = 0.05) -> str:
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

def _normalize_timestamp_like(val: Any) -> str:
    try:
        if not val:
            return _iso_utc_now()
        if isinstance(val, (int, float)):
            dt = datetime.fromtimestamp(float(val), tz=timezone.utc)
            return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        dt = pd.to_datetime(val, utc=True, errors="coerce")
        if pd.isna(dt):
            return _iso_utc_now()
        return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    except Exception:
        return _iso_utc_now()

# ── нормализация строк под схему ──────────────────────────────────────────────
def _normalize_trade_row(row: Dict[str, Any], schema_to_use: List[str]) -> Dict[str, Any]:
    n = {k: row.get(k, TRADES_DEFAULTS.get(k, "")) for k in schema_to_use}
    if "timestamp" in schema_to_use:
        n["timestamp"] = _normalize_timestamp_like(n.get("timestamp"))
    if "exit_ts" in schema_to_use and not n.get("exit_ts"):
        n["exit_ts"] = n.get("timestamp", _iso_utc_now())

    # округления
    for key, nd in (("entry_price", 6), ("exit_price", 6), ("qty_usd", 2), ("pnl_pct", 4), ("pnl_abs", 2)):
        if key in schema_to_use:
            n[key] = _round_num(n.get(key), nd)

    # строки
    for key in ("symbol", "side", "reason", "market_condition", "pattern"):
        if key in schema_to_use:
            val = n.get(key)
            n[key] = "" if val is None else str(val).strip()

    # score-поля
    for key in ("buy_score", "ai_score", "final_score"):
        if key in schema_to_use:
            v = n.get(key)
            if v == "" or v is None:
                n[key] = ""
            else:
                try:
                    n[key] = _round_num(float(v), 4)
                except Exception:
                    n[key] = str(v)

    # duration
    if "duration_min" in schema_to_use:
        v = n.get("duration_min")
        try:
            n["duration_min"] = "" if v in ("", None) else _round_num(float(v), 2)
        except Exception:
            n["duration_min"] = ""

    # entry/exit ts
    for key in ("entry_ts", "exit_ts"):
        if key in schema_to_use:
            val = n.get(key)
            if not val:
                n[key] = ""
            else:
                n[key] = _normalize_timestamp_like(val)
    return n

def _normalize_signal_row(row: Dict[str, Any], schema_to_use: List[str]) -> Dict[str, Any]:
    n = {k: row.get(k, SIGNALS_DEFAULTS.get(k, "")) for k in schema_to_use}
    if "timestamp" in schema_to_use:
        n["timestamp"] = _normalize_timestamp_like(n.get("timestamp"))
    # числа с округлением
    round_map = {
        "close": 6, "rsi": 4, "macd": 6, "macd_signal": 6, "macd_hist": 6,
        "ema_20": 6, "ema_50": 6, "sma_20": 6, "sma_50": 6,
        "atr_14": 6, "price_change_1": 6, "price_change_3": 6, "price_change_5": 6,
        "vol_change": 6, "buy_score": 4, "ai_score": 4,
    }
    for k, nd in round_map.items():
        if k in schema_to_use:
            n[k] = _round_num(n.get(k), nd)

    # строки
    for key in ("symbol", "timeframe", "market_condition", "decision", "reason"):
        if key in schema_to_use:
            val = n.get(key)
            n[key] = "" if val is None else str(val).strip()
    return n

# ── основной класс ────────────────────────────────────────────────────────────
class CSVHandler:
    """Безопасная работа с CSV: закрытые сделки, снапшоты сигналов, плюс базовые методы."""

    # ============= Закрытые сделки ============================================
    @staticmethod
    def log_closed_trade(row: Dict[str, Any], filepath: str = DEFAULT_CLOSED_TRADES_CSV) -> bool:
        """
        Атомарная дозапись закрытой сделки.
        Если файл уже есть со старой схемой — пишем только существующие колонки.
        Если файла нет — создаём с расширенной TRADES_SCHEMA.
        """
        try:
            file_schema = _read_file_schema(filepath)
            schema_to_use = file_schema if file_schema else TRADES_SCHEMA
            _ensure_header(filepath, schema_to_use)

            norm = _normalize_trade_row(row, schema_to_use)

            lock_path = _acquire_lock(filepath)
            try:
                # защита от гонок схемы
                current_schema = _read_file_schema(filepath) or schema_to_use
                if current_schema != schema_to_use:
                    schema_to_use = current_schema
                    norm = _normalize_trade_row(row, schema_to_use)

                line = ",".join([str(norm.get(col, "")) for col in schema_to_use]) + "\n"
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
    def log_open_trade(row: Dict[str, Any], filepath: str = DEFAULT_CLOSED_TRADES_CSV) -> bool:
        """
        (Опционально) фиксируем момент входа в тот же CSV.
        side здесь будет 'LONG' (у вас только лонги).
        При закрытии будет отдельная строка с side='EXIT'.
        """
        try:
            file_schema = _read_file_schema(filepath)
            schema_to_use = file_schema if file_schema else TRADES_SCHEMA
            _ensure_header(filepath, schema_to_use)

            # переиспользуем нормализацию — exit поля могут быть пустыми
            norm = _normalize_trade_row(row, schema_to_use)

            lock_path = _acquire_lock(filepath)
            try:
                current_schema = _read_file_schema(filepath) or schema_to_use
                if current_schema != schema_to_use:
                    schema_to_use = current_schema
                    norm = _normalize_trade_row(row, schema_to_use)

                line = ",".join([str(norm.get(col, "")) for col in schema_to_use]) + "\n"
                with open(filepath, "a", encoding="utf-8", newline="") as f:
                    f.write(line)
            finally:
                _release_lock(lock_path)

            logging.info("✅ Open trade logged")
            return True
        except Exception as e:
            logging.error(f"Failed to log open trade: {e}")
            return False

    @staticmethod
    def read_last_trades(limit: int = 10, filepath: str = DEFAULT_CLOSED_TRADES_CSV) -> List[Dict[str, Any]]:
        """Возвращает последние N сделок (поддерживает старую/новую схему)."""
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return []
        try:
            df = pd.read_csv(filepath, dtype=str)
            if df.empty:
                return []
            for col in TRADES_SCHEMA:
                if col not in df.columns:
                    df[col] = ""

            try:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
                df = df.sort_values("timestamp", ascending=False)
            except Exception:
                df = df.iloc[::-1]

            df = df[[c for c in df.columns if c in TRADES_SCHEMA]].head(int(limit)).copy()

            def _fmt(v, nd=None):
                try:
                    if v == "" or v is None or (isinstance(v, float) and np.isnan(v)):
                        return ""
                    return round(float(v), nd) if nd is not None else v
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
                    "entry_ts": r.get("entry_ts", ""),
                    "exit_ts": r.get("exit_ts", ""),
                    "duration_min": _fmt(r.get("duration_min"), 2) if str(r.get("duration_min", "")) != "" else "",
                    "market_condition": str(r.get("market_condition", "")),
                    "pattern": str(r.get("pattern", "")),
                })
            return out
        except Exception as e:
            logging.error(f"Failed to read last trades: {e}")
            return []

    # ============= Снапшоты сигналов ==========================================
    @staticmethod
    def log_signal_snapshot(row: Dict[str, Any], filepath: str = DEFAULT_SIGNALS_CSV) -> bool:
        """
        Сохранение «снимка» цикла анализа/сигнала.
        Если CSV отсутствует — создаём с полной схемой SIGNALS_SCHEMA.
        """
        try:
            file_schema = _read_file_schema(filepath)
            schema_to_use = file_schema if file_schema else SIGNALS_SCHEMA
            _ensure_header(filepath, schema_to_use)

            norm = _normalize_signal_row(row, schema_to_use)

            lock_path = _acquire_lock(filepath)
            try:
                current_schema = _read_file_schema(filepath) or schema_to_use
                if current_schema != schema_to_use:
                    schema_to_use = current_schema
                    norm = _normalize_signal_row(row, schema_to_use)

                line = ",".join([str(norm.get(col, "")) for col in schema_to_use]) + "\n"
                with open(filepath, "a", encoding="utf-8", newline="") as f:
                    f.write(line)
            finally:
                _release_lock(lock_path)

            return True
        except Exception as e:
            logging.error(f"Failed to log signal snapshot: {e}")
            return False

    # ============= Базовые совместимые операции ===============================
    @staticmethod
    def read_csv_safe(filepath: str, expected_columns: list = None) -> Optional[pd.DataFrame]:
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

            critical = ["open", "high", "low", "close"] if "close" in df.columns else []
            if critical:
                df = df.dropna(subset=critical)
            return df.reset_index(drop=True)
        except Exception as e:
            logging.error(f"Data validation failed: {e}")
            raise DataValidationException(f"Data validation failed: {e}")

    @staticmethod
    def save_csv_safe(df: pd.DataFrame, filepath: str) -> bool:
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
        """Совместимость: добавление строки в произвольный CSV без жёсткой схемы."""
        try:
            file_schema = _read_file_schema(filepath)
            if not file_schema:
                # без заголовка — создадим из ключей словаря
                schema_to_use = list(new_data.keys())
                _ensure_header(filepath, schema_to_use)
            else:
                schema_to_use = file_schema

            # простая запись без нормализации
            lock_path = _acquire_lock(filepath)
            try:
                line = ",".join([str(new_data.get(col, "")) for col in schema_to_use]) + "\n"
                with open(filepath, "a", encoding="utf-8", newline="") as f:
                    f.write(line)
            finally:
                _release_lock(lock_path)
            return True
        except Exception as e:
            logging.error(f"Failed to append to CSV {filepath}: {e}")
            return False
