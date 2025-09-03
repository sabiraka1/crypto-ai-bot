from __future__ import annotations

from dataclasses import dataclass

from .ports import BtcDomPort, DxyPort, FomcCalendarPort
from .types import MacroSnapshot, Regime


@dataclass
class RegimeConfig:
    dxy_up_pct: float = 0.5
    dxy_down_pct: float = -0.2
    btc_dom_up_pct: float = 0.5
    btc_dom_down_pct: float = -0.5
    fomc_block_minutes: int = 60


class RegimeDetector:
    """ДћЛњДћВЅГ‘вЂћДћВµГ‘в‚¬ДћВµДћВЅГ‘ВЃ Г‘в‚¬ДћВµДћВ¶ДћВёДћВјДћВ° Г‘в‚¬Г‘вЂ№ДћВЅДћВєДћВ° ДћВїДћВѕ DXY/BTC.D/FOMC (Г‘вЂЎДћВёГ‘ВЃГ‘вЂљДћВ°Г‘ВЏ ДћВґДћВѕДћВјДћВµДћВЅДћВЅДћВ°Г‘ВЏ ДћВ»ДћВѕДћВіДћВёДћВєДћВ°)."""

    def __init__(
        self,
        *,
        dxy: DxyPort | None,
        btc_dom: BtcDomPort | None,
        fomc: FomcCalendarPort | None,
        cfg: RegimeConfig | None = None,
    ) -> None:
        self._dxy = dxy
        self._btc = btc_dom
        self._fomc = fomc
        self._cfg = cfg or RegimeConfig()

    async def snapshot(self) -> MacroSnapshot:
        dxy = await self._dxy.change_pct() if self._dxy else None
        btd = await self._btc.change_pct() if self._btc else None
        fomc_today = await self._fomc.event_today() if self._fomc else False
        return MacroSnapshot(dxy_change_pct=dxy, btc_dom_change_pct=btd, fomc_event_today=fomc_today)

    async def regime(self) -> Regime:
        snap = await self.snapshot()
        if snap.fomc_event_today:
            return "risk_off"
        votes_off = 0
        votes_on = 0
        if snap.dxy_change_pct is not None:
            if snap.dxy_change_pct >= self._cfg.dxy_up_pct:
                votes_off += 1
            elif snap.dxy_change_pct <= self._cfg.dxy_down_pct:
                votes_on += 1
        if snap.btc_dom_change_pct is not None:
            if snap.btc_dom_change_pct >= self._cfg.btc_dom_up_pct:
                votes_off += 1
            elif snap.btc_dom_change_pct <= self._cfg.btc_dom_down_pct:
                votes_on += 1
        if votes_off > votes_on and votes_off > 0:
            return "risk_off"
        if votes_on > votes_off and votes_on > 0:
            return "risk_on"
        return "range"
