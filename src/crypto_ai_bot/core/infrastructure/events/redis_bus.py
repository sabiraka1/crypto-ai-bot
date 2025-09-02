from crypto_ai_bot.utils.metrics import inc
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from redis.asyncio import Redis
    from redis.asyncio.client import PubSub
except Exception as exc:
    raise RuntimeError("redis.asyncio is required for RedisEventBus") from exc

from crypto_ai_bot.utils.logging import get_logger

