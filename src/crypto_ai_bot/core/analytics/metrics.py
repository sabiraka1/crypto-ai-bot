from __future__ import annotations
from typing import Dict, Any
from ...utils.metrics import snapshot

def render_metrics_json() -> Dict[str, Any]:
    """
    JSON-снимок метрик для /metrics фолбэка или отладки.
    Структура стабильная: {"counters": {...}, "histograms": {...}}.
    """
    return snapshot()

# ✅ Backward-compat для старого server.py
def report_dict() -> Dict[str, Any]:
    return render_metrics_json()
