# src/crypto_ai_bot/utils/charts.py
from __future__ import annotations

from typing import Iterable, List, Tuple, Optional


def _extent(vals: Iterable[float]) -> Tuple[float, float]:
    xs = [float(v) for v in vals if v is not None]
    if not xs:
        return (0.0, 0.0)
    lo = min(xs)
    hi = max(xs)
    if hi == lo:
        # защитимся от деления на ноль — добавим 1%
        pad = hi * 0.01 if hi != 0 else 1.0
        return (lo - pad, hi + pad)
    return (lo, hi)


def _polyline(points: List[Tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _scale_series(series: List[float], w: float, h: float, pad: float = 8.0) -> List[Tuple[float, float]]:
    if not series:
        return []
    lo, hi = _extent(series)
    rng = (hi - lo) if hi != lo else 1.0
    n = len(series)
    if n == 1:
        n = 2  # одна точка — нарисуем вертикаль
        series = [series[0], series[0]]
    dx = (w - 2 * pad) / (n - 1)
    out: List[Tuple[float, float]] = []
    for i, v in enumerate(series):
        x = pad + i * dx
        # инвертируем Y (SVG-система координат сверху вниз)
        y = pad + (h - 2 * pad) * (1.0 - (float(v) - lo) / rng)
        out.append((x, y))
    return out


def _svg_wrap(paths: List[str], w: int, h: int, title: Optional[str] = None) -> bytes:
    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="white"/>',
    ]
    if title:
        head.append(f'<text x="12" y="20" font-family="sans-serif" font-size="14">{title}</text>')
    body = "\n".join(paths)
    tail = "</svg>"
    return ("\n".join(head) + "\n" + body + "\n" + tail).encode("utf-8")


def render_price_spark_svg(
    closes: List[float],
    *,
    width: int = 640,
    height: int = 200,
    title: Optional[str] = None,
) -> bytes:
    """Простая линия цены (по close) как SVG (без зависимостей)."""
    pts = _scale_series(closes, width, height)
    if not pts:
        return _svg_wrap([], width, height, title)
    d = _polyline(pts)
    paths = [
        f'<polyline fill="none" stroke="#1f77b4" stroke-width="2" points="{d}"/>'
    ]
    # последняя точка
    x, y = pts[-1]
    paths.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="#1f77b4"/>')
    return _svg_wrap(paths, width, height, title)


def render_profit_curve_svg(
    pnls: List[float],
    *,
    width: int = 640,
    height: int = 200,
    title: Optional[str] = None,
) -> bytes:
    """Рисует кумулятивную доходность по последовательности PnL."""
    cum: List[float] = []
    s = 0.0
    for p in pnls:
        try:
            s += float(p)
        except Exception:
            continue
        cum.append(s)
    pts = _scale_series(cum, width, height)
    if not pts:
        return _svg_wrap([], width, height, title)
    d = _polyline(pts)
    paths = [
        f'<polyline fill="none" stroke="#2ca02c" stroke-width="2" points="{d}"/>'
    ]
    x, y = pts[-1]
    paths.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="#2ca02c"/>')
    return _svg_wrap(paths, width, height, title)


def closes_from_ohlcv(ohlcv: List[List[float]]) -> List[float]:
    """Достаёт close из стандартного OHLCV [[ts, o, h, l, c, v], ...]."""
    out: List[float] = []
    for row in ohlcv:
        if len(row) >= 5:
            try:
                out.append(float(row[4]))
            except Exception:
                continue
    return out
