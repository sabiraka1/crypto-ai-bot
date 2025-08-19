from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Optional, Tuple, Dict, Any


# ---------- ccxt market meta ----------

def _market_meta(broker: Any, symbol: str) -> Dict[str, Any]:
    """
    Берём спецификации рынка из ccxt: precision/limits.
    Не требует дополнительных модулей.
    """
    m = getattr(getattr(broker, "ccxt", broker), "markets", {}).get(symbol, {}) or {}
    prec = (m.get("precision") or {})
    lims = (m.get("limits") or {})
    amt = lims.get("amount") or {}
    cost = lims.get("cost") or {}
    return {
        "amount_precision": prec.get("amount"),
        "price_precision": prec.get("price"),
        "amount_min": amt.get("min"),
        "amount_max": amt.get("max"),
        "min_notional": cost.get("min"),
        "max_notional": cost.get("max"),
    }


# ---------- helpers: quantization & minimum checks ----------

def quantize_amount(qty: float, market: Dict[str, Any], *, side: str = "buy") -> float:
    """
    Квантование объёма по precision.amount.
    Для BUY — округляем вниз (не превысить бюджет),
    Для SELL — округляем вниз (чтобы не «перепродать» из-за точности).
    """
    out = float(qty or 0.0)
    p = market.get("amount_precision")
    if p is None:
        return max(0.0, out)

    step = Decimal(1).scaleb(-int(p))
    d = Decimal(str(out))
    # SELL иногда округляют UP, чтобы гарантировать полную распродажу.
    # Но надёжнее — ROUND_DOWN и подрезка «хвоста» → не вылезем за доступный баланс.
    out = float(d.quantize(step, rounding=ROUND_DOWN))
    return max(0.0, out)


def validate_minimums(*, price: float, amount: float, market: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[float]]:
    """
    Проверяем минимальные ограничения:
      - min_amount (минимальный объём base)
      - min_notional (минимальная «стоимость» сделки в quote)
    Возвращает: (ok, reason, need)
    """
    amt_min = market.get("amount_min")
    if amt_min is not None and amount < float(amt_min):
        return False, "min_amount", float(amt_min)

    min_notional = market.get("min_notional")
    if min_notional is not None:
        notional = float(price) * float(amount)
        if notional < float(min_notional):
            return False, "min_notional", float(min_notional)

    return True, None, None


# ---------- sizing (legacy) ----------

def _cfg_position_size_usd(cfg: Any) -> Decimal:
    """
    Поддерживаем оба имени поля: каноническое и историческое.
    """
    v = getattr(cfg, "POSITION_SIZE_USD", None)
    if v is None:
        v = getattr(cfg, "POSITION_SIZE", None)
    if v is None:
        v = getattr(cfg, "TRADE_AMOUNT", 10.0)
    return Decimal(str(v))


def compute_qty_for_notional(cfg: Any, *, side: str, price: float) -> float:
    """
    Упрощённый расчёт base-qty по бюджету, без учёта market limits/precision.
    Оставлено для обратной совместимости со старым кодом/бэктестами.
    """
    notional = _cfg_position_size_usd(cfg)
    fee_bps = Decimal(str(getattr(cfg, "FEE_TAKER_BPS", 10)))
    slip_bps = Decimal(str(getattr(cfg, "SLIPPAGE_BPS", 5)))

    eff_price = Decimal(str(price)) * (Decimal(1) + slip_bps / Decimal(10_000))
    budget = notional * (Decimal(1) - fee_bps / Decimal(10_000))
    if eff_price <= 0:
        return 0.0
    qty = (budget / eff_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    return float(qty)


# ---------- sizing (market-aware) ----------

def compute_qty_for_notional_market(
    cfg: Any,
    *,
    side: str,
    price: float,
    market: Dict[str, Any],
) -> Tuple[float, Optional[str], Optional[float]]:
    """
    Расчёт base-qty с учётом комиссии, слиппеджа, precision и лимитов рынка.

    Возвращает (qty, err_reason, err_needed):
      - qty > 0 и err_reason is None — всё ок
      - qty == 0 и err_reason — не проходим ограничения
        (err_reason в {"min_amount", "min_notional"}, err_needed — требуемый минимум)

    NOTE: для Gate.io MARKET BUY реальный order.amount = QUOTE-сумма (USDT).
    Эта функция считает base-qty для риск-оценки; для ордера используй quote-бюджет,
    см. `compute_quote_cost_for_market_buy`.
    """
    notional = _cfg_position_size_usd(cfg)
    fee_bps = Decimal(str(getattr(cfg, "FEE_TAKER_BPS", 10)))
    slip_bps = Decimal(str(getattr(cfg, "SLIPPAGE_BPS", 5)))

    eff_price = Decimal(str(price)) * (Decimal(1) + slip_bps / Decimal(10_000))
    if eff_price <= 0:
        return 0.0, "no_price", None

    budget = notional * (Decimal(1) - fee_bps / Decimal(10_000))
    qty_raw = budget / eff_price

    # квантование по precision.amount
    qty_q = quantize_amount(float(qty_raw), market, side=side)

    if qty_q <= 0:
        # невозможно пройти из-за дискретности лота
        need = float(market.get("amount_min") or 0.0)
        return 0.0, "min_amount", need if need > 0 else None

    ok, reason, need = validate_minimums(price=float(eff_price), amount=qty_q, market=market)
    if not ok:
        return 0.0, reason, need

    return qty_q, None, None


# ---------- quote-cost для Gate.io MARKET BUY ----------

def compute_quote_cost_for_market_buy(cfg: Any) -> float:
    """
    Для Gate.io MARKET BUY поле amount — это сумма в QUOTE (например, USDT).
    Возвращает безопасный budget с учётом комиссии.
    """
    notional = _cfg_position_size_usd(cfg)
    fee_bps = Decimal(str(getattr(cfg, "FEE_TAKER_BPS", 10)))
    budget = notional * (Decimal(1) - fee_bps / Decimal(10_000))
    return float(budget)
