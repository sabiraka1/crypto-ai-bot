from __future__ import annotations
import json
import logging
from typing import Optional
from urllib.request import urlopen, Request

logger = logging.getLogger(__name__)

COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"

def fetch_btc_dominance(timeout: float = 6.0) -> Optional[float]:
    """
    Р’РѕР·РІСЂР°С‰Р°РµС‚ BTC Dominance РІ РїСЂРѕС†РµРЅС‚Р°С… (РЅР°РїСЂРёРјРµСЂ, 52.1), Р»РёР±Рѕ None РїСЂРё РѕС€РёР±РєРµ.
    РСЃС‚РѕС‡РЅРёРє: Coingecko /global (Р±РµР· РєР»СЋС‡Р°).
    """
    try:
        req = Request(COINGECKO_GLOBAL, headers={"User-Agent": "crypto-ai-bot/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        dom = data.get("data", {}).get("market_cap_percentage", {}).get("btc")
        if dom is None:
            return None
        return float(dom)
    except Exception as e:
        logger.warning(f"BTC.D fetch failed: {e}")
        return None


