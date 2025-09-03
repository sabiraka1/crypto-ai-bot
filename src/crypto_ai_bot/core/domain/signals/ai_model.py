from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

try:
    import onnxruntime as rt  # type: ignore
except Exception:
    rt = None  # type: ignore


@dataclass
class AIModelMeta:
    feature_order: list[str]
    bias: float | None = None
    weights: list[float] | None = None
    calibration_a: float | None = None
    calibration_b: float | None = None


class AIModel:
    def __init__(self, model_path: str | Path | None = None, meta_path: str | Path | None = None) -> None:
        self._sess = None
        self._input_name = None
        self._meta: AIModelMeta | None = None
        if model_path:
            p = Path(model_path)
            if rt is not None and p.exists():
                try:
                    self._sess = rt.InferenceSession(str(p), providers=["CPUExecutionProvider"])
                    self._input_name = self._sess.get_inputs()[0].name  # type: ignore[index]
                except Exception:
                    self._sess = None
        if meta_path:
            mp = Path(meta_path)
            if mp.exists():
                try:
                    raw = json.loads(mp.read_text(encoding="utf-8"))
                    self._meta = AIModelMeta(
                        feature_order=list(raw.get("feature_order") or []),
                        bias=raw.get("bias"),
                        weights=list(raw.get("weights") or []) or None,
                        calibration_a=(raw.get("calibration") or {}).get("a"),
                        calibration_b=(raw.get("calibration") or {}).get("b"),
                    )
                except Exception:
                    self._meta = None

    @property
    def ready(self) -> bool:
        if self._sess is not None and self._input_name:
            return True
        if self._meta and self._meta.weights and self._meta.bias is not None:
            return True
        return False

    def _sigmoid(self, x: float) -> float:
        import math

        return 1.0 / (1.0 + math.exp(-x))

    def _calibrate(self, p: float) -> float:
        if not self._meta or self._meta.calibration_a is None or self._meta.calibration_b is None:
            return p
        a = float(self._meta.calibration_a)
        b = float(self._meta.calibration_b)
        z = a * p + b
        return max(0.0, min(1.0, z))

    def predict_proba(self, feature_map: dict[str, float] | None) -> float | None:
        if not feature_map:
            return None
        if self._meta and self._meta.feature_order:
            order = self._meta.feature_order
        else:
            order = sorted(feature_map.keys())
        feats = [float(feature_map.get(k, 0.0) or 0.0) for k in order]
        if self._sess is not None and self._input_name:
            try:
                import numpy as np  # type: ignore

                x = np.asarray([feats], dtype=np.float32)
                out = self._sess.run(None, {self._input_name: x})
                p = float(out[0].ravel()[0])
                return self._calibrate(p)
            except Exception:
                return None
        if self._meta and self._meta.weights is not None and self._meta.bias is not None:
            w = self._meta.weights
            b = float(self._meta.bias)
            n = min(len(w), len(feats))
            s = b + sum(float(w[i]) * float(feats[i]) for i in range(n))
            p = self._sigmoid(s)
            return self._calibrate(p)
        return None
