"""B HTTP API 테스트 — mock 검출기로 계약(docs/03-messages.md §6)만 본다. 모델·mediapipe 불필요."""
import cv2
import numpy as np
import pytest

pytest.importorskip("fastapi")  # 호스트에 fastapi 가 없으면 건너뜀 (pip install fastapi)
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from shared.schemas import NUM_LANDMARKS, DetectResponse  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # with → lifespan(검출기 생성·워밍업)이 실행된다
        yield c


def jpeg(w: int = 480, h: int = 360) -> bytes:
    return cv2.imencode(".jpg", np.full((h, w, 3), 128, np.uint8))[1].tobytes()


def test_health(client):
    body = client.get("/health").json()
    assert body["ok"] is True and body["backend"] == "mock"


def test_detect_matches_contract(client):
    r = client.post("/v1/detect", content=jpeg(), headers={
        "Content-Type": "image/jpeg", "X-Session": "apitest", "X-Seq": "128", "X-Ts-Ms": "1761710000123"})
    assert r.status_code == 200
    det = DetectResponse.model_validate(r.json())
    assert (det.seq, det.w, det.h, det.backend) == (128, 480, 360, "mock")
    assert len(det.hands) == 1 and len(det.hands[0].landmarks) == NUM_LANDMARKS
    assert {"decode", "wait", "infer"} <= {p.split(";")[0].strip() for p in r.headers["server-timing"].split(",")}


def test_detect_without_headers_uses_defaults(client):
    r = client.post("/v1/detect", content=jpeg(), headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200 and r.json()["seq"] == 0


def test_broken_jpeg_is_400(client):
    r = client.post("/v1/detect", content=b"not a jpeg", headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 400


def test_delete_session_is_204_even_if_unknown(client):
    assert client.delete("/v1/sessions/apitest").status_code == 204
    assert client.delete("/v1/sessions/never-seen").status_code == 204
