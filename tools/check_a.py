"""A gateway 통합 체크리스트 자동 점검 (팀원 1 개발용). 계약: docs/03-messages.md §2~§4, 체크리스트: docs/04-team-plan.md §5

  VISION_BACKEND=mock docker compose up -d --build
  python tools/check_a.py                 # 전체 점검 (마지막에 b-vision 을 잠깐 멈췄다가 다시 켠다)
  python tools/check_a.py --no-stop-b     # B 중단 점검은 건너뜀
fps 기준(>= 10)은 mock B 기준이다. 터널 주소를 아직 모르면 phone_url 이 null 이라 폰 점검을 못 한다.
"""
import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import httpx
import numpy as np
import websockets

ROOT = Path(__file__).resolve().parent.parent
JPG = cv2.imencode(".jpg", np.full((360, 480, 3), 128, np.uint8))[1].tobytes()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


class Board:
    """board WS 에 붙어서 받은 메시지를 모아 둔다."""

    def __init__(self, ws_base, sid):
        self.url, self.msgs = f"{ws_base}/ws/board?s={sid}", []

    async def __aenter__(self):
        self.ws = await websockets.connect(self.url, max_size=None)
        self.task = asyncio.create_task(self._read())
        return self

    async def _read(self):
        try:
            async for m in self.ws:
                self.msgs.append(json.loads(m))
        except websockets.ConnectionClosed:
            pass

    def of(self, t):
        return [m for m in self.msgs if m["type"] == t]

    async def __aexit__(self, *a):
        self.task.cancel()
        await self.ws.close()


async def phone_run(phone_ws, seconds):
    """fake_phone.py 와 같은 흐름 제어(미확인 2개까지)로 seconds 동안 15fps 송출."""
    ws = await websockets.connect(phone_ws, max_size=None)
    await ws.send(json.dumps({"type": "hello", "w": 480, "h": 360, "facing": "user", "ua": "check_a.py"}))
    st = {"inflight": 0, "acks": [], "stats": [], "config": None}

    async def reader():
        try:
            async for m in ws:
                m = json.loads(m)
                if m["type"] == "config":
                    st["config"] = m
                elif m["type"] == "ack":
                    st["inflight"] = max(0, st["inflight"] - 1)
                    st["acks"].append(m["seq"])
                elif m["type"] == "stats":
                    st["stats"].append(m)
        except websockets.ConnectionClosed:
            pass

    task = asyncio.create_task(reader())
    end = time.time() + seconds
    while time.time() < end:
        if st["inflight"] < 2:
            await ws.send(JPG)
            st["inflight"] += 1
        await asyncio.sleep(1 / 15)
    await asyncio.sleep(0.3)
    task.cancel()
    await ws.close()
    return st


async def close_code(url):
    """접속 후 서버가 끊을 때의 close code. 3초 안에 안 끊으면 None."""
    try:
        async with websockets.connect(url) as ws:
            while True:
                await asyncio.wait_for(ws.recv(), 3)
    except websockets.ConnectionClosed as e:
        return e.rcvd.code if e.rcvd else None
    except asyncio.TimeoutError:
        return None


async def main(a):
    base = a.base.rstrip("/")
    ws_base = "ws" + base[len("http"):]

    # 1~2. REST
    async with httpx.AsyncClient() as c:
        h = (await c.get(f"{base}/health")).json()
        check("1. A /health ok", h.get("ok") is True, json.dumps(h, ensure_ascii=False))
        r = await c.post(f"{base}/api/sessions")
        s = r.json()
        check("2a. POST /api/sessions 201 + 필드", r.status_code == 201 and {"v", "session", "phone_url", "qr_url"} <= s.keys(),
              f"public_url={s.get('public_url')}")
        q = await c.get(base + s["qr_url"])
        check("2b. QR PNG", q.status_code == 200 and q.content[:4] == b"\x89PNG", f"{len(q.content)} bytes")
        page, ph = await c.get(f"{base}/"), await c.get(f"{base}/phone")
        check("2c. / , /phone 페이지", page.status_code == 200 and ph.status_code == 200)

    if not s["phone_url"]:
        check("2d. phone_url 발급", False, "터널 주소 미확정 — 잠시 후 다시 실행하거나 .env 의 PUBLIC_URL 설정")
        return
    sid, tok = s["session"], s["phone_url"].split("t=")[1]
    phone_ws = f"{ws_base}/ws/phone?s={sid}&t={tok}"

    # 3. 토큰·세션 검증
    check("3a. 잘못된 토큰 → 4401", await close_code(f"{ws_base}/ws/phone?s={sid}&t=bad") == 4401)
    check("3b. 없는 세션 → 4404", await close_code(f"{ws_base}/ws/phone?s=zzzzzz&t=x") == 4404)

    # 4. 정상 흐름: 폰 → A → B → C → board
    async with Board(ws_base, sid) as b:
        await asyncio.sleep(0.3)
        check("4a. board 첫 메시지 session + phone{connected:false}",
              b.of("session") and b.of("phone") and b.of("phone")[0]["connected"] is False)
        st = await phone_run(phone_ws, 5)
        fr = b.of("frame_result")
        conn = [m["connected"] for m in b.of("phone")]
        check("4b. board 에 '폰 연결됨' 후 끊김 알림", True in conn and conn[-1] is False, f"{conn}")
        check("4c. 폰 hello → config", st["config"] is not None, json.dumps(st["config"]))
        check("4d. ack 수신, seq 단조 증가", st["acks"] and st["acks"] == sorted(st["acks"]), f"acks={len(st['acks'])}")
        ops = [c["op"] for m in fr for c in m["commands"]]
        check("4e. frame_result 수신 + 그리기 명령", fr and any(op.startswith("stroke") for op in ops),
              f"frame_result={len(fr)}, 명령 종류={sorted(set(ops))}")
        fps = [m["fps_done"] for m in b.of("stats")]
        lat = [m["latency_ms"] for m in b.of("stats") if m["latency_ms"]]
        check("4f. stats fps_done >= 10", fps and max(fps) >= 10, f"fps_done={fps}, latency_ms={lat}")
        check("4g. 폰에도 stats 전송", st["stats"])
        last_seq = st["acks"][-1] if st["acks"] else -1

    # 5. 재접속
    async with Board(ws_base, sid) as b:
        await asyncio.sleep(0.3)
        check("5a. 그림판 재접속 → session 재수신", b.of("session"))
        st = await phone_run(phone_ws, 2)
        check("5b. 폰 재접속 → seq 이어서 증가", st["acks"] and st["acks"][0] > last_seq,
              f"이전 마지막={last_seq}, 재접속 첫={st['acks'][:1]}")
        check("5c. 재접속 후 frame_result 다시 흐름", b.of("frame_result"), f"{len(b.of('frame_result'))}")

    # 6. 세션당 폰 1대
    p1 = await websockets.connect(phone_ws)
    await p1.send(json.dumps({"type": "hello", "facing": "user"}))
    await asyncio.sleep(0.3)
    p2 = await websockets.connect(phone_ws)
    code = None
    try:
        while True:
            await asyncio.wait_for(p1.recv(), 3)
    except websockets.ConnectionClosed as e:
        code = e.rcvd.code if e.rcvd else None
    except asyncio.TimeoutError:
        pass
    check("6. 두 번째 폰 접속 → 기존 폰 4409", code == 4409, f"code={code}")
    await p2.close()

    # 7. 크기 초과 프레임: 처리하지 않지만 거부 ack 는 와야 폰 송출이 멈추지 않는다
    p = await websockets.connect(phone_ws, max_size=None)
    await p.send(json.dumps({"type": "hello", "facing": "user"}))
    await p.recv()
    await p.send(b"\xff" * (a.max_frame_bytes + 1))
    got, deadline = None, time.time() + 3
    try:
        while time.time() < deadline:
            m = json.loads(await asyncio.wait_for(p.recv(), 2))
            if m["type"] == "ack":
                got = m
                break
    except (asyncio.TimeoutError, websockets.ConnectionClosed):
        pass
    check("7. 크기 초과 프레임 → 거부 ack", got and got.get("seq") is None and got.get("rejected") == "too_large", f"응답={got}")
    await p.close()

    # 8. B 중단: A 는 죽지 않고 errors.b 만 증가
    if not a.stop_b:
        return
    subprocess.run(["docker", "compose", "stop", "b-vision"], capture_output=True, cwd=ROOT)
    try:
        async with Board(ws_base, sid) as b:
            st = await phone_run(phone_ws, 4)
            errs = [m["errors"]["b"] for m in b.of("stats")]
            async with httpx.AsyncClient() as c:
                alive = (await c.get(f"{base}/health")).status_code == 200
            check("8. B 중단 → A 생존 + errors.b 증가", alive and any(e > 0 for e in errs),
                  f"errors.b={errs}, ack={len(st['acks'])}")
    finally:
        subprocess.run(["docker", "compose", "start", "b-vision"], capture_output=True, cwd=ROOT)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000", help="A 주소")
    p.add_argument("--max-frame-bytes", type=int, default=300000, help=".env 의 MAX_FRAME_BYTES 와 맞춘다")
    p.add_argument("--no-stop-b", dest="stop_b", action="store_false", help="B 중단 점검 건너뜀")
    asyncio.run(main(p.parse_args()))
    print(f"\n요약: {sum(results)}/{len(results)} 통과")
    sys.exit(0 if all(results) else 1)
