# src/crypto_ai_bot/backtest/runner.py
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from crypto_ai_bot.backtest.csv_loader import load_ohlcv_csv
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.use_cases.evaluate import evaluate
from crypto_ai_bot.core.use_cases.place_order import place_order
from crypto_ai_bot.core.risk.manager import RiskManager
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.uow import SqliteUnitOfWork
from crypto_ai_bot.core.storage.repositories.positions import SqlitePositionRepository
from crypto_ai_bot.core.storage.repositories.trades import SqliteTradeRepository
from crypto_ai_bot.core.storage.repositories.audit import SqliteAuditRepository
from crypto_ai_bot.core.storage.repositories.idempotency import SqliteIdempotencyRepository
from crypto_ai_bot.utils import metrics

# для оценки DD переиспользуем расчёт из risk.rules
try:
    from crypto_ai_bot.core.risk.rules import _max_drawdown_from_pnls as _dd_from_pnls  # type: ignore
except Exception:
    def _dd_from_pnls(pnls: List[float]) -> float:  # fallback
        eq, s, mdd, peak = [], 0.0, 0.0, 0.0
        for p in pnls:
            try:
                s += float(p); eq.append(s)
            except Exception:
                continue
        for v in eq:
            if v > peak: peak = v
            dd = (peak - v)
            if peak != 0: mdd = max(mdd, (dd / abs(peak)) * 100.0)
        return mdd


class _SeriesBroker:
    """
    Мини-брокер для бэктеста поверх готовой серии OHLCV.
    Реализованы методы: fetch_ohlcv, fetch_ticker, fetch_order_book.
    Учитывает проскальзывание/комиссию через _pending_side, установленный раннером.
    """
    def __init__(
        self,
        symbol: str,
        timeframe: str,
        ohlcv: List[List[float]],
        *,
        spread_bps: float = 5.0,
        slippage_bps: float = 0.0,
        fee_bps: float = 0.0,
        fee_fixed: float = 0.0,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self._data = ohlcv
        self._i = 0
        self._book_spread = float(spread_bps) / 10_000.0
        self._slip = float(slippage_bps) / 10_000.0
        self._fee_bps = float(fee_bps) / 10_000.0
        self._fee_fixed = float(fee_fixed)
        self._pending_side: Optional[str] = None
        self._pending_size: Optional[float] = None
        self._last_exec_price: float = 0.0

    def set_index(self, i: int) -> None:
        self._i = max(0, min(i, len(self._data) - 1))

    def set_pending_side(self, side: Optional[str], size: Optional[float]) -> None:
        self._pending_side = (side or "").lower() if side else None
        try:
            self._pending_size = float(size) if size is not None else None
        except Exception:
            self._pending_size = None

    @property
    def last_exec_price(self) -> float:
        return self._last_exec_price

    # --- интерфейс, используемый стратегией ---
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        if symbol != self.symbol or timeframe != self.timeframe:
            raise ValueError("symbol/timeframe mismatch")
        if self._i <= 0:
            return self._data[: max(0, limit)]
        start = max(0, self._i - int(limit) + 1)
        return self._data[start : self._i + 1]

    def _mid(self) -> float:
        return float(self._data[self._i][4]) if self._data else 0.0

    def fetch_ticker(self, symbol: str) -> Dict[str, float]:
        if symbol != self.symbol:
            raise ValueError("symbol mismatch")
        mid = self._mid()
        half = mid * self._book_spread / 2.0
        bid = mid - half
        ask = mid + half

        # вычисляем "исполнительную" цену под side (если есть)
        px = mid
        side = self._pending_side
        size = self._pending_size or 0.0
        if side == "buy":
            px = ask
            # проскальзывание/комиссии
            px = px * (1.0 + self._slip) * (1.0 + self._fee_bps)
            if size > 0 and self._fee_fixed > 0:
                px += (self._fee_fixed / size)
        elif side == "sell":
            px = bid
            px = px * (1.0 - self._slip) * (1.0 - self._fee_bps)
            if size > 0 and self._fee_fixed > 0:
                px -= (self._fee_fixed / size)

        self._last_exec_price = float(px)
        return {"last": float(px), "bid": float(bid), "ask": float(ask)}

    def fetch_order_book(self, symbol: str) -> Dict[str, List[List[float]]]:
        t = self.fetch_ticker(symbol)
        bid, ask = float(t["bid"]), float(t["ask"])
        return {
            "bids": [[bid, 1.0], [bid * 0.999, 1.0]],
            "asks": [[ask, 1.0], [ask * 1.001, 1.0]],
        }


class _DummyBus:
    def publish(self, event: Dict[str, Any]) -> None:
        pass
    def subscribe(self, type_: str, handler) -> None:
        pass
    def health(self) -> Dict[str, Any]:
        return {"dlq_size": 0, "status": "ok"}


@dataclass
class BacktestReport:
    symbol: str
    timeframe: str
    bars: int
    trades: int
    total_pnl: float
    max_drawdown_pct: float
    win_rate_pct: float
    equity_series: List[float]           # кумулятивная доходность
    closed_pnls: List[float]             # последовательность PnL по закрытым сделкам
    meta: Dict[str, Any]


def _collect_closed_pnls(trades_repo: Any, cap: int = 100000) -> List[float]:
    try:
        if hasattr(trades_repo, "last_closed_pnls"):
            vals = trades_repo.last_closed_pnls(cap)  # type: ignore
            return [float(x) for x in (vals or []) if x is not None]
    except Exception:
        pass
    return []


def _export_trades_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    if not path:
        return
    fields = ["ts_ms", "bar_index", "symbol", "timeframe", "action", "qty", "price", "equity_cum"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})


def run_backtest_from_csv(
    cfg: Settings,
    *,
    csv_path: str,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    lookback: Optional[int] = None,
    spread_bps: float = 5.0,
    slippage_bps: float = 0.0,
    fee_bps: float = 0.0,
    fee_fixed: float = 0.0,
    db_path: Optional[str] = None,
    export_trades_path: Optional[str] = None,
) -> BacktestReport:
    sym = symbol or getattr(cfg, "SYMBOL", "BTC/USDT")
    tf = timeframe or getattr(cfg, "TIMEFRAME", "1h")
    lb = int(lookback or getattr(cfg, "LOOKBACK_LIMIT", getattr(cfg, "LIMIT_BARS", 300)) or 300)

    data = load_ohlcv_csv(csv_path)
    if len(data) < max(5, lb):
        raise ValueError(f"Not enough rows in CSV ({len(data)}) for lookback={lb}")

    dbp = db_path or ":memory:"
    con = connect(dbp)

    class _Repos:
        def __init__(self, con_):
            self.positions = SqlitePositionRepository(con_)
            self.trades = SqliteTradeRepository(con_)
            self.audit = SqliteAuditRepository(con_)
            self.uow = SqliteUnitOfWork(con_)
            self.idempotency = SqliteIdempotencyRepository(con_)
            self.decisions = None
    repos = _Repos(con)

    broker = _SeriesBroker(
        sym, tf, data,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        fee_fixed=fee_fixed,
    )
    bus = _DummyBus()
    rm = RiskManager(cfg, broker=broker, positions_repo=repos.positions, trades_repo=repos.trades, http=None)

    executed = 0
    trade_rows: List[Dict[str, Any]] = []
    equity_cum = 0.0

    for i in range(lb - 1, len(data)):
        broker.set_index(i)

        # 1) evaluate
        d = evaluate(cfg, broker, symbol=sym, timeframe=tf, limit=lb)
        action = str(d.get("action", "hold")).lower()
        if action not in ("buy", "sell"):
            continue

        # 2) risk
        risk = rm.evaluate(symbol=sym, action=action)
        if not risk.get("ok", True):
            continue

        # 3) side-aware fill pricing
        size = d.get("size")
        try:
            qty = float(size) if size is not None else 0.0
        except Exception:
            qty = 0.0
        broker.set_pending_side(action, qty)

        # 4) place
        out = place_order(
            cfg,
            broker,
            positions_repo=repos.positions,
            trades_repo=repos.trades,
            audit_repo=repos.audit,
            uow=repos.uow,
            decision=d,
            symbol=sym,
            bus=bus,
            idem_repo=repos.idempotency,
        )
        if str(out.get("status")) == "executed":
            executed += 1

            # обновим кумулятивную доходность
            pnls = _collect_closed_pnls(repos.trades)
            equity_cum = sum(pnls) if pnls else 0.0

            # лог в CSV
            trade_rows.append({
                "ts_ms": int(data[i][0]),
                "bar_index": i,
                "symbol": sym,
                "timeframe": tf,
                "action": action,
                "qty": d.get("size"),
                "price": broker.last_exec_price,
                "equity_cum": equity_cum,
            })

    pnls = _collect_closed_pnls(repos.trades)
    total = sum(pnls) if pnls else 0.0
    # кумулятив
    cum, s = [], 0.0
    for p in pnls:
        s += float(p)
        cum.append(s)
    dd = _dd_from_pnls(pnls)
    if pnls:
        wins = sum(1 for x in pnls if x > 0)
        wr = 100.0 * wins / len(pnls)
    else:
        wr = 0.0

    # экспорт CSV (если задан)
    if export_trades_path:
        _export_trades_csv(export_trades_path, trade_rows)

    # запишем метрики (в реестр процесса)
    metrics.gauge("backtest_trades_total", float(executed))
    metrics.gauge("backtest_equity_last", float(cum[-1] if cum else 0.0))
    metrics.gauge("backtest_max_drawdown_pct", float(dd))

    return BacktestReport(
        symbol=sym,
        timeframe=tf,
        bars=len(data),
        trades=executed,
        total_pnl=float(total),
        max_drawdown_pct=float(dd),
        win_rate_pct=float(wr),
        equity_series=cum,
        closed_pnls=pnls,
        meta={
            "csv_path": csv_path,
            "lookback": lb,
            "spread_bps": float(spread_bps),
            "slippage_bps": float(slippage_bps),
            "fee_bps": float(fee_bps),
            "fee_fixed": float(fee_fixed),
            "db_path": dbp,
            "export_trades_path": export_trades_path,
        },
    )
