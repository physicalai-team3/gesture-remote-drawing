"""A 없이 웹캠/동영상 → B → C 를 직접 호출하고 결과를 OpenCV 창에 그린다 (팀원 2 개발·튜닝용).

  docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build b-vision c-gesture
  python tools/replay_landmarks.py --src 0
q: 종료, c: 캔버스 지우기
"""
import argparse
import time

import cv2
import httpx
import numpy as np

BONES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
         (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]


def main(a):
    cap = cv2.VideoCapture(int(a.src) if a.src.isdigit() else a.src)
    client = httpx.Client(timeout=2.0)
    canvas = None
    strokes: dict[int, tuple] = {}  # id → (last_pt, color, width, tool)
    seq = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.resize(frame, (a.width, int(a.width * frame.shape[0] / frame.shape[1])))
        h, w = frame.shape[:2]
        if canvas is None:
            canvas = np.full_like(frame, 255)
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        t_ms = int(time.time() * 1000)

        det = client.post(f"{a.b}/v1/detect", content=jpg.tobytes(),
                          headers={"Content-Type": "image/jpeg", "X-Session": "replay", "X-Seq": str(seq), "X-Ts-Ms": str(t_ms)}).json()
        res = client.post(f"{a.c}/v1/interpret", json={"session": "replay", "seq": seq, "t_ms": t_ms, "hands": det["hands"],
                                                       "config": {"mirror": a.mirror}}).json()
        seq += 1

        # 그리기 명령 실행 (board.js 와 같은 의미)
        for c in res["commands"]:
            if c["op"] == "stroke_begin":
                strokes[c["id"]] = ((int(c["x"] * w), int(c["y"] * h)), c["color"], c["width"], c["tool"])
            elif c["op"] == "stroke_point" and c["id"] in strokes:
                p0, color, width, tool = strokes[c["id"]]
                p1 = (int(c["x"] * w), int(c["y"] * h))
                bgr = (255, 255, 255) if tool == "eraser" else tuple(int(color[i:i + 2], 16) for i in (5, 3, 1))
                cv2.line(canvas, p0, p1, bgr, int(width * (5 if tool == "eraser" else 1)), cv2.LINE_AA)
                strokes[c["id"]] = (p1, color, width, tool)
            elif c["op"] == "stroke_end":
                strokes.pop(c["id"], None)
            elif c["op"] == "clear":
                canvas[:] = 255

        view = cv2.flip(frame, 1) if a.mirror else frame.copy()
        if res.get("landmarks"):
            pts = [(int(x * w), int(y * h)) for x, y in res["landmarks"]]
            for i, j in BONES:
                cv2.line(view, pts[i], pts[j], (143, 157, 42), 2)
        dbg = res.get("debug", {})
        cv2.putText(view, f"{res['gesture']} raw={dbg.get('raw_gesture')} fingers={dbg.get('fingers')} B={det['infer_ms']}ms",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        cv2.imshow("replay", np.hstack([view, canvas]))
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("c"):
            canvas[:] = 255


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="0", help="웹캠 번호 또는 동영상 경로")
    p.add_argument("--b", default="http://localhost:8001")
    p.add_argument("--c", default="http://localhost:8002")
    p.add_argument("--width", type=int, default=480)
    p.add_argument("--no-mirror", dest="mirror", action="store_false")
    main(p.parse_args())
