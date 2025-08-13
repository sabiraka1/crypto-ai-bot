from __future__ import annotations
import json
import logging
from typing import Optional
from urllib.request import urlopen, Request

logger = logging.getLogger(__name__)

FNG_API = "https://api.alternative.me/fng/"

def fetch_fear_greed(timeout: float = 6.0) -> Optional[int]:
    """
    Возвращает Fear & Greed Index (0..100) либо None.
    """
    try:
        req = Request(FNG_API, headers={"User-Agent": "crypto-ai-bot/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        v = data.get("data", [{}])[0].get("value")
        return int(v) if v is not None else None
    except Exception as e:
        logger.warning(f"Fear&Greed fetch failed: {e}")
        return None
