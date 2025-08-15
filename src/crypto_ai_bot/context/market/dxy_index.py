from __future__ import annotations
import csv
import io
import logging
from typing import Optional, Tuple
from urllib.request import urlopen, Request

logger = logging.getLogger(__name__)

STOOQ_DXY_DAILY = "https://stooq.com/q/d/l/?s=dxy&i=d"

def fetch_dxy_last_and_prev(timeout: float = 6.0) -> Optional[Tuple[float, float]]:
    """
    Р’РѕР·РІСЂР°С‰Р°РµС‚ (last, prev) РїРѕ DXY (РµР¶РµРґРЅРµРІРЅС‹Рµ СЃРІРµС‡Рё Stooq).
    """
    try:
        req = Request(STOOQ_DXY_DAILY, headers={"User-Agent": "crypto-ai-bot/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
        if len(rows) < 2:
            return None
        last = float(rows[-1]["Close"])
        prev = float(rows[-2]["Close"])
        return last, prev
    except Exception as e:
        logger.warning(f"DXY fetch failed: {e}")
        return None

def dxy_change_pct_1d(timeout: float = 6.0) -> Optional[float]:
    """РР·РјРµРЅРµРЅРёРµ DXY Р·Р° 1 РґРµРЅСЊ, РІ % (РЅР°РїСЂРёРјРµСЂ, +0.45)."""
    lp = fetch_dxy_last_and_prev(timeout)
    if not lp:
        return None
    last, prev = lp
    if prev == 0:
        return None
    return (last / prev - 1.0) * 100.0






