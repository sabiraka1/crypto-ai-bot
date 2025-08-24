import pytest
from crypto_ai_bot.core.reconciliation import OrdersReconciler, PositionsReconciler, BalancesReconciler

@pytest.mark.anyio
async def test_reconcilers_run_once(container):
    sym = container.settings.SYMBOL

    ors = OrdersReconciler(storage=container.storage, broker=container.broker, symbol=sym)
    prs = PositionsReconciler(storage=container.storage, exits=container.exits, symbol=sym)
    bls = BalancesReconciler(broker=container.broker)

    # все должны отработать без исключений
    await ors.run_once()
    await prs.run_once()
    await bls.run_once()
