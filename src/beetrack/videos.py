"""Result videos: the annotated recording, a paths map, and an occupancy heatmap.

All three share one set of options (:class:`RenderOptions`):

* ``step_s``: recording time per output frame. ``None`` = every analysed
  frame (real time at 15 fps). ``0.5`` = one output frame per half second of
  recording, so at ``fps=15`` the video plays 7.5× faster than real time.
* ``trail_s``: how much recent path to draw. ``0`` = none, ``-1`` = the
  entire path so far. For the heatmap: ``-1`` = cumulative, otherwise a
  sliding window of that length.
* ``fps``: playback frame rate of the output file.
* ``bees``: restrict to these bee/track IDs (``None`` = all).

Paths and heatmap videos are drawn from the trajectories alone (no video
decoding), so they render fast even for long recordings. The annotated video
decodes the recording.

Positions between two output frames are not skipped: trails and the heatmap
use *every* analysed frame, so a large step makes a faster video without
losing data.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections import deque
from pathlib import Path
from typing import Callable, Literal

import cv2
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from .calibration import Geometry
from .config import AnalysisConfig, ExperimentSetup
from .video import Recording

VideoKind = Literal["annotated", "paths", "heatmap"]
VIDEO_FILES: dict[str, str] = {"annotated": "annotated.mp4", "paths": "paths.mp4", "heatmap": "heatmap.mp4"}

ProgressFn = Callable[[float, str], None]

_CAT_BGR = [(180, 119, 31), (14, 127, 255), (44, 160, 44), (40, 39, 214), (189, 103, 148),
            (75, 86, 140), (194, 119, 227), (127, 127, 127), (34, 189, 188), (207, 190, 23)]
_BG = (242, 245, 246)        # page background (BGR)
_INK = (40, 35, 31)
_MUTED = (130, 120, 110)
_CELL = (77, 72, 229)


class RenderOptions(BaseModel):
    step_s: float | None = Field(None, ge=0, le=3600, description="Recording seconds per output frame; None = every analysed frame")
    trail_s: float = Field(3.0, ge=-1, le=86400, description="Seconds of trail; 0 = none, -1 = entire path / cumulative heatmap")
    fps: float = Field(15.0, ge=1, le=60, description="Playback frame rate of the output video")
    bees: list[str] | None = Field(None, description="Only these bee/track IDs (None = all)")
    max_width: int = Field(1280, ge=320, le=3840, description="Annotated video: maximum output width (px)")

    def describe(self) -> str:
        step = "real time" if not self.step_s else f"{self.step_s:g} s/step"
        trail = "entire path" if self.trail_s < 0 else ("no trail" if self.trail_s == 0 else f"{self.trail_s:g} s trail")
        return f"{step} · {trail} · {self.fps:g} fps"


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
def bee_colors_bgr(setup: ExperimentSetup, cfg: AnalysisConfig, ids: list[str]) -> dict[str, tuple[int, int, int]]:
    """Colour per bee: its paint dot (white drawn light grey), or a categorical colour for anonymous tracks."""
    pal = {}
    for c in cfg.color.palette:
        h = c.display.lstrip("#")
        pal[c.name] = (194, 188, 185) if c.white else (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))
    dot = {b.bee_id: pal.get(b.color) for b in setup.bees} if setup.marking == "color" else {}
    out = {}
    for i, b in enumerate(ids):
        if dot.get(b):
            out[b] = dot[b]
        else:
            digits = "".join(ch for ch in str(b) if ch.isdigit())
            out[b] = _CAT_BGR[(int(digits) if digits else i) % len(_CAT_BGR)]
    return out


class _Plan:
    """Which frames to output, and how to slice the trajectory table quickly."""

    def __init__(self, traj: pd.DataFrame, src_fps: float, opts: RenderOptions):
        t = traj.sort_values("frame")
        if opts.bees:
            t = t[t["bee_id"].isin(opts.bees)]
        self.traj = t.reset_index(drop=True)
        frames = np.sort(traj["frame"].unique()) if not traj.empty else np.array([0])
        self.analysis_step = int(np.median(np.diff(frames))) if len(frames) > 1 else 1
        self.src_fps = src_fps
        k = max(1, int(round((opts.step_s or 0) * src_fps / self.analysis_step))) if opts.step_s else 1
        self.step = k * self.analysis_step
        self.out_frames = frames[(frames - frames[0]) % self.step == 0]
        self.trail_frames = None if opts.trail_s < 0 else int(round(opts.trail_s * src_fps))
        self._f = self.traj["frame"].to_numpy()
        self.bees = sorted(self.traj["bee_id"].dropna().unique()) if not self.traj.empty else []

    def rows(self, lo: int, hi: int) -> pd.DataFrame:
        """Trajectory rows with lo < frame ≤ hi."""
        a, b = np.searchsorted(self._f, lo, side="right"), np.searchsorted(self._f, hi, side="right")
        return self.traj.iloc[a:b]


def _ylorrd_lut() -> np.ndarray:
    """256-entry BGR lookup table, light yellow (rare) → dark red (often): readable on a white dish."""
    stops = ["#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#bd0026", "#800026"]
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in stops], float)
    x = np.linspace(0, 1, len(stops))
    t = np.linspace(0, 1, 256)
    lut = np.stack([np.interp(t, x, rgb[:, 2 - ch]) for ch in range(3)], axis=1)  # → BGR
    return lut.astype(np.uint8)


_HEAT_LUT = _ylorrd_lut()


def _heat(v: np.ndarray) -> np.ndarray:
    return _HEAT_LUT[np.clip((v * 255).astype(int), 0, 255)]


def _step_label(step_frames: int, analysis_step: int, src_fps: float) -> str:
    return "real time" if step_frames == analysis_step else f"{step_frames / src_fps:.2f}".rstrip("0").rstrip(".") + " s/step"


def _clock(t: float) -> str:
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _text(img, s, org, scale=0.55, color=_INK, thick=1, shadow=None):
    if shadow is not None:
        cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, shadow, thick + 2, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def _draw_segments(img, g: pd.DataFrame, to_px, color, max_gap_frames: int, thickness: int, xcol="x_mm", ycol="y_mm"):
    """Polyline through a bee's points, broken at missing data and at gaps longer than ``max_gap_frames``."""
    if g.empty:
        return
    xs, ys = to_px(g[xcol].to_numpy(), g[ycol].to_numpy())
    f = g["frame"].to_numpy()
    ok = np.isfinite(xs) & np.isfinite(ys)
    pts = np.column_stack([xs, ys])
    run: list[np.ndarray] = []
    for i in range(len(f)):
        if not ok[i] or (run and f[i] - f[i - 1] > max_gap_frames):
            if len(run) > 1:
                cv2.polylines(img, [np.round(np.array(run)).astype(np.int32)], False, color, thickness, cv2.LINE_AA)
            run = []
        if ok[i]:
            run.append(pts[i])
    if len(run) > 1:
        cv2.polylines(img, [np.round(np.array(run)).astype(np.int32)], False, color, thickness, cv2.LINE_AA)


H264_ENCODERS = [
    ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"],
    ["-c:v", "h264_mf", "-b:v", "6M"],             # Windows Media Foundation
    ["-c:v", "h264_videotoolbox", "-b:v", "6M"],   # macOS
]


class _Writer:
    """mp4v via OpenCV into a temp file, re-encoded to H.264 with ffmpeg when available."""

    def __init__(self, out: Path, fps: float, size: tuple[int, int]):
        self.out, self.size = Path(out), (size[0] // 2 * 2, size[1] // 2 * 2)
        self.tmp = Path(tempfile.mkdtemp(prefix="beetrack_render_"))
        self.raw = self.tmp / "raw.mp4"
        self.w = cv2.VideoWriter(str(self.raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, self.size)
        if not self.w.isOpened():
            raise IOError("could not open a video writer")

    def write(self, img: np.ndarray) -> None:
        if (img.shape[1], img.shape[0]) != self.size:
            img = cv2.resize(img, self.size, interpolation=cv2.INTER_AREA)
        self.w.write(img)

    def close(self) -> Path:
        self.w.release()
        self.out.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            # H.264 plays everywhere. libx264 is in most ffmpeg builds; the LGPL build shipped with the
            # Windows app has the system encoders instead (Media Foundation on Windows, VideoToolbox on macOS).
            for enc in H264_ENCODERS:
                cmd = [ffmpeg, "-y", "-v", "error", "-i", str(self.raw), *enc,
                       "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(self.out)]
                if subprocess.run(cmd, capture_output=True).returncode == 0:
                    shutil.rmtree(self.tmp, ignore_errors=True)
                    return self.out
        shutil.move(str(self.raw), self.out)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return self.out


class _MapCanvas:
    """A top-down dish map in mm: dish, queen cell, zones, legend panel."""

    def __init__(self, geom: Geometry, setup: ExperimentSetup, cfg: AnalysisConfig, title: str, size: int = 860, legend_w: int = 240):
        self.S, self.L = size, legend_w
        self.R = setup.dish.diameter_mm / 2 if setup.dish else 75.0
        self.k = (size - 70) / (2 * self.R)
        self.c = (size / 2, size / 2 + 18)
        self.geom, self.title = geom, title
        base = np.full((size, size + legend_w, 3), _BG, np.uint8)
        cv2.circle(base, self.px(0, 0), int(self.R * self.k), (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(base, self.px(0, 0), int(self.R * self.k), (180, 170, 160), 2, cv2.LINE_AA)
        for a in geom.ignore or []:  # ignored areas: light grey
            ax, ay = geom.to_mm(a[:, 0], a[:, 1])
            cv2.fillPoly(base, [np.column_stack(self.px(ax, ay)).round().astype(np.int32)], (226, 226, 226), cv2.LINE_AA)
        self.cell_px = None
        if geom.queen_cell is not None:
            cx, cy = geom.to_mm(geom.queen_cell[:, 0], geom.queen_cell[:, 1])
            self.cell_px = np.column_stack(self.px(cx, cy)).round().astype(np.int32)
            overlay = base.copy()
            cv2.fillPoly(overlay, [self.cell_px], (205, 205, 250), cv2.LINE_AA)
            cv2.addWeighted(overlay, 0.7, base, 0.3, 0, base)
            cv2.polylines(base, [self.cell_px], True, _CELL, 2, cv2.LINE_AA)
            for z in cfg.visits.zones:
                zp = geom.zone_polygon_px(z)
                zx, zy = geom.to_mm(zp[:, 0], zp[:, 1])
                pts = np.column_stack(self.px(zx, zy)).round().astype(np.int32)
                for i in range(0, len(pts), 2):
                    cv2.line(base, tuple(pts[i]), tuple(pts[(i + 1) % len(pts)]), (150, 150, 235), 1, cv2.LINE_AA)
        # scale bar: 10 mm
        x0, y0 = 24, size - 26
        cv2.line(base, (x0, y0), (x0 + int(10 * self.k), y0), _INK, 2)
        _text(base, "10 mm", (x0, y0 - 8), 0.45, _MUTED)
        _text(base, title, (20, 30), 0.7, _INK, 2)
        cv2.line(base, (size, 0), (size, size), (225, 220, 214), 1)
        self.base = base

    def px(self, x_mm, y_mm):
        x_mm, y_mm = np.asarray(x_mm, float), np.asarray(y_mm, float)
        x, y = self.c[0] + x_mm * self.k, self.c[1] - y_mm * self.k
        if np.ndim(x) == 0:
            return int(round(float(x))), int(round(float(y)))
        return x, y

    def header(self, img, t: float, extra: str = ""):
        _text(img, _clock(t), (self.S - 170, 30), 0.65, _INK, 2)
        if extra:
            _text(img, extra, (20, 54), 0.45, _MUTED)


def _done(path: Path, progress: ProgressFn | None) -> Path:
    if progress:
        progress(1.0, "done")
    return path


# --------------------------------------------------------------------------- #
# 1. annotated recording
# --------------------------------------------------------------------------- #
def render_annotated(videos: list[str | Path], setup: ExperimentSetup, cfg: AnalysisConfig, traj: pd.DataFrame,
                     out: str | Path, opts: RenderOptions, progress: ProgressFn | None = None) -> Path:
    from .server.overlay import draw_overlay

    rec = Recording(list(videos))
    plan = _Plan(traj, rec.fps, opts)
    scale = min(1.0, opts.max_width / rec.width)
    w = _Writer(Path(out), opts.fps, (int(rec.width * scale), int(rec.height * scale)))
    geom = Geometry.from_setup(setup, rec.width, rec.height)
    colors = bee_colors_bgr(setup, cfg, plan.bees)
    layer = np.zeros((rec.height, rec.width, 3), np.uint8)   # persistent "entire path" trails
    mask = np.zeros((rec.height, rec.width), np.uint8)
    lw = max(1, int(round(min(rec.width, rec.height) / 500)))
    targets = set(int(f) for f in plan.out_frames)
    prev_out = -1
    total = len(plan.out_frames)
    k = 0
    for ref, img in rec.iter_frames(plan.step):  # skipped frames are not decoded
        if ref.index not in targets:
            continue
        if plan.trail_frames is None:  # draw every new segment onto the persistent layer
            new = plan.rows(prev_out - plan.analysis_step, ref.index)
            for b, g in new.groupby("bee_id"):
                _draw_segments(layer, g, lambda x, y: geom.to_px(x, y), colors[b], 3 * plan.analysis_step, lw)
                _draw_segments(mask, g, lambda x, y: geom.to_px(x, y), 255, 3 * plan.analysis_step, lw)
            img[mask > 0] = layer[mask > 0]
            window, trail = plan.rows(ref.index - 1, ref.index), 0
        else:
            window = plan.rows(ref.index - max(plan.trail_frames, 1) - 1, ref.index)
            trail = plan.trail_frames // plan.analysis_step if plan.trail_frames else 0
        img = draw_overlay(img, setup, cfg, window, ref.index, trail)
        hgt = img.shape[0]
        cv2.rectangle(img, (6, hgt - 36), (150, hgt - 8), (20, 20, 20), -1)
        _text(img, _clock(ref.time_s), (14, hgt - 16), 0.6, (255, 255, 255), 1)
        w.write(img)
        prev_out = ref.index
        k += 1
        if progress and k % 25 == 0:
            progress(min(0.98, k / max(1, total)), f"frame {k}/{total}")
    return _done(w.close(), progress)


# --------------------------------------------------------------------------- #
# 2. paths map
# --------------------------------------------------------------------------- #
def render_paths(setup: ExperimentSetup, cfg: AnalysisConfig, traj: pd.DataFrame, width: int, height: int, src_fps: float,
                 out: str | Path, opts: RenderOptions, progress: ProgressFn | None = None, title: str = "Bee paths") -> Path:
    geom = Geometry.from_setup(setup, width, height)
    plan = _Plan(traj, src_fps, opts)
    canvas = _MapCanvas(geom, setup, cfg, title)
    colors = bee_colors_bgr(setup, cfg, plan.bees)
    w = _Writer(Path(out), opts.fps, (canvas.base.shape[1], canvas.base.shape[0]))
    persistent = canvas.base.copy()
    contact = cfg.visits.zones[0] if cfg.visits.zones else None
    prev_out = -1
    total = len(plan.out_frames)
    gap = 3 * plan.analysis_step
    trail_desc = "entire path" if plan.trail_frames is None else ("no trail" if plan.trail_frames == 0 else f"{opts.trail_s:g} s trail")
    step_desc = _step_label(plan.step, plan.analysis_step, src_fps)
    for k, f in enumerate(plan.out_frames):
        f = int(f)
        if plan.trail_frames is None:
            for b, g in plan.rows(prev_out - plan.analysis_step, f).groupby("bee_id"):
                _draw_segments(persistent, g, canvas.px, colors[b], gap, 2)
            img = persistent.copy()
        else:
            img = canvas.base.copy()
            if plan.trail_frames:
                for b, g in plan.rows(f - plan.trail_frames, f).groupby("bee_id"):
                    _draw_segments(img, g, canvas.px, colors[b], gap, 2)
        now = plan.rows(f - 1, f).dropna(subset=["x_mm"])
        at_cell = set()
        if contact is not None and geom.queen_cell is not None and not now.empty:
            hx, hy = geom.to_px(now["head_x_mm"].to_numpy(), now["head_y_mm"].to_numpy())
            d = geom.distance_to_cell_mm(hx, hy)
            at_cell = set(now["bee_id"][np.nan_to_num(d, nan=1e9) <= contact.margin_mm])
        for r in now.itertuples(index=False):
            p, ph = canvas.px(r.x_mm, r.y_mm), canvas.px(r.head_x_mm, r.head_y_mm)
            col = colors[r.bee_id]
            if r.bee_id in at_cell:
                cv2.circle(img, p, 15, _CELL, 2, cv2.LINE_AA)
            cv2.line(img, p, ph, col, 3, cv2.LINE_AA)
            cv2.circle(img, p, 7, col, -1, cv2.LINE_AA)
            cv2.circle(img, p, 7, _INK, 1, cv2.LINE_AA)
            _text(img, str(r.bee_id), (p[0] + 10, p[1] - 9), 0.45, _INK, 1, shadow=(255, 255, 255))
        # legend
        x0, y = canvas.S + 18, 34
        _text(img, "Bees" if setup.marking == "color" else "Tracks", (x0, y), 0.6, _INK, 2)
        present = set(now["bee_id"])
        shown = plan.bees if len(plan.bees) <= 26 else sorted(present)[:26]
        for b in shown:
            y += 28
            cv2.rectangle(img, (x0, y - 13), (x0 + 16, y + 3), colors[b], -1)
            cv2.rectangle(img, (x0, y - 13), (x0 + 16, y + 3), _INK, 1)
            label = f"{b}" + ("   at cell" if b in at_cell else ("" if b in present else "   (not seen)"))
            _text(img, label, (x0 + 26, y), 0.48, _CELL if b in at_cell else (_INK if b in present else _MUTED), 1)
        _text(img, f"{len(at_cell)} at the queen cell", (x0, canvas.S - 50), 0.5, _CELL, 1)
        _text(img, f"{step_desc} / {trail_desc}", (x0, canvas.S - 24), 0.42, _MUTED, 1)
        canvas.header(img, f / src_fps)
        w.write(img)
        prev_out = f
        if progress and k % 25 == 0:
            progress(min(0.98, (k + 1) / max(1, total)), f"frame {k + 1}/{total}")
    return _done(w.close(), progress)


# --------------------------------------------------------------------------- #
# 3. where bees spend time (occupancy heatmap)
# --------------------------------------------------------------------------- #
def render_heatmap(setup: ExperimentSetup, cfg: AnalysisConfig, traj: pd.DataFrame, width: int, height: int, src_fps: float,
                   out: str | Path, opts: RenderOptions, progress: ProgressFn | None = None, title: str = "Where bees spend time",
                   bins: int = 90) -> Path:
    geom = Geometry.from_setup(setup, width, height)
    plan = _Plan(traj, src_fps, opts)
    canvas = _MapCanvas(geom, setup, cfg, title)
    w = _Writer(Path(out), opts.fps, (canvas.base.shape[1], canvas.base.shape[0]))
    R = canvas.R
    dt = plan.analysis_step / src_fps
    H = np.zeros((bins, bins))
    chunks: deque[tuple[int, np.ndarray]] = deque()
    side = int(round(2 * R * canvas.k))
    x0, y0 = canvas.px(-R, R)
    yy, xx = np.mgrid[0:side, 0:side]
    disk = (xx - side / 2) ** 2 + (yy - side / 2) ** 2 <= (side / 2) ** 2
    prev_out = -1
    total = len(plan.out_frames)
    mode = "cumulative" if plan.trail_frames is None else f"last {opts.trail_s:g} s"
    for k, f in enumerate(plan.out_frames):
        f = int(f)
        new = plan.rows(prev_out, f).dropna(subset=["x_mm"])
        h, _, _ = np.histogram2d(new["x_mm"], new["y_mm"], bins=bins, range=[[-R, R], [-R, R]])
        H += h
        if plan.trail_frames is not None:
            chunks.append((f, h))
            while chunks and chunks[0][0] <= f - max(plan.trail_frames, plan.analysis_step):
                H -= chunks.popleft()[1]
        sec = np.clip(H.T[::-1], 0, None) * dt  # rows = y from top
        img = canvas.base.copy()
        vmax = float(sec.max())
        if vmax > 0:
            v = np.log1p(sec) / np.log1p(vmax)
            heat = cv2.resize(_heat(v), (side, side), interpolation=cv2.INTER_LINEAR)
            show = disk & (cv2.resize(v, (side, side)) > 0.02)
            roi = img[y0:y0 + side, x0:x0 + side]
            hh, ww = roi.shape[:2]
            roi[show[:hh, :ww]] = heat[:hh, :ww][show[:hh, :ww]]
        cv2.circle(img, canvas.px(0, 0), int(R * canvas.k), (180, 170, 160), 2, cv2.LINE_AA)
        if canvas.cell_px is not None:
            cv2.polylines(img, [canvas.cell_px], True, _CELL, 2, cv2.LINE_AA)
        # colour bar
        bx, by, bh = canvas.S + 30, 90, 360
        bar = _heat(np.linspace(1, 0, bh)[:, None].repeat(22, 1))
        img[by:by + bh, bx:bx + 22] = bar
        cv2.rectangle(img, (bx, by), (bx + 22, by + bh), _INK, 1)
        _text(img, "time per cell", (bx - 6, by - 30), 0.5, _INK, 1)
        _text(img, f"{vmax:.1f} s", (bx + 30, by + 8), 0.48, _INK, 1)
        _text(img, "0", (bx + 30, by + bh), 0.48, _INK, 1)
        _text(img, "(log scale)", (bx - 6, by + bh + 28), 0.42, _MUTED, 1)
        _text(img, f"{mode} · {_step_label(plan.step, plan.analysis_step, src_fps)}", (bx - 6, canvas.S - 50), 0.45, _INK, 1)
        who = "all bees" if not opts.bees else ", ".join(opts.bees[:4]) + ("…" if len(opts.bees) > 4 else "")
        _text(img, who, (bx - 6, canvas.S - 24), 0.42, _MUTED, 1)
        canvas.header(img, f / src_fps)
        w.write(img)
        prev_out = f
        if progress and k % 25 == 0:
            progress(min(0.98, (k + 1) / max(1, total)), f"frame {k + 1}/{total}")
    return _done(w.close(), progress)


def render(kind: VideoKind, *, videos, setup, cfg, traj, width, height, src_fps, out, opts, progress=None) -> Path:
    if traj.empty:
        raise ValueError("no trajectories to draw")
    if kind == "annotated":
        return render_annotated(videos, setup, cfg, traj, out, opts, progress)
    if kind == "paths":
        return render_paths(setup, cfg, traj, width, height, src_fps, out, opts, progress)
    if kind == "heatmap":
        return render_heatmap(setup, cfg, traj, width, height, src_fps, out, opts, progress)
    raise ValueError(f"unknown video kind {kind!r}")
