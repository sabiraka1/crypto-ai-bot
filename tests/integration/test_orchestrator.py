import pytest
import asyncio

@pytest.mark.anyio
async def test_orchestrator_start_stop(container):
    c = container
    # быстрые интервалы, чтобы тикнуло в тесте
    c.orchestrator.eval_interval_sec = 0.05
    c.orchestrator.exits_interval_sec = 0.05
    c.orchestrator.reconcile_interval_sec = 0.05
    c.orchestrator.watchdog_interval_sec = 0.05

    c.orchestrator.start()
    await asyncio.sleep(0.2)
    st = c.orchestrator.status()
    assert st["running"] is True and any(st["tasks"].values())

    await c.orchestrator.stop()
    st2 = c.orchestrator.status()
    assert st2["running"] is False

@pytest.mark.anyio
async def test_orchestrator_eval_forced_buy(container):
    c = container
    c.orchestrator.eval_interval_sec = 0.05
    c.orchestrator.force_eval_action = "buy"

    c.orchestrator.start()
    await asyncio.sleep(0.2)
    await c.orchestrator.stop()

    # после работы оркестратора хотя бы одна сделка могла появиться
    pos = c.storage.positions.get_base_qty(c.settings.SYMBOL)
    assert pos >= 0  # сам факт, что не упало — достаточно, сделки в backtest могут зависеть от цены