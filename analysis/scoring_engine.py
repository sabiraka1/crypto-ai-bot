import os
import math
from typing import Dict, Any, Tuple

# Опционально подключаем твою ML-модель; если её нет — работаем с заглушкой
try:
    from ml.adaptive_model import AdaptiveMLModel
except Exception:
    AdaptiveMLModel = None


# ====== Настройки порога ======
def get_min_buy_score() -> float:
    # можно переопределить через .env (MIN_SCORE_TO_BUY), но по умолчанию 1.4 как мы решили
    try:
        return float(os.getenv("MIN_SCORE_TO_BUY", "1.4"))
    except Exception:
        return 1.4


# ====== BUY SCORE (правила TA) ======
def compute_buy_score(features: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    """
    features = {
        "rsi": float,
        "macd_hist": float,
        "ema_fast_above": bool,
        "adx": float
    }
    Возвращает (score, breakdown) где breakdown по компонентам.
    Суммарный максимум условно ~2.0, чтобы соответствовать прежним логам.
    """
    rsi = float(features.get("rsi", 50))
    macd_hist = float(features.get("macd_hist", 0))
    ema_fast_above = bool(features.get("ema_fast_above", False))
    adx = float(features.get("adx", 20))

    breakdown = {
        "rsi": 0.0,
        "macd": 0.0,
        "ema": 0.0,
        "trend": 0.0,
    }

    # RSI: «здоровая зона» ~ 40..65
    if 40 <= rsi <= 65:
        breakdown["rsi"] = 1.0

    # MACD: растущий гистограммный столбик — сильнее
    if macd_hist > 0:
        breakdown["macd"] = 1.0
    # (если хочешь тоньше: положительный, но уменьшается → 0.5)

    # EMA-фильтр: если short EMA выше long EMA — небольшой бонус
    if ema_fast_above:
        breakdown["ema"] = 0.4

    # ADX как фильтр слабого тренда — бонус при тренде
    if adx >= 18:
        breakdown["trend"] = 0.2

    score = sum(breakdown.values())
    # мягкое ограничение до 2.0, чтобы сохранять привычные шкалы логов
    score = min(score, 2.0)
    return score, breakdown


# ====== AI SCORE (вероятностная модель) ======
def compute_ai_score(features: Dict[str, Any]) -> float:
    """
    Возвращает вероятность (0..1) успеха сделки.
    Если модели нет — возвращаем 0.5 (нейтрально).
    """
    try:
        if AdaptiveMLModel is None:
            return 0.5
        model = AdaptiveMLModel()
        # ожидается метод safe/predict_proba, подстраиваемся:
        if hasattr(model, "predict_proba_safely"):
            return float(model.predict_proba_safely(features))
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(features)
            return float(proba) if isinstance(proba, (int, float)) else float(proba[0])
        if hasattr(model, "predict"):
            # если только predict → маппим {True:0.7, False:0.3} как эвристика
            pred = model.predict(features)
            return 0.7 if bool(pred) else 0.3
    except Exception:
        pass
    return 0.5


# ====== Маппинг AI→доля объёма (твоя сетка) ======
def decide_trade_amount(ai_score: float, base_amount_usd: float) -> Tuple[float, float]:
    """
    Возвращает (amount_usd, fraction).
      AI ≥ 0.70  -> 100%
      0.60–0.70  -> 90%
      0.50–0.60  -> 60%
      < 0.50     -> 0% (не торгуем)
    """
    if ai_score >= 0.70:
        frac = 1.00
    elif 0.60 <= ai_score < 0.70:
        frac = 0.90
    elif 0.50 <= ai_score < 0.60:
        frac = 0.60
    else:
        frac = 0.0

    return round(base_amount_usd * frac, 2), frac


# ====== Итоговое решение ======
def decide(features: Dict[str, Any], base_amount_usd: float) -> Dict[str, Any]:
    """
    Вычисляет buy_score, ai_score и принимает решение о входе.
    Возвращает dict:
    {
        "buy_score": float,
        "ai_score": float,
        "min_buy_score": float,
        "amount_usd": float,  # 0 если не входить
        "amount_fraction": float,
        "reason": str,
        "breakdown": Dict[str, float]
    }
    """
    min_buy = get_min_buy_score()
    buy_score, breakdown = compute_buy_score(features)
    ai_score = compute_ai_score(features)
    amount_usd, frac = decide_trade_amount(ai_score, base_amount_usd)

    if buy_score < min_buy:
        return {
            "buy_score": buy_score,
            "ai_score": ai_score,
            "min_buy_score": min_buy,
            "amount_usd": 0.0,
            "amount_fraction": 0.0,
            "reason": f"Buy Score {buy_score:.2f} ниже порога {min_buy:.2f}",
            "breakdown": breakdown
        }

    if frac <= 0.0:
        return {
            "buy_score": buy_score,
            "ai_score": ai_score,
            "min_buy_score": min_buy,
            "amount_usd": 0.0,
            "amount_fraction": 0.0,
            "reason": f"AI {ai_score:.2f} ниже 0.50 — вход пропущен",
            "breakdown": breakdown
        }

    return {
        "buy_score": buy_score,
        "ai_score": ai_score,
        "min_buy_score": min_buy,
        "amount_usd": amount_usd,
        "amount_fraction": frac,
        "reason": "OK",
        "breakdown": breakdown
    }
