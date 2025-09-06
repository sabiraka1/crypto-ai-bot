"""
Market regime detector based on macro indicators.

Determines market regime (risk_on / risk_small / neutral / risk_off)
based on DXY, BTC dominance, and FOMC events.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple

from crypto_ai_bot.core.application import events_topics as EVT
from crypto_ai_bot.core.application.ports import (
    EventBusPort,
    MacroDataPort,
    MetricsPort,
)
from crypto_ai_bot.core.domain.macro.types import (
    MacroSnapshot,
    RegimeConfig,
    RegimeState,
)
from crypto_ai_bot.core.infrastructure.settings import Settings
from crypto_ai_bot.utils.logging import get_logger

_log = get_logger(__name__)


class RegimeDetector:
    """
    4-level market regime detector based on macro indicators.

    Score range: -1.0 .. 1.0  →  states:
      - risk_on     (score > 0.5): full size
      - risk_small  (0 < score ≤ 0.5): 50% size
      - neutral     (-0.5 ≤ score ≤ 0): exits only
      - risk_off    (score < -0.5): full blocking
    """

    def __init__(
        self,
        *,
        dxy_source: Optional[MacroDataPort] = None,
        btc_dom_source: Optional[MacroDataPort] = None,
        fomc_source: Optional[MacroDataPort] = None,
        event_bus: Optional[EventBusPort] = None,
        metrics: Optional[MetricsPort] = None,
        settings: Optional[Settings] = None,
        config: Optional[RegimeConfig] = None,
    ) -> None:
        self._dxy = dxy_source
        self._btc_dom = btc_dom_source
        self._fomc = fomc_source
        self._event_bus = event_bus
        self._metrics = metrics

        self._settings = settings or Settings.load()
        self._config = config or self._create_config()

        # cache
        self._last_snapshot: Optional[MacroSnapshot] = None
        self._last_state: Optional[RegimeState] = None
        self._last_update: Optional[datetime] = None

        # validate config
        self._config.validate()

    # ---------- public API ----------

    async def get_snapshot(self, force_refresh: bool = False) -> MacroSnapshot:
        """
        Get current macro snapshot. Uses small TTL caching per update_interval_sec.
        """
        now = datetime.now(timezone.utc)

        if (
            not force_refresh
            and self._last_snapshot is not None
            and self._last_update is not None
        ):
            cache_age = (now - self._last_update).total_seconds()
            if cache_age < self._config.update_interval_sec:
                return self._last_snapshot

        # Always run 3 tasks in fixed order to avoid indexing bugs
        dxy_task = self._fetch_dxy() if self._dxy else self._empty()
        btc_task = self._fetch_btc_dom() if self._btc_dom else self._empty()
        fomc_task = self._fetch_fomc() if self._fomc else self._empty()

        dxy_data, btc_data, fomc_data = await asyncio.gather(
            dxy_task, btc_task, fomc_task, return_exceptions=False
        )

        # Build snapshot
        snapshot = MacroSnapshot(
            # DXY
            dxy_value=self._get_float(dxy_data, "value"),
            dxy_change_pct=self._get_float(dxy_data, "change_pct"),
            dxy_updated_at=self._get_dt(dxy_data, "updated_at"),
            # BTC Dominance
            btc_dom_value=self._get_float(btc_data, "value"),
            btc_dom_change_pct=self._get_float(btc_data, "change_pct"),
            btc_dom_updated_at=self._get_dt(btc_data, "updated_at"),
            # FOMC
            fomc_event_today=bool(fomc_data.get("event_today", False)),
            fomc_hours_until=self._get_int(fomc_data, "hours_until"),
            fomc_hours_since=self._get_int(fomc_data, "hours_since"),
            # timestamp
            timestamp=now,
        ).resolve_state(
            dxy_weight=self._config.dxy_weight,
            btc_dom_weight=self._config.btc_dom_weight,
            fomc_weight=self._config.fomc_weight,
            set_timestamp=False,  # already set to 'now'
        )

        # detect regime change
        if snapshot.state != self._last_state:
            prev = self._last_state.value if self._last_state else "unknown"
            _log.info(
                "regime_changed",
                extra={
                    "from": prev,
                    "to": snapshot.state.value if snapshot.state else "unknown",
                    "score": snapshot.score,
                    "dxy_change": self._get_float(dxy_data, "change_pct"),
                    "btc_dom_change": self._get_float(btc_data, "change_pct"),
                    "fomc_active": bool(fomc_data.get("event_today", False)),
                },
            )
            await self._on_regime_change(self._last_state, snapshot.state, snapshot)
            self._last_state = snapshot.state

        # update cache
        self._last_snapshot = snapshot
        self._last_update = now

        return snapshot

    async def get_regime(self, force_refresh: bool = False) -> RegimeState:
        """Return current RegimeState (defaults to NEUTRAL if None)."""
        snap = await self.get_snapshot(force_refresh)
        return snap.state or RegimeState.NEUTRAL

    async def allows_entry(self, force_refresh: bool = False) -> bool:
        """Check if current regime allows new entries."""
        regime = await self.get_regime(force_refresh)
        return regime.allows_entry()

    async def get_position_multiplier(self, force_refresh: bool = False) -> float:
        """Get position size multiplier for current regime (float)."""
        regime = await self.get_regime(force_refresh)
        return float(regime.position_size_multiplier())

    # ---------- internals ----------

    def _create_config(self) -> RegimeConfig:
        """Create config from settings with reasonable defaults."""
        s = self._settings
        # Be defensive if nested fields are missing
        regime = getattr(s, "regime", None)

        def _get(obj: Any, name: str, default: Any) -> Any:
            return getattr(obj, name, default) if obj is not None else default

        return RegimeConfig(
            # thresholds (README-aligned)
            risk_on_threshold=0.5,
            risk_small_threshold=0.0,
            neutral_threshold=-0.5,
            # weights
            dxy_weight=0.35,
            btc_dom_weight=0.35,
            fomc_weight=0.30,
            # change thresholds
            dxy_significant_change=float(_get(regime, "DXY_CHANGE_PCT", 0.35)),
            btc_dom_significant_change=float(_get(regime, "BTC_DOM_CHANGE_PCT", 0.60)),
            # FOMC timings (hours)
            fomc_block_hours_before=int(_get(regime, "FOMC_BLOCK_HOURS", 8)),
            fomc_block_hours_after=4,
            # update frequency
            update_interval_sec=int(_get(regime, "UPDATE_INTERVAL_SEC", 300)),
        )

    async def _on_regime_change(
        self,
        old_state: Optional[RegimeState],
        new_state: Optional[RegimeState],
        snapshot: MacroSnapshot,
    ) -> None:
        """Publish events & update metrics on regime change (best effort)."""
        # metrics
        try:
            if self._metrics and snapshot.score is not None:
                self._metrics.gauge("regime.score", float(snapshot.score))
            if self._metrics and new_state is not None:
                self._metrics.gauge("regime.state", self._state_to_metric(new_state))
        except Exception as e:
            _log.warning("regime_metrics_failed", extra={"error": str(e)})

        # events
        if not self._event_bus or new_state is None:
            return

        try:
            topic, payload = EVT.build_regime_event(
                old_state=old_state.value if old_state else "unknown",
                new_state=new_state.value,
                score=snapshot.score or 0.0,
                dxy_change=snapshot.dxy_change_pct,
                btc_dom_change=snapshot.btc_dom_change_pct,
                fomc_active=snapshot.fomc_event_today,
                trace_id="regime-change",
            )
            await self._event_bus.publish(topic, payload)

            # specific regime topics
            regime_topic = {
                RegimeState.RISK_ON: EVT.REGIME_RISK_ON,
                RegimeState.RISK_SMALL: EVT.REGIME_RISK_SMALL,
                RegimeState.NEUTRAL: EVT.REGIME_NEUTRAL,
                RegimeState.RISK_OFF: EVT.REGIME_RISK_OFF,
            }.get(new_state)

            if regime_topic:
                await self._event_bus.publish(
                    regime_topic,
                    {"state": new_state.value, "score": snapshot.score},
                )
        except Exception as e:
            _log.error("regime_event_publish_failed", extra={"error": str(e)})

    # ----- data sources -----

    async def _fetch_dxy(self) -> Dict[str, Any]:
        """Fetch DXY data from MacroDataPort."""
        try:
            data = await self._dxy.fetch_latest()  # type: ignore[union-attr]
            return {
                "value": float(getattr(data, "value", 0.0)),
                "change_pct": float(getattr(data, "change_pct", 0.0)),
                "updated_at": getattr(data, "timestamp", None),
            }
        except Exception as e:
            _log.error("dxy_fetch_failed", extra={"error": str(e)})
            return {}

    async def _fetch_btc_dom(self) -> Dict[str, Any]:
        """Fetch BTC dominance data from MacroDataPort."""
        try:
            data = await self._btc_dom.fetch_latest()  # type: ignore[union-attr]
            return {
                "value": float(getattr(data, "value", 0.0)),
                "change_pct": float(getattr(data, "change_pct", 0.0)),
                "updated_at": getattr(data, "timestamp", None),
            }
        except Exception as e:
            _log.error("btc_dom_fetch_failed", extra={"error": str(e)})
            return {}

    async def _fetch_fomc(self) -> Dict[str, Any]:
        """Fetch FOMC calendar data from MacroDataPort."""
        try:
            data = await self._fomc.fetch_latest()  # type: ignore[union-attr]
            metadata = getattr(data, "metadata", None) or {}
            next_event = metadata.get("next_event")
            last_event = metadata.get("last_event")

            now = datetime.now(timezone.utc)
            result: Dict[str, Any] = {"event_today": False}

            # next event
            if next_event:
                nx = self._parse_dt(next_event)
                if nx:
                    hours_until = (nx - now).total_seconds() / 3600.0
                    if 0 <= hours_until <= 24:
                        result["event_today"] = True
                    elif hours_until > 0:
                        result["hours_until"] = int(hours_until)

            # last event
            if last_event:
                ls = self._parse_dt(last_event)
                if ls:
                    hours_since = (now - ls).total_seconds() / 3600.0
                    if 0 <= hours_since <= 24:
                        result["event_today"] = True
                    elif hours_since > 0:
                        result["hours_since"] = int(hours_since)

            return result
        except Exception as e:
            _log.error("fomc_fetch_failed", extra={"error": str(e)})
            return {}

    # ----- utils -----

    @staticmethod
    async def _empty() -> Dict[str, Any]:
        """Empty async placeholder (for absent sources)."""
        return {}

    @staticmethod
    def _state_to_metric(state: RegimeState) -> float:
        """Convert regime state to numeric metric."""
        return {
            RegimeState.RISK_ON: 2.0,
            RegimeState.RISK_SMALL: 1.0,
            RegimeState.NEUTRAL: 0.0,
            RegimeState.RISK_OFF: -1.0,
        }.get(state, 0.0)

    @staticmethod
    def _parse_dt(v: Any) -> Optional[datetime]:
        """Parse datetime from iso string or datetime; ensure UTC aware."""
        try:
            if isinstance(v, datetime):
                return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            if isinstance(v, str):
                s = v.replace("Z", "+00:00")
                dt = datetime.fromisoformat(s)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
        return None

    @staticmethod
    def _get_float(d: Dict[str, Any], key: str) -> Optional[float]:
        try:
            v = d.get(key, None)
            return float(v) if v is not None else None
        except Exception:
            return None

    @staticmethod
    def _get_int(d: Dict[str, Any], key: str) -> Optional[int]:
        try:
            v = d.get(key, None)
            return int(v) if v is not None else None
        except Exception:
            return None

    @staticmethod
    def _get_dt(d: Dict[str, Any], key: str) -> Optional[datetime]:
        try:
            v = d.get(key, None)
            if v is None:
                return None
            if isinstance(v, datetime):
                return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            if isinstance(v, str):
                return RegimeDetector._parse_dt(v)
            return None
        except Exception:
            return None


__all__ = ["RegimeDetector"]
