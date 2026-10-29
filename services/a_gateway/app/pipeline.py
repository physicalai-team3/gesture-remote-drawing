"""세션당 워커 1개: 최신 프레임 → B(/v1/detect) → C(/v1/interpret) → board 로 frame_result."""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from shared.schemas import DetectResponse, FrameResult, InterpretRequest, InterpretResponse, ResetResponse, Timing

from .sessions import Session

log = logging.getLogger("pipeline")


class Pipeline:
    def __init__(self, client: httpx.AsyncClient, b_url: str, c_url: str, timeout_s: float):
        self.client = client
        self.b_url = b_url.rstrip("/")
        self.c_url = c_url.rstrip("/")
        self.timeout = timeout_s

    def ensure_worker(self, s: Session) -> None:
        if s.worker is None or s.worker.done():
            s.worker = asyncio.create_task(self._run(s), name=f"worker-{s.id}")

    async def _run(self, s: Session) -> None:
        while True:
            frame = await s.take_frame()
            t0 = time.perf_counter()

            # ① B: JPEG → 손 랜드마크
            try:
                r = await self.client.post(
                    f"{self.b_url}/v1/detect",
                    content=frame.jpeg,
                    headers={"Content-Type": "image/jpeg", "X-Session": s.id,
                             "X-Seq": str(frame.seq), "X-Ts-Ms": str(frame.t_ms)},
                    timeout=self.timeout,
                )
                r.raise_for_status()
                det = DetectResponse.model_validate(r.json())
            except Exception as e:  # 실패한 프레임은 건너뛴다 (획을 끊지 않음)
                s.stats.errors_b += 1
                log.warning("B 실패 session=%s seq=%d: %s", s.id, frame.seq, e)
                continue
            t1 = time.perf_counter()

            # ② C: 랜드마크 → 제스처·그리기 명령
            req = InterpretRequest(session=s.id, seq=frame.seq, t_ms=frame.t_ms, hands=det.hands, config=s.config)
            try:
                r = await self.client.post(f"{self.c_url}/v1/interpret", json=req.model_dump(), timeout=self.timeout)
                r.raise_for_status()
                res = InterpretResponse.model_validate(r.json())
            except Exception as e:
                s.stats.errors_c += 1
                log.warning("C 실패 session=%s seq=%d: %s", s.id, frame.seq, e)
                continue
            t2 = time.perf_counter()

            total_ms = (t2 - t0) * 1000
            s.stats.done += 1
            s.stats.latency_sum += total_ms
            s.stats.hand = bool(det.hands)
            out = FrameResult(
                seq=frame.seq, gesture=res.gesture, cursor=res.cursor, commands=res.commands,
                landmarks=res.landmarks,
                timing=Timing(b_ms=round((t1 - t0) * 1000, 1), c_ms=round((t2 - t1) * 1000, 1), total_ms=round(total_ms, 1)),
            )
            await s.broadcast(out.model_dump())

    async def reset(self, s: Session) -> None:
        """C 의 펜 상태 초기화. 진행 중 획이 있으면 stroke_end 를 board 에 전달."""
        try:
            r = await self.client.post(f"{self.c_url}/v1/sessions/{s.id}/reset", timeout=self.timeout)
            r.raise_for_status()
            cmds = ResetResponse.model_validate(r.json()).commands
        except Exception as e:
            log.warning("C reset 실패 session=%s: %s", s.id, e)
            return
        if cmds:
            await s.broadcast({"type": "frame_result", "seq": -1, "gesture": "none", "cursor": None,
                               "commands": [c.model_dump() for c in cmds], "landmarks": None,
                               "timing": {"b_ms": 0, "c_ms": 0, "total_ms": 0}})

    async def close(self, s: Session) -> None:
        if s.worker:
            s.worker.cancel()
        for url in (f"{self.b_url}/v1/sessions/{s.id}", f"{self.c_url}/v1/sessions/{s.id}"):
            try:
                await self.client.delete(url, timeout=self.timeout)
            except httpx.HTTPError:
                pass
