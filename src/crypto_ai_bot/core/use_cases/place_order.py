# src/crypto_ai_bot/core/use_cases/place_order.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from crypto_ai_bot.utils.time import now_ms
from crypto_ai_bot.utils.logging import get_logger

logger = get_logger(__name__)

# TypedDict-и вы уже добавляли ранее; оставлю минимальные type hints через Dict[str, Any]
OrderResult = Dict[str, Any]


def _buy_quote_budget(notional_usd: Decimal, fee_bps: int) -> Decimal:
    # вычитаем комиссию, чтобы хватало на market buy (Gate.io)
    fee = (notional_usd * Decimal(fee_bps)) / Decimal(10_000)
    return notional_usd - fee


async def place_order(
    *,
    broker,
    trades_repo,
    positions_repo,
    idempotency_repo,
    audit_repo,
    settings,
    symbol: str,
    side: str,               # "buy" | "sell"
    notional_usd: Optional[Decimal] = None,  # для BUY
    qty: Optional[Decimal] = None,           # для SELL
    expected_price: Optional[Decimal] = None,
    idempotency_key: str,
) -> OrderResult:
    """
    Единая точка исполнения:
      - бронь идемпотентности (TTL внутри репозитория)
      - market BUY: сумма в котируемой валюте (Gate.io), с учётом комиссии
      - market SELL: реальный объём позиции, округлённый по лимитам (ожидается вне — в use-case перед вызовом)
      - create_order вызывает БРОКЕР; именно он генерит clientOrderId (CID) по idempotency_key
      - коммит идемпотентности после успешного возврата брокера
    """
    # 1) бронь идемпотентности
    if not idempotency_repo.check_and_store(idempotency_key):
        logger.info("place_order duplicate blocked: %s", idempotency_key)
        return {"status": "duplicate", "idem_key": idempotency_key}

    try:
        if side == "buy":
            if notional_usd is None:
                raise ValueError("notional_usd is required for BUY")
            fee_bps = int(getattr(settings, "FEE_BPS", 20))
            quote_cost = _buy_quote_budget(notional_usd, fee_bps)
            res = await broker.create_order(
                symbol=symbol,
                type="market",
                side="buy",
                amount=float(quote_cost),  # Gate.io: сумма в quote
                price=None,
                params={},
                idempotency_key=idempotency_key,  # CID делает брокер
            )
        elif side == "sell":
            if qty is None:
                raise ValueError("qty is required for SELL")
            res = await broker.create_order(
                symbol=symbol,
                type="market",
                side="sell",
                amount=float(qty),
                price=None,
                params={},
                idempotency_key=idempotency_key,  # CID делает брокер
            )
        else:
            raise ValueError(f"unsupported side: {side}")

        # 2) запись pending → done / обновления в trades_repo обычно делают выше по стеку (reconcile)
        #     здесь зафиксируем аудит
        audit_repo.log(
            kind="order_submitted",
            payload={
                "symbol": symbol,
                "side": side,
                "expected_price": str(expected_price) if expected_price is not None else None,
                "idem_key": idempotency_key,
                "exchange_order": res,
            },
        )

        # 3) коммит идемпотентности — защита от повторов после успеха
        idempotency_repo.commit(idempotency_key)

        return {"status": "submitted", "order": res, "idem_key": idempotency_key}

    except Exception as e:
        logger.exception("place_order failed: %s", e)
        # при ошибке — можно пометить ключ как failed или оставить с TTL, чтобы повторить позже
        return {"status": "error", "error": str(e), "idem_key": idempotency_key}
