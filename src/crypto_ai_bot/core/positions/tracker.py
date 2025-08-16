from __future__ import annotations
from typing import Any, Dict, Optional, List
from decimal import Decimal
from datetime import datetime, timezone

def _utc_hour() -> int:
    return int(datetime.now(tz=timezone.utc).hour)

def _get_price_from_ticker(t: Dict[str, Any]) -> Optional[float]:
    for k in ("last", "close", "price"):
        v = t.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    # some adapters may return nested structure
    try:
        return float(t.get("info", {}).get("last", None))
    except Exception:
        return None

def _spread_pct_from_ticker(t: Dict[str, Any]) -> Optional[float]:
    try:
        bid = t.get("bid")
        ask = t.get("ask")
        if bid and ask and bid > 0 and ask >= bid:
            return (ask - bid) / ((ask + bid) / 2.0) * 100.0
    except Exception:
        pass
    return None

def _safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

def _sum_abs(vs: List[float]) -> float:
    s = 0.0
    for v in vs:
        try:
            s += abs(float(v))
        except Exception:
            continue
    return s

def _fetch_equity_usd_from_balance(broker) -> Optional[float]:
    try:
        bal = broker.fetch_balance()
        # best-effort: many exchanges return total.USD or USDT
        for k in ("USD", "USDT", "USDC"):
            wallet = (bal.get("total") or {}).get(k) if isinstance(bal.get("total"), dict) else None
            if wallet is None and isinstance(bal, dict):
                wallet = bal.get(k, {}).get("total")
            if wallet:
                try:
                    return float(wallet)
                except Exception:
                    continue
        # fallback: try 'info'->'equity'
        info = bal.get("info") if isinstance(bal, dict) else None
        if info and "equity" in info:
            return float(info["equity"])
    except Exception:
        return None
    return None

def exposure_snapshot(cfg, broker, positions_repo=None, *, symbol: Optional[str]=None) -> Dict[str, Optional[float]]:
    """
    Возвращает оценку текущей экспозиции:
      - exposure_usd: суммарная номинальная стоимость открытых позиций по mark price
      - exposure_pct: если известен equity (из брокера или cfg.ACCOUNT_EQUITY_USD)
    Пытается использовать быстрый путь из репозитория (если реализован метод get_open_exposure_fast()).
    """
    # 1) быстрый путь через репозиторий (если есть)
    if positions_repo is not None and hasattr(positions_repo, "get_open_exposure_fast"):
        try:
            data = positions_repo.get_open_exposure_fast(symbol=symbol)  # type: ignore[attr-defined]
            exp_usd = _safe_float(data.get("exposure_usd"))
            exp_pct = _safe_float(data.get("exposure_pct"))
            if exp_usd is not None and exp_pct is not None:
                return {"exposure_usd": exp_usd, "exposure_pct": exp_pct}
        except Exception:
            pass

    # 2) универсальный путь: берём открытые позиции и текущую цену
    price = None
    try:
        t = broker.fetch_ticker(symbol or cfg.SYMBOL)
        price = _get_price_from_ticker(t)
    except Exception:
        price = None

    amounts: List[float] = []
    if positions_repo is not None and hasattr(positions_repo, "get_open"):
        try:
            opens = positions_repo.get_open()  # list of positions
            for p in opens or []:
                amt = p.get("amount") if isinstance(p, dict) else getattr(p, "amount", None)
                if amt is None:
                    continue
                amounts.append(float(amt))
        except Exception:
            pass

    exposure_usd = None
    if price and amounts:
        exposure_usd = _sum_abs([price * a for a in amounts])

    # equity
    equity = None
    # explicit cfg hint
    acc_eq = getattr(cfg, "ACCOUNT_EQUITY_USD", None)
    if acc_eq:
        equity = _safe_float(acc_eq)
    if equity is None:
        equity = _fetch_equity_usd_from_balance(broker)

    exposure_pct = None
    if exposure_usd is not None and equity and equity > 0:
        exposure_pct = exposure_usd / equity * 100.0

    return {"exposure_usd": exposure_usd, "exposure_pct": exposure_pct}

def seq_losses(trades_repo=None, limit: int = 20) -> Optional[int]:
    """
    Возвращает количество последних подряд убыточных сделок.
    Если у репозитория есть быстрый метод get_seq_losses_fast() — используем его.
    Иначе пытаемся прочитать недавние трейды и посчитать по полю pnl(usd).
    """
    if trades_repo is not None and hasattr(trades_repo, "get_seq_losses_fast"):
        try:
            return int(trades_repo.get_seq_losses_fast(limit=limit))  # type: ignore[attr-defined]
        except Exception:
            pass

    #\tfallback
    try:
        # ожидаем метод list_recent(limit) -> [{..., 'pnl_usd': float}|{'pnl': float}|...]
        recent = trades_repo.list_recent(limit=limit)  # type: ignore[attr-defined]
    except Exception:
        return None

    cnt = 0
    for tr in recent or []:
        pnl = tr.get("pnl_usd", tr.get("pnl", 0.0)) if isinstance(tr, dict) else getattr(tr, "pnl_usd", getattr(tr, "pnl", 0.0))
        try:
            pnl = float(pnl)
        except Exception:
            pnl = 0.0
        if pnl < 0:
            cnt += 1
        else:
            break
    return cnt

def day_drawdown_pct(trades_repo=None) -> Optional[float]:
    """
    Пытается вернуть текущий дневной дроудаун в % от equity (если доступно).
    Предпочитает метод репозитория get_pnl_summary(days=1) -> {'day_pnl_usd':..., 'equity_usd':...}
    """
    if trades_repo is not None and hasattr(trades_repo, "get_pnl_summary"):
        try:
            s = trades_repo.get_pnl_summary(days=1)  # type: ignore[attr-defined]
            pnl = _safe_float((s or {}).get("day_pnl_usd"))
            eq = _safe_float((s or {}).get("equity_usd"))
            if pnl is not None and eq and eq > 0:
                return pnl / eq * 100.0
        except Exception:
            pass
    return None

def build_context(cfg, broker, positions_repo=None, trades_repo=None) -> Dict[str, Optional[float]]:
    """Собирает контекст для explain: час, спред, экспозиция, дроудаун, последовательность лоссов."""
    try:
        t = broker.fetch_ticker(cfg.SYMBOL)
    except Exception:
        t = {}

    return {
        "hour": _utc_hour(),
        "spread_pct": _spread_pct_from_ticker(t),
        **exposure_snapshot(cfg, broker, positions_repo=positions_repo),
        "day_drawdown_pct": day_drawdown_pct(trades_repo),
        "seq_losses": seq_losses(trades_repo),
        "price": _get_price_from_ticker(t),
    }
