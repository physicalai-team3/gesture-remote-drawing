"""공개 URL 확인: PUBLIC_URL 환경변수 → 없으면 cloudflared 의 /quicktunnel 을 주기적으로 조회.

/quicktunnel 은 cloudflared 소스(metrics/metrics.go)에는 있지만 공식 문서에는 없는 경로다.
응답: {"hostname": "brave-cat-1234.trycloudflare.com"}. 조회가 안 되면 PUBLIC_URL 을 수동으로 넣는다.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

# 주소를 찾기 전에는 1초마다, 찾은 뒤에는 cloudflared 재시작으로 주소가 바뀌는지만 가끔 확인
FOUND_INTERVAL_S = 30.0


class Tunnel:
    def __init__(self, env_url: Optional[str], metrics_url: str):
        self.env_url = env_url.rstrip("/") if env_url else None
        self.metrics_url = metrics_url.rstrip("/")
        self.discovered: Optional[str] = None
        self.ok = False
        self.next_check = 0.0

    @property
    def public_url(self) -> Optional[str]:
        return self.env_url or self.discovered

    @property
    def source(self) -> str:
        return "env" if self.env_url else ("quicktunnel" if self.discovered else "none")

    async def refresh(self, client: httpx.AsyncClient) -> bool:
        """조회해서 URL 이 바뀌었으면 True."""
        if self.env_url:
            self.ok = True
            return False
        if time.monotonic() < self.next_check:
            return False
        try:
            r = await client.get(f"{self.metrics_url}/quicktunnel", timeout=2.0)
            host = r.json().get("hostname") if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            host = None
        self.ok = bool(host)
        self.next_check = time.monotonic() + FOUND_INTERVAL_S if host else 0.0
        url = f"https://{host}" if host else None
        if url and url != self.discovered:
            self.discovered = url
            return True
        return False
