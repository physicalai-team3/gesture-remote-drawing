"""세션별 상태 머신: 제스처 디바운스 → 커서 스무딩 → 그리기 명령 생성."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

from shared.schemas import (Clear, Command, Cursor, InterpretRequest, InterpretResponse, SetColor, StrokeBegin,
                            StrokeEnd, StrokePoint)

from .filters import OneEuro2D
from .rules import INDEX_TIP, PALM_CENTER, classify, fingers_extended


@dataclass
class Params:
    debounce_frames: int = int(os.getenv("DEBOUNCE_FRAMES", "3"))
    extend_ratio: float = float(os.getenv("EXTEND_RATIO", "1.15"))
    lost_hand_ms: int = int(os.getenv("LOST_HAND_MS", "300"))
    clear_hold_ms: int = int(os.getenv("CLEAR_HOLD_MS", "1500"))
    jump_max: float = float(os.getenv("JUMP_MAX", "0.25"))
    min_move: float = float(os.getenv("MIN_MOVE", "0.003"))
    min_cutoff: float = float(os.getenv("ONE_EURO_MIN_CUTOFF", "1.0"))
    beta: float = float(os.getenv("ONE_EURO_BETA", "0.02"))


CURSOR_MODE = {"draw": "draw", "hover": "hover", "erase": "erase"}
TOOL = {"draw": "pen", "erase": "eraser"}


@dataclass
class GestureSession:
    p: Params = field(default_factory=Params)
    stable: str = "none"  # 디바운스를 통과한 제스처
    candidate: str = "none"
    count: int = 0
    stroke_id: Optional[int] = None
    stroke_tool: Optional[str] = None
    last_pt: Optional[tuple[float, float]] = None
    next_id: int = 0
    color_idx: int = 0
    last_hand_ms: int = 0
    fist_since_ms: Optional[int] = None
    clear_fired: bool = False

    def __post_init__(self) -> None:
        self.tip_filter = OneEuro2D(self.p.min_cutoff, self.p.beta)
        self.palm_filter = OneEuro2D(self.p.min_cutoff, self.p.beta)

    # ── 획 헬퍼 ──
    def _end(self, out: list[Command]) -> None:
        if self.stroke_id is not None:
            out.append(StrokeEnd(id=self.stroke_id))
        self.stroke_id = self.stroke_tool = self.last_pt = None

    def _begin(self, x: float, y: float, tool: str, req: InterpretRequest, out: list[Command]) -> None:
        self._end(out)
        palette = req.config.palette or ["#111111"]
        self.stroke_id, self.stroke_tool, self.last_pt = self.next_id, tool, (x, y)
        self.next_id += 1
        out.append(StrokeBegin(id=self.stroke_id, x=x, y=y, color=palette[self.color_idx % len(palette)],
                               width=req.config.width, tool=tool))

    def reset(self) -> list[Command]:
        out: list[Command] = []
        self._end(out)
        self.stable = self.candidate = "none"
        self.count = 0
        self.fist_since_ms, self.clear_fired = None, False
        self.tip_filter.reset()
        self.palm_filter.reset()
        return out

    # ── 메인 ──
    def update(self, req: InterpretRequest) -> InterpretResponse:
        out: list[Command] = []
        t = req.t_ms

        if not req.hands:
            # 손이 잠깐 안 보이는 건 무시하고, LOST_HAND_MS 넘으면 획 종료
            if self.stroke_id is not None and t - self.last_hand_ms > self.p.lost_hand_ms:
                out.extend(self.reset())
            return InterpretResponse(seq=req.seq, gesture="none", commands=out)

        if t - self.last_hand_ms > self.p.lost_hand_ms:  # 손이 다시 나타남 → 필터 초기화 (이전 위치에서 끌려오지 않게)
            self.tip_filter.reset()
            self.palm_filter.reset()
        self.last_hand_ms = t

        hand = req.hands[0]
        lm = [((1.0 - x) if req.config.mirror else x, y) for x, y, _ in hand.landmarks]
        fingers = fingers_extended(lm, self.p.extend_ratio)
        raw = classify(fingers)

        # ① 디바운스: 같은 제스처가 N프레임 연속이어야 전환
        if raw == self.candidate:
            self.count += 1
        else:
            self.candidate, self.count = raw, 1
        entered = self.count >= self.p.debounce_frames and raw != self.stable
        if entered:
            self.stable = raw
            if raw == "color":
                self.color_idx += 1
                palette = req.config.palette or ["#111111"]
                out.append(SetColor(color=palette[self.color_idx % len(palette)]))
        g = self.stable

        # ② 커서: 그리기·이동은 검지 끝, 지우개는 손바닥 중심
        t_s = t / 1000.0
        if g == "erase":
            x, y = self.palm_filter(*lm[PALM_CENTER], t_s)
        else:
            x, y = self.tip_filter(*lm[INDEX_TIP], t_s)
        x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)

        # ③ 획 상태 머신
        if g in TOOL:
            tool = TOOL[g]
            if self.stroke_id is None or self.stroke_tool != tool:
                self._begin(x, y, tool, req, out)
            else:
                d = math.hypot(x - self.last_pt[0], y - self.last_pt[1])
                if d > self.p.jump_max:  # 튐 → 획을 끊고 새로 시작
                    self._begin(x, y, tool, req, out)
                elif d >= self.p.min_move:
                    out.append(StrokePoint(id=self.stroke_id, x=round(x, 4), y=round(y, 4)))
                    self.last_pt = (x, y)
        else:
            self._end(out)

        # ④ 주먹 유지 → 전체 지우기 (1회)
        if g == "clear":
            if self.fist_since_ms is None:
                self.fist_since_ms = t
            if not self.clear_fired and t - self.fist_since_ms >= self.p.clear_hold_ms:
                out.append(Clear())
                self.clear_fired = True
        else:
            self.fist_since_ms, self.clear_fired = None, False

        return InterpretResponse(
            seq=req.seq, gesture=g,
            cursor=Cursor(x=round(x, 4), y=round(y, 4), mode=CURSOR_MODE.get(g, "idle")),
            commands=out,
            landmarks=[(round(a, 4), round(b, 4)) for a, b in lm],
            debug={"fingers": fingers, "raw_gesture": raw, "stable_count": self.count},
        )
