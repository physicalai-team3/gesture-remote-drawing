"""손 모양 규칙: 랜드마크 21개 → 손가락 5개 펴짐 여부 → 제스처. 규칙표: docs/02-containers.md (Container C)."""
from __future__ import annotations

import math
from typing import Sequence

Point = Sequence[float]

WRIST = 0
THUMB_IP, THUMB_TIP = 3, 4
INDEX_MCP = 5
MIDDLE_MCP = 9
PINKY_MCP = 17
# (PIP, TIP) — 검지·중지·약지·소지
FINGER_JOINTS = [(6, 8), (10, 12), (14, 16), (18, 20)]
INDEX_TIP = 8
PALM_CENTER = 9  # 중지 MCP — 지우개 위치


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def fingers_extended(lm: Sequence[Point], extend_ratio: float = 1.15) -> list[bool]:
    """[엄지, 검지, 중지, 약지, 소지]. 손 회전에 강하도록 '손목까지의 거리' 비율로 판정한다."""
    w = lm[WRIST]
    out = []
    # 엄지: 끝(4)이 IP(3)보다 소지 MCP(17)에서 충분히 멀면 폄 (엄지는 옆으로 펴지기 때문)
    out.append(_dist(lm[THUMB_TIP], lm[PINKY_MCP]) > _dist(lm[THUMB_IP], lm[PINKY_MCP]) * extend_ratio)
    for pip, tip in FINGER_JOINTS:
        out.append(_dist(lm[tip], w) > _dist(lm[pip], w) * extend_ratio)
    return out


def classify(fingers: list[bool]) -> str:
    """손가락 펴짐 패턴 → 제스처 (엄지는 draw/hover/color 에서 무시: 사람마다 엄지 자세가 제각각)."""
    thumb, index, middle, ring, pinky = fingers
    n = sum(fingers)
    if n == 5:
        return "erase"
    if index and not middle and not ring and not pinky:
        return "draw"
    if index and middle and not ring and not pinky:
        return "hover"
    if index and middle and ring and not pinky:
        return "color"
    if n == 0 or (thumb and n == 1):
        return "clear"  # 주먹 — CLEAR_HOLD_MS 유지해야 실제 clear (state.py)
    return "none"
