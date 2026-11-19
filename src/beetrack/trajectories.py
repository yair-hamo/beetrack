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
    "heading_deg", "heading_source", "speed_mm_s", "observed", "interpolated", "id_confidence",
]


def _angdiff(a, b):
    return np.abs(np.angle(np.exp(1j * (np.asarray(a) - np.asarray(b)))))


ANCHORS = ("mark", "motion")
# heading sources good enough to say which way a bee faces (see the accuracy table in CLAUDE.md)
RELIABLE_HEADING = ("head", "mark", "motion", "shape")


def _resolve_heading(axis: np.ndarray, vx: np.ndarray, vy: np.ndarray, moving: np.ndarray,
                     spot: np.ndarray | None = None, shape: np.ndarray | None = None,
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Heading per frame (radians, mm frame) and where it came from.

    The body axis has a 180° ambiguity; cues pick ``axis`` or ``axis + π``:

    1. **mark**: the direction the mark says the head is in (works when still).
       If the axis disagrees with it by more than 45° (a merged blob gives a
       meaningless axis), the dot vector itself is the heading;
    2. **motion**: velocity direction when moving;
    3. **continuity**: closest to the previous heading (forward pass, then
       a backward pass fills the start);
    4. **shape** (optional, ``shape`` = per-frame head direction from the
       silhouette, NaN if unusable): each run of continuity-only frames is
       checked against the shape votes inside it and flipped as a whole when
       they clearly disagree. A run that continues straight from a mark/motion
       frame needs stronger evidence than one whose start was uncertain (a gap,
       an axis jump in a cluster, or the start of the track).

    Returns ``(heading, source)`` with source in ``mark / motion / continuity / shape / guess / ""``:
    (``build_trajectories`` adds ``cluster``: the bee was part of a merged blob, so no cue is trustworthy.)
    ``continuity`` = carried over unbroken from a mark/motion frame; ``guess`` = a run whose start
    was uncertain and that nothing confirmed (≈ a coin toss; facing tests treat it as unknown).
    """
    n = len(axis)
    spot = np.full(n, np.nan) if spot is None else spot
    out = np.full(n, np.nan)
    src = np.full(n, "", dtype=object)
    brk = np.zeros(n, bool)       # continuity choice was a guess here (gap or ambiguous axis jump)
    back = np.zeros(n, bool)      # filled by the backward pass
    prev, prev_i = np.nan, -2
    for i in range(n):
        a = axis[i]
        if np.isfinite(spot[i]):
            if np.isfinite(a):
                c = np.array([a, a + np.pi])
                best = c[int(np.argmin(_angdiff(c, spot[i])))]
                prev = out[i] = best if _angdiff(best, spot[i]) < np.pi / 4 else spot[i]
            else:
                prev = out[i] = spot[i]
            src[i], prev_i = "mark", i
            continue
        if not np.isfinite(a):
            continue
        cands = np.array([a, a + np.pi])
        if moving[i]:
            ref, src[i] = np.arctan2(vy[i], vx[i]), "motion"
        elif np.isfinite(prev):
            ref, src[i] = prev, "continuity"
            brk[i] = prev_i != i - 1 or float(np.min(_angdiff(cands, ref))) > np.pi / 3
        elif shape is not None and np.isfinite(shape[i]):
            ref, src[i], brk[i] = shape[i], "continuity", True   # nothing yet: start from the silhouette (checked below)
        else:
            continue
        prev = out[i] = cands[int(np.argmin(_angdiff(cands, ref)))]
        prev_i = i
    nxt, nxt_i = np.nan, n + 1
    for i in range(n - 1, -1, -1):
        if np.isfinite(out[i]):
            nxt, nxt_i = out[i], i
        elif np.isfinite(axis[i]) and np.isfinite(nxt):
            cands = np.array([axis[i], axis[i] + np.pi])
            brk[i] = nxt_i != i + 1 or float(np.min(_angdiff(cands, nxt))) > np.pi / 3
            nxt = out[i] = cands[int(np.argmin(_angdiff(cands, nxt)))]
            src[i], back[i], nxt_i = "continuity", True, i
    _check_runs(out, src, brk, back, shape if shape is not None and np.isfinite(shape).any() else None)
    return np.angle(np.exp(1j * out)), src


def _check_runs(out, src, brk, back, shape, min_votes: int = 3, detached: float = 0.65, attached: float = 0.8):
    """Each run of continuity frames: check it against the silhouette (flip it when clearly backwards), and
    relabel it ``guess`` when nothing supports it (its start was uncertain and no silhouette evidence)."""
    n = len(out)
    i = 0
    while i < n:
        if src[i] != "continuity":
            i += 1
            continue
        j = i + 1
        while j < n and src[j] == "continuity" and back[j] == back[i] and not (brk[j] if not back[j] else brk[j - 1]):
            j += 1
        # run = [i, j)
        if back[i]:   # backward-filled: its anchor is on the right
            anchored = j < n and src[j] in ANCHORS and not brk[j - 1]
        else:
            anchored = i > 0 and src[i - 1] in ANCHORS and not brk[i]
        votes = np.cos(shape[i:j] - out[i:j]) if shape is not None else np.array([])
        votes = votes[np.isfinite(votes)]
        if not anchored:
            src[i:j] = "guess"
        if len(votes) >= min_votes:
            disagree = float((votes < 0).mean())
            need = attached if anchored else detached
            if disagree >= need:
                out[i:j] += np.pi
                src[i:j] = "shape"
            elif 1 - disagree >= need:
                src[i:j] = "shape"   # the silhouette confirms the guess
        i = j


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


def _window_velocity(g: pd.DataFrame, fps: float, step_frames: int, px_per_mm: float, moving_speed_mm_s: float):
    """(k, direction, moving) from positions over about ±0.3 s (frame-to-frame differences are mostly jitter).
    ``direction`` (image frame, radians) and ``moving`` are for rows ``k … len-k-1``."""
    f, x, y = g["frame"].to_numpy(float), g["x_px"].to_numpy(float), g["y_px"].to_numpy(float)
    k = max(1, int(round(0.3 * fps / step_frames)))
    if len(g) <= 2 * k:
        return k, np.array([]), np.array([], bool)
    span = f[2 * k:] - f[:-2 * k]
    vx, vy = (x[2 * k:] - x[:-2 * k]) / span * fps, (y[2 * k:] - y[:-2 * k]) / span * fps
    steady = span <= 3 * k * step_frames
    moving = steady & (np.hypot(vx, vy) > max(moving_speed_mm_s, 4.0) * px_per_mm)
    return k, np.arctan2(vy, vx), moving


def _single_bee(g: pd.DataFrame, area_median: float) -> np.ndarray:
    a = g["area_px"].to_numpy(float)
    return (a >= 0.7 * area_median) & (a <= 1.3 * area_median)


def learn_shape_sign(det: pd.DataFrame, px_per_mm: float, fps: float, step_frames: int, moving_speed_mm_s: float,
                     min_skew: float = 0.05, min_frames: int = 50, min_agreement: float = 0.7) -> dict:
    """Does the silhouette's lopsidedness (``axis_skew``) point to the head (+1), the tail (−1), or neither (0)?

    Learned from this video: while single bees walk, the head is in the direction of motion. Real bees
    (wings over the abdomen, a long tapering abdomen) and the lighting decide the sign, so it is never
    assumed. Returns ``{"sign", "agreement", "frames"}``.
    """
    if "axis_skew" not in det or det["axis_skew"].isna().all():
        return {"sign": 0, "agreement": None, "frames": 0}
    area_median = float(det["area_px"].median())
    hits = total = 0
    for _, g in det[det["bee_id"].notna()].groupby("bee_id"):
        g = g.drop_duplicates("frame").sort_values("frame")
        k, vel, moving = _window_velocity(g, fps, step_frames, px_per_mm, moving_speed_mm_s)
        if not len(vel):
            continue
        sk = g["axis_skew"].to_numpy(float)[k:-k]
        ax = g["axis_angle"].to_numpy(float)[k:-k]
        ok = moving & np.isfinite(sk) & (np.abs(sk) >= min_skew) & np.isfinite(ax) & _single_bee(g, area_median)[k:-k]
        d = ax[ok] + np.where(sk[ok] > 0, 0.0, np.pi)   # the end the silhouette's tail points to
        hits += int((np.cos(d - vel[ok]) > 0).sum())
        total += int(ok.sum())
    if total < min_frames:
        return {"sign": 0, "agreement": None, "frames": total}
    share = hits / total
    sign = 1 if share >= min_agreement else (-1 if share <= 1 - min_agreement else 0)
    return {"sign": sign, "agreement": round(max(share, 1 - share), 3), "frames": total}


def _shape_heading(g: pd.DataFrame, sign: int, area_median: float, min_skew: float = 0.05) -> np.ndarray:
    """Per-row head direction (mm frame) from the silhouette, NaN where it can't be trusted."""
    sk = g["axis_skew"].to_numpy(float) if "axis_skew" in g else np.full(len(g), np.nan)
    ax = g["axis_angle"].to_numpy(float)
    ok = np.isfinite(sk) & (np.abs(sk) >= min_skew) & np.isfinite(ax) & _single_bee(g, area_median)
    img = ax + np.where(sk * sign > 0, 0.0, np.pi)
    return np.where(ok, np.angle(np.exp(-1j * img)), np.nan)   # y flipped: mm angle = −image angle


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
    heading_report: dict | None = None,
) -> pd.DataFrame:
    """Identified detections → long-format trajectory table (see TRAJ_COLUMNS).

    ``codes`` maps bee_id → mark colour. With it, the mark's position relative
    to the body centre is used to tell head from tail (``dot_position``: see
    :class:`~beetrack.config.ColorIdConfig`). If ``report`` is given, it
    receives ``{bee_id: "thorax" | "abdomen" | "unknown"}`` (what was used).
    ``heading_report`` receives the learned silhouette rule (``shape``) and the
    share of observed frames per heading source (``sources``).
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
    shape_info = {"sign": 0, "agreement": None, "frames": 0}
    if cfg.shape_heading and not np.isfinite(det["head_x_px"].to_numpy(float)).any():
        shape_info = learn_shape_sign(det, geom.px_per_mm, source_fps, step_frames, cfg.moving_speed_mm_s)
    area_median = float(det["area_px"].median()) if "area_px" in det else np.nan

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
            hsrc = np.where(np.isfinite(heading), "head", "")
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
            shape = _shape_heading(g, shape_info["sign"], area_median) if shape_info["sign"] else None
            # direction of travel over about ±0.3 s, and only clearly walking (≥ 4 mm/s): frame-to-frame
            # velocity in a cluster is mostly centroid jitter and points anywhere
            k = max(1, int(round(0.3 / dt)))
            xs, ys = t["x"].to_numpy(), t["y"].to_numpy()
            wx, wy = np.full(len(t), np.nan), np.full(len(t), np.nan)
            if len(t) > 2 * k:
                wx[k:-k], wy[k:-k] = (xs[2 * k:] - xs[:-2 * k]) / (2 * k * dt), (ys[2 * k:] - ys[:-2 * k]) / (2 * k * dt)
            walking = np.nan_to_num(np.hypot(wx, wy)) > max(cfg.moving_speed_mm_s, 4.0)
            heading, hsrc = _resolve_heading(axis_mm, wx, wy, walking, spot, shape)
            # two bees touching form one blob whose axis, centre and mark offset belong to neither: keep the
            # estimate (the head point needs one) but say it can't be trusted
            merged = observed & ~_single_bee(g, area_median)
            hsrc = np.where(merged & (hsrc != ""), "cluster", hsrc)
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
            "heading_source": hsrc,
            "speed_mm_s": speed,
            "observed": observed,
            "interpolated": interpolated,
            "id_confidence": conf,
        }))
    traj = pd.concat(out, ignore_index=True)[TRAJ_COLUMNS]
    if heading_report is not None:
        obs = traj[traj["observed"]]
        heading_report["shape"] = shape_info
        heading_report["sources"] = {k: round(float(v), 4) for k, v in
                                     obs["heading_source"].replace("", "none").value_counts(normalize=True).items()}
    return traj
