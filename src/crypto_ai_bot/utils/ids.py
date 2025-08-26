from __future__ import annotations

import time
import os
import random
import string


def _env_tag() -> str:
    mode = (os.getenv("MODE") or "paper").lower()
    sandbox = (os.getenv("SANDBOX") or "0") in {"1", "true", "yes", "y", "on"}
    if mode == "paper":
        return "PAPER"
    if mode == "live" and sandbox:
        return "SBX"
    return "LIVE"


def _rand(n: int = 5) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(n))


def make_client_order_id(exchange_id: str, tag: str) -> str:
    """
    Делает стабильный clientOrderId с env-префиксом:
      PAPER_/SBX_/LIVE_ + {exchange}:{tag}:{ms}:{rnd}
    """
    ms = int(time.time() * 1000)
    return f"{_env_tag()}_{exchange_id}:{tag}:{ms}:{_rand()}"
