# src/crypto_ai_bot/core/signals/_fusion.py
"""
Единая сборка фич и принятие решения для long-only.

Публичный API:
    build(symbol: str, *, cfg, positions_repo=None, external=None, **_ignored) -> dict
    decide(features: dict, *, cfg) -> dict

Особенности:
- build допускает "лишние" именованные аргументы через **_ignored (напр. broker=...),
  чтобы не ломать существующие вызовы из evaluate.py / orchestrator.
- Пороговые значения BUY_TH/SELL_TH берутся из cfg при наличии, иначе — дефолты.
- Если external содержит OHLCV, рассчитываем простые индикаторы (RSI, momentum, MA-тренд).
- Возвращаем понятный explain: score, вклад индикаторов, пороги.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict
import math


class Explain(TypedDict, total=False):
    reason: str
    score: float
    indicators: Dict[str, float]
    thresholds: Dict[str, float]


# Дефолтные пороги на случай отсутствия настроек
BUY_TH: float = 0.60
SELL_TH: float = -0.60

__all__ = ["build", "decide", "Explain", "BUY_TH", "SELL_TH"]


# --------------------------- helpers ---------------------------

def _extract_closes(external: Optional[Dict[str, Any]]) -> List[float]:
    """
    Ожидаем external.get("ohlcv") как список свечей: [ts, o, h, l, c, v] (как в CCXT).
    Возвращаем список close-цен (float). При отсутствии данных — пустой список.
    """
    if not external:
        return []
    ohlcv = external.get("ohlcv") or []
    closes: List[float] = []
    for row in ohlcv:
        try:
            # допускаем как список, так и dict-представление
            if isinstance(row, (list, tuple)) and len(row) >= 5:
                closes.append(float(row[4]))
            elif isinstance(row, dict) and "close" in row:
                closes.append(float(row["close"]))
        except Exception:
            # пропускаем битые строки
            continue
    return closes


def _sma(values: List[float], period: int) -> Optional[float]:
    n = len(values)
    if n < period or period <= 0:
        return None
    return sum(values[-period:]) / float(period)


def _rsi(values: List[float], period: int = 14) -> Optional[float]:
    """
    Простейший RSI (без Wilder smoothing). Возвращает [0..100] или None, если мало данных.
    """
    n = len(values)
    if n <= period:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(n - period, n - 1):
        ch = values[i + 1] - values[i]
        if ch > 0:
            gains += ch
        else:
            losses -= ch  # минус к положительному
    if (gains + losses) == 0:
        return 50.0
    rs = (gains / max(1e-12, losses)) if losses > 0 else math.inf
    rsi = 100.0 - (100.0 / (1.0 + rs)) if math.isfinite(rs) else 100.0
    return max(0.0, min(100.0, rsi))


def _pct_change(a: float, b: float) -> Optional[float]:
    """Относительное изменение b vs a (в долях), если вход валиден."""
    if a is None or b is None:
        return None
    if a == 0:
        return None
    return (b - a) / a


def _normalize_minus1_1(value: Optional[float], *, low: float, high: float) -> float:
    """
    Нормализация value в диапазон [-1..1] по линейной шкале [low..high].
    Если value отсутствует — 0.0.
    """
    if value is None or not math.isfinite(value):
        return 0.0
    if high == low:
        return 0.0
    x = (value - low) / (high - low)  # 0..1
    return max(-1.0, min(1.0, 2.0 * x - 1.0))  # -> -1..1


# ------------------------ public API ------------------------

def build(
    symbol: str,
    *,
    cfg: Any,
    positions_repo: Any = None,
    external: Optional[Dict[str, Any]] = None,
    **_ignored: Any,  # <— ключ для совместимости (принимаем broker=..., market_meta=..., и т.д.)
) -> Dict[str, Any]:
    """
    Сборка фич/контекста для принятия решения.
    Возвращает словарь с ключами:
        - "symbol": str
        - "indicators": Dict[str, float]  # нормализованные индикаторы [-1..1]
        - "raw": Dict[str, Any]           # необязательные «сырые» значения для/отладки
        - "score": float                  # агрегированный скор [-1..1]
        - "thresholds": Dict[str, float]
    """

    # Пороговые значения (приоритет — из cfg, иначе дефолты модуля)
    buy_th = float(getattr(cfg, "BUY_TH", BUY_TH))
    sell_th = float(getattr(cfg, "SELL_TH", SELL_TH))

    closes = _extract_closes(external)
    last = closes[-1] if closes else None
    prev = closes[-2] if len(closes) >= 2 else None

    # --- Индикаторы (raw) ---
    rsi = _rsi(closes, period=int(getattr(cfg, "RSI_PERIOD", 14)))
    mom = _pct_change(prev, last)  # доли, например 0.01 = +1%
    ma_period = int(getattr(cfg, "MA_TREND_PERIOD", 20))
    ma = _sma(closes, period=ma_period)

    # --- Нормализация ---
    # RSI 30..70 -> -1..1 (при 50 ~ 0)
    rsi_n = _normalize_minus1_1(rsi, low=30.0, high=70.0)
    # momentum нормализуем в коридор ±2% (0.02): больше капим.
    mom_clip = None if mom is None else max(-0.02, min(0.02, mom))
    mom_n = _normalize_minus1_1(mom_clip, low=-0.02, high=0.02)
    # тренд: close vs MA → {-1, 0, +1}
    trend_n = 0.0
    if last is not None and ma is not None:
        trend_n = 1.0 if last >= ma else -1.0

    # --- Смешивание (веса можно держать в cfg) ---
    w_rsi = float(getattr(cfg, "FUSION_W_RSI", 0.30))
    w_mom = float(getattr(cfg, "FUSION_W_MOM", 0.50))
    w_trd = float(getattr(cfg, "FUSION_W_TREND", 0.20))
    # Нормируем веса на всякий
    w_sum = max(1e-12, abs(w_rsi) + abs(w_mom) + abs(w_trd))
    w_rsi /= w_sum
    w_mom /= w_sum
    w_trd /= w_sum

    score = w_rsi * rsi_n + w_mom * mom_n + w_trd * trend_n
    score = max(-1.0, min(1.0, float(score)))

    features: Dict[str, Any] = {
        "symbol": symbol,
        "indicators": {
            "rsi_n": rsi_n,
            "mom_n": mom_n,
            "trend_n": trend_n,
        },
        "raw": {
            "last_close": last,
            "prev_close": prev,
            "rsi": rsi,
            "momentum": mom,
            "sma": ma,
            "ma_period": ma_period,
        },
        "score": score,
        "thresholds": {
            "BUY_TH": buy_th,
            "SELL_TH": sell_th,
        },
    }
    return features


def decide(features: Dict[str, Any], *, cfg: Any) -> Dict[str, Any]:
    """
    Принимает features из build() и возвращает решение:
        {
          "action": "buy" | "sell" | "hold",
          "score": float,
          "explain": Explain
        }
    NB: long-only стратегия — "sell" трактуем как сигнал на закрытие лонга (если он есть).
    """
    buy_th = float(getattr(cfg, "BUY_TH", BUY_TH))
    sell_th = float(getattr(cfg, "SELL_TH", SELL_TH))

    score: float = float(features.get("score", 0.0))
    ind: Dict[str, float] = features.get("indicators", {})

    if score >= buy_th:
        action = "buy"
        reason = "score >= BUY_TH"
    elif score <= sell_th:
        action = "sell"
        reason = "score <= SELL_TH"
    else:
        action = "hold"
        reason = "neutral band"

    explain: Explain = {
        "reason": reason,
        "score": score,
        "indicators": {
            "rsi_n": float(ind.get("rsi_n", 0.0)),
            "mom_n": float(ind.get("mom_n", 0.0)),
            "trend_n": float(ind.get("trend_n", 0.0)),
        },
        "thresholds": {
            "BUY_TH": buy_th,
            "SELL_TH": sell_th,
        },
    }
    return {"action": action, "score": score, "explain": explain}
