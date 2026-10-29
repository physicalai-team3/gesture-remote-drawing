"""세션별 상태 머신: 제스처 디바운스 → 커서 스무딩 → 그리기 명령 생성."""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Optional

from shared.schemas import (Clear, Command, Cursor, InterpretRequest, InterpretResponse, SetColor, StrokeBegin,
                            StrokeEnd, StrokePoint, Zoom)

from .filters import OneEuro, OneEuro2D
from .rules import INDEX_TIP, PALM_CENTER, THUMB_TIP, classify, finger_ratios, pinch_distance, thumb_spread

log = logging.getLogger("c.gesture")


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
    zoom_thumb_out: float = float(os.getenv("ZOOM_THUMB_OUT", "0.8"))  # 엄지가 이만큼 벌어지면 핀치(zoom)
    zoom_gain: float = float(os.getenv("ZOOM_GAIN", "1.0"))  # 핀치 거리 1.0 변화당 e^gain 배 (오므림 0.1 → 활짝 1.4 ≈ 3.7배)
    zoom_deadband: float = float(os.getenv("ZOOM_DEADBAND", "0.05"))  # 핀치 거리가 이만큼 변해야 zoom 명령 (떨림 무시)
    edge_margin: float = float(os.getenv("EDGE_MARGIN", "0.1"))  # 카메라 가장자리 이만큼은 버리고 안쪽을 그림판 전체로 늘림


def _remap(v: float, margin: float) -> float:
    """카메라 좌표 [margin, 1-margin] → 그림판 [0, 1]. 손가락 판정 비율은 그대로 (균일 확대라서), 자르기는 커서만."""
    return (v - margin) / (1.0 - 2 * margin)


CURSOR_MODE = {"draw": "draw", "hover": "hover", "erase": "erase", "zoom": "zoom"}
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
    raw_pt: Optional[tuple[int, float, float]] = None  # 필터 전 커서 (기준 랜드마크, x, y) — 점프 감지용
    zoom_center: Optional[tuple[float, float]] = None  # 핀치를 시작한 위치 — 이 점을 중심으로 확대
    zoom_ref: Optional[float] = None  # 마지막 zoom 명령을 보낸 시점의 핀치 거리

    def __post_init__(self) -> None:
        self.tip_filter = OneEuro2D(self.p.min_cutoff, self.p.beta)
        self.palm_filter = OneEuro2D(self.p.min_cutoff, self.p.beta)
        self.pinch_filter = OneEuro(self.p.min_cutoff, self.p.beta)

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
        out.append(StrokeBegin(id=self.stroke_id, x=round(x, 4), y=round(y, 4), color=palette[self.color_idx % len(palette)],
                               width=req.config.width, tool=tool))

    def reset(self) -> list[Command]:
        out: list[Command] = []
        self._end(out)
        self.stable = self.candidate = "none"
        self.count = 0
        self.fist_since_ms, self.clear_fired = None, False
        self.raw_pt = self.zoom_center = self.zoom_ref = None
        self.tip_filter.reset()
        self.palm_filter.reset()
        return out

    # ── 메인 ──
    def update(self, req: InterpretRequest) -> InterpretResponse:
        out: list[Command] = []
        t = req.t_ms

        if not req.hands:
            # 손이 잠깐 안 보이는 건 무시하고, LOST_HAND_MS 넘으면 획 종료 + 제스처 상태도 초기화
            # (그러지 않으면 주먹 쥔 채 손을 뺐다 넣을 때 이전 stable 제스처가 디바운스 없이 이어진다)
            if t - self.last_hand_ms > self.p.lost_hand_ms:
                out.extend(self.reset())
            return InterpretResponse(seq=req.seq, gesture="none", commands=out)

        if t - self.last_hand_ms > self.p.lost_hand_ms:  # 손이 다시 나타남 → 필터 초기화 (이전 위치에서 끌려오지 않게)
            self.tip_filter.reset()
            self.palm_filter.reset()
        self.last_hand_ms = t

        hand = max(req.hands, key=lambda h: h.score)  # 손이 여러 개면 가장 확실한 손
        m = self.p.edge_margin
        lm = [(_remap((1.0 - x) if req.config.mirror else x, m), _remap(y, m)) for x, y, _ in hand.landmarks]
        ratios = finger_ratios(lm)
        pinch, thumb_out = pinch_distance(lm), thumb_spread(lm)
        log.debug("%s seq=%d pinch=%.2f thumb_out=%.2f ratios=[%s]", req.session, req.seq, pinch, thumb_out,
                  " ".join(f"{r:.2f}" for r in ratios))
        fingers = [r > self.p.extend_ratio for r in ratios]
        raw = classify(fingers, thumb_out, self.p.zoom_thumb_out)
        if raw == "clear" and self.stable == "zoom" and thumb_out > self.p.zoom_thumb_out:
            raw = "zoom"  # 핀치를 꽉 오므리다 검지가 굽어도 주먹(전체 지우기)으로 넘어가지 않게
        if raw != self.candidate:  # 손 모양이 바뀔 때만 기록 (실제 손 튜닝용: docker compose logs c-gesture)
            log.info("%s seq=%d raw=%s ratios=[%s]", req.session, req.seq, raw, " ".join(f"{r:.2f}" for r in ratios))

        # ① 디바운스: 같은 제스처가 N프레임 연속이어야 전환
        if raw == self.candidate:
            self.count += 1
        else:
            self.candidate, self.count = raw, 1
        entered = self.count >= self.p.debounce_frames and raw != self.stable
        if entered:
            self.stable = raw
            if raw == "zoom":  # 핀치 시작: 중심 고정, 기준 거리는 다음 프레임부터 (진입 순간 튐 방지)
                (ax, ay), (bx, by) = lm[THUMB_TIP], lm[INDEX_TIP]
                self.zoom_center = (min(max((ax + bx) / 2, 0.0), 1.0), min(max((ay + by) / 2, 0.0), 1.0))
                self.zoom_ref = None
                self.pinch_filter.reset()
            if raw == "color":
                self.color_idx += 1
                palette = req.config.palette or ["#111111"]
                out.append(SetColor(color=palette[self.color_idx % len(palette)]))
        g = self.stable

        # ② 커서: 그리기·이동은 검지 끝, 지우개는 손바닥 중심
        anchor, filt = (PALM_CENTER, self.palm_filter) if g == "erase" else (INDEX_TIP, self.tip_filter)
        rx, ry = lm[anchor]
        # 점프 감지는 필터 '전' 좌표로: 필터를 거치면 순간이동도 여러 프레임에 걸친 이동으로 뭉개져서 못 잡는다
        jumped = (self.raw_pt is not None and self.raw_pt[0] == anchor
                  and math.hypot(rx - self.raw_pt[1], ry - self.raw_pt[2]) > self.p.jump_max)
        self.raw_pt = (anchor, rx, ry)
        if jumped:
            filt.reset()  # 새 위치로 바로 이동 (이전 위치에서 끌려오지 않게)
        x, y = filt(rx, ry, t / 1000.0)
        x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)

        # ③ 획 상태 머신
        if g in TOOL:
            tool = TOOL[g]
            if self.stroke_id is None or self.stroke_tool != tool or jumped:  # 튐 → 획을 끊고 새로 시작
                self._begin(x, y, tool, req, out)
            else:
                d = math.hypot(x - self.last_pt[0], y - self.last_pt[1])
                if d >= self.p.min_move:
                    out.append(StrokePoint(id=self.stroke_id, x=round(x, 4), y=round(y, 4)))
                    self.last_pt = (x, y)
        else:
            self._end(out)

        # ④ 핀치 거리 변화 → 확대·축소 (휴대폰 핀치와 같은 방향: 벌리면 확대)
        # 거리의 '비율'이 아니라 '차이'로 계산한다: 끝까지 붙이면 거리가 0.02~0.1 이라 비율로는 작은 떨림도 몇 배로 튄다
        if g == "zoom":
            d = self.pinch_filter(pinch, t / 1000.0)
            if self.zoom_ref is None:
                self.zoom_ref = d
            elif abs(d - self.zoom_ref) >= self.p.zoom_deadband:
                cx, cy = self.zoom_center
                factor = math.exp(self.p.zoom_gain * (d - self.zoom_ref))
                out.append(Zoom(factor=round(factor, 4), x=round(cx, 4), y=round(cy, 4)))
                self.zoom_ref = d
            x, y = self.zoom_center  # 커서는 확대 중심에 고정해서 보여준다

        # ⑤ 주먹 유지 → 전체 지우기 (1회)
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
            debug={"fingers": fingers, "ratios": [round(r, 2) for r in ratios], "pinch": round(pinch, 2),
                   "thumb_out": round(thumb_out, 2), "raw_gesture": raw,
                   "stable_count": self.count},
        )
