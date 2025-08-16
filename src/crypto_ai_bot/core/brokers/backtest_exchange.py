# src/crypto_ai_bot/core/brokers/backtest_exchange.py
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from .base import (
    ExchangeInterface,
    PermanentExchangeError,
)
from .symbols import normalize_symbol, normalize_timeframe, split_symbol
from crypto_ai_bot.utils import metrics


# ───────────────────────────── helpers ────────────────────────────────────────

def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_float(x: Any, default: float = 0.0) -> float:
    if isinstance(x, Decimal):
        try:
            return float(x)
        except Exception:
            return default
    try:
        return float(x)
    except Exception:
        return default


def _labels(method: str) -> Dict[str, str]:
    return {"method": method, "exchange": "backtest"}


_OHLCV_CANDIDATES = {
    "time": {"time", "timestamp", "ts", "datetime", "date"},
    "open": {"open", "o"},
    "high": {"high", "h"},
    "low": {"low", "l"},
    "close": {"close", "c"},
    "volume": {"volume", "vol", "v"},
}


def _find_col(df: pd.DataFrame, logical: str) -> str:
    lowmap = {str(c).lower(): c for c in df.columns}
    for cand in _OHLCV_CANDIDATES.get(logical, {logical}):
        if cand in lowmap:
            return lowmap[cand]
    raise KeyError(f"Required column not found for '{logical}'. Available: {list(df.columns)}")


# ───────────────────────────── state ─────────────────────────────────────────

@dataclass
class _State:
    df: pd.DataFrame
    time_col: str
    open_col: str
    high_col: str
    low_col: str
    close_col: str
    volume_col: Optional[str]
    cursor: int  # индекс текущего бара (включительно)
    base_ccy: str
    quote_ccy: str
    balances: Dict[str, Dict[str, float]]  # {'USDT': {'free':..,'used':..,'total':..}, ...}
    fee_pct: float
    slip_pct: float


# ───────────────────────────── broker ────────────────────────────────────────

class BacktestExchange(ExchangeInterface):
    """
    Исторический брокер (backtest):
      - читает OHLCV из CSV (cfg.BACKTEST_CSV)
      - внешняя логика (раннер) может двигать курсор методами `advance()`/`set_cursor()`
      - API совместим с ExchangeInterface; все вызовы без сети
    """

    def __init__(self, *, cfg: Any):
        self._cfg = cfg
        csv_path = getattr(cfg, "BACKTEST_CSV", None)
        if not csv_path:
            raise PermanentExchangeError("BACKTEST_CSV is not set in Settings")

        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            raise PermanentExchangeError(f"Failed to read BACKTEST_CSV at {csv_path!r}: {e}")

        if not isinstance(df, pd.DataFrame) or df.empty:
            raise PermanentExchangeError(f"BACKTEST_CSV {csv_path!r} is empty or invalid")

        # locate columns
        tcol = _find_col(df, "time")
        ocol = _find_col(df, "open")
        hcol = _find_col(df, "high")
        lcol = _find_col(df, "low")
        ccol = _find_col(df, "close")
        try:
            vcol = _find_col(df, "volume")
        except Exception:
            vcol = None

        # normalize time to int ms
        ts = df[tcol]
        if pd.api.types.is_datetime64_any_dtype(ts):
            df["_ts_ms_"] = (ts.astype("int64") // 10**6).astype("int64")
        else:
            # попытка привести к datetime → иначе предполагаем уже миллисекунды/секунды
            try:
                parsed = pd.to_datetime(ts, utc=True, errors="raise")
                df["_ts_ms_"] = (parsed.astype("int64") // 10**6).astype("int64")
            except Exception:
                # пробуем угадать секунды/миллисекунды
                s = pd.to_numeric(ts, errors="coerce").fillna(0).astype("int64")
                # если значения выглядят как секунды (10^10), домножим
                df["_ts_ms_"] = s.where(s > 10**12, s * 1000)

        # сортировка по времени по возрастанию
        df = df.sort_values("_ts_ms_").reset_index(drop=True)

        # стартовые балансы: пополняем котируемую валюту
        sym = normalize_symbol(getattr(cfg, "SYMBOL", "BTC/USDT"))
        base, quote = split_symbol(sym)
        initial_quote = _to_float(getattr(cfg, "BACKTEST_INITIAL_BALANCE", 10000.0))
        balances = {
            base: {"free": 0.0, "used": 0.0, "total": 0.0},
            quote: {"free": initial_quote, "used": 0.0, "total": initial_quote},
        }

        self._st = _State(
            df=df,
            time_col=tcol,
            open_col=ocol,
            high_col=hcol,
            low_col=lcol,
            close_col=ccol,
            volume_col=vcol,
            cursor=max(0, int(getattr(cfg, "MIN_FEATURE_BARS", 100)) - 1),  # чтобы с первого вызова хватало истории
            base_ccy=base,
            quote_ccy=quote,
            balances=balances,
            fee_pct=float(getattr(cfg, "BACKTEST_FEE_PCT", 0.0005)),
            slip_pct=float(getattr(cfg, "BACKTEST_SLIPPAGE_PCT", 0.0002)),
        )

        # рамки курсора
        self._st.cursor = min(max(self._st.cursor, 0), len(self._st.df) - 1)

        metrics.inc("broker_created_total", {"mode": "backtest"})

    # ─────────────────────────── ExchangeInterface ─────────────────────────────

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        sym = normalize_symbol(symbol)
        normalize_timeframe(timeframe)  # валидируем формально; бэктест читает из CSV и не ресемплит

        t0 = time.perf_counter()
        try:
            end = self._st.cursor
            start = max(0, end - int(limit) + 1)
            sl = self._st.df.iloc[start : end + 1]
            out: List[List[float]] = []
            for _, r in sl.iterrows():
                ts = int(r["_ts_ms_"])
                o = float(r[self._st.open_col])
                h = float(r[self._st.high_col])
                l = float(r[self._st.low_col])
                c = float(r[self._st.close_col])
                v = float(r[self._st.volume_col]) if self._st.volume_col else 0.0
                out.append([ts, o, h, l, c, v])
            metrics.inc("broker_requests_total", _labels("fetch_ohlcv") | {"code": "200"})
            return out
        finally:
            metrics.observe("broker_latency_seconds", time.perf_counter() - t0, _labels("fetch_ohlcv"))

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        r = self._st.df.iloc[self._st.cursor]
        last = float(r[self._st.close_col])
        # небольшой синтетический спред (±1 bps), чтобы логика, рассчитывающая spread, не падала на нуле
        bid = last * (1.0 - 0.0001)
        ask = last * (1.0 + 0.0001)
        ts = int(r["_ts_ms_"])
        t0 = time.perf_counter()
        try:
            out = {
                "symbol": sym,
                "last": last,
                "close": last,
                "bid": bid,
                "ask": ask,
                "timestamp": ts,
            }
            metrics.inc("broker_requests_total", _labels("fetch_ticker") | {"code": "200"})
            return out
        finally:
            metrics.observe("broker_latency_seconds", time.perf_counter() - t0, _labels("fetch_ticker"))

    def create_order(
        self,
        symbol: str,
        type_: str,
        side: str,
        amount: Decimal,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> Dict[str, Any]:
        sym = normalize_symbol(symbol)
        typ = str(type_).lower()
        sd = str(side).lower()
        if typ not in {"market", "limit"}:
            raise PermanentExchangeError(f"Unsupported order type: {type_!r}")
        if sd not in {"buy", "sell"}:
            raise PermanentExchangeError(f"Unsupported side: {side!r}")

        # текущая котировка (исполняем сразу)
        r = self._st.df.iloc[self._st.cursor]
        last = float(r[self._st.close_col])
        bid = last * (1.0 - 0.0001)
        ask = last * (1.0 + 0.0001)

        amt = _to_float(amount)
        if amt <= 0.0:
            raise PermanentExchangeError("amount must be > 0")

        # цена исполнения с проскальзыванием
        if typ == "market":
            exec_price = ask * (1.0 + self._st.slip_pct) if sd == "buy" else bid * (1.0 - self._st.slip_pct)
        else:  # limit — исполняем сразу по лимитной цене
            exec_price = _to_float(price, default=last)

        fee = exec_price * amt * self._st.fee_pct

        base, quote = self._st.base_ccy, self._st.quote_ccy
        # проверка и изменение балансов
        if sd == "buy":
            cost = exec_price * amt + fee
            if self._st.balances[quote]["free"] + 1e-12 < cost:
                raise PermanentExchangeError("insufficient funds (quote)")
            self._st.balances[quote]["free"] -= cost
            self._st.balances[quote]["total"] -= cost
            self._st.balances[base]["free"] += amt
            self._st.balances[base]["total"] += amt
        else:
            if self._st.balances[base]["free"] + 1e-12 < amt:
                raise PermanentExchangeError("insufficient funds (base)")
            proceeds = exec_price * amt - fee
            self._st.balances[base]["free"] -= amt
            self._st.balances[base]["total"] -= amt
            self._st.balances[quote]["free"] += proceeds
            self._st.balances[quote]["total"] += proceeds

        # формируем ответ
        order_id = f"backtest-{int(time.time()*1000)}"
        res = {
            "id": order_id,
            "clientOrderId": client_order_id,
            "symbol": sym,
            "type": typ,
            "side": sd,
            "status": "closed",
            "filled": amt,
            "price": exec_price,
            "cost": exec_price * amt,
            "fee": {"currency": quote, "cost": fee, "rate": self._st.fee_pct},
            "timestamp": _now_ms(),
        }
        metrics.inc("broker_requests_total", _labels("create_order") | {"code": "200"})
        return res

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        # «ожидающих» ордеров в этой реализации нет
        metrics.inc("broker_requests_total", _labels("cancel_order") | {"code": "200"})
        return {"id": order_id, "status": "canceled", "timestamp": _now_ms()}

    def fetch_balance(self) -> Dict[str, Any]:
        free = {k: round(v["free"], 12) for k, v in self._st.balances.items()}
        total = {k: round(v["total"], 12) for k, v in self._st.balances.items()}
        used = {k: round(total[k] - free[k], 12) for k in total.keys()}
        metrics.inc("broker_requests_total", _labels("fetch_balance") | {"code": "200"})
        return {"free": free, "used": used, "total": total}

    # ─────────────────────────── дополнительные API ───────────────────────────
    # не часть ExchangeInterface, но удобно для бэктест-раннера

    def advance(self, steps: int = 1) -> int:
        """
        Сдвинуть курсор на N баров вперёд. Возвращает новый индекс курсора.
        """
        self._st.cursor = min(self._st.cursor + int(steps), len(self._st.df) - 1)
        return self._st.cursor

    def set_cursor(self, idx_or_ts: Union[int, float, int]) -> int:
        """
        Установить курсор по индексу или timestamp (ms/seconds).
        """
        if isinstance(idx_or_ts, int) and 0 <= idx_or_ts < len(self._st.df):
            self._st.cursor = idx_or_ts
            return self._st.cursor

        ts = int(idx_or_ts)
        # если похоже на секунды → переведём в миллисекунды
        if ts < 10**12:
            ts *= 1000

        # бинарный поиск по времени
        s = self._st.df["_ts_ms_"].values
        lo, hi = 0, len(s) - 1
        pos = hi
        while lo <= hi:
            mid = (lo + hi) // 2
            if s[mid] <= ts:
                pos = mid
                lo = mid + 1
            else:
                hi = mid - 1
        self._st.cursor = int(pos)
        return self._st.cursor
