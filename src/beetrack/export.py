"""Exports: annotated video and per-frame path annotations.

* Videos (annotated recording, paths, heatmap) live in :mod:`beetrack.videos`.
* :func:`annotations_table`: one row per bee per observed frame, with centre,
  head, heading and an axis-aligned bounding box. Use it for re-labelling,
  for other tools, or to train a detector.
* :func:`annotations_mot`: the same in the MOT Challenge format
  (``frame,id,left,top,width,height,conf,-1,-1,-1``, 1-based frames), which
  CVAT, py-motmetrics and most multi-object-tracking tools read.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import AnalysisConfig, ExperimentSetup

ANNOTATION_COLUMNS = [
    "frame", "time_s", "bee_id", "track_no", "x_px", "y_px", "head_x_px", "head_y_px", "heading_deg",
    "bbox_left", "bbox_top", "bbox_width", "bbox_height", "observed",
]


def _bbox(x, y, major, minor, angle):
    """Axis-aligned box around a rotated ellipse (full axes ``major`` × ``minor``, angle in rad)."""
    a, b = major / 2, minor / 2
    c, s = np.cos(angle), np.sin(angle)
    hw = np.sqrt((a * c) ** 2 + (b * s) ** 2)
    hh = np.sqrt((a * s) ** 2 + (b * c) ** 2)
    return x - hw, y - hh, 2 * hw, 2 * hh


def annotations_table(det: pd.DataFrame, traj: pd.DataFrame, setup: ExperimentSetup, width: int, height: int) -> pd.DataFrame:
    """Observed (not interpolated) positions of identified bees, in image pixels."""
    from .calibration import Geometry

    geom = Geometry.from_setup(setup, width, height)
    t = traj[traj["observed"] & traj["x_mm"].notna()].copy()
    if t.empty:
        return pd.DataFrame(columns=ANNOTATION_COLUMNS)
    t["x_px"], t["y_px"] = geom.to_px(t["x_mm"].to_numpy(), t["y_mm"].to_numpy())
    t["head_x_px"], t["head_y_px"] = geom.to_px(t["head_x_mm"].to_numpy(), t["head_y_mm"].to_numpy())
    d = det[det["bee_id"].notna()].sort_values("id_confidence", ascending=False).drop_duplicates(["frame", "bee_id"])
    d = d[["frame", "bee_id", "major_px", "minor_px", "axis_angle"]]
    t = t.merge(d, on=["frame", "bee_id"], how="left")
    med_major = float(np.nanmedian(d["major_px"])) if len(d) else 40.0
    med_minor = float(np.nanmedian(d["minor_px"])) if len(d) and d["minor_px"].notna().any() else med_major / 2.7
    major = t["major_px"].fillna(med_major).to_numpy()
    minor = t["minor_px"].fillna(med_minor).to_numpy()
    angle = t["axis_angle"].fillna(0).to_numpy()
    left, top, w, h = _bbox(t["x_px"].to_numpy(), t["y_px"].to_numpy(), major, minor, angle)
    order = {b: i + 1 for i, b in enumerate(sorted(t["bee_id"].unique()))}
    out = pd.DataFrame({
        "frame": t["frame"].astype(int), "time_s": t["time_s"], "bee_id": t["bee_id"], "track_no": t["bee_id"].map(order),
        "x_px": t["x_px"].round(1), "y_px": t["y_px"].round(1),
        "head_x_px": t["head_x_px"].round(1), "head_y_px": t["head_y_px"].round(1),
        "heading_deg": t["heading_deg"].round(1),
        "bbox_left": np.clip(left, 0, width).round(1), "bbox_top": np.clip(top, 0, height).round(1),
        "bbox_width": w.round(1), "bbox_height": h.round(1), "observed": True,
    })
    return out.sort_values(["frame", "track_no"]).reset_index(drop=True)[ANNOTATION_COLUMNS]


def annotations_mot(ann: pd.DataFrame) -> str:
    """MOT Challenge text (``frame,id,left,top,w,h,conf,-1,-1,-1``); ids are ``track_no``."""
    rows = [f"{int(r.frame) + 1},{int(r.track_no)},{r.bbox_left:.1f},{r.bbox_top:.1f},{r.bbox_width:.1f},{r.bbox_height:.1f},1,-1,-1,-1"
            for r in ann.itertuples(index=False)]
    return "\n".join(rows) + ("\n" if rows else "")


def render_annotated_video(videos, setup, cfg, traj, out_path, *, fps=None, trail_s=3.0, max_width=1280, progress=None):
    """Backward-compatible wrapper; see :mod:`beetrack.videos` for all three result videos."""
    from .videos import RenderOptions, render_annotated

    opts = RenderOptions(trail_s=trail_s, fps=fps or 15.0, max_width=max_width)
    return render_annotated(videos, setup, cfg, traj, out_path, opts, progress)
