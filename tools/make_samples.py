"""shared/samples/*.json 생성 — 상대방 코드 없이 테스트할 때 쓰는 계약 예제. 계약이 바뀌면 다시 실행."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "services" / "c_gesture")]

from app.state import GestureSession, Params  # noqa: E402
from shared.fake_hand import fake_hand  # noqa: E402
from shared.schemas import DetectResponse, Hand, InterpretRequest  # noqa: E402

OUT = ROOT / "shared" / "samples"


def dump(name, model):
    (OUT / name).write_text(json.dumps(model.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", name)


OUT.mkdir(exist_ok=True)
hand = Hand(handedness="Right", score=0.97, landmarks=fake_hand(0.45, 0.35, "draw"))
dump("detect_response.json", DetectResponse(seq=128, w=480, h=360, backend="mock", infer_ms=21.3, hands=[hand]))
dump("detect_response_empty.json", DetectResponse(seq=129, w=480, h=360, backend="mock", infer_ms=18.0, hands=[]))
req = InterpretRequest(session="k3x9q2", seq=128, t_ms=1761710000123, hands=[hand])
dump("interpret_request.json", req)
s = GestureSession(Params(debounce_frames=1))
dump("interpret_response.json", s.update(req))
