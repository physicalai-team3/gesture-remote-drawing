"""Container B — vision (영상 분석 엔진). 계약: docs/03-messages.md §6."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import cv2  # mediapipe 의존성(opencv-contrib-python)으로 설치된다
import numpy as np
from fastapi import FastAPI, Header, HTTPException, Request, Response

from shared.schemas import DetectResponse

from .detector import make_detector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("b-vision")
cv2.setNumThreads(int(os.getenv("CV_THREADS", "1")))

detector = None
# MediaPipe 그래프는 스레드 안전하지 않다 → 한 번에 1프레임만 (CPU 경쟁도 줄어든다)
lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 모델 로드·첫 추론을 요청 전에 끝낸다. 실패하면 서버가 뜨지 않아 compose 가 A 를 띄우지 않는다
    global detector
    t0 = time.perf_counter()
    detector = make_detector()
    await asyncio.to_thread(detector.warmup)
    log.info("검출기 준비: backend=%s warmup=%.0fms", detector.name, (time.perf_counter() - t0) * 1000)
    yield
    async with lock:
        detector.close_all()


app = FastAPI(title="b-vision", lifespan=lifespan)


def _decode(body: bytes) -> np.ndarray | None:
    bgr = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    return None if bgr is None else cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


@app.get("/health")
async def health():
    return {"ok": True, "service": "b-vision", "backend": detector.name, "sessions": detector.active_sessions}


@app.post("/v1/detect", response_model=DetectResponse)
async def detect(
    request: Request,
    response: Response,
    x_session: str = Header("default"),
    x_seq: int = Header(0),
    x_ts_ms: int = Header(0),
):
    body = await request.body()
    t_recv = time.perf_counter()
    # 디코드도 CPU 작업 → 이벤트 루프를 막지 않도록 스레드에서 (락 밖이라 다른 세션 추론과 겹칠 수 있다)
    rgb = await asyncio.to_thread(_decode, body)
    if rgb is None:
        raise HTTPException(400, "JPEG decode failed")
    h, w = rgb.shape[:2]
    t_decoded = time.perf_counter()

    async with lock:
        t0 = time.perf_counter()  # 락을 잡은 뒤부터 → infer_ms 는 순수 추론 시간
        # 추론은 CPU 바운드 → 이벤트 루프를 막지 않도록 스레드에서
        hands = await asyncio.to_thread(detector.detect, x_session, rgb, x_ts_ms or int(time.time() * 1000))
        infer_ms = (time.perf_counter() - t0) * 1000

    decode_ms, wait_ms = (t_decoded - t_recv) * 1000, (t0 - t_decoded) * 1000
    # 계약 필드는 그대로 두고, 세부 시간은 표준 Server-Timing 헤더로 (tools/bench_vision.py 가 읽음)
    response.headers["Server-Timing"] = f"decode;dur={decode_ms:.1f}, wait;dur={wait_ms:.1f}, infer;dur={infer_ms:.1f}"
    log.debug("session=%s seq=%d decode=%.1fms wait=%.1fms infer=%.1fms hands=%d",
              x_session, x_seq, decode_ms, wait_ms, infer_ms, len(hands))
    return DetectResponse(seq=x_seq, w=w, h=h, backend=detector.name, infer_ms=round(infer_ms, 1), hands=hands)


@app.delete("/v1/sessions/{session}", status_code=204)
async def close_session(session: str):
    async with lock:
        detector.close(session)
    return Response(status_code=204)
