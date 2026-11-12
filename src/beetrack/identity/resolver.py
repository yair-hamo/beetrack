"""Assign bee IDs to tracklets from accumulated colour evidence.

Input: the detections table (one row per detection) with ``tracklet`` and the
per-detection colour scores. Output: the same table with a ``bee_id`` column
(``None`` = unidentified) and an ``id_confidence`` column (the winning bee's
share of the evidence).

Steps
-----
1. **Split on identity switches.** When two bees cross, the tracker can
   occasionally swap them. Inside each tracklet we look at frames with a
   *full* code match, smooth them with a rolling majority, and cut the
   tracklet where the majority label changes for good (each side needs
   ``switch_min_votes`` full matches).
2. **Vote.** Sum the evidence per (tracklet, bee).
3. **Assign without conflicts.** Each bee is in at most one place at a time,
   so two tracklets that overlap in time can't get the same bee. Candidate
   pairs are taken greedily in order of evidence × purity. A pair is
   accepted only if the bee is free for the tracklet's whole time span and
   the evidence passes ``min_votes`` and ``min_purity``.
4. **Gap-linking.** Tracklets with too little colour evidence (typically
   fragments inside a cluster on the queen cell) inherit the identity of
   the named tracklet they continue in space and time, if exactly one bee
   fits.

This is the same idea as NAPS (Wolf et al. 2023, *Methods Ecol Evol*): keep
identity separate from tracking, accumulate ID evidence over time windows,
and carry identity across frames where the mark can't be read. NAPS reads
ArUco tags; we read paint codes. A tag reader could replace
:class:`~beetrack.identity.ColorCodeIdentifier` without changing this module.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from ..config import IdentityConfig


class IdentityResolver:
    def __init__(self, cfg: IdentityConfig):
        self.cfg = cfg

    # ------------------------------------------------------------------ #
    def split_switches(self, det: pd.DataFrame, scores: list[dict[str, float]]) -> pd.Series:
        """Return new tracklet ids, with tracklets cut at detected identity switches."""
        new_ids = det["tracklet"].to_numpy().copy()
        next_id = int(new_ids.max()) + 1 if len(new_ids) else 0
        w = self.cfg.switch_window
        for tid, idx in det.groupby("tracklet").indices.items():
            idx = np.sort(idx)
            full = [(i, max(scores[i], key=scores[i].get)) for i in idx if scores[i] and max(scores[i].values()) >= 1.0]
            if len(full) < 2 * self.cfg.switch_min_votes:
                continue
            labels = [b for _, b in full]
            smooth = []
            for k in range(len(labels)):
                win = labels[max(0, k - w // 2): k + w // 2 + 1]
                smooth.append(max(set(win), key=win.count))
            # runs of constant smoothed label
            runs: list[tuple[int, int, str]] = []
            start = 0
            for k in range(1, len(smooth) + 1):
                if k == len(smooth) or smooth[k] != smooth[start]:
                    runs.append((start, k, smooth[start]))
                    start = k
            runs = [r for r in runs if r[1] - r[0] >= self.cfg.switch_min_votes]
            # merge neighbouring runs with the same label
            merged: list[list] = []
            for r in runs:
                if merged and merged[-1][2] == r[2]:
                    merged[-1][1] = r[1]
                else:
                    merged.append(list(r))
            if len(merged) < 2:
                continue
            frames = det["frame"].to_numpy()
            for a, b in zip(merged[:-1], merged[1:]):
                f_end = frames[full[a[1] - 1][0]]
                f_start = frames[full[b[0]][0]]
                cut = (f_end + f_start) / 2
                sel = idx[(frames[idx] > cut) & (new_ids[idx] == new_ids[idx[-1]])]
                new_ids[sel] = next_id
                next_id += 1
        return pd.Series(new_ids, index=det.index)

    # ------------------------------------------------------------------ #
    def resolve(self, det: pd.DataFrame, scores: list[dict[str, float]], bee_ids: list[str],
                max_gap_frames: int = 0, max_dist_px: float = 0.0) -> pd.DataFrame:
        """Name tracklets. ``max_gap_frames``/``max_dist_px`` enable gap-linking (step 4)."""
        det = det.copy()
        det["tracklet"] = self.split_switches(det, scores)

        evidence: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for i, tid in enumerate(det["tracklet"].to_numpy()):
            for b, s in scores[i].items():
                evidence[int(tid)][b] += s
        span = det.groupby("tracklet")["frame"].agg(["min", "max"])

        candidates = []
        for tid, ev in evidence.items():
            total = sum(ev.values())
            for b, v in ev.items():
                purity = v / total if total else 0.0
                if v >= self.cfg.min_votes and purity >= self.cfg.min_purity:
                    candidates.append((v * purity, tid, b, purity))
        candidates.sort(reverse=True)

        occupied: dict[str, list[tuple[int, int]]] = defaultdict(list)
        assigned: dict[int, tuple[str, float]] = {}
        for _, tid, b, purity in candidates:
            if tid in assigned or b not in bee_ids:
                continue
            lo, hi = int(span.at[tid, "min"]), int(span.at[tid, "max"])
            if any(not (hi < a or lo > z) for a, z in occupied[b]):
                continue
            occupied[b].append((lo, hi))
            assigned[tid] = (b, purity)

        if max_gap_frames > 0 and max_dist_px > 0:
            self._link_unidentified(det, span, assigned, occupied, max_gap_frames, max_dist_px)

        det["bee_id"] = det["tracklet"].map(lambda t: assigned.get(int(t), (None, 0.0))[0])
        det["id_confidence"] = det["tracklet"].map(lambda t: assigned.get(int(t), (None, 0.0))[1])
        return det

    # ------------------------------------------------------------------ #
    @staticmethod
    def _link_unidentified(det, span, assigned, occupied, max_gap, max_dist) -> None:
        """Gap-linking: name an unidentified tracklet after the bee it continues.

        An unnamed tracklet ``u`` takes bee *B* if one of *B*'s tracklets ends
        shortly before ``u`` starts (or starts shortly after ``u`` ends), close
        in space, and *B* is free during ``u``. Only unambiguous links are
        made (exactly one candidate bee). Repeats until nothing changes, so
        chains of short fragments are followed. Linked tracklets get half the
        neighbour's confidence, marking them as inferred.
        """
        g = det.sort_values("frame").groupby("tracklet")
        first = g.first()[["frame", "x_px", "y_px"]]
        last = g.last()[["frame", "x_px", "y_px"]]
        for _ in range(20):
            changed = False
            named = [t for t in assigned]
            for u in span.index:
                u = int(u)
                if u in assigned:
                    continue
                lo, hi = int(span.at[u, "min"]), int(span.at[u, "max"])
                cands: dict[str, float] = {}
                for t in named:
                    bee, conf = assigned[t]
                    # t ends before u starts
                    gap = lo - int(last.at[t, "frame"])
                    if 0 < gap <= max_gap and np.hypot(first.at[u, "x_px"] - last.at[t, "x_px"],
                                                       first.at[u, "y_px"] - last.at[t, "y_px"]) <= max_dist:
                        cands[bee] = max(cands.get(bee, 0), conf)
                    # t starts after u ends
                    gap = int(first.at[t, "frame"]) - hi
                    if 0 < gap <= max_gap and np.hypot(first.at[t, "x_px"] - last.at[u, "x_px"],
                                                       first.at[t, "y_px"] - last.at[u, "y_px"]) <= max_dist:
                        cands[bee] = max(cands.get(bee, 0), conf)
                free = {b: c for b, c in cands.items() if not any(not (hi < a or lo > z) for a, z in occupied[b])}
                if len(free) == 1:
                    (b, c), = free.items()
                    assigned[u] = (b, 0.5 * c)
                    occupied[b].append((lo, hi))
                    changed = True
            if not changed:
                break
