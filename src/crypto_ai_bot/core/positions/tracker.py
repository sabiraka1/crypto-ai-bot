from __future__ import annotations
from typing import Dict, Any, Optional, Iterable
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone, timedelta

# --- Lightweight data adapters (duck-typing) ----------------------------------

@dataclass
class _TradeView:
    pnl: float
    ts: int  # ms

    @classmethod
    def from_obj(cls, obj: Any) -> "_TradeView":
        # Accept common attribute names
        pnl = getattr(obj, "pnl", None)
        if pnl is None:
            pnl = getattr(obj, "pnl_usd", None)
        if pnl is None:
            pnl = getattr(obj, "profit", None)
        if pnl is None:
            pnl = getattr(obj, "profit_usd", None)
        if pnl is None:
            pnl = getattr(obj, "pnl_amount", 0.0)
        try:
            pnl = float(pnl)
        except Exception:
            pnl = 0.0

        ts = getattr(obj, "ts", None) or getattr(obj, "timestamp", None) or getattr(obj, "time", None)
        if ts is None:
            # fallback now
            ts = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        return cls(pnl=pnl, ts=int(ts))

@dataclass
class _PositionView:
    symbol: str
    size: Decimal

    @classmethod
    def from_obj(cls, obj: Any) -> "_PositionView":
        symbol = getattr(obj, "symbol", "") or getattr(obj, "pair", "")
        size = getattr(obj, "size", None) or getattr(obj, "amount", None) or 0
        try:
            size = Decimal(str(size))
        except Exception:
            size = Decimal(0)
        return cls(symbol=str(symbol), size=size)

# --- Core tracker --------------------------------------------------------------

class PnLTracker:
    """
    Собирает вычисляемый контекст для risk-правил и explain:
      - последовательность лоссов;
      - дневной дроудаун;
      - экспозиция в USD и %.
    Источники:
      - trades_repo: для seq_losses и дневного PnL;
      - positions_repo: для открытой экспозиции;
      - broker: для текущего equity/баланса и цены.
    Все зависимости опциональны — функции устойчивы к None.
    """
    def __init__(self, *, trades_repo=None, positions_repo=None, snapshots_repo=None, broker=None, cfg=None):
        self.trades_repo = trades_repo
        self.positions_repo = positions_repo
        self.snapshots_repo = snapshots_repo
        self.broker = broker
        self.cfg = cfg

    # ------------------------ helpers ------------------------

    @staticmethod
    def _start_of_utc_day_ms(now_ms: int) -> int:
        dt = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        sod = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
        return int(sod.timestamp() * 1000)

    def _list_recent_trades(self, limit: int = 200) -> list[_TradeView]:
        try:
            trades = self.trades_repo.list_recent(limit)  # type: ignore[attr-defined]
        except Exception:
            trades = []
        out: list[_TradeView] = []
        for t in trades or []:
            try:
                out.append(_TradeView.from_obj(t))
            except Exception:
                continue
        return out

    def _open_positions(self) -> list[_PositionView]:
        try:
            pos = self.positions_repo.get_open()  # type: ignore[attr-defined]
        except Exception:
            pos = []
        out: list[_PositionView] = []
        for p in pos or []:
            try:
                out.append(_PositionView.from_obj(p))
            except Exception:
                continue
        return out

    def _equity_usd(self) -> Optional[float]:
        # Try snapshots repo first (preferred, if present)
        try:
            if self.snapshots_repo is not None:
                eq = self.snapshots_repo.get_current_equity_usd()  # type: ignore[attr-defined]
                if eq is not None:
                    return float(eq)
        except Exception:
            pass
        # Fallback to broker balance
        try:
            if self.broker is not None:
                bal = self.broker.fetch_balance()  # ccxt-like
                # Try common fields
                for key in ("USDT", "USD", "total"):
                    v = bal.get("total", {}).get(key) if key != "total" else bal.get("total")
                    if isinstance(v, dict):
                        # guess approximate equity as sum
                        eq = sum(float(x or 0) for x in v.values())
                        if eq > 0:
                            return eq
                    else:
                        try:
                            eq = float(v)
                            if eq > 0:
                                return eq
                        except Exception:
                            continue
        except Exception:
            pass
        return None

    # ------------------------ public API ---------------------

    def consecutive_losses(self, *, lookback: int = 50) -> Optional[int]:
        trades = self._list_recent_trades(lookback)
        if not trades:
            return None
        cnt = 0
        for t in reversed(trades):
            if t.pnl < 0:
                cnt += 1
            else:
                break
        return cnt

    def day_drawdown_pct(self) -> Optional[float]:
        # Approach: need today's starting equity and current equity.
        start_equity = None
        try:
            if self.snapshots_repo is not None:
                start_equity = self.snapshots_repo.get_today_start_equity_usd()  # type: ignore[attr-defined]
        except Exception:
            start_equity = None
        if start_equity is None:
            return None  # no stable baseline → skip rule, return None

        current = self._equity_usd()
        if current is None or start_equity <= 0:
            return None
        dd = max(0.0, (start_equity - current) / start_equity * 100.0)
        return dd

    def exposure(self, *, symbol: str, price: float) -> tuple[Optional[float], Optional[float]]:
        """
        Returns (exposure_usd, exposure_pct) — both optional if sources unknown.
        """
        exp_usd = 0.0
        positions = self._open_positions()
        if positions:
            for p in positions:
                try:
                    if p.symbol and p.size:
                        exp_usd += abs(float(p.size) * float(price))
                except Exception:
                    continue
        else:
            # if no repo, we cannot infer; return None to avoid wrong blocks
            return None, None

        equity = self._equity_usd()
        exp_pct = (exp_usd / equity * 100.0) if equity and equity > 0 else None
        return exp_usd if exp_usd > 0 else 0.0, exp_pct

# ------------------------ top-level helper ---------------------

def enrich_context(*, cfg, broker, features: Dict[str, Any], trades_repo=None, positions_repo=None, snapshots_repo=None) -> Dict[str, Any]:
    """
    Computes context fields and merges them into features['context'].
    Safe to call with repos=None — only fields with available data will be filled.
    Returns updated context dict (also mutates features in-place).
    """
    ctx = dict(features.get("context") or {})
    price = float((features.get("market") or {}).get("price") or 0.0)
    symbol = str(features.get("symbol") or cfg.SYMBOL)

    tracker = PnLTracker(trades_repo=trades_repo, positions_repo=positions_repo, snapshots_repo=snapshots_repo, broker=broker, cfg=cfg)

    # seq_losses
    try:
        ctx["seq_losses"] = tracker.consecutive_losses()
    except Exception:
        pass

    # day drawdown
    try:
        ctx["day_drawdown_pct"] = tracker.day_drawdown_pct()
    except Exception:
        pass

    # exposure
    try:
        exp_usd, exp_pct = tracker.exposure(symbol=symbol, price=price)
        ctx["exposure_usd"] = exp_usd
        ctx["exposure_pct"] = exp_pct
    except Exception:
        pass

    features["context"] = ctx
    return ctx
