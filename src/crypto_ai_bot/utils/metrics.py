from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Dict, Tuple

# counters[name][label_tuple][bucket_ts] = value
_counters: Dict[str, Dict[Tuple[Tuple[str,str],...], Dict[int, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
_sum: Dict[str, Dict[Tuple[Tuple[str,str],...], Dict[int, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
_lock = threading.RLock()

# окна
_WINDOW_S = (5 * 60, 60 * 60)  # 5m, 60m
_BUCKET = 60  # 60s

def _now_bucket() -> int:
    return int(time.time()) // _BUCKET * _BUCKET

def _labels_dict_to_tuple(labels: Dict[str,str]) -> Tuple[Tuple[str,str],...]:
    return tuple(sorted((str(k), str(v)) for k, v in labels.items() if v is not None))

def inc(name: str, **labels) -> None:
    """
    Совместим с существующим кодом:
      inc("broker_call_total", fn="fetch_ticker")
      inc("broker_call_errors_total", fn="create_order")
      inc("broker_call_latency_ms_sum", fn="fetch_balance", ms="123")
    """
    with _lock:
        b = _now_bucket()
        ms = labels.pop("ms", None)
        lt = _labels_dict_to_tuple(labels)
        if ms is not None and (name.endswith("_sum") or name.endswith("_ms_sum")):
            try:
                v = float(ms)
            except Exception:
                v = 0.0
            _sum[name][lt][b] += v
        else:
            _counters[name][lt][b] += 1.0

def _sum_window(d: Dict[int,float], window_s: int) -> float:
    now = int(time.time())
    start = now - window_s
    s = 0.0
    for ts, v in list(d.items()):
        if ts < start - _BUCKET:
            del d[ts]
            continue
        if ts >= start:
            s += v
    return s

# ---------- programmatic getters (для SLA) ----------
def window_total(name: str, labels: Dict[str,str], window_s: int) -> float:
    with _lock:
        lt = _labels_dict_to_tuple(labels)
        series = _counters.get(name, {}).get(lt, {})
        return _sum_window(series, window_s)

def window_sum(name: str, labels: Dict[str,str], window_s: int) -> float:
    with _lock:
        lt = _labels_dict_to_tuple(labels)
        series = _sum.get(name, {}).get(lt, {})
        return _sum_window(series, window_s)

def error_rate(labels: Dict[str,str], window_s: int) -> float:
    tot = window_total("broker_call_total", labels, window_s)
    err = window_total("broker_call_errors_total", labels, window_s)
    return (err / tot) if tot > 0 else 0.0

def avg_latency_ms(labels: Dict[str,str], window_s: int) -> float:
    tot = window_total("broker_call_total", labels, window_s)
    lat = window_sum("broker_call_latency_ms_sum", labels, window_s)
    return (lat / tot) if tot > 0 else 0.0

# ---------- exporters ----------
def _render_single_prom(name: str, labels: Tuple[Tuple[str,str],...], value: float) -> str:
    if not labels:
        return f"{name} {value:.6f}\n"
    parts = ",".join(f'{k}="{v}"' for k, v in labels)
    return f'{name}{{{parts}}} {value:.6f}\n'

def render_prometheus() -> str:
    with _lock:
        out = []

        # текущее ведро (сырьевое)
        for name, by_lbl in _counters.items():
            for lt, series in by_lbl.items():
                out.append(_render_single_prom(f"crypto_{name}_bucket", lt, series.get(_now_bucket(), 0.0)))
        for name, by_lbl in _sum.items():
            for lt, series in by_lbl.items():
                out.append(_render_single_prom(f"crypto_{name}_bucket", lt, series.get(_now_bucket(), 0.0)))

        def window_block(window_s: int, suffix: str) -> None:
            for name, by_lbl in _counters.items():
                for lt, series in by_lbl.items():
                    out.append(_render_single_prom(f"crypto_{name}_{suffix}", lt, _sum_window(series, window_s)))
            # latency avg
            lat_name = "broker_call_latency_ms_sum"; total_name = "broker_call_total"; err_name = "broker_call_errors_total"
            for lt, series in _sum.get(lat_name, {}).items():
                lat = _sum_window(series, window_s)
                tot = _sum_window(_counters.get(total_name, {}).get(lt, {}), window_s)
                avg = (lat / tot) if tot > 0 else 0.0
                out.append(_render_single_prom(f"crypto_broker_call_latency_ms_avg_{suffix}", lt, avg))
            # error rate
            for lt, series in _counters.get(total_name, {}).items():
                tot = _sum_window(series, window_s)
                err = _sum_window(_counters.get(err_name, {}).get(lt, {}), window_s)
                rate = (err / tot) if tot > 0 else 0.0
                out.append(_render_single_prom(f"crypto_broker_call_error_rate_{suffix}", lt, rate))

        window_block(_WINDOW_S[0], "5m")
        window_block(_WINDOW_S[1], "60m")
        return "".join(out)

def render_metrics_json() -> Dict[str, Dict]:
    with _lock:
        data: Dict[str, Dict] = {"windows": {}}
        for win, suf in ((_WINDOW_S[0], "5m"), (_WINDOW_S[1], "60m")):
            entry: Dict[str, Dict] = {}
            for name, by_lbl in _counters.items():
                for lt, series in by_lbl.items():
                    entry[f"{name}:{dict(lt)}"] = {"total": _sum_window(series, win)}
            lat_by = _sum.get("broker_call_latency_ms_sum", {})
            for lt, series in lat_by.items():
                tot = _sum_window(_counters.get("broker_call_total", {}).get(lt, {}), win)
                lat = _sum_window(series, win)
                entry[f"latency:{dict(lt)}"] = {"avg_ms": (lat / tot) if tot > 0 else 0.0}
            for lt, series in _counters.get("broker_call_total", {}).items():
                tot = _sum_window(series, win)
                err = _sum_window(_counters.get("broker_call_errors_total", {}).get(lt, {}), win)
                entry[f"error_rate:{dict(lt)}"] = {"rate": (err / tot) if tot > 0 else 0.0}
            data["windows"][suf] = entry
        return data
