"""Unmarked bees: turn tracklets into anonymous tracks (``T001``, ``T002``, …).

Without paint there's no appearance cue, so identity can only come from
continuity. The tracker already cuts a tracklet whenever linking is uncertain.
Here we join tracklets back together **only when it's unambiguous**:

1. **Candidates**: tracklet *a* ends, tracklet *b* starts 0 < gap ≤
   ``stitch_max_gap_s`` later, at most ``stitch_max_dist_mm`` away.
2. **Never guess**: if *b* has a second candidate predecessor (or *a* a second
   candidate successor) whose distance is < ``stitch_ambiguity_ratio`` × the
   best one, the link is skipped. Two bees separating after a contact look
   exactly like that, and a wrong join would silently merge two bees' paths.
3. **Greedy by distance**: unambiguous candidate links are accepted closest
   first, each tracklet with at most one predecessor and one successor.
4. Chains shorter than ``min_track_s`` are dropped (noise, fragments). The
   rest are named ``T001…`` by start time.

What a track means: *one bee, continuously, from the track's start to its
end*. The same bee can appear as several tracks over a recording. Per-track
numbers are therefore lower bounds on per-bee numbers. Population-level
numbers (total visits, time at the cell, bees at the cell over time) are not
affected.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import UnmarkedConfig


def stitch_tracklets(det: pd.DataFrame, fps: float, px_per_mm: float, cfg: UnmarkedConfig) -> pd.DataFrame:
    """Add ``bee_id`` (track name, or None for dropped fragments) and ``id_confidence`` (NaN) to ``det``."""
    det = det.copy()
    if det.empty:
        det["bee_id"] = pd.Series(dtype=object)
        det["id_confidence"] = pd.Series(dtype=float)
        return det
    g = det.sort_values("frame").groupby("tracklet")
    first, last = g.first(), g.last()
    ends = last[["frame", "x_px", "y_px"]].rename(columns=lambda c: f"e_{c}")
    starts = first[["frame", "x_px", "y_px"]].rename(columns=lambda c: f"s_{c}")
    max_gap = cfg.stitch_max_gap_s * fps
    max_d = cfg.stitch_max_dist_mm * px_per_mm

    # candidate links a → b: b starts within (end of a, end of a + max_gap] and within max_d.
    # Starts are sorted by frame, so each end only looks at a short window (memory stays small on long recordings).
    E = ends.reset_index().to_numpy()    # tracklet, e_frame, e_x, e_y
    S = starts.reset_index().to_numpy()  # tracklet, s_frame, s_x, s_y
    S = S[np.argsort(S[:, 1], kind="stable")]
    s_frames = S[:, 1]
    cands: list[tuple[float, int, int]] = []          # (distance, index into E, index into S)
    succ_d: dict[int, list[float]] = {}               # per end: distances of all its candidate successors
    pred_d: dict[int, list[float]] = {}               # per start: distances of all its candidate predecessors
    for a in range(len(E)):
        lo = np.searchsorted(s_frames, E[a, 1], side="right")
        hi = np.searchsorted(s_frames, E[a, 1] + max_gap, side="right")
        if hi <= lo:
            continue
        d = np.hypot(S[lo:hi, 2] - E[a, 2], S[lo:hi, 3] - E[a, 3])
        for j in np.flatnonzero((d <= max_d) & (S[lo:hi, 0] != E[a, 0])):
            b = lo + int(j)
            cands.append((float(d[j]), a, b))
            succ_d.setdefault(a, []).append(float(d[j]))
            pred_d.setdefault(b, []).append(float(d[j]))
    cands.sort()

    def ambiguous(d: float, a: int, b: int) -> bool:
        limit = cfg.stitch_ambiguity_ratio * max(d, 1e-6)
        return sum(x < limit for x in pred_d[b]) > 1 or sum(x < limit for x in succ_d[a]) > 1

    succ: dict[int, int] = {}
    pred: dict[int, int] = {}
    for d, a, b in cands:
        ta, tb = int(E[a, 0]), int(S[b, 0])
        if ta in succ or tb in pred or ambiguous(d, a, b):
            continue
        succ[ta], pred[tb] = tb, ta

    # follow chains from their heads
    chain_of: dict[int, int] = {}
    chains: list[list[int]] = []
    for t in first.sort_values("frame").index:
        t = int(t)
        if t in pred:
            continue
        chain = [t]
        while chain[-1] in succ:
            chain.append(succ[chain[-1]])
        for x in chain:
            chain_of[x] = len(chains)
        chains.append(chain)

    min_frames = cfg.min_track_s * fps
    names: dict[int, str | None] = {}
    k = 0
    for ci, chain in enumerate(chains):
        span = last.loc[chain[-1], "frame"] - first.loc[chain[0], "frame"]
        if span < min_frames:
            names[ci] = None
        else:
            k += 1
            names[ci] = f"T{k:03d}"
    det["bee_id"] = det["tracklet"].map(lambda t: names[chain_of[int(t)]])
    det["id_confidence"] = np.nan  # no identity evidence in unmarked mode
    return det
