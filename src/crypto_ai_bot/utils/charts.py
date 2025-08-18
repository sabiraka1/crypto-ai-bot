# src/crypto_ai_bot/utils/charts.py
from __future__ import annotations

from typing import List, Optional
import math

def _svg_header(width: int, height: int) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'

def _svg_footer() -> str:
    return "</svg>"

def _fmt(num: float) -> str:
    # компактное форматирование до 2-4 значащих
    if num == 0:
        return "0"
    order = int(math.floor(math.log10(abs(num))))
    digits = max(0, 2 - order)
    return f"{num:.{min(4, max(0, digits))}f}"

def _polyline(points: List[tuple[float, float]], stroke: str = "#111", stroke_width: int = 2) -> str:
    ps = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return f'<polyline fill="none" stroke="{stroke}" stroke-width="{stroke_width}" points="{ps}"/>'

def _text(x: float, y: float, s: str, size: int = 12, anchor: str = "start", color: str = "#111") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif">{s}</text>'

def _box(width: int, height: int, padding: int) -> str:
    return f'<rect x="0" y="0" width="{width}" height="{height}" fill="#fff"/><rect x="{padding}" y="{padding}" width="{width-2*padding}" height="{height-2*padding}" fill="#fff" stroke="#e5e7eb"/>'

def _sparkline(values: List[float], *, width: int = 640, height: int = 240, padding: int = 24, title: Optional[str] = None, stroke: str = "#111") -> bytes:
    if not values or len(values) < 2:
        svg = [
            _svg_header(width, height),
            _box(width, height, padding),
            _text(width/2, height/2, "no data", 14, anchor="middle", color="#9ca3af"),
            _svg_footer(),
        ]
        return ("\n".join(svg)).encode("utf-8")

    w = width - 2 * padding
    h = height - 2 * padding
    vmin = min(values)
    vmax = max(values)
    rng = (vmax - vmin) or 1.0

    pts: List[tuple[float, float]] = []
    n = len(values)
    for i, v in enumerate(values):
        x = padding + (w * i) / (n - 1)
        # инверсия по Y: 0 внизу, max вверху
        y = padding + h - ((v - vmin) / rng) * h
        pts.append((x, y))

    svg = [_svg_header(width, height)]
    svg.append(_box(width, height, padding))
    # ось Y мин/макс
    svg.append(_text(padding + 4, padding + 12, _fmt(vmax), 11, "start", "#6b7280"))
    svg.append(_text(padding + 4, height - padding + 12, _fmt(vmin), 11, "start", "#6b7280"))

    if title:
        svg.append(_text(width/2, padding - 6, title, 13, anchor="middle", color="#111"))

    svg.append(_polyline(pts, stroke=stroke, stroke_width=2))
    svg.append(_svg_footer())
    return ("\n".join(svg)).encode("utf-8")

def render_price_spark_svg(closes: List[float], *, title: Optional[str] = None) -> bytes:
    return _sparkline(closes, title=title or "price", stroke="#111")

def render_profit_curve_svg(pnls: List[float], *, title: Optional[str] = None) -> bytes:
    # pnls — список доходностей по сделкам; строим кумулятив
    acc: List[float] = []
    s = 0.0
    for p in pnls:
        try:
            s += float(p)
        except Exception:
            continue
        acc.append(s)
    return _sparkline(acc, title=title or "profit", stroke="#111")
