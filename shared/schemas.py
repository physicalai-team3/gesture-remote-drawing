"""서비스 간 메시지 계약 — docs/03-messages.md 와 항상 함께 수정한다."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field

CONTRACT_VERSION = 1
NUM_LANDMARKS = 21

Gesture = Literal["draw", "hover", "erase", "color", "clear", "none"]
CursorMode = Literal["draw", "hover", "erase", "idle"]
Tool = Literal["pen", "eraser"]

DEFAULT_PALETTE = ["#111111", "#e53935", "#1e88e5", "#43a047", "#fdd835"]


# ── B 출력: 손 1개 ──
class Hand(BaseModel):
    handedness: str  # MediaPipe 원본 "Left" | "Right" (전면 카메라면 반대로 나옴)
    score: float
    # [x, y, z] × 21. x·y 는 원본 이미지 기준 0~1 (반전 안 함)
    landmarks: list[tuple[float, float, float]] = Field(min_length=NUM_LANDMARKS, max_length=NUM_LANDMARKS)


# ── A → B: POST /v1/detect (body=JPEG, 헤더 X-Session / X-Seq / X-Ts-Ms) ──
class DetectResponse(BaseModel):
    v: int = CONTRACT_VERSION
    seq: int
    w: int
    h: int
    backend: str  # mediapipe | mock
    infer_ms: float
    hands: list[Hand] = []


# ── 세션 설정 (A 보관, C 요청에 실어 보냄) ──
class SessionConfig(BaseModel):
    mirror: bool = True  # 전면 카메라면 True (폰 hello 의 facing 으로 기본값 결정)
    width: float = 6.0  # 펜 굵기, 짧은 변 1000px 환산
    palette: list[str] = Field(default_factory=lambda: list(DEFAULT_PALETTE))


# ── A → C: POST /v1/interpret ──
class InterpretRequest(BaseModel):
    v: int = CONTRACT_VERSION
    session: str
    seq: int
    t_ms: int
    hands: list[Hand] = []
    config: SessionConfig = Field(default_factory=SessionConfig)


class Cursor(BaseModel):
    x: float
    y: float
    mode: CursorMode


# ── 그리기 명령 (C 생성 → A 전달 → board 실행) ──
class StrokeBegin(BaseModel):
    op: Literal["stroke_begin"] = "stroke_begin"
    id: int
    x: float
    y: float
    color: str
    width: float
    tool: Tool = "pen"


class StrokePoint(BaseModel):
    op: Literal["stroke_point"] = "stroke_point"
    id: int
    x: float
    y: float


class StrokeEnd(BaseModel):
    op: Literal["stroke_end"] = "stroke_end"
    id: int


class SetColor(BaseModel):
    op: Literal["set_color"] = "set_color"
    color: str


class Clear(BaseModel):
    op: Literal["clear"] = "clear"


Command = Annotated[Union[StrokeBegin, StrokePoint, StrokeEnd, SetColor, Clear], Field(discriminator="op")]


class InterpretResponse(BaseModel):
    v: int = CONTRACT_VERSION
    seq: int
    gesture: Gesture
    cursor: Optional[Cursor] = None
    commands: list[Command] = []
    landmarks: Optional[list[tuple[float, float]]] = None  # mirror 적용된 [x, y] × 21 (디버그 오버레이용)
    debug: dict[str, Any] = {}


class ResetResponse(BaseModel):
    commands: list[Command] = []


# ── A → board: WS frame_result ──
class Timing(BaseModel):
    b_ms: float
    c_ms: float
    total_ms: float


class FrameResult(BaseModel):
    type: Literal["frame_result"] = "frame_result"
    seq: int
    gesture: Gesture
    cursor: Optional[Cursor] = None
    commands: list[Command] = []
    landmarks: Optional[list[tuple[float, float]]] = None
    timing: Timing


class Health(BaseModel):
    ok: bool = True
    service: str
