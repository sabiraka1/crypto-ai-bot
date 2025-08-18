from decimal import Decimal
from typing import Optional, Tuple, Dict, Any

from crypto_ai_bot.core.market_specs import quantize_amount, validate_minimums


def compute_qty_for_notional(cfg, *, side: str, price: float) -> float:
    """
    БЫЛО: базовый расчёт без знания рынка.
    Оставлено для совместимости со старым кодом (бэктест и т.д.).
    """
    notional = Decimal(str(getattr(cfg, "TRADE_AMOUNT", 10.0)))
    fee_bps = Decimal(str(getattr(cfg, "FEE_TAKER_BPS", 10)))
    slip_bps = Decimal(str(getattr(cfg, "SLIPPAGE_BPS", 5)))
    eff_price = Decimal(str(price)) * (Decimal(1) + slip_bps / Decimal(10_000))
    budget = notional * (Decimal(1) - fee_bps / Decimal(10_000))
    qty = (budget / eff_price).quantize(Decimal("0.00000001"))
    return float(qty)


def compute_qty_for_notional_market(
    cfg,
    *,
    side: str,
    price: float,
    market: Dict[str, Any]
) -> Tuple[float, Optional[str], Optional[float]]:
    """
    Новый расчёт: учитывает комиссию, проскальзывание, precision и лимиты рынка.
    Возвращает (qty, err_reason, err_needed):
      - qty > 0 без ошибок — готово
      - qty == 0 и err_reason — невозможно из-за min_amount/min_notional (err_needed подсказывает величину)
    """
    notional = Decimal(str(getattr(cfg, "TRADE_AMOUNT", 10.0)))
    fee_bps = Decimal(str(getattr(cfg, "FEE_TAKER_BPS", 10)))
    slip_bps = Decimal(str(getattr(cfg, "SLIPPAGE_BPS", 5)))

    eff_price = Decimal(str(price)) * (Decimal(1) + slip_bps / Decimal(10_000))
    budget = notional * (Decimal(1) - fee_bps / Decimal(10_000))
    qty_raw = (budget / eff_price)

    # квантование объёма по precision.amount (всегда вниз)
    qty_q = float(qty_raw)
    qty_q = quantize_amount(qty_q, market, side=side)

    if qty_q <= 0:
        # невозможно купить на такой бюджет при заданной точности
        return 0.0, "min_amount", float((market.get("limits") or {}).get("amount", {}).get("min") or 0.0)

    ok, reason, need = validate_minimums(price=float(eff_price), amount=qty_q, market=market)
    if not ok:
        # если не проходим лимиты — не поднимаем qty выше бюджета, возвращаем ошибку
        return 0.0, reason, need

    return qty_q, None, None
