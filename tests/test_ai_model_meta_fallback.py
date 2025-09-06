import json
import math
from pathlib import Path
from crypto_ai_bot.core.domain.signals.ai_model import AIModel

def _write_meta(tmp_path: Path, a=None, b=None, ctype=None):
    meta = {
        "feature_order": ["x1", "x2"],
        "weights": [1.0, -0.5],
        "bias": 0.0,
        "calibration": {} if a is None and b is None else {"a": a, "b": b, "type": ctype},
    }
    p = tmp_path / "meta.json"
    p.write_text(json.dumps(meta), encoding="utf-8")
    return p

def test_ai_model_linear_calibration(tmp_path):
    meta = _write_meta(tmp_path, a=1.0, b=0.0, ctype="linear")
    m = AIModel(model_path=None, meta_path=meta)
    assert m.ready
    p = m.predict_proba({"x1": 3.0, "x2": 1.0})
    assert p is not None and 0.0 <= p <= 1.0

def test_ai_model_platt_calibration(tmp_path):
    meta = _write_meta(tmp_path, a=1.2, b=-0.3, ctype="platt")
    m = AIModel(model_path=None, meta_path=meta)
    p = m.predict_proba({"x1": 3.0, "x2": 1.0})
    assert p is not None and 0.0 <= p <= 1.0
