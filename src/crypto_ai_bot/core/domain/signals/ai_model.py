from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

try:
    import onnxruntime as rt  # type: ignore
except Exception:  # noqa: BLE001
    rt = None  # type: ignore

# Лёгкое логирование, без жёсткой зависимости (не провоцируем импорты при офлайн-инференсе)
try:
    from crypto_ai_bot.utils.logging import get_logger  # type: ignore

    _log = get_logger("signals.ai_model")
except Exception:  # noqa: BLE001

    class _Dummy:
        def debug(self, *a: Any, **k: Any) -> None: ...
        def warning(self, *a: Any, **k: Any) -> None: ...
        def error(self, *a: Any, **k: Any) -> None: ...
        def exception(self, *a: Any, **k: Any) -> None: ...

    _log = _Dummy()  # type: ignore


@dataclass
class AIModelMeta:
    feature_order: list[str]
    # Линейная логистическая регрессия как фолбэк (вес + смещение)
    bias: float | None = None
    weights: list[float] | None = None
    # Калибровка:
    # - история поддерживает linear (p' = clamp(a*p+b))
    # - добавлена поддержка platt (p' = sigmoid(a*logit(p)+b))
    calibration_type: str | None = None  # "linear" | "platt" | None
    calibration_a: float | None = None
    calibration_b: float | None = None
    # Опциональная стандартизация признаков
    mean: dict[str, float] | None = None
    std: dict[str, float] | None = None
    # Необязательные клипы по признакам
    clip_min: dict[str, float] | None = None
    clip_max: dict[str, float] | None = None


class AIModel:
    """
    Универсальный инференс-класс:
      - если доступен ONNX и файл существует — используем его;
      - иначе — фолбэк на логистическую регрессию из meta.json (weights+bias);
      - строгая валидация и нормализация признаков (mean/std/clip* из меты при наличии);
      - расширенная калибровка: linear и platt (обратимо совместимо с прежней схемой).
    Публичный API неизменён:
      - .ready -> bool
      - .predict_proba(feature_map: dict[str, float] | None) -> float | None  (0..1)
    """

    def __init__(self, model_path: str | Path | None = None, meta_path: str | Path | None = None) -> None:
        self._sess = None
        self._input_name = None
        self._meta: AIModelMeta | None = None

        # ONNX
        if model_path:
            p = Path(model_path)
            if rt is not None and p.exists():
                try:
                    self._sess = rt.InferenceSession(str(p), providers=["CPUExecutionProvider"])
                    # Берём имя первого входа (как было раньше)
                    self._input_name = self._sess.get_inputs()[0].name  # type: ignore[index]
                    _log.debug("onnx_session_ready", extra={"path": str(p)})
                except Exception:  # noqa: BLE001
                    self._sess = None
                    _log.warning("onnx_init_failed", extra={"path": str(p)})

        # META
        if meta_path:
            mp = Path(meta_path)
            if mp.exists():
                try:
                    raw = json.loads(mp.read_text(encoding="utf-8"))
                    calib = raw.get("calibration") or {}
                    # Обратная совместимость: если type отсутствует — считаем linear (как было)
                    calib_type = (calib.get("type") or "linear") if ("a" in calib or "b" in calib) else None
                    self._meta = AIModelMeta(
                        feature_order=list(raw.get("feature_order") or []),
                        bias=raw.get("bias"),
                        weights=(list(raw.get("weights") or []) or None),
                        calibration_type=calib_type,
                        calibration_a=calib.get("a"),
                        calibration_b=calib.get("b"),
                        mean=raw.get("mean") or None,
                        std=raw.get("std") or None,
                        clip_min=raw.get("clip_min") or None,
                        clip_max=raw.get("clip_max") or None,
                    )
                    _log.debug("meta_loaded", extra={"path": str(mp)})
                except Exception:  # noqa: BLE001
                    self._meta = None
                    _log.warning("meta_parse_failed", extra={"path": str(mp)})

    @property
    def ready(self) -> bool:
        if self._sess is not None and self._input_name:
            return True
        if self._meta and self._meta.weights and self._meta.bias is not None:
            return True
        return False

    # ---------- utils ----------
    @staticmethod
    def _sigmoid(x: float) -> float:
        # Численно стабильный сигмоид
        if x >= 0:
            z = math.exp(-x)
            return 1.0 / (1.0 + z)
        z = math.exp(x)
        return z / (1.0 + z)

    @staticmethod
    def _logit(p: float, eps: float = 1e-6) -> float:
        # Обратная функция к сигмоиду (для Platt calibration)
        p = min(1.0 - eps, max(eps, p))
        return math.log(p / (1.0 - p))

    @staticmethod
    def _clip(x: float, lo: float | None, hi: float | None) -> float:
        if lo is not None:
            x = max(lo, x)
        if hi is not None:
            x = min(hi, x)
        return x

    def _vectorize(self, feature_map: dict[str, float]) -> list[float]:
        """
        Составляем вектор признаков в нужном порядке.
        Если meta содержит mean/std — делаем стандартизацию.
        Если есть clip_min/clip_max — применяем клипы пост-факту.
        Если порядок отсутствует — берём отсортированные ключи (как раньше).
        """
        if self._meta and self._meta.feature_order:
            order = self._meta.feature_order
        else:
            order = sorted(feature_map.keys())

        feats: list[float] = []
        mean = (self._meta.mean if self._meta else None) or {}
        std = (self._meta.std if self._meta else None) or {}
        cmin = (self._meta.clip_min if self._meta else None) or {}
        cmax = (self._meta.clip_max if self._meta else None) or {}

        for k in order:
            v = float(feature_map.get(k, 0.0) or 0.0)
            # стандартизация, если есть параметры
            m = mean.get(k)
            s = std.get(k)
            if s is not None and s != 0 and m is not None:
                v = (v - float(m)) / float(s)
            # клипы (после стандартизации)
            v = self._clip(v, cmin.get(k), cmax.get(k))
            # финальная защита от NaN/inf
            if math.isnan(v) or math.isinf(v):
                v = 0.0
            feats.append(v)

        return feats

    def _calibrate(self, p: float) -> float:
        """Калибровка вероятности согласно meta (linear | platt)."""
        meta = self._meta
        if not meta or meta.calibration_a is None or meta.calibration_b is None:
            return max(0.0, min(1.0, p))

        a = float(meta.calibration_a)
        b = float(meta.calibration_b)
        ctype = (meta.calibration_type or "").lower()

        if ctype == "platt":
            # Platt scaling: p' = sigmoid(a*logit(p) + b)
            z = a * self._logit(p) + b
            return self._sigmoid(z)

        # По умолчанию (обратная совместимость): линейная калибровка
        z = a * p + b
        return max(0.0, min(1.0, z))

    # ---------- inference ----------
    def predict_proba(self, feature_map: dict[str, float] | None) -> float | None:
        if not feature_map:
            return None

        try:
            feats = self._vectorize(feature_map)

            # ONNX путь
            if self._sess is not None and self._input_name:
                try:
                    import numpy as np  # type: ignore

                    x = np.asarray([feats], dtype=np.float32)
                    out = self._sess.run(None, {self._input_name: x})
                    # предполагаем, что первый выход — вероятность; иначе берём первый скаляр
                    y = out[0]
                    p = float(getattr(y, "ravel", lambda: [y])()[0])
                    return self._calibrate(p)
                except Exception:  # noqa: BLE001
                    _log.warning("onnx_infer_failed", exc_info=True)
                    # не падаем — попробуем фолбэк (если есть)

            # Линейная регрессия (логистическая) фолбэк
            if self._meta and self._meta.weights is not None and self._meta.bias is not None:
                w = self._meta.weights
                b = float(self._meta.bias)
                n = min(len(w), len(feats))
                s = b + sum(float(w[i]) * float(feats[i]) for i in range(n))
                p = self._sigmoid(s)
                return self._calibrate(p)

            return None
        except Exception:  # noqa: BLE001
            _log.error("predict_failed", exc_info=True)
            return None
