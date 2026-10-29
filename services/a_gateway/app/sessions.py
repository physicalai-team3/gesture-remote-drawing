"""세션 저장소 (메모리). 세션 = 그림판 1개 + 폰 1대."""
from __future__ import annotations

import asyncio
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

from shared.schemas import SessionConfig

_ALPHABET = string.ascii_lowercase + string.digits


@dataclass
class Frame:
    seq: int
    t_ms: int
    jpeg: bytes


@dataclass
class Stats:
    """1초 창(window) 통계. tick() 이 호출될 때마다 초기화된다."""
    recv: int = 0
    done: int = 0
    dropped: int = 0
    latency_sum: float = 0.0
    errors_b: int = 0
    errors_c: int = 0
    hand: bool = False

    def tick(self, dt: float) -> dict:
        out = {
            "fps_in": round(self.recv / dt, 1),
            "fps_done": round(self.done / dt, 1),
            "dropped": self.dropped,
            "latency_ms": round(self.latency_sum / self.done, 1) if self.done else None,
            "errors": {"b": self.errors_b, "c": self.errors_c},
            "hand": self.hand,
        }
        self.recv = self.done = self.dropped = 0
        self.latency_sum = 0.0
        return out


@dataclass
class Session:
    id: str
    token: str
    config: SessionConfig = field(default_factory=SessionConfig)
    phone: Optional[WebSocket] = None
    phone_facing: Optional[str] = None
    boards: set[WebSocket] = field(default_factory=set)
    next_seq: int = 0
    stats: Stats = field(default_factory=Stats)
    last_seen: float = field(default_factory=time.time)
    # 최신 프레임 슬롯: 처리 중에 새 프레임이 오면 덮어쓴다 (docs/01-architecture.md §4)
    slot: Optional[Frame] = None
    slot_event: asyncio.Event = field(default_factory=asyncio.Event)
    worker: Optional[asyncio.Task] = None

    def put_frame(self, jpeg: bytes) -> Frame:
        frame = Frame(seq=self.next_seq, t_ms=int(time.time() * 1000), jpeg=jpeg)
        self.next_seq += 1
        if self.slot is not None:
            self.stats.dropped += 1
        self.slot = frame
        self.slot_event.set()
        self.stats.recv += 1
        return frame

    async def take_frame(self) -> Frame:
        while self.slot is None:
            self.slot_event.clear()
            await self.slot_event.wait()
        frame, self.slot = self.slot, None
        return frame

    async def broadcast(self, msg: dict) -> None:
        for ws in list(self.boards):
            try:
                await ws.send_json(msg)
            except Exception:
                self.boards.discard(ws)

    @property
    def idle(self) -> bool:
        return self.phone is None and not self.boards


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        while True:
            sid = "".join(secrets.choice(_ALPHABET) for _ in range(6))
            if sid not in self._sessions:
                break
        s = Session(id=sid, token=secrets.token_urlsafe(16))
        self._sessions[sid] = s
        return s

    def get(self, sid: str) -> Optional[Session]:
        return self._sessions.get(sid)

    def all(self) -> list[Session]:
        return list(self._sessions.values())

    def expired(self, ttl_s: float) -> list[Session]:
        now = time.time()
        return [s for s in self._sessions.values() if s.idle and now - s.last_seen > ttl_s]

    def remove(self, sid: str) -> None:
        self._sessions.pop(sid, None)
