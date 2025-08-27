from __future__ import annotations
from crypto_ai_bot.utils.metrics import snapshot

def render_metrics_json() -> dict:
    return snapshot()