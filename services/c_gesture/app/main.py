"""Container C — gesture (동작 인식 엔진). 계약: docs/03-messages.md §7."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Response

from shared.schemas import InterpretRequest, InterpretResponse, ResetResponse

from .state import GestureSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="c-gesture")
sessions: dict[str, GestureSession] = {}


@app.get("/health")
async def health():
    return {"ok": True, "service": "c-gesture", "sessions": len(sessions)}


@app.post("/v1/interpret", response_model=InterpretResponse)
async def interpret(req: InterpretRequest):
    s = sessions.setdefault(req.session, GestureSession())
    return s.update(req)


@app.post("/v1/sessions/{session}/reset", response_model=ResetResponse)
async def reset(session: str):
    s = sessions.get(session)
    return ResetResponse(commands=s.reset() if s else [])


@app.delete("/v1/sessions/{session}", status_code=204)
async def close(session: str):
    sessions.pop(session, None)
    return Response(status_code=204)
