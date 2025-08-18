# src/crypto_ai_bot/backtest/runner.py
"""
Единый раннер бэктеста:

- Загружает CSV с OHLCV (ts,open,high,low,close,volume).
- Считает индикаторы через core.indicators.unified.
- Прогоняет стратегию (по умолчанию — RSI/MACD-демо).
- Исполняет сделки через core.brokers.backtest_exchange.BacktestExchange.
- Возвращает сводку результатов + опционально трейды и equity-кривую.

Сводка:
{
  'trades': int, 'wins': int, 'losses': int, 'win_rate': float,
  'final_equity': float, 'pnl': float, 'max_drawdown': float,
  'trades_list': [ ... ],     # если collect_trades=True
  'equity_curve': [ ... ]     # если collect_equity=True
}
"""

from typing import List, Dict, Any, Optional
from types import SimpleNamespace
import csv

from crypto_ai_bot.core.indicators.unified import compute_all
from crypto_ai_bot.core.brokers.backtest_exchange import BacktestExchange, BacktestFees
from crypto_ai_bot.core.risk.sizing import compute_qty_for_notional


def load_ohlcv_csv(path: str) -> List[List[float]]:
    out: List[List[float]] = []
    with open(path, "r", newline="") as f:
        rd = csv.reader(f)
        header = next(rd, None)
        for row in rd:
            if not row or len(row) < 5:
                continue
            ts = float(row[0])
            o = float(row[1]); h = float(row[2]); l = float(row[3]); c = float(row[4])
            v = float(row[5]) if len(row) > 5 and row[5] != "" else 0.0
            out.append([ts, o, h, l, c, v])
    return out


class BasicRSIMACDStrategy:
    """
    Демо-стратегия:
    - BUY, если RSI < 30 и MACD пересёк выше сигнальной (последние 2 бара).
    - SELL, если RSI > 70 или MACD пересёк ниже сигнальной.
    """
    def __init__(self, rsi_buy=30.0, rsi_sell=70.0):
        self.rsi_buy = rsi_buy
        self.rsi_sell = rsi_sell

    def on_bar(self, i: int, closes: List[float], ind: Dict[str, List[Optional[float]]], has_long: bool) -> Optional[str]:
        rsi = ind["rsi"][i]
        macd = ind["macd"][i]
        sig = ind["macd_signal"][i]
        macd_prev = ind["macd"][i-1] if i-1 >= 0 else None
        sig_prev  = ind["macd_signal"][i-1] if i-1 >= 0 else None
        if rsi is None or macd is None or sig is None or macd_prev is None or sig_prev is None:
            return None
        cross_up = macd_prev <= sig_prev and macd > sig
        cross_dn = macd_prev >= sig_prev and macd < sig
        if not has_long and rsi < self.rsi_buy and cross_up:
            return "buy"
        if has_long and (rsi > self.rsi_sell or cross_dn):
            return "sell"
        return None


def run_backtest(
    csv_path: str,
    *,
    symbol: str = "BTC/USDT",
    starting_cash: float = 1000.0,
    trade_amount: float = 10.0,
    fee_taker_bps: float = 10.0,
    slippage_bps: float = 5.0,
    strategy: Optional[BasicRSIMACDStrategy] = None,
    collect_trades: bool = False,
    collect_equity: bool = False
) -> Dict[str, Any]:
    ohlcv = load_ohlcv_csv(csv_path)
    if len(ohlcv) < 50:
        raise ValueError("Недостаточно данных для бэктеста")

    closes = [row[4] for row in ohlcv]
    ind = compute_all(closes)

    # Exchange
    fees = BacktestFees(taker_bps=fee_taker_bps, maker_bps=fee_taker_bps)
    ex = BacktestExchange(ohlcv=ohlcv, symbol=symbol, fees=fees)

    # Псевдо-конфиг для sizing
    cfg = SimpleNamespace(TRADE_AMOUNT=trade_amount, FEE_TAKER_BPS=fee_taker_bps, SLIPPAGE_BPS=slippage_bps)

    # State
    cash = float(starting_cash)
    position_qty = 0.0
    entry_price = 0.0

    trades_cnt = 0
    wins = 0
    losses = 0
    equity_peak = cash
    equity = cash

    trades_list: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []

    strat = strategy or BasicRSIMACDStrategy()

    lookback = max(26, 20, 15)  # slow, bb, rsi(14)+1
    i = 0
    while i < len(ohlcv):
        ts = int(ohlcv[i][0])
        if i < lookback:
            equity = cash + position_qty * closes[i]
            if collect_equity:
                equity_curve.append({"ts": ts, "equity": equity})
            i += 1
            ex.advance() if i < len(ohlcv) else None
            continue

        px = float(closes[i])
        has_long = position_qty > 0.0
        action = strat.on_bar(i, closes, ind, has_long)

        if action == "buy" and not has_long:
            qty = compute_qty_for_notional(cfg, side="buy", price=px)
            if qty > 0:
                o = ex.create_order(symbol=symbol, type="market", side="buy", amount=qty)
                fee = float(o["fee"]["cost"] if o.get("fee") else 0.0)
                cost = px * qty + fee
                if cost <= cash:
                    cash -= cost
                    position_qty += qty
                    entry_price = px
                    if collect_trades:
                        trades_list.append({"ts": ts, "side": "buy", "price": px, "qty": qty, "fee": fee})

        elif action == "sell" and has_long:
            qty = position_qty
            if qty > 0:
                o = ex.create_order(symbol=symbol, type="market", side="sell", amount=qty)
                fee = float(o["fee"]["cost"] if o.get("fee") else 0.0)
                proceeds = px * qty - fee
                cash += proceeds
                pnl_trade = (px - entry_price) * qty - fee
                trades_cnt += 1
                if pnl_trade >= 0:
                    wins += 1
                else:
                    losses += 1
                if collect_trades:
                    trades_list.append({"ts": ts, "side": "sell", "price": px, "qty": qty, "fee": fee, "pnl": pnl_trade})
                position_qty = 0.0
                entry_price = 0.0

        equity = cash + position_qty * px
        equity_peak = max(equity_peak, equity)
        if collect_equity:
            equity_curve.append({"ts": ts, "equity": equity})

        i += 1
        if i < len(ohlcv):
            ex.advance()

    # Финальное закрытие
    if position_qty > 0.0:
        ts = int(ohlcv[-1][0])
        px = float(closes[-1])
        fee = px * position_qty * (fee_taker_bps / 10_000.0)
        cash += px * position_qty - fee
        pnl_trade = (px - entry_price) * position_qty - fee
        trades_cnt += 1
        if pnl_trade >= 0:
            wins += 1
        else:
            losses += 1
        if collect_trades:
            trades_list.append({"ts": ts, "side": "sell", "price": px, "qty": position_qty, "fee": fee, "pnl": pnl_trade})
        position_qty = 0.0
        entry_price = 0.0
        equity = cash
        if collect_equity:
            equity_curve.append({"ts": ts, "equity": equity})

    pnl = equity - starting_cash
    dd = (equity_peak - equity) / equity_peak if equity_peak > 0 else 0.0

    out = {
        "trades": trades_cnt,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / trades_cnt) if trades_cnt > 0 else 0.0,
        "final_equity": equity,
        "pnl": pnl,
        "max_drawdown": dd
    }
    if collect_trades:
        out["trades_list"] = trades_list
    if collect_equity:
        out["equity_curve"] = equity_curve
    return out
