from __future__ import annotations

from dataclasses import dataclass

from .ai_model import AIModel
from .feature_pipeline import Candle, last_features


@dataclass
class AIScoringConfig:
    model_path: str = "models/ai/model.onnx"
    meta_path: str = "models/ai/meta.json"
    required: bool = False  # если True — при недоступности модели вернём None
    min_len_15m: int = 100  # минимальное число баров для 15m, иначе None
    pct_floor: float = 0.0  # нижняя отсечка для процента (0..100)
    pct_ceiling: float = 100.0  # верхняя отсечка
    temperature: float = 1.0  # сглаживание: 1.0 = без изменений; >1 «приглушает» крайности

    # Примечание: все новые поля — опциональны. Старые конфиги останутся совместимы.


class AIScorer:
    def __init__(self, cfg: AIScoringConfig | None = None) -> None:
        self.cfg = cfg or AIScoringConfig()
        self._model = AIModel(self.cfg.model_path, self.cfg.meta_path)

    @property
    def ready(self) -> bool:
        return self._model.ready

    @staticmethod
    def _apply_temperature(p: float, t: float) -> float:
        """Температурное сглаживание вероятности (через логиты)."""
        if t == 1.0:
            return p
        eps = 1e-6
        import math

        p = min(1.0 - eps, max(eps, p))
        logit = math.log(p / (1.0 - p))
        adj = logit / max(1e-6, float(t))
        return 1.0 / (1.0 + math.exp(-adj))

    def score(
        self,
        ohlcv_15m: list[Candle],
        ohlcv_1h: list[Candle] | None = None,
        ohlcv_4h: list[Candle] | None = None,
        ohlcv_1d: list[Candle] | None = None,
        ohlcv_1w: list[Candle] | None = None,
    ) -> float | None:
        # Базовая валидация длины — иначе признаки часто «дырявые»
        if not ohlcv_15m or len(ohlcv_15m) < int(self.cfg.min_len_15m or 0):
            return None if self.cfg.required else 50.0  # нейтральная оценка

        feats = last_features(ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d, ohlcv_1w)
        p = self._model.predict_proba(feats)

        if p is None:
            return None if self.cfg.required else 50.0

        # Температурное сглаживание + безопасные границы
        p = self._apply_temperature(float(p), float(self.cfg.temperature or 1.0))
        pct = max(float(self.cfg.pct_floor), min(float(self.cfg.pct_ceiling), p * 100.0))
        return float(pct)
