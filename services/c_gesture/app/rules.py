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


def finger_ratios(lm: Sequence[Point]) -> list[float]:
    """[엄지, 검지, 중지, 약지, 소지] 펴짐 정도. 손 회전에 강하도록 '손목까지의 거리' 비율 (펴면 ~1.3+, 접으면 ~1 이하)."""
    w = lm[WRIST]
    # 엄지: 끝(4)과 IP(3)의 소지 MCP(17)까지 거리 비 (엄지는 옆으로 펴지기 때문)
    out = [_dist(lm[THUMB_TIP], lm[PINKY_MCP]) / max(_dist(lm[THUMB_IP], lm[PINKY_MCP]), 1e-6)]
    for pip, tip in FINGER_JOINTS:
        out.append(_dist(lm[tip], w) / max(_dist(lm[pip], w), 1e-6))
    return out


def fingers_extended(lm: Sequence[Point], extend_ratio: float = 1.15) -> list[bool]:
    """[엄지, 검지, 중지, 약지, 소지] 펴짐 여부."""
    return [r > extend_ratio for r in finger_ratios(lm)]


def _palm(lm: Sequence[Point]) -> float:
    """손 크기 기준 (손목~중지 뿌리). 거리를 이걸로 나누면 카메라와의 거리에 무관해진다."""
    return max(_dist(lm[WRIST], lm[MIDDLE_MCP]), 1e-6)


def thumb_spread(lm: Sequence[Point]) -> float:
    """엄지 끝 ~ 검지 뿌리 거리 / 손 크기. 엄지를 접으면 ~0.3 이하, 옆으로 벌리면(L자·핀치) ~1.3 이상 (실측).
    엄지 '펴짐 비율'은 흔들리지만 엄지 끝 '위치'는 안정적이라 핀치 판정에 쓴다."""
    return _dist(lm[THUMB_TIP], lm[INDEX_MCP]) / _palm(lm)


def pinch_distance(lm: Sequence[Point]) -> float:
    """엄지 끝 ~ 검지 끝 거리 / 손 크기. 오므리면 ~0.5, 벌리면 ~1.7 (실측)."""
    return _dist(lm[THUMB_TIP], lm[INDEX_TIP]) / _palm(lm)


def classify(fingers: list[bool], thumb_out: float = 0.0, zoom_thumb_out: float = 0.8) -> str:
    """손가락 펴짐 패턴 → 제스처. 엄지 펴짐은 무시한다: 사람마다 엄지 자세가 제각각이고 판정도 가장 흔들린다.
    대신 검지만 편 상태에서 엄지 끝이 옆으로 벌어져 있으면(thumb_out) 핀치 = zoom."""
    _thumb, index, middle, ring, pinky = fingers
    pattern = (index, middle, ring, pinky)
    if pattern == (True, False, False, False) and thumb_out > zoom_thumb_out:
        return "zoom"
    return {
        (True, True, True, True): "erase",
        (True, False, False, False): "draw",
        (True, True, False, False): "hover",
        (True, True, True, False): "color",
        (False, False, False, False): "clear",  # 주먹 — CLEAR_HOLD_MS 유지해야 실제 clear (state.py)
    }.get(pattern, "none")
