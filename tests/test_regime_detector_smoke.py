import types
from datetime import datetime, timezone
import pytest

from crypto_ai_bot.core.domain.macro.regime_detector import RegimeDetector
from crypto_ai_bot.core.domain.macro.types import RegimeState

class _FakeMacro:
    def __init__(self, value=100.0, change=0.0, meta=None):
        self._value = value
        self._change = change
        self._meta = meta or {}

    async def fetch_latest(self):
        obj = types.SimpleNamespace(
            value=self._value,
            change_pct=self._change,
            timestamp=datetime.now(timezone.utc),
            metadata=self._meta,
        )
        return obj

@pytest.mark.asyncio
async def test_regime_snapshot_basic(fake_event_bus, fake_metrics):
    d = RegimeDetector(
        dxy_source=_FakeMacro(100.0, -0.2),
        btc_dom_source=_FakeMacro(50.0, -0.3),
        fomc_source=_FakeMacro(meta={"next_event": datetime.now(timezone.utc).isoformat()}),
        event_bus=fake_event_bus,
        metrics=fake_metrics,
    )
    snap = await d.get_snapshot(force_refresh=True)
    assert snap.timestamp.tzinfo is not None
    assert isinstance(await d.get_regime(), RegimeState)
