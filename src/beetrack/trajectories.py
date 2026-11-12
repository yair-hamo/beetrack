"""Per-bee trajectories in millimetres, on a regular time grid.

From identified detections, for each bee:

1. **One observation per analysed frame.** If two detections claim the same
   bee in one frame (rare after resolution), keep the most confident.
2. **Regular grid.** Re-index onto every analysed frame and mark ``observed``.
3. **Gap filling.** Linear interpolation for gaps ≤ ``max_interp_gap_s`` whose
   crossing speed is plausible (≤ ``max_interp_speed_mm_s``).
   Longer gaps (≤ ``max_still_gap_s``) are filled only if the bee reappears
   where it vanished (a resting bee hidden in a cluster). Anything else
   stays NaN: unknown is better than invented.
4. **Smoothing.** A centred rolling median removes segmentation jitter.
5. **Kinematics.** Velocity from central differences, then speed (mm/s).
6. **Heading.** The body axis has a 180° ambiguity. Resolved per frame by
   (a) the mark, when it sits clearly ahead of or behind the body centre
   (thorax or abdomen): which of the two is learned per bee from the frames in
   which it walks, and then also works while it stands still; (b) velocity
   when moving; (c) continuity.
7. **Head point** = centroid + ``head_offset_fraction`` × the bee's median
   body length, along the heading. This is the point used for queen-cell
   contact.

If a detector already supplies head coordinates (SLEAP), those are used
directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .calibration import Geometry
from .config import TrajectoryConfig

TRAJ_COLUMNS = [
    "bee_id", "frame", "time_s", "x_mm", "y_mm", "head_x_mm", "head_y_mm",
    "heading_deg", "speed_mm_s", "observed", "interpolated", "id_confidence",
]


def _angdiff(a, b):
    return np.abs(np.angle(np.exp(1j * (np.asarray(a) - np.asarray(b)))))


def _resolve_heading(axis: np.ndarray, vx: np.ndarray, vy: np.ndarray, moving: np.ndarray,
                     spot: np.ndarray | None = None) -> np.ndarray:
    """Heading per frame (radians, mm frame) from the body axis plus direction cues.

    Cue priority for picking ``axis`` vs ``axis + π``:

    1. **mark**: the direction the mark says the head is in (works when still).
       If the axis disagrees with it by more than 45° (a merged blob gives a
       meaningless axis), the dot vector itself is the heading;
    2. **motion**: velocity direction when moving;
    3. **continuity**: closest to the previous heading (forward pass, then
       a backward pass fills the start).
    """
    n = len(axis)
    spot = np.full(n, np.nan) if spot is None else spot
    out = np.full(n, np.nan)
    prev = np.nan
    for i in range(n):
        a = axis[i]
        if np.isfinite(spot[i]):
            if np.isfinite(a):
                c = np.array([a, a + np.pi])
                best = c[int(np.argmin(_angdiff(c, spot[i])))]
                prev = out[i] = best if _angdiff(best, spot[i]) < np.pi / 4 else spot[i]
            else:
                prev = out[i] = spot[i]
            continue
        if not np.isfinite(a):
            continue
        cands = np.array([a, a + np.pi])
        if moving[i]:
            ref = np.arctan2(vy[i], vx[i])
        elif np.isfinite(prev):
            ref = prev
        else:
            continue
        prev = out[i] = cands[int(np.argmin(_angdiff(cands, ref)))]
    nxt = np.nan
    for i in range(n - 1, -1, -1):
        if np.isfinite(out[i]):
            nxt = out[i]
        elif np.isfinite(axis[i]) and np.isfinite(nxt):
            cands = np.array([axis[i], axis[i] + np.pi])
            nxt = out[i] = cands[int(np.argmin(_angdiff(cands, nxt)))]
    return np.angle(np.exp(1j * out))  # wrap to (-π, π]


def _dot_share(dot: np.ndarray, vel: np.ndarray, moving: np.ndarray) -> tuple[int, int]:
    """(frames in which the mark is ahead of the body centre, frames usable) while the bee walks."""
    ok = moving & np.isfinite(dot) & np.isfinite(vel)
    return int((np.cos(dot[ok] - vel[ok]) > 0).sum()), int(ok.sum())


def learn_mark_positions(det: pd.DataFrame, codes: dict[str, str], px_per_mm: float, fps: float, step_frames: int,
                         moving_speed_mm_s: float, min_frames: int = 8, min_agreement: float = 0.75) -> dict[str, int]:
    """Per bee: is the mark ahead of the body centre (+1, thorax), behind it (−1, abdomen), or unknown (0)?

    Bees walk forwards, so while a bee moves, the centre→mark vector points
    either along its velocity or against it; a clear majority of frames decides.
    A bee that hardly walked (or whose mark was rarely read) takes the answer of
    the other bees, if at least two could be judged and they all agree: people
    mark a whole group the same way.
    """
    signs: dict[str, int] = {}
    for bee, g in det[det["bee_id"].isin(codes)].groupby("bee_id"):
        g = g.drop_duplicates("frame").sort_values("frame")
        if len(g) < 3:
            signs[bee] = 0
            continue
        f, x, y = g["frame"].to_numpy(float), g["x_px"].to_numpy(float), g["y_px"].to_numpy(float)
        # velocity over about ±0.3 s: frame-to-frame differences are mostly segmentation jitter
        k = max(1, int(round(0.3 * fps / step_frames)))
        if len(g) <= 2 * k:
            signs[bee] = 0
            continue
        span = f[2 * k:] - f[:-2 * k]
        vx, vy = (x[2 * k:] - x[:-2 * k]) / span * fps, (y[2 * k:] - y[:-2 * k]) / span * fps  # px/s, image frame
        steady = span <= 3 * k * step_frames                       # no long gap inside the window
        moving = steady & (np.hypot(vx, vy) > max(moving_speed_mm_s, 4.0) * px_per_mm)
        med_len = np.nanmedian(g["major_px"].to_numpy(float))
        dot = -_dot_heading(g, codes[bee], min_offset_px=0.06 * med_len)[k:-k]  # back to the image frame (y down)
        ahead, n = _dot_share(dot, np.arctan2(vy, vx), moving)
        share = ahead / n if n else 0.5
        signs[bee] = 0 if n < min_frames else (1 if share >= min_agreement else (-1 if share <= 1 - min_agreement else 0))
    decided = [v for v in signs.values() if v]
    if len(decided) >= 2 and len(set(decided)) == 1:  # all we could judge agree: assume the rest were marked the same way
        signs = {b: (v or decided[0]) for b, v in signs.items()}
    return signs


def _dot_heading(g: pd.DataFrame, color: str, min_offset_px: float) -> np.ndarray:
    """Image→mm direction from the body centre to this bee's mark (NaN if not seen or too central)."""
    n = len(g)
    if "s1_color" not in g:
        return np.full(n, np.nan)
    dx, dy = np.full(n, np.nan), np.full(n, np.nan)
    for k in (2, 1):  # s1 (largest) wins
        c = g[f"s{k}_color"].to_numpy()
        hit = c == color
        dx = np.where(hit, g[f"s{k}_x"].to_numpy(float) - g["x_px"].to_numpy(float), dx)
        dy = np.where(hit, g[f"s{k}_y"].to_numpy(float) - g["y_px"].to_numpy(float), dy)
    h = np.arctan2(-dy, dx)  # y flipped: image down = mm up
    h[np.hypot(dx, dy) < min_offset_px] = np.nan  # dot too close to the centre to tell direction
    return h


def _fill_gaps(t: pd.DataFrame, max_len: int, accept) -> None:
    """In place: linearly fill each NaN gap of ≤ ``max_len`` samples for which ``accept(distance_mm, n_steps)`` holds.

    ``distance_mm`` is how far apart the two ends of the gap are and ``n_steps``
    the number of sample intervals it spans. Gaps at the very start or end have
    only one side and are never filled.
    """
    x = t["x"].to_numpy()
    missing = np.isnan(x)
    if not missing.any() or max_len <= 0:
        return
    edges = np.diff(np.concatenate([[0], missing.astype(int), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)  # [start, end)
    cols = list(t.columns)
    for s, e in zip(starts, ends):
        if s == 0 or e >= len(x) or e - s > max_len:
            continue
        a, b = t.iloc[s - 1], t.iloc[e]
        if not accept(float(np.hypot(a["x"] - b["x"], a["y"] - b["y"])), e - s + 1):
            continue
        w = (np.arange(1, e - s + 1) / (e - s + 1))[:, None]
        t.iloc[s:e, :] = (1 - w) * a[cols].to_numpy()[None, :] + w * b[cols].to_numpy()[None, :]


def build_trajectories(
    det: pd.DataFrame,
    geom: Geometry,
    cfg: TrajectoryConfig,
    analysed_frames: np.ndarray,
    source_fps: float,
    codes: dict[str, str] | None = None,
    dot_position: str = "auto",
    report: dict | None = None,
) -> pd.DataFrame:
    """Identified detections → long-format trajectory table (see TRAJ_COLUMNS).

    ``codes`` maps bee_id → mark colour. With it, the mark's position relative
    to the body centre is used to tell head from tail (``dot_position``: see
    :class:`~beetrack.config.ColorIdConfig`). If ``report`` is given, it
    receives ``{bee_id: "thorax" | "abdomen" | "unknown"}`` (what was used).
    """
    det = det[det["bee_id"].notna()]
    if det.empty:
        return pd.DataFrame(columns=TRAJ_COLUMNS)
    step_frames = int(np.median(np.diff(analysed_frames))) if len(analysed_frames) > 1 else 1
    dt = step_frames / source_fps
    max_gap = int(round(cfg.max_interp_gap_s / dt))
    win = max(1, int(round(cfg.smooth_window_s / dt)) | 1)

    signs: dict[str, int] = {}
    if codes and dot_position == "auto":
        signs = learn_mark_positions(det, codes, geom.px_per_mm, source_fps, step_frames, cfg.moving_speed_mm_s)

    out = []
    grid = pd.Index(analysed_frames, name="frame")
    for bee, g in det.groupby("bee_id"):
        g = g.sort_values("id_confidence", ascending=False).drop_duplicates("frame").set_index("frame").sort_index()
        g = g.reindex(grid)
        observed = g["x_px"].notna().to_numpy()

        x_mm, y_mm = geom.to_mm(g["x_px"].to_numpy(), g["y_px"].to_numpy())
        has_head = np.isfinite(g["head_x_px"].to_numpy()).any()
        if has_head:
            hx_mm, hy_mm = geom.to_mm(g["head_x_px"].to_numpy(), g["head_y_px"].to_numpy())
        t = pd.DataFrame({"x": x_mm, "y": y_mm}, index=grid)
        if has_head:
            t["hx"], t["hy"] = hx_mm, hy_mm
        # a resting bee hidden in a cluster that reappears in the same place
        _fill_gaps(t, int(round(cfg.max_still_gap_s / dt)), lambda d, n: d <= cfg.still_gap_max_move_mm)
        # a short gap the bee could have walked across (a faster "crossing" is a tracking jump, not a walk)
        _fill_gaps(t, max_gap, lambda d, n: d / (n * dt) <= cfg.max_interp_speed_mm_s)
        interpolated = t["x"].notna().to_numpy() & ~observed
        if win > 1:
            t = t.rolling(win, center=True, min_periods=1).median().where(t.notna())

        if len(t) > 1:
            vx = np.gradient(t["x"].to_numpy()) / dt
            vy = np.gradient(t["y"].to_numpy()) / dt
        else:  # a single analysed frame has no velocity
            vx = vy = np.full(len(t), np.nan)
        speed = np.hypot(vx, vy)
        moving = np.nan_to_num(speed) > cfg.moving_speed_mm_s

        if has_head:
            hx, hy = t["hx"].to_numpy(), t["hy"].to_numpy()
            heading = np.arctan2(hy - t["y"].to_numpy(), hx - t["x"].to_numpy())
        else:
            # image-frame axis angle → mm frame (y flipped ⇒ angle negated)
            axis_mm = -g["axis_angle"].to_numpy()
            if max_gap > 0:
                axis_mm = pd.Series(axis_mm, index=grid).ffill(limit=max_gap).to_numpy()
            spot, used = None, "unknown"
            if codes and bee in codes and dot_position != "unknown":
                med_len = np.nanmedian(g["major_px"].to_numpy(float))
                dot = _dot_heading(g, codes[bee], min_offset_px=0.06 * med_len)
                sign = {"thorax": 1, "abdomen": -1}.get(dot_position) or signs.get(bee, 0)
                if sign:
                    spot = dot if sign > 0 else np.angle(np.exp(1j * (dot + np.pi)))
                    used = "thorax" if sign > 0 else "abdomen"
            if report is not None and codes and bee in codes:
                report[bee] = used
            heading = _resolve_heading(axis_mm, vx, vy, moving, spot)
            # body length: this bee's median over single-bee blobs (merged blobs give garbage)
            area = g["area_px"]
            single = area.between(0.7 * area.median(), 1.3 * area.median())
            body_mm = float(np.nanmedian(g.loc[single, "major_px"])) / geom.px_per_mm if single.any() else np.nan
            off = cfg.head_offset_fraction * body_mm
            known = np.isfinite(heading)
            hx = np.where(known, t["x"].to_numpy() + off * np.cos(heading), t["x"].to_numpy())
            hy = np.where(known, t["y"].to_numpy() + off * np.sin(heading), t["y"].to_numpy())

        conf = pd.Series(g["id_confidence"].to_numpy(), index=grid).ffill().bfill().to_numpy()
        out.append(pd.DataFrame({
            "bee_id": bee,
            "frame": analysed_frames,
            "time_s": analysed_frames / source_fps,
            "x_mm": t["x"].to_numpy(),
            "y_mm": t["y"].to_numpy(),
            "head_x_mm": hx,
            "head_y_mm": hy,
            "heading_deg": np.degrees(heading),
            "speed_mm_s": speed,
            "observed": observed,
            "interpolated": interpolated,
            "id_confidence": conf,
        }))
    return pd.concat(out, ignore_index=True)[TRAJ_COLUMNS]
