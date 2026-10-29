"""Container A — gateway (웹/보안 서버). 계약: docs/03-messages.md §2~§4."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Optional

import httpx
import qrcode
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from shared.schemas import CONTRACT_VERSION, SessionConfig

from .pipeline import Pipeline
from .sessions import Session, SessionStore
from .tunnel import Tunnel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("a-gateway")

PUBLIC_URL = os.getenv("PUBLIC_URL") or None
CLOUDFLARED_METRICS = os.getenv("CLOUDFLARED_METRICS", "http://cloudflared:2000")
B_URL = os.getenv("B_URL", "http://b-vision:8001")
C_URL = os.getenv("C_URL", "http://c-gesture:8002")
STAGE_TIMEOUT_S = int(os.getenv("STAGE_TIMEOUT_MS", "1000")) / 1000
TARGET_FPS = int(os.getenv("TARGET_FPS", "15"))
FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", "480"))
JPEG_QUALITY = float(os.getenv("JPEG_QUALITY", "0.7"))
MAX_FRAME_BYTES = int(os.getenv("MAX_FRAME_BYTES", "300000"))
SESSION_TTL_S = int(os.getenv("SESSION_TTL_S", "600"))
MAX_INFLIGHT = 2

STATIC = Path(__file__).resolve().parent.parent / "static"

store = SessionStore()
tunnel = Tunnel(PUBLIC_URL, CLOUDFLARED_METRICS)
pipeline: Optional[Pipeline] = None


def session_info(s: Session, request_base: Optional[str] = None) -> dict:
    # 터널 주소를 모르면 요청이 들어온 주소로 대체 (같은 PC 테스트용 — 폰 카메라는 HTTPS 필요)
    base = tunnel.public_url or request_base
    phone_url = f"{base}/phone?s={s.id}&t={s.token}" if base else None
    return {"v": CONTRACT_VERSION, "session": s.id, "public_url": tunnel.public_url,
            "phone_url": phone_url, "qr_url": f"/api/sessions/{s.id}/qr.png"}


async def background(client: httpx.AsyncClient) -> None:
    """1초마다: 터널 URL 확인, 통계 전송, 만료 세션 정리."""
    loop = asyncio.get_running_loop()
    last = loop.time()
    while True:
        await asyncio.sleep(1.0)
        now = loop.time()
        dt, last = now - last, now
        changed = await tunnel.refresh(client)
        for s in store.all():
            if changed:
                await s.broadcast({"type": "session", **session_info(s)})
            st = s.stats.tick(dt)
            await s.broadcast({"type": "stats", **st})
            if s.phone:
                with suppress(Exception):
                    await s.phone.send_json({"type": "stats", **st})
        for s in store.expired(SESSION_TTL_S):
            log.info("세션 만료: %s", s.id)
            await pipeline.close(s)
            store.remove(s.id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline
    async with httpx.AsyncClient() as client:
        pipeline = Pipeline(client, B_URL, C_URL, STAGE_TIMEOUT_S)
        task = asyncio.create_task(background(client))
        yield
        task.cancel()


app = FastAPI(title="a-gateway", lifespan=lifespan)


# ── 정적 페이지 ──
@app.get("/")
async def board_page():
    return FileResponse(STATIC / "board.html")


@app.get("/phone")
async def phone_page():
    return FileResponse(STATIC / "phone.html")


@app.get("/static/{name}")
async def static_file(name: str):
    path = (STATIC / name).resolve()
    if path.parent != STATIC or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/health")
async def health():
    return {"ok": True, "service": "a-gateway", "tunnel": tunnel.source, "sessions": len(store.all())}


# ── REST: board ↔ A (docs/03-messages.md §2) ──
def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@app.post("/api/sessions", status_code=201)
async def create_session(request: Request):
    s = store.create()
    log.info("세션 생성: %s", s.id)
    return session_info(s, _base(request))


@app.get("/api/sessions/{sid}")
async def get_session(sid: str, request: Request):
    s = store.get(sid) or _404()
    return session_info(s, _base(request))


@app.get("/api/sessions/{sid}/qr.png")
async def session_qr(sid: str, request: Request):
    s = store.get(sid) or _404()
    url = session_info(s, _base(request))["phone_url"]
    buf = io.BytesIO()
    qrcode.make(url, box_size=8, border=2).save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


def _404():
    raise HTTPException(404, "session not found")


# ── WS: board ↔ A (§4) ──
@app.websocket("/ws/board")
async def ws_board(ws: WebSocket, s: str):
    sess = store.get(s)
    await ws.accept()
    if not sess:
        await ws.close(code=4404)
        return
    sess.boards.add(ws)
    await ws.send_json({"type": "session", **session_info(sess, f"{ws.url.scheme.replace('ws', 'http')}://{ws.url.netloc}")})
    await ws.send_json({"type": "phone", "connected": sess.phone is not None, "facing": sess.phone_facing})
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "config":
                sess.config = SessionConfig.model_validate({**sess.config.model_dump(), **{k: v for k, v in msg.items() if k != "type"}})
            elif msg.get("type") == "reset":
                await pipeline.reset(sess)
    except WebSocketDisconnect:
        pass
    finally:
        sess.boards.discard(ws)
        sess.last_seen = time.time()


# ── WS: phone ↔ A (§3) ──
@app.websocket("/ws/phone")
async def ws_phone(ws: WebSocket, s: str, t: str = ""):
    sess = store.get(s)
    await ws.accept()
    if not sess:
        await ws.close(code=4404)
        return
    if t != sess.token:
        await ws.close(code=4401)
        return
    if sess.phone is not None:  # 세션당 폰 1대: 이전 폰을 끊는다
        with suppress(Exception):
            await sess.phone.close(code=4409)
    sess.phone = ws
    pipeline.ensure_worker(sess)
    await sess.broadcast({"type": "phone", "connected": True, "facing": None})
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                data = msg["bytes"]
                if len(data) > MAX_FRAME_BYTES:
                    continue
                frame = sess.put_frame(data)
                await ws.send_json({"type": "ack", "seq": frame.seq})
            elif msg.get("text") is not None:
                await _phone_text(sess, ws, msg["text"])
    except WebSocketDisconnect:
        pass
    finally:
        if sess.phone is ws:
            sess.phone = None
            sess.last_seen = time.time()
            await sess.broadcast({"type": "phone", "connected": False, "facing": None})
            await pipeline.reset(sess)


async def _phone_text(sess: Session, ws: WebSocket, text: str) -> None:
    msg = json.loads(text)
    if msg.get("type") == "hello":
        sess.phone_facing = msg.get("facing")
        # 전면 카메라면 거울 모드 (docs/03-messages.md §3)
        sess.config = sess.config.model_copy(update={"mirror": sess.phone_facing != "environment"})
        await ws.send_json({"type": "config", "v": CONTRACT_VERSION, "fps": TARGET_FPS, "width": FRAME_WIDTH,
                            "quality": JPEG_QUALITY, "max_inflight": MAX_INFLIGHT})
        await sess.broadcast({"type": "phone", "connected": True, "facing": sess.phone_facing})
