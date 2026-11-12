"""Queen-cell visits: when is a worker *at* the cell, and for how long?

Definition (all thresholds in :class:`~beetrack.config.VisitConfig`)
--------------------------------------------------------------------
For each zone (the cell outline grown by ``margin_mm``; by default
**contact** = 3 mm ≈ within antenna reach, and **vicinity** = 10 mm) and each bee:

1. ``inside[t]`` = the chosen body point (``head`` by default) lies within
   the zone. Frames where the bee's position is unknown are *unknown*, not
   "outside".
2. **Bouts** = maximal runs of ``inside``.
3. **Merge**: two bouts separated by ≤ ``merge_gap_s`` (outside *or*
   unknown) become one visit. A bee leaning back for half a second, or being
   briefly occluded, doesn't end its visit.
4. **Filter**: visits shorter than ``min_visit_s`` are dropped (a worker
   just walking past the cell).

A visit's duration is ``end_s - start_s + one frame interval``. Each visit
also records how much of it was actually observed rather than bridged
(``observed_fraction``) and how sure the bee's identity is during it
(``id_probability``), so you can filter on data quality later.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..calibration import Geometry
from ..config import VisitConfig, Zone

VISIT_COLUMNS = [
    "bee_id", "zone", "visit_no", "start_frame", "end_frame", "start_s", "end_s",
    "duration_s", "observed_fraction", "min_distance_mm", "id_probability",
]


class VisitDetector:
    def __init__(self, cfg: VisitConfig, geom: Geometry):
        if geom.queen_cell is None:
            raise ValueError("visit detection needs a queen-cell outline")
        self.cfg = cfg
        self.geom = geom

    def distances(self, traj: pd.DataFrame) -> np.ndarray:
        """Distance (mm) of the chosen body point to the cell outline (0 inside, NaN unknown)."""
        if self.cfg.point == "head":
            xm, ym = traj["head_x_mm"].to_numpy(), traj["head_y_mm"].to_numpy()
        else:
            xm, ym = traj["x_mm"].to_numpy(), traj["y_mm"].to_numpy()
        xp, yp = self.geom.to_px(xm, ym)
        return self.geom.distance_to_cell_mm(xp, yp)

    def detect(self, traj: pd.DataFrame, fps: float) -> pd.DataFrame:
        rows = []
        for bee, g in traj.groupby("bee_id", sort=True):
            g = g.sort_values("frame")
            dist = self.distances(g)
            frames = g["frame"].to_numpy()
            dt = float(np.median(np.diff(frames))) / fps if len(frames) > 1 else 1 / fps
            conf = g["id_confidence"].to_numpy(float) if "id_confidence" in g else np.full(len(g), np.nan)
            for zone in self.cfg.zones:
                rows.extend(self._zone_visits(bee, zone, frames, dist, dt, fps, conf))
        df = pd.DataFrame(rows, columns=VISIT_COLUMNS)
        return df.sort_values(["zone", "start_s", "bee_id"]).reset_index(drop=True)

    def _zone_visits(self, bee, zone: Zone, frames, dist, dt, fps, conf):
        known = np.isfinite(dist)
        inside = known & (np.nan_to_num(dist, nan=np.inf) <= zone.margin_mm)
        if not inside.any():
            return []
        # bouts of inside
        edges = np.diff(np.concatenate([[0], inside.astype(int), [0]]))
        starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1
        # merge across short gaps
        max_gap = int(round(self.cfg.merge_gap_s / dt))
        merged = [[starts[0], ends[0]]]
        for s, e in zip(starts[1:], ends[1:]):
            if s - merged[-1][1] - 1 <= max_gap:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        out = []
        n = 0
        for s, e in merged:
            dur = (frames[e] - frames[s]) / fps + dt
            if dur < self.cfg.min_visit_s:
                continue
            n += 1
            seg_d = dist[s:e + 1]
            out.append({
                "bee_id": bee, "zone": zone.name, "visit_no": n,
                "start_frame": int(frames[s]), "end_frame": int(frames[e]),
                "start_s": frames[s] / fps, "end_s": frames[e] / fps, "duration_s": dur,
                "observed_fraction": float(np.isfinite(seg_d).mean()),
                "min_distance_mm": float(np.nanmin(seg_d)),
                # how sure we are that it was this bee (mean over the visit; NaN where identity has no probability)
                "id_probability": float(np.nanmean(conf[s:e + 1])) if np.isfinite(conf[s:e + 1]).any() else np.nan,
            })
        return out
