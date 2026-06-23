"""Keyframe interpolation for the camera (zoom + pan).

A camera move is a list of keyframes ``(t, zoom, cx, cy)`` where ``(cx, cy)`` is the focus
point. Between keyframes every channel is eased so zooms glide and pans drift instead of
snapping — the "follow the click" feel.

Easing modes:
  - smoothstep : classic 3u²-2u³ (gentle, no overshoot)
  - cubic      : easeInOutCubic (snappier)
  - spring     : easeOutBack with a subtle overshoot past the target (most "alive")

When zoomed in and ``idle_drift`` is on, a tiny sinusoidal offset keeps the frame
breathing so static holds never look frozen.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass


def smoothstep(u: float) -> float:
    if u <= 0.0:
        return 0.0
    if u >= 1.0:
        return 1.0
    return u * u * (3.0 - 2.0 * u)


def ease_in_out_cubic(u: float) -> float:
    if u <= 0.0:
        return 0.0
    if u >= 1.0:
        return 1.0
    if u < 0.5:
        return 4 * u * u * u
    return 1 - pow(-2 * u + 2, 3) / 2


def ease_out_back(u: float, s: float) -> float:
    if u <= 0.0:
        return 0.0
    if u >= 1.0:
        return 1.0
    c1 = s
    c3 = s + 1
    u1 = u - 1
    return 1 + c3 * u1 * u1 * u1 + c1 * u1 * u1


def _easer(mode: str, overshoot: float):
    if mode == "cubic":
        return ease_in_out_cubic
    if mode == "spring":
        s = max(0.0, overshoot) * 10.0  # overshoot 0.06 -> s≈0.6 (~few % overshoot)
        return lambda u: ease_out_back(u, s)
    return smoothstep


@dataclass
class Keyframe:
    t: float
    zoom: float
    cx: float
    cy: float


class CameraTrack:
    _EPS = 1e-3

    def __init__(
        self,
        width: int,
        height: int,
        easing: str = "spring",
        overshoot: float = 0.06,
        idle_drift: bool = True,
        drift_amount: float = 0.010,
    ) -> None:
        self.width = width
        self.height = height
        self.idle_drift = idle_drift
        self.drift_amount = drift_amount
        self._ease = _easer(easing, overshoot)
        self._kfs: list[Keyframe] = []

    @property
    def keyframes(self) -> list[Keyframe]:
        return list(self._kfs)

    def add(self, t: float, zoom: float, cx: float, cy: float) -> None:
        if self._kfs and t <= self._kfs[-1].t:
            t = self._kfs[-1].t + self._EPS
        self._kfs.append(Keyframe(t, zoom, float(cx), float(cy)))

    def last(self) -> Keyframe | None:
        return self._kfs[-1] if self._kfs else None

    def sample(self, t: float) -> tuple[float, float, float]:
        kfs = self._kfs
        if not kfs:
            return 1.0, self.width / 2.0, self.height / 2.0
        if t <= kfs[0].t:
            z, cx, cy = kfs[0].zoom, kfs[0].cx, kfs[0].cy
        elif t >= kfs[-1].t:
            z, cx, cy = kfs[-1].zoom, kfs[-1].cx, kfs[-1].cy
        else:
            times = [k.t for k in kfs]
            i = bisect_right(times, t) - 1
            a, b = kfs[i], kfs[i + 1]
            span = b.t - a.t
            u = 0.0 if span <= 0 else (t - a.t) / span
            s = self._ease(u)
            z = a.zoom + (b.zoom - a.zoom) * s
            cx = a.cx + (b.cx - a.cx) * s
            cy = a.cy + (b.cy - a.cy) * s

        if self.idle_drift and z > 1.05:
            amp = self.drift_amount * self.width
            cx += amp * math.sin(t * 0.55)
            cy += amp * 0.7 * math.cos(t * 0.42)
        return z, cx, cy


def remap(track: CameraTrack, fn, width: int, height: int, **kw) -> CameraTrack:
    """Return a new track with every keyframe's (cx, cy) mapped through ``fn``.

    Used to translate page-space keyframes (emitted at capture) into stage-space
    keyframes (the framed composition) at compose time. Zoom factors are preserved.
    """
    out = CameraTrack(width, height, **kw)
    for k in track.keyframes:
        mx, my = fn(k.cx, k.cy)
        out.add(k.t, k.zoom, mx, my)
    return out
