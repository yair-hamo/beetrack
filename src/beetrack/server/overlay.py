"""Draw geometry and tracking results onto a video frame (for the UI)."""

from __future__ import annotations

import cv2
import numpy as np
import pandas as pd

from ..calibration import Geometry
from ..config import AnalysisConfig, ExperimentSetup

# Categorical colours (BGR) for bee labels; paint colours are drawn as swatches.
_LABEL_BGR = [(180, 119, 31), (14, 127, 255), (44, 160, 44), (40, 39, 214), (189, 103, 148),
              (75, 86, 140), (194, 119, 227), (127, 127, 127), (34, 189, 188), (207, 190, 23)]


def _hex_bgr(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def draw_overlay(frame: np.ndarray, setup: ExperimentSetup, cfg: AnalysisConfig,
                 traj: pd.DataFrame | None = None, frame_index: int | None = None, trail_frames: int = 0) -> np.ndarray:
    img = frame.copy()
    h, w = img.shape[:2]
    lw = max(1, int(round(min(h, w) / 500)))
    if setup.dish is not None:
        cx, cy = setup.dish.center_px
        cv2.circle(img, (int(cx), int(cy)), int(setup.dish.radius_px), (60, 180, 255), lw, cv2.LINE_AA)
        cv2.drawMarker(img, (int(cx), int(cy)), (60, 180, 255), cv2.MARKER_CROSS, 12 * lw, lw)
    geom = None
    if setup.dish is not None:
        geom = Geometry.from_setup(setup, w, h)
    for a in setup.ignore_areas:  # ignored areas: grey, dashed
        pts = np.round(np.asarray(a.polygon_px)).astype(np.int32)
        for k in range(0, len(pts), 2):
            cv2.line(img, tuple(pts[k]), tuple(pts[(k + 1) % len(pts)]), (150, 150, 150), lw, cv2.LINE_AA)
    if setup.queen_cell is not None:
        poly = np.round(np.asarray(setup.queen_cell.polygon_px)).astype(np.int32)
        cv2.polylines(img, [poly], True, (40, 40, 220), lw + 1, cv2.LINE_AA)
        if geom is not None:
            for z, dash in zip(cfg.visits.zones, (6, 12, 18)):
                zp = np.round(geom.zone_polygon_px(z)).astype(np.int32)
                for k in range(0, len(zp), 2):
                    p1, p2 = tuple(zp[k]), tuple(zp[(k + 1) % len(zp)])
                    cv2.line(img, p1, p2, (90, 90, 230), lw, cv2.LINE_AA)
    if traj is not None and frame_index is not None and geom is not None and not traj.empty:
        palette = {c.name: _hex_bgr(c.display) for c in cfg.color.palette}
        codes = {b.bee_id: b.code for b in setup.bees}
        # each bee is drawn in its own dot colour (as in the UI charts)
        white = {c.name for c in cfg.color.palette if c.white}
        dot_bgr = {b.bee_id: (194, 188, 185) if b.color in white else palette.get(b.color, (128, 128, 128))
                   for b in setup.bees}  # white is drawn light grey so it shows on the light dish
        # colour index = position in the bee registry, the same order the UI charts use
        reg = [b.bee_id for b in setup.bees] if setup.marking == "color" else []
        bees = reg + sorted(set(traj["bee_id"].dropna().unique()) - set(reg))  # + anonymous tracks (T001…)
        frames = np.sort(traj["frame"].unique())
        k = int(np.searchsorted(frames, frame_index))
        k = min(max(k, 0), len(frames) - 1)
        f_now = frames[k]
        f_lo = frames[max(0, k - trail_frames)]
        win = traj[(traj["frame"] >= f_lo) & (traj["frame"] <= f_now)]
        for i, bee in enumerate(bees):
            col = dot_bgr.get(bee, _LABEL_BGR[i % len(_LABEL_BGR)])
            g = win[win["bee_id"] == bee].dropna(subset=["x_mm"])
            if g.empty:
                continue
            xs, ys = geom.to_px(g["x_mm"].to_numpy(), g["y_mm"].to_numpy())
            if trail_frames and len(xs) > 1:
                pts = np.column_stack([xs, ys]).round().astype(np.int32)
                cv2.polylines(img, [pts], False, col, lw, cv2.LINE_AA)
            last = g.iloc[-1]
            if last["frame"] != f_now:
                continue
            x, y = geom.to_px(last["x_mm"], last["y_mm"])
            hx, hy = geom.to_px(last["head_x_mm"], last["head_y_mm"])
            p, ph = (int(x), int(y)), (int(hx), int(hy))
            cv2.line(img, p, ph, col, lw + 1, cv2.LINE_AA)
            cv2.circle(img, ph, 3 * lw, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(img, ph, 3 * lw, col, lw, cv2.LINE_AA)
            style = "" if last["observed"] else "*"
            prob = last.get("id_confidence", np.nan) if hasattr(last, "get") else np.nan
            # closed group: show how sure the identity is when it isn't near-certain
            label = f"{bee}{style}" + (f" {prob:.0%}" if np.isfinite(prob) and 0 < prob < 0.9 else "")
            org = (p[0] + 8 * lw, p[1] - 8 * lw)
            cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.45 * lw, (0, 0, 0), 3 * lw, cv2.LINE_AA)
            cv2.putText(img, label, org, cv2.FONT_HERSHEY_SIMPLEX, 0.45 * lw, col, lw, cv2.LINE_AA)
            for j, c in enumerate(codes.get(bee, ())):
                sw = (org[0] + j * 9 * lw, org[1] + 5 * lw)
                cv2.rectangle(img, sw, (sw[0] + 7 * lw, sw[1] + 7 * lw), palette.get(c, (128, 128, 128)), -1)
                cv2.rectangle(img, sw, (sw[0] + 7 * lw, sw[1] + 7 * lw), (0, 0, 0), 1)
    return img


def encode_jpeg(img: np.ndarray, max_width: int = 1600, quality: int = 85) -> bytes:
    h, w = img.shape[:2]
    if w > max_width:
        img = cv2.resize(img, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()
