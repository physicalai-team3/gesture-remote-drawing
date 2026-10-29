"""C 단위 테스트: cd services/c_gesture && python -m pytest tests  (PYTHONPATH 에 저장소 루트 필요 — conftest.py)"""
import math

import pytest

from app.rules import classify, fingers_extended, thumb_spread
from app.state import GestureSession, Params
from shared.fake_hand import POSES, fake_hand
from shared.schemas import Hand, InterpretRequest, SessionConfig


@pytest.mark.parametrize("pose", list(POSES))
def test_classify_fake_poses(pose):
    lm = [(x, y) for x, y, _ in fake_hand(0.5, 0.4, pose)]
    assert fingers_extended(lm) == list(POSES[pose])
    assert classify(fingers_extended(lm), thumb_spread(lm)) == pose


def req(seq, pose=None, x=0.5, y=0.4, mirror=False, hands=None):
    if hands is None:
        hands = [Hand(handedness="Right", score=0.9, landmarks=fake_hand(x, y, pose))] if pose else []
    return InterpretRequest(session="t", seq=seq, t_ms=1000 + seq * 66, hands=hands, config=SessionConfig(mirror=mirror))


def ops(res):
    return [c.op for c in res.commands]


def test_draw_begins_after_debounce_then_points():
    s = GestureSession(Params(debounce_frames=3))
    assert ops(s.update(req(0, "draw"))) == []
    assert ops(s.update(req(1, "draw"))) == []
    r = s.update(req(2, "draw"))
    assert ops(r) == ["stroke_begin"] and r.gesture == "draw"
    r = s.update(req(3, "draw", x=0.6))
    assert ops(r) == ["stroke_point"]


def test_hover_ends_stroke():
    s = GestureSession(Params(debounce_frames=1))
    s.update(req(0, "draw"))
    assert ops(s.update(req(1, "hover"))) == ["stroke_end"]


def test_lost_hand_ends_stroke_after_timeout():
    s = GestureSession(Params(debounce_frames=1, lost_hand_ms=300))
    s.update(req(0, "draw"))
    assert ops(s.update(req(1))) == []          # 66ms: 아직 유지
    assert ops(s.update(req(10))) == ["stroke_end"]  # 660ms: 종료


def test_color_fires_once_on_enter():
    s = GestureSession(Params(debounce_frames=1))
    assert ops(s.update(req(0, "color"))) == ["set_color"]
    assert ops(s.update(req(1, "color"))) == []


def test_fist_hold_clears_once():
    s = GestureSession(Params(debounce_frames=1, clear_hold_ms=500))
    fired = [ops(s.update(req(i, "clear"))) for i in range(15)]
    assert sum(f.count("clear") for f in fired) == 1


def test_mirror_flips_x():
    s = GestureSession(Params(debounce_frames=1, edge_margin=0.0))
    r = s.update(req(0, "draw", x=0.2, mirror=True))
    assert r.cursor.x == pytest.approx(0.8, abs=1e-3)


# ── 손가락 판정: 실제 손은 기울어지고, 멀고 가깝고, 왼손일 수 있다 ──
def transform(lm, angle_deg=0.0, scale=1.0, flip=False):
    """손목(0) 기준으로 회전·확대, flip 이면 좌우 반전(왼손)."""
    wx, wy = lm[0][0], lm[0][1]
    c, s_ = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    out = []
    for x, y, *_ in lm:
        dx, dy = (x - wx) * scale, (y - wy) * scale
        if flip:
            dx = -dx
        out.append((wx + dx * c - dy * s_, wy + dx * s_ + dy * c))
    return out


@pytest.mark.parametrize("pose", list(POSES))
@pytest.mark.parametrize("angle", [-60, -30, 30, 60, 90])
@pytest.mark.parametrize("scale", [0.5, 1.5])
@pytest.mark.parametrize("flip", [False, True])
def test_classify_robust_to_rotation_scale_and_left_hand(pose, angle, scale, flip):
    lm = transform(fake_hand(0.5, 0.5, pose), angle, scale, flip)
    assert classify(fingers_extended(lm), thumb_spread(lm)) == pose


def test_thumb_is_ignored():
    assert classify([False, True, True, True, True]) == "erase"  # 엄지만 접은 손바닥도 지우개
    assert classify([True, False, False, False, False]) == "clear"  # 엄지 내민 주먹
    assert classify([True, True, False, False, False]) == "draw"  # 엄지 펴고 검지 (L자)
    assert classify([False, False, False, False, True]) == "none"


# ── 상태 머신 ──
def test_erase_uses_eraser_tool_at_palm():
    s = GestureSession(Params(debounce_frames=1, edge_margin=0.0))
    r = s.update(req(0, "erase", x=0.5, y=0.3))
    (cmd,) = r.commands
    assert cmd.op == "stroke_begin" and cmd.tool == "eraser"
    assert r.cursor.mode == "erase" and r.cursor.y > 0.3  # 손바닥은 검지 끝보다 아래


def test_switch_draw_to_erase_ends_and_begins():
    s = GestureSession(Params(debounce_frames=1))
    s.update(req(0, "draw"))
    r = s.update(req(1, "erase"))
    assert ops(r) == ["stroke_end", "stroke_begin"] and r.commands[1].tool == "eraser"


def test_jump_breaks_stroke():
    s = GestureSession(Params(debounce_frames=1, jump_max=0.25))
    s.update(req(0, "draw", x=0.3))
    r = s.update(req(1, "draw", x=0.8))
    assert ops(r) == ["stroke_end", "stroke_begin"]
    assert r.cursor.x > 0.8  # 필터에 끌려오지 않고 새 위치로 바로 이동 (edge_margin 확대 포함)


def test_small_move_sends_nothing():
    s = GestureSession(Params(debounce_frames=1, min_move=0.01))
    s.update(req(0, "draw", x=0.5))
    assert ops(s.update(req(1, "draw", x=0.501))) == []


def test_lost_hand_resets_gesture_state():
    s = GestureSession(Params(debounce_frames=3, lost_hand_ms=300))
    for i in range(3):
        s.update(req(i, "hover"))
    assert s.stable == "hover"
    s.update(req(10))  # 손 사라지고 300ms 넘음 (획이 없어도)
    assert s.update(req(11, "draw")).gesture == "none"  # 디바운스를 처음부터 다시


def test_picks_highest_score_hand():
    s = GestureSession(Params(debounce_frames=1))
    weak = Hand(handedness="Left", score=0.3, landmarks=fake_hand(0.5, 0.4, "erase"))
    strong = Hand(handedness="Right", score=0.95, landmarks=fake_hand(0.5, 0.4, "draw"))
    assert s.update(req(0, hands=[weak, strong])).gesture == "draw"


def test_edge_margin_stretches_center_to_full_board():
    s = GestureSession(Params(debounce_frames=1, edge_margin=0.1))
    assert s.update(req(0, "hover", x=0.1, y=0.1)).cursor.x == pytest.approx(0.0, abs=1e-3)
    s = GestureSession(Params(debounce_frames=1, edge_margin=0.1))
    assert s.update(req(0, "hover", x=0.5)).cursor.x == pytest.approx(0.5, abs=1e-3)


def test_reset_ends_stroke_once():
    s = GestureSession(Params(debounce_frames=1))
    s.update(req(0, "draw"))
    assert ops_list(s.reset()) == ["stroke_end"]
    assert s.reset() == []


def ops_list(cmds):
    return [c.op for c in cmds]


# ── 핀치 확대·축소 ──
def pinch_hand(k, x=0.5, y=0.4):
    """zoom 손에서 엄지 끝(4)을 검지 끝(8) 쪽으로 당긴다. k=1 이면 활짝, 작을수록 오므림."""
    lm = [list(p) for p in fake_hand(x, y, "zoom")]
    lm[4] = [lm[8][i] + k * (lm[4][i] - lm[8][i]) for i in range(3)]
    return [tuple(p) for p in lm]


def zreq(seq, k):
    return req(seq, hands=[Hand(handedness="Right", score=0.9, landmarks=pinch_hand(k))])


def zooms(res):
    return [c for c in res.commands if c.op == "zoom"]


def test_zoom_needs_thumb_spread():
    assert classify([False, True, False, False, False], thumb_out=1.3) == "zoom"
    assert classify([False, True, False, False, False], thumb_out=0.3) == "draw"  # 엄지 접은 그리기 (실측 ~0.2)


def test_zoom_spread_zooms_in_and_close_zooms_out():
    s = GestureSession(Params(debounce_frames=1, zoom_thumb_out=0.5))
    r = s.update(zreq(0, 0.6))
    assert r.gesture == "zoom" and r.cursor.mode == "zoom" and zooms(r) == []  # 진입 순간엔 확대 안 함
    out = [z for i, k in enumerate([0.7, 0.8, 0.9, 1.0, 1.0, 1.0], start=1) for z in zooms(s.update(zreq(i, k)))]
    assert out and all(z.factor > 1 for z in out)
    total = math.prod(z.factor for z in out)
    assert 1.2 < total < 1.9  # 핀치 거리 0.89 → 1.49 = e^0.6 ≈ 1.8배 (필터 지연으로 조금 덜)
    out = [z for i, k in enumerate([0.8, 0.6, 0.6, 0.6], start=10) for z in zooms(s.update(zreq(i, k)))]
    assert out and all(z.factor < 1 for z in out)


def test_zoom_closed_pinch_jitter_does_not_explode():
    """끝까지 붙인 핀치(실측 0.02~0.1)에서 흔들려도 배율이 튀지 않는다 (비율이 아니라 차이로 계산)."""
    s = GestureSession(Params(debounce_frames=1, zoom_thumb_out=0.5))
    s.update(zreq(0, 0.05))
    out = [z for i in range(1, 10) for z in zooms(s.update(zreq(i, 0.02 if i % 2 else 0.06)))]
    assert math.prod(z.factor for z in out) < 1.1


def test_zoom_center_is_fixed_at_pinch_start():
    s = GestureSession(Params(debounce_frames=1, zoom_thumb_out=0.5))
    c0 = s.update(zreq(0, 0.6)).cursor
    c1 = s.update(zreq(1, 1.0)).cursor
    assert (c0.x, c0.y) == (c1.x, c1.y)


def test_zoom_ignores_jitter():
    s = GestureSession(Params(debounce_frames=1, zoom_thumb_out=0.5, zoom_deadband=0.05))
    s.update(zreq(0, 0.8))
    assert [zooms(s.update(zreq(i, 0.8 + (0.005 if i % 2 else -0.005)))) for i in range(1, 8)] == [[]] * 7


def test_zoom_ends_stroke():
    s = GestureSession(Params(debounce_frames=1, zoom_thumb_out=0.5))
    s.update(req(0, "draw"))
    assert ops(s.update(zreq(1, 0.8))) == ["stroke_end"]


def test_tight_pinch_does_not_become_fist_clear():
    """핀치를 꽉 오므리다 검지가 굽어 '주먹'처럼 보여도 엄지가 벌어져 있으면 zoom 유지 → 전체 지우기 안 됨."""
    s = GestureSession(Params(debounce_frames=1, zoom_thumb_out=0.5, clear_hold_ms=100))
    s.update(zreq(0, 0.8))
    fist = [list(p) for p in fake_hand(0.5, 0.4, "clear")]
    zoom = fake_hand(0.5, 0.4, "zoom")
    dx, dy = fist[0][0] - zoom[0][0], fist[0][1] - zoom[0][1]
    for i in (1, 2, 3, 4):  # 엄지만 벌린 자세로 (손목 기준 맞춤)
        fist[i] = [zoom[i][0] + dx, zoom[i][1] + dy, 0.0]
    hand = Hand(handedness="Right", score=0.9, landmarks=[tuple(p) for p in fist])
    res = [s.update(req(i, hands=[hand])) for i in range(1, 10)]
    assert all(r.gesture == "zoom" for r in res)
    assert "clear" not in [op for r in res for op in ops(r)]
