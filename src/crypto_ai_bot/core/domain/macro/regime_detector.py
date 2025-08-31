# src/crypto_ai_bot/core/application/macro/regime_detector.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from crypto_ai_bot.core.domain.macro.types import MacroSnapshot, Regime


@dataclass
class RegimeConfig:
    dxy_up_pct: float = 0.5         # рост DXY > +0.5% => риск-офф
    dxy_down_pct: float = -0.2      # падение DXY < -0.2% => сигнал риск-он
    btc_dom_up_pct: float = 0.5     # рост доминации BTC > +0.5% => риск-офф для альтов
    btc_dom_down_pct: float = -0.5  # падение доминации BTC < -0.5% => риск-он
    fomc_block_minutes: int = 60    # окно перед/после FOMC (если источник так помечает)


class RegimeDetector:
    """
    Агрегирует макро-сигналы (DXY/BTC.D/FOMC) и решает режим:
      - "risk_off" — избегаем новых лонгов, снижаем агрессию
      - "risk_on"  — допускаем лонги, breakout и т.п.
      - "range"    — нейтрально
    Источники опциональны: если какого-то нет, он не влияет.
    """

    def __init__(self, *, dxy_source, btc_dom_source, fomc_source, cfg: Optional[RegimeConfig] = None) -> None:
        self._dxy = dxy_source
        self._btc = btc_dom_source
        self._fomc = fomc_source
        self._cfg = cfg or RegimeConfig()

    async def snapshot(self) -> MacroSnapshot:
        dxy = await self._dxy.change_pct() if self._dxy else None
        btd = await self._btc.change_pct() if self._btc else None
        fomc_today = await self._fomc.event_today() if self._fomc else False
        return MacroSnapshot(dxy_change_pct=dxy, btc_dom_change_pct=btd, fomc_event_today=fomc_today)

    async def regime(self) -> Regime:
        snap = await self.snapshot()
        # FOMC — всегда осторожность
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
