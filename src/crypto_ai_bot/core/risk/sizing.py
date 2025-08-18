# src/crypto_ai_bot/core/risk/sizing.py
from decimal import Decimal

def compute_qty_for_notional(cfg, *, side: str, price: float) -> float:
    """
    Возвращает qty для покупки на фиксированную сумму (TRADE_AMOUNT),
    учитывая такерскую комиссию и проскальзывание.
    Совместимость: если нет настроек, берём безопасные дефолты.
    """
    notional = Decimal(str(getattr(cfg, "TRADE_AMOUNT", 10.0)))
    fee_bps = Decimal(str(getattr(cfg, "FEE_TAKER_BPS", 10)))  # 0.10% по умолчанию
    slip_bps = Decimal(str(getattr(cfg, "SLIPPAGE_BPS", 5)))   # 0.05% по умолчанию

    eff_price = Decimal(str(price)) * (Decimal(1) + slip_bps / Decimal(10_000))
    # На входе платим комиссию; чтобы не превысить notional, закладываем её заранее
    budget = notional * (Decimal(1) - fee_bps / Decimal(10_000))
    qty = (budget / eff_price).quantize(Decimal("0.00000001"))  # 8 знаков как безопасный дефолт
    return float(qty)
