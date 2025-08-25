from __future__ import annotations
from ...utils.metrics import snapshot

def render_metrics_json() -> dict:
    return snapshot()