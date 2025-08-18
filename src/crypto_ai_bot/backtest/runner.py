# src/crypto_ai_bot/backtest/runner.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from crypto_ai_bot.backtest.csv_loader import load_ohlcv_csv
from crypto_ai_bot.core.settings import Settings
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute as uc_eval_and_execute
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
    """
    def __init__(self, symbol: str, timeframe: str, ohlcv: List[List[float]], *, spread_bps: float = 5.0) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self._data = ohlcv
        self._i = 0
        self._spread = float(spread_bps) / 10_000.0

    def set_index(self, i: int) -> None:
        self._i = max(0, min(i, len(self._data) - 1))

    # --- интерфейс, используемый стратегией ---
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[List[float]]:
        if symbol != self.symbol or timeframe != self.timeframe:
            # в рамках бэктеста работаем с одним инструментом/ТФ
            raise ValueError("symbol/timeframe mismatch")
        if self._i <= 0:
            return self._data[: max(0, limit)]
        start = max(0, self._i - int(limit) + 1)
        return self._data[start : self._i + 1]

    def fetch_ticker(self, symbol: str) -> Dict[str, float]:
        if symbol != self.symbol:
            raise ValueError("symbol mismatch")
        close = float(self._data[self._i][4]) if self._data else 0.0
        mid = close
        half = mid * self._spread / 2.0
        return {"last": close, "bid": mid - half, "ask": mid + half}

    def fetch_order_book(self, symbol: str) -> Dict[str, List[List[float]]]:
        t = self.fetch_ticker(symbol)
        bid, ask = float(t["bid"]), float(t["ask"])
        # легкий стакан
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
    # Предпочитаем last_closed_pnls
    try:
        if hasattr(trades_repo, "last_closed_pnls"):
            vals = trades_repo.last_closed_pnls(cap)  # type: ignore
            return [float(x) for x in (vals or []) if x is not None]
    except Exception:
        pass
    # Фоллбек — пусто: репорт всё равно будет валиден
    return []


def run_backtest_from_csv(
    cfg: Settings,
    *,
    csv_path: str,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    lookback: Optional[int] = None,
    spread_bps: float = 5.0,
    db_path: Optional[str] = None,
) -> BacktestReport:
    sym = symbol or getattr(cfg, "SYMBOL", "BTC/USDT")
    tf = timeframe or getattr(cfg, "TIMEFRAME", "1h")
    lb = int(lookback or getattr(cfg, "LOOKBACK_LIMIT", getattr(cfg, "LIMIT_BARS", 300)) or 300)

    data = load_ohlcv_csv(csv_path)
    if len(data) < max(5, lb):
        raise ValueError(f"Not enough rows in CSV ({len(data)}) for lookback={lb}")

    # БД: отдельный путь, чтобы не трогать «рабочую»
    dbp = db_path or ":memory:"
    con = connect(dbp)

    # Репозитории (как в server._Repos)
    class _Repos:
        def __init__(self, con_):
            self.positions = SqlitePositionRepository(con_)
            self.trades = SqliteTradeRepository(con_)
            self.audit = SqliteAuditRepository(con_)
            self.uow = SqliteUnitOfWork(con_)
            self.idempotency = SqliteIdempotencyRepository(con_)
            self.decisions = None
    repos = _Repos(con)

    # Брокер и шина
    broker = _SeriesBroker(sym, tf, data, spread_bps=spread_bps)
    bus = _DummyBus()

    # Прогон
    executed = 0
    for i in range(lb - 1, len(data)):
        broker.set_index(i)
        out = uc_eval_and_execute(cfg, broker, repos, symbol=sym, timeframe=tf, limit=lb, bus=bus, http=None)
        if str(out.get("status")) == "ok" and out.get("order", {}).get("status") == "executed":
            executed += 1

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
            "db_path": dbp,
        },
    )
