"""가짜 손 랜드마크 생성기 — B 의 mock 백엔드, C 테스트, 샘플 생성에서 같이 쓴다 (의존성 없음)."""
from __future__ import annotations

# 제스처별 [엄지, 검지, 중지, 약지, 소지] 펴짐 (docs/02-containers.md 규칙표)
POSES = {
    "draw": (False, True, False, False, False),
    "hover": (False, True, True, False, False),
    "color": (False, True, True, True, False),
    "erase": (True, True, True, True, True),
    "clear": (False, False, False, False, False),
    "zoom": (True, True, False, False, False),  # 엄지를 옆으로 벌린 핀치 (rules.thumb_spread 로 draw 와 구분)
}

# 손가락별 MCP 의 x 오프셋 (손 크기 단위). 엄지는 바깥쪽으로 펴진다
_FINGER_DX = (-0.9, -0.3, 0.0, 0.3, 0.6)


def fake_hand(tip_x: float, tip_y: float, pose: str = "draw", size: float = 0.12) -> list[tuple[float, float, float]]:
    """손목이 아래, 손가락이 위를 향하는 오른손(원본 이미지 기준). 검지 끝(8)이 (tip_x, tip_y)에 온다."""
    pts = [(0.0, 0.0)]  # 0 손목
    for i, (dx, up) in enumerate(zip(_FINGER_DX, POSES[pose])):
        if i == 0:  # 엄지: 펴면 옆으로 뻗고, 접으면 손바닥 쪽으로
            pts += [(-0.5, -0.4), (-0.8, -0.7), (-1.1, -0.9), (-1.4, -1.1)] if up else \
                   [(-0.5, -0.4), (-0.6, -0.7), (-0.4, -0.9), (-0.2, -1.0)]
        else:
            ys = (-1.0, -1.5, -1.8, -2.1) if up else (-1.0, -1.3, -1.1, -0.9)
            pts += [(dx, y) for y in ys]
    ox, oy = tip_x - pts[8][0] * size, tip_y - pts[8][1] * size
    return [(round(ox + x * size, 4), round(oy + y * size, 4), 0.0) for x, y in pts]
