"""실제 MediaPipe 검출기 테스트. mediapipe 와 모델 파일(MODEL_PATH)이 있을 때만 돈다.

  MODEL_PATH=/path/to/hand_landmarker.task python -m pytest services/b_vision/tests
"""
import os

import numpy as np
import pytest

pytest.importorskip("mediapipe")
if not os.path.isfile(os.getenv("MODEL_PATH", "/models/hand_landmarker.task")):
    pytest.skip("모델 파일 없음 (MODEL_PATH 지정)", allow_module_level=True)

from app import detector as dmod  # noqa: E402

BLANK = np.zeros((360, 480, 3), np.uint8)


@pytest.fixture
def det():
    d = dmod.MediaPipeDetector()
    yield d
    d.close_all()


def test_warmup_leaves_no_session(det):
    det.warmup()
    assert det.active_sessions == 0


def test_blank_image_has_no_hands(det):
    assert det.detect("s", BLANK, 1000) == []


def test_timestamp_going_backwards_is_corrected(det):
    det.detect("s", BLANK, 1000)
    det.detect("s", BLANK, 500)  # MediaPipe 는 거꾸로 가면 ValueError → B 가 last+1 로 보정
    det.detect("s", BLANK, 500)
    assert det._sessions["s"][1] == 1002


def test_lru_closes_oldest_session(det, monkeypatch):
    monkeypatch.setattr(dmod, "MAX_SESSIONS", 2)
    for s in ("a", "b", "a", "c"):  # a 를 다시 써서 b 가 가장 오래된 세션이 된다
        det.detect(s, BLANK, 1000)
    assert list(det._sessions) == ["a", "c"]


def test_missing_model_file_fails_fast(monkeypatch):
    monkeypatch.setattr(dmod, "MODEL_PATH", "/nonexistent/hand_landmarker.task")
    with pytest.raises(FileNotFoundError):
        dmod.MediaPipeDetector()
