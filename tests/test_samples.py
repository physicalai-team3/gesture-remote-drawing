"""계약 샘플이 스키마에 맞는지 검사: python -m pytest tests"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.schemas import DetectResponse, InterpretRequest, InterpretResponse  # noqa: E402

SAMPLES = ROOT / "shared" / "samples"
MODELS = {"detect_response": DetectResponse, "interpret_request": InterpretRequest, "interpret_response": InterpretResponse}


def test_samples_match_schema():
    files = sorted(SAMPLES.glob("*.json"))
    assert files
    for f in files:
        model = next(m for prefix, m in MODELS.items() if f.stem.startswith(prefix))
        model.model_validate(json.loads(f.read_text(encoding="utf-8")))
