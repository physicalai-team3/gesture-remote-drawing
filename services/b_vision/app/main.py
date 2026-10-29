"""Container B — vision (영상 분석 엔진). 계약: docs/03-messages.md §6."""
from __future__ import annotations

import asyncio
import logging
import os
import time

import cv2
import numpy as np
from fastapi import FastAPI, Header, HTTPException, Request, Response

from shared.schemas import DetectResponse

from .detector import make_detector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
cv2.setNumThreads(int(os.getenv("CV_THREADS", "1")))

app = FastAPI(title="b-vision")
detector = make_detector()
# MediaPipe 그래프는 스레드 안전하지 않다 → 한 번에 1프레임만 (CPU 경쟁도 줄어든다)
lock = asyncio.Lock()


@app.get("/health")
async def health():
    return {"ok": True, "service": "b-vision", "backend": detector.name}


@app.post("/v1/detect", response_model=DetectResponse)
async def detect(
    request: Request,
    x_session: str = Header("default"),
    x_seq: int = Header(0),
    x_ts_ms: int = Header(0),
):
    body = await request.body()
    bgr = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise HTTPException(400, "JPEG decode failed")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]

    t0 = time.perf_counter()
    async with lock:
        # 추론은 CPU 바운드 → 이벤트 루프를 막지 않도록 스레드에서
        hands = await asyncio.to_thread(detector.detect, x_session, rgb, x_ts_ms or int(time.time() * 1000))
    infer_ms = (time.perf_counter() - t0) * 1000

    return DetectResponse(seq=x_seq, w=w, h=h, backend=detector.name, infer_ms=round(infer_ms, 1), hands=hands)


@app.delete("/v1/sessions/{session}", status_code=204)
async def close_session(session: str):
    async with lock:
        detector.close(session)
    return Response(status_code=204)
