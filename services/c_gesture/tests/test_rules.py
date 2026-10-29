"""C 단위 테스트: cd services/c_gesture && python -m pytest tests  (PYTHONPATH 에 저장소 루트 필요 — conftest.py)"""
import pytest

from app.rules import classify, fingers_extended
from app.state import GestureSession, Params
from shared.fake_hand import POSES, fake_hand
from shared.schemas import Hand, InterpretRequest, SessionConfig


@pytest.mark.parametrize("pose", list(POSES))
def test_classify_fake_poses(pose):
    lm = [(x, y) for x, y, _ in fake_hand(0.5, 0.4, pose)]
    assert fingers_extended(lm) == list(POSES[pose])
    assert classify(fingers_extended(lm)) == pose


def req(seq, pose=None, x=0.5, y=0.4, mirror=False):
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
    s = GestureSession(Params(debounce_frames=1))
    r = s.update(req(0, "draw", x=0.2, mirror=True))
    assert r.cursor.x == pytest.approx(0.8, abs=1e-3)
