from __future__ import annotations
import json
import logging
from typing import Optional
from urllib.request import urlopen, Request

logger = logging.getLogger(__name__)

COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"

def fetch_btc_dominance(timeout: float = 6.0) -> Optional[float]:
    """
    Возвращает BTC Dominance в процентах (например, 52.1), либо None при ошибке.
    Источник: Coingecko /global (без ключа).
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
