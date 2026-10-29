"""손 랜드마크 검출기. mediapipe(실제) / mock(가짜 손, A 개발용)."""
from __future__ import annotations

import logging
import math
import os
import time
from collections import OrderedDict
from typing import Protocol

import numpy as np

from shared.fake_hand import fake_hand
from shared.schemas import Hand

log = logging.getLogger("b-vision")

MODEL_PATH = os.getenv("MODEL_PATH", "/models/hand_landmarker.task")
NUM_HANDS = int(os.getenv("NUM_HANDS", "1"))
MIN_DETECTION_CONF = float(os.getenv("MIN_DETECTION_CONF", "0.5"))
# 손 존재 점수가 이보다 낮으면 손바닥 검출을 다시 돌린다. 없으면 예전처럼 MIN_DETECTION_CONF 를 따른다
MIN_PRESENCE_CONF = float(os.getenv("MIN_PRESENCE_CONF", str(MIN_DETECTION_CONF)))
MIN_TRACKING_CONF = float(os.getenv("MIN_TRACKING_CONF", "0.5"))
RUNNING_MODE = os.getenv("RUNNING_MODE", "video")
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "4"))


class Detector(Protocol):
    name: str

    @property
    def active_sessions(self) -> int: ...

    def warmup(self) -> None: ...

    def detect(self, session: str, rgb: np.ndarray, ts_ms: int) -> list[Hand]: ...

    def close(self, session: str) -> None: ...

    def close_all(self) -> None: ...


class MediaPipeDetector:
    """세션마다 HandLandmarker 1개. VIDEO 모드는 타임스탬프가 단조 증가해야 해서 세션끼리 공유하지 않는다."""

    name = "mediapipe"

    def __init__(self) -> None:
        if not os.path.isfile(MODEL_PATH):
            raise FileNotFoundError(f"모델 파일이 없습니다: {MODEL_PATH} (MODEL_PATH 확인)")
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

        self._mp = mp
        self._HandLandmarker = HandLandmarker
        self._options = lambda: HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=MODEL_PATH, delegate=BaseOptions.Delegate.CPU),
            running_mode=RunningMode.VIDEO if RUNNING_MODE == "video" else RunningMode.IMAGE,
            num_hands=NUM_HANDS,
            min_hand_detection_confidence=MIN_DETECTION_CONF,
            min_hand_presence_confidence=MIN_PRESENCE_CONF,
            min_tracking_confidence=MIN_TRACKING_CONF,
        )
        self._sessions: OrderedDict[str, tuple[object, int]] = OrderedDict()  # session → (landmarker, last_ts)

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    def warmup(self) -> None:
        """서버 시작 때 1회: 모델 로드·첫 추론 비용을 미리 치르고, 모델이 깨졌으면 여기서 실패한다."""
        self.detect("__warmup__", np.zeros((240, 320, 3), np.uint8), 0)
        self.close("__warmup__")

    def _get(self, session: str):
        if session in self._sessions:
            self._sessions.move_to_end(session)
            return self._sessions[session]
        if len(self._sessions) >= MAX_SESSIONS:  # LRU 정리
            old, (lm, _) = self._sessions.popitem(last=False)
            lm.close()
            log.info("세션 %s 정리 (LRU, 최대 %d개)", old, MAX_SESSIONS)
        entry = (self._HandLandmarker.create_from_options(self._options()), -1)
        self._sessions[session] = entry
        return entry

    def detect(self, session: str, rgb: np.ndarray, ts_ms: int) -> list[Hand]:
        lm, last_ts = self._get(session)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        if RUNNING_MODE == "video":
            ts_ms = max(ts_ms, last_ts + 1)  # 단조 증가 보정
            self._sessions[session] = (lm, ts_ms)
            result = lm.detect_for_video(image, ts_ms)
        else:
            result = lm.detect(image)

        hands = []
        for i, pts in enumerate(result.hand_landmarks):
            cat = result.handedness[i][0]
            hands.append(Hand(
                handedness=cat.category_name, score=round(cat.score, 3),
                landmarks=[(round(p.x, 4), round(p.y, 4), round(p.z, 4)) for p in pts],
            ))
        return hands

    def close(self, session: str) -> None:
        entry = self._sessions.pop(session, None)
        if entry:
            entry[0].close()

    def close_all(self) -> None:
        for session in list(self._sessions):
            self.close(session)


class MockDetector:
    """검지가 원을 그리는 가짜 손. 3초마다 draw(검지만) ↔ hover(검지+중지) 손 모양이 바뀐다."""

    name = "mock"
    active_sessions = 0

    def warmup(self) -> None:
        pass

    def detect(self, session: str, rgb: np.ndarray, ts_ms: int) -> list[Hand]:
        t = time.time()
        cx, cy = 0.5 + 0.25 * math.cos(t), 0.5 + 0.25 * math.sin(t)  # 검지 끝 위치
        two_fingers = int(t / 3) % 2 == 1
        return [Hand(handedness="Right", score=0.99, landmarks=fake_hand(cx, cy, "hover" if two_fingers else "draw"))]

    def close(self, session: str) -> None:
        pass

    def close_all(self) -> None:
        pass


def make_detector() -> Detector:
    return MockDetector() if os.getenv("VISION_BACKEND", "mediapipe") == "mock" else MediaPipeDetector()
