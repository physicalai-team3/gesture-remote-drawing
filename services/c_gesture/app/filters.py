"""One Euro Filter — 느릴 땐 떨림을 강하게 잡고, 빠를 땐 지연을 줄인다.

Casiez et al., "1€ Filter: A Simple Speed-based Low-pass Filter for Noisy Input in Interactive Systems" (CHI 2012)
"""
from __future__ import annotations

import math
from typing import Optional


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuro:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.02, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x: Optional[float] = None
        self.dx = 0.0
        self.t: Optional[float] = None

    def reset(self) -> None:
        self.x, self.dx, self.t = None, 0.0, None

    def __call__(self, x: float, t_s: float) -> float:
        if self.x is None or self.t is None or t_s <= self.t:
            self.x, self.t = x, t_s
            return x
        dt = t_s - self.t
        dx = (x - self.x) / dt
        self.dx = self.dx + _alpha(self.d_cutoff, dt) * (dx - self.dx)
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        self.x = self.x + _alpha(cutoff, dt) * (x - self.x)
        self.t = t_s
        return self.x


class OneEuro2D:
    def __init__(self, min_cutoff: float, beta: float):
        self.fx, self.fy = OneEuro(min_cutoff, beta), OneEuro(min_cutoff, beta)

    def reset(self) -> None:
        self.fx.reset()
        self.fy.reset()

    def __call__(self, x: float, y: float, t_s: float) -> tuple[float, float]:
        return self.fx(x, t_s), self.fy(y, t_s)
