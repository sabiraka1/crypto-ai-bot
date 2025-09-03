from __future__ import annotations

from dataclasses import dataclass

from .ai_model import AIModel
from .feature_pipeline import Candle, last_features


@dataclass
class AIScoringConfig:
    model_path: str = "models/ai/model.onnx"
    meta_path: str = "models/ai/meta.json"
    required: bool = False


class AIScorer:
    def __init__(self, cfg: AIScoringConfig | None = None) -> None:
        self.cfg = cfg or AIScoringConfig()
        self._model = AIModel(self.cfg.model_path, self.cfg.meta_path)

    @property
    def ready(self) -> bool:
        return self._model.ready

    def score(
        self,
        ohlcv_15m: list[Candle],
        ohlcv_1h: list[Candle] | None = None,
        ohlcv_4h: list[Candle] | None = None,
        ohlcv_1d: list[Candle] | None = None,
        ohlcv_1w: list[Candle] | None = None,
    ) -> float | None:
        feats = last_features(ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d, ohlcv_1w)
        p = self._model.predict_proba(feats)
        if p is None and self.cfg.required:
            return None
        return None if p is None else float(max(0.0, min(1.0, p)) * 100.0)
