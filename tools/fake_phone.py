"""폰 없이 A 에 프레임 송출 (팀원 1 개발용). 계약: docs/03-messages.md §3

  python tools/fake_phone.py --phone-url "http://localhost:8000/phone?s=k3x9q2&t=..."   # 그림판 QR 아래 주소
  python tools/fake_phone.py --phone-url ... --src 0          # 웹캠
  python tools/fake_phone.py --phone-url ... --src hand.mp4   # 동영상
--src 를 주지 않으면 회색 이미지를 보낸다 (B 가 mock 이면 이걸로 충분).
"""
import argparse
import asyncio
import json
import time
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
import websockets


async def main(a):
    u = urlparse(a.phone_url)
    q = parse_qs(u.query)
    ws_url = f"{'wss' if u.scheme == 'https' else 'ws'}://{u.netloc}/ws/phone?s={q['s'][0]}&t={q['t'][0]}"
    cap = None if a.src is None else cv2.VideoCapture(int(a.src) if a.src.isdigit() else a.src)
    blank = np.full((360, 480, 3), 128, np.uint8)

    async with websockets.connect(ws_url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "w": 480, "h": 360, "facing": "user", "ua": "fake_phone.py"}))
        cfg = {"fps": 15, "width": 480, "quality": 0.7, "max_inflight": 2}
        inflight, sent, t_end = 0, 0, time.time() + a.duration

        async def reader():
            nonlocal inflight, cfg
            async for msg in ws:
                m = json.loads(msg)
                if m["type"] == "config":
                    cfg.update(m)
                elif m["type"] == "ack":
                    inflight = max(0, inflight - 1)
                elif m["type"] == "stats":
                    print(f"sent={sent} server fps={m['fps_done']} latency={m['latency_ms']}ms hand={m['hand']}")

        task = asyncio.create_task(reader())
        while time.time() < t_end:
            t0 = time.time()
            if inflight < cfg["max_inflight"]:
                frame = blank
                if cap is not None:
                    ok, frame = cap.read()
                    if not ok:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                h = int(cfg["width"] * frame.shape[0] / frame.shape[1])
                ok, jpg = cv2.imencode(".jpg", cv2.resize(frame, (cfg["width"], h)),
                                       [cv2.IMWRITE_JPEG_QUALITY, int(cfg["quality"] * 100)])
                await ws.send(jpg.tobytes())
                inflight += 1
                sent += 1
            await asyncio.sleep(max(0, 1 / cfg["fps"] - (time.time() - t0)))
        task.cancel()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--phone-url", required=True)
    p.add_argument("--src", default=None, help="웹캠 번호 또는 동영상 경로")
    p.add_argument("--duration", type=float, default=60)
    asyncio.run(main(p.parse_args()))
