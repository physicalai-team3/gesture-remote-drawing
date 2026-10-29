"""Container C — gesture (동작 인식 엔진). 계약: docs/03-messages.md §7."""
from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Response

from shared.schemas import InterpretRequest, InterpretResponse, ResetResponse

from .state import GestureSession

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="c-gesture")
sessions: dict[str, GestureSession] = {}
last_used: dict[str, float] = {}
SESSION_TTL_S = float(os.getenv("SESSION_TTL_S", "600"))  # A 와 같은 값 (.env 공유). A 가 DELETE 를 못 보내도 메모리가 쌓이지 않게


def _prune(now: float) -> None:
    for sid in [k for k, t in last_used.items() if now - t > SESSION_TTL_S]:
        sessions.pop(sid, None)
        last_used.pop(sid, None)


@app.get("/health")
async def health():
    return {"ok": True, "service": "c-gesture", "sessions": len(sessions)}


@app.post("/v1/interpret", response_model=InterpretResponse)
async def interpret(req: InterpretRequest):
    now = time.monotonic()
    if req.session not in sessions:
        _prune(now)
        sessions[req.session] = GestureSession()
    last_used[req.session] = now
    s = sessions[req.session]
    return s.update(req)


@app.post("/v1/sessions/{session}/reset", response_model=ResetResponse)
async def reset(session: str):
    s = sessions.get(session)
    return ResetResponse(commands=s.reset() if s else [])


@app.delete("/v1/sessions/{session}", status_code=204)
async def close(session: str):
    sessions.pop(session, None)
    last_used.pop(session, None)
    return Response(status_code=204)
