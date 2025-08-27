## `reconcile.py`
from __future__ import annotations
from typing import Optional
from ..events.bus import AsyncEventBus
from ..events import topics
from ..brokers.base import IBroker
from ..storage.facade import Storage
from crypto_ai_bot.utils.logging import get_logger
_log = get_logger("use_cases.reconcile")
async def reconcile(
    *,
    symbol: str,
    storage: Storage,
    broker: IBroker,
    bus: Optional[AsyncEventBus] = None,
) -> int:
    """Минимальная сверка состояния: на текущем этапе просто подтверждает доступность
    брокера и обновляет последний тикер в репозитории, эмитя событие по завершении.
    Возвращает 1 при успешном пинге брокера и обновлении снапшота, иначе 0.
    """
    try:
        t = await broker.fetch_ticker(symbol)
        storage.market_data.store_ticker(t)
        if bus:
            await bus.publish(topics.RECONCILIATION_COMPLETED, {"symbol": symbol, "ts_ms": t.timestamp}, key=symbol)
        return 1
    except Exception as exc:
        _log.error("reconcile_error", extra={"symbol": symbol, "error": str(exc)})
        return 0
### Мини-пример интеграции (backtest)
from decimal import Decimal
from crypto_ai_bot.core.events.bus import AsyncEventBus
from crypto_ai_bot.core.brokers.backtest_exchange import BacktestExchange
from crypto_ai_bot.core.storage.sqlite_adapter import connect
from crypto_ai_bot.core.storage.migrations.runner import run_migrations
from crypto_ai_bot.core.storage.facade import Storage
from crypto_ai_bot.core.use_cases.eval_and_execute import eval_and_execute
conn = connect("/tmp/crypto_ai_bot.db")
run_migrations(conn, now_ms=0)
storage = Storage.from_connection(conn)
bus = AsyncEventBus()
price = Decimal("68000")
be = BacktestExchange(symbol="BTC/USDT", balances={"USDT": Decimal("1000")}, price_feed=lambda: price)
res = await eval_and_execute(
    symbol="BTC/USDT",
    storage=storage,
    broker=be,
    bus=bus,
    exchange="gateio",
    fixed_quote_amount=Decimal("100"),
    idempotency_bucket_ms=60_000,
    idempotency_ttl_sec=60,
    force_action="buy",
)
print(res)
**Совместимость и расширяемость:** интерфейсы не будут меняться при добавлении сигналов/риска/exit‑логики на следующем шаге: мы просто подключим `risk_manager` и `protective_exits` в уже предусмотренные точки.