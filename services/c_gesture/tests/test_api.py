"""C HTTP API 테스트 — 계약 샘플(shared/samples)을 그대로 보내본다."""
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")  # 호스트에 fastapi 가 없으면 건너뜀 (pip install fastapi)
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[3] / "shared" / "samples"
client = TestClient(app)


def test_health():
    assert client.get("/health").json()["ok"] is True


def test_interpret_sample_then_reset_and_delete():
    body = json.loads((SAMPLES / "interpret_request.json").read_text(encoding="utf-8"))
    body["session"] = "apitest"
    r = client.post("/v1/interpret", json=body)
    assert r.status_code == 200
    assert r.json()["seq"] == body["seq"] and r.json()["cursor"] is not None

    r = client.post("/v1/sessions/apitest/reset")
    assert r.status_code == 200 and isinstance(r.json()["commands"], list)

    assert client.delete("/v1/sessions/apitest").status_code == 204
    assert client.post("/v1/sessions/apitest/reset").json() == {"commands": []}


def test_empty_hands_returns_null_cursor():
    body = json.loads((SAMPLES / "interpret_request.json").read_text(encoding="utf-8"))
    body.update(session="apitest2", hands=[])
    r = client.post("/v1/interpret", json=body).json()
    assert r["gesture"] == "none" and r["cursor"] is None and r["landmarks"] is None
