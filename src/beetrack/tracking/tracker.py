"""Online multi-object tracker: Hungarian assignment with a speed gate.

The tracker only answers *"is this blob the same one as a moment ago?"*. It
cuts a track whenever that's uncertain (a large jump, or a long disappearance),
producing short, **clean** tracklets rather than long, possibly mixed ones.
The identity resolver names the tracklets later from colour evidence, and the
same bee's tracklets are joined up there.

Prediction is constant-velocity with a damped velocity, which is enough for
walking bees at ≥10 fps.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..config import TrackingConfig
from ..models import Detection


@dataclass
class _Track:
    tid: int
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    last_frame: int = 0


class OnlineTracker:
    def __init__(self, cfg: TrackingConfig, px_per_mm: float, source_fps: float):
        self.cfg = cfg
        self.px_per_mm = px_per_mm
        self.fps = source_fps
        self._active: list[_Track] = []
        self._next_id = 0

    def _gate_px(self, dframes: int) -> float:
        dt = min(dframes / self.fps, self.cfg.gate_max_dt_s)  # don't let the gate grow without bound
        return (self.cfg.max_speed_mm_s * dt + self.cfg.gate_slack_mm) * self.px_per_mm

    def update(self, frame: int, dets: list[Detection]) -> None:
        """Assign ``tracklet`` ids to ``dets`` in place."""
        max_gap = self.cfg.max_gap_s * self.fps
        self._active = [t for t in self._active if frame - t.last_frame <= max_gap]

        if self._active and dets:
            P = np.array([[t.x + t.vx * (frame - t.last_frame), t.y + t.vy * (frame - t.last_frame)] for t in self._active])
            D = np.array([[d.x, d.y] for d in dets])
            cost = np.linalg.norm(P[:, None, :] - D[None, :, :], axis=-1)
            gates = np.array([self._gate_px(frame - t.last_frame) for t in self._active])
            big = 1e6
            cost_g = np.where(cost <= gates[:, None], cost, big)
            rows, cols = linear_sum_assignment(cost_g)
            matched_d = set()
            for r, c in zip(rows, cols):
                if cost_g[r, c] >= big:
                    continue
                t, d = self._active[r], dets[c]
                df = max(1, frame - t.last_frame)
                t.vx = 0.5 * t.vx + 0.5 * (d.x - t.x) / df
                t.vy = 0.5 * t.vy + 0.5 * (d.y - t.y) / df
                t.x, t.y, t.last_frame = d.x, d.y, frame
                d.tracklet = t.tid
                matched_d.add(c)
            unmatched = [d for i, d in enumerate(dets) if i not in matched_d]
        else:
            unmatched = list(dets)

        for d in unmatched:
            t = _Track(self._next_id, d.x, d.y, last_frame=frame)
            self._next_id += 1
            self._active.append(t)
            d.tracklet = t.tid
