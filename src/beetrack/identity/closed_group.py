"""Closed-group identity: exactly N bees, each track piece assigned to one of them with a probability.

The dish holds a known, fixed number of bees N for the whole recording. So
instead of inventing a new anonymous ID every time a track breaks, every
piece of track is assigned to one of **N identities**:

* the **marked** bees from the registry (``W01``…), and
* ``N − marked`` **unmarked** bees (``U01``…).

Units of assignment ("pieces")
------------------------------
* Colour mode: the tracker's tracklets, already cut where the mark readings
  say two bees were swapped.
* Unmarked mode: tracklets joined where the join is unambiguous (see
  :func:`~beetrack.identity.anonymous.stitch_tracklets`).

A piece is taken to be one bee; the question is *which*.

Evidence (log-likelihood of piece *c* being identity *i*)
---------------------------------------------------------
* **Colour.** A marked bee shows its own mark in a fraction ``r`` of
  detections (estimated from the data), rarely another colour (``ε``), and
  otherwise nothing. An unmarked bee produces only rare spurious readings.
  So a few readings of blue are strong evidence for the blue bee, and a long
  piece with no reading at all is (mild) evidence *against* every marked
  identity: mild, because a mark stays hidden for whole stretches, so silent
  frames count once per ``silence_s`` seconds, not once per frame.
* **Motion.** A piece can only continue an identity that was last seen near
  where the piece starts: the gap distance over the gap time is scored as
  Gaussian with ``σ = σ0 + v·Δt``, and is impossible beyond
  ``vmax·Δt + slack``. The same applies to the identity's next piece.
* **Exclusion.** An identity is in one place at a time, so pieces that
  overlap in time can't share an identity. A piece for which no identity is
  free is a **false detection** (more blobs than bees) and is dropped.

Assignment
----------
1. *Anchors*: pieces whose mark readings make one marked bee very likely
   (posterior ≥ ``anchor_posterior``, ≥ ``min_votes`` readings, purity ≥
   ``min_purity``) are fixed first, strongest first.
2. A registered bee whose mark anchors nothing (its colour is never read
   clearly) can't be told apart by colour. It stays in the group, but from
   here on it is treated like an unmarked bee, and it is reported in
   ``never_read`` so the user can fix the registry.
3. The remaining pieces are assigned **longest first** (a long piece is
   surely a real bee; short fragments get what's left), each to the most
   probable identity that is free during its span.

Probability (``id_confidence``)
-------------------------------
The posterior of the chosen identity among all hypotheses for that piece:
every free identity, plus "the bee is one that is already placed elsewhere at
that time" (weighted by ``1 − that placement's probability``, since a placement
that is itself doubtful doesn't rule its identity out), plus "false detection".
Identities that haven't been used yet and can't be told apart (unmarked ones)
count as a single hypothesis, since their labels are interchangeable.

``id_source`` says where the name came from: ``mark`` (an anchor) or
``motion`` (continuity with pieces already placed).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import IdentityConfig, UnmarkedConfig
from .anonymous import stitch_tracklets


@dataclass
class Piece:
    cid: int
    start: int
    end: int
    p0: tuple[float, float]
    p1: tuple[float, float]
    n_obs: int
    reads: dict[str, float] = field(default_factory=dict)  # marked bee_id -> evidence
    n_read: float = 0.0
    prob: float = 1.0


@dataclass
class ClosedGroupParams:
    read_rate: float | None = None   # None = estimate from the data
    wrong_colour: float = 0.08       # share of a marked bee's readings that show another colour
    spurious_rate: float = 0.03      # readings per detection on an unmarked bee
    silence_s: float = 1.0           # frames without a reading count as one observation per this many seconds
    sigma0_mm: float = 3.0
    walk_mm_s: float = 10.0
    vmax_mm_s: float = 40.0
    slack_mm: float = 6.0
    first_seen_ll: float = -3.0      # an identity's first piece (instead of continuing a known one)
    false_detection_ll: float = -0.35  # per detection: log-odds that a piece is not a bee at all
    anchor_posterior: float = 0.9


class _Timeline:
    """One identity's pieces, sorted by start, with O(log n) neighbour lookup."""

    def __init__(self) -> None:
        self.starts: list[int] = []
        self.pieces: list[Piece] = []

    def neighbours(self, c: Piece) -> tuple[Piece | None, Piece | None]:
        i = bisect.bisect_left(self.starts, c.start)
        return (self.pieces[i - 1] if i > 0 else None), (self.pieces[i] if i < len(self.pieces) else None)

    def free(self, c: Piece) -> bool:
        before, after = self.neighbours(c)
        return (before is None or before.end < c.start) and (after is None or after.start > c.end)

    def blocker(self, c: Piece) -> Piece | None:
        before, after = self.neighbours(c)
        if before is not None and before.end >= c.start:
            return before
        if after is not None and after.start <= c.end:
            return after
        return None

    def add(self, c: Piece) -> None:
        i = bisect.bisect_left(self.starts, c.start)
        self.starts.insert(i, c.start)
        self.pieces.insert(i, c)

    def __len__(self) -> int:
        return len(self.pieces)


def _join_ll(a, b, dt_s: float, px_per_mm: float, P: ClosedGroupParams) -> float:
    d_mm = float(np.hypot(b[0] - a[0], b[1] - a[1])) / px_per_mm
    if d_mm > P.vmax_mm_s * dt_s + P.slack_mm:
        return -np.inf  # physically impossible
    sigma = P.sigma0_mm + P.walk_mm_s * dt_s
    return float(-0.5 * (d_mm / sigma) ** 2 - np.log(sigma))


def _pieces_unmarked(det: pd.DataFrame, fps: float, px_per_mm: float, ucfg: UnmarkedConfig) -> np.ndarray:
    """Piece id per detection: tracklets joined where unambiguous (nothing dropped)."""
    cfg = ucfg.model_copy(update={"min_track_s": 0.0})
    named = stitch_tracklets(det[["frame", "tracklet", "x_px", "y_px"]], fps, px_per_mm, cfg)
    return named["bee_id"].map(lambda s: int(s[1:]) if isinstance(s, str) else -1).to_numpy()


def assign_closed_group(
    det: pd.DataFrame,
    scores: list[dict[str, float]] | None,
    marked: list[str],
    n_total: int,
    fps: float,
    px_per_mm: float,
    ucfg: UnmarkedConfig,
    icfg: IdentityConfig,
    params: ClosedGroupParams | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Assign every detection to one of ``n_total`` identities.

    ``scores`` is the per-detection mark evidence (same order as ``det`` rows),
    or ``None`` for unmarked bees. Returns ``det`` with ``bee_id``,
    ``id_confidence`` and ``id_source`` added, and a report for ``summary.json``.
    """
    P = params or ClosedGroupParams()
    det = det.copy()
    marked = list(marked)
    ids = marked + [f"U{i + 1:02d}" for i in range(max(0, n_total - len(marked)))]
    report = {"n_total": n_total, "marked": marked, "unmarked": ids[len(marked):], "never_read": [], "read_rate": None,
              "n_pieces": 0, "n_anchors": 0, "dropped_detections": 0, "dropped_fraction": 0.0, "mean_probability": None}
    if det.empty or not ids:
        det["bee_id"], det["id_confidence"], det["id_source"] = None, np.nan, None
        return det, report

    piece_of = det["tracklet"].to_numpy() if scores is not None else _pieces_unmarked(det, fps, px_per_mm, ucfg)
    marked_set = set(marked)

    # ---- summarise pieces -------------------------------------------------- #
    order = np.argsort(det["frame"].to_numpy(), kind="stable")
    frames, xs, ys = det["frame"].to_numpy(), det["x_px"].to_numpy(), det["y_px"].to_numpy()
    pieces: dict[int, Piece] = {}
    for i in order:
        cid = int(piece_of[i])
        c = pieces.get(cid)
        if c is None:
            c = pieces[cid] = Piece(cid, int(frames[i]), int(frames[i]), (xs[i], ys[i]), (xs[i], ys[i]), 0)
        c.end, c.p1 = int(frames[i]), (xs[i], ys[i])
        c.n_obs += 1
        s = scores[i] if scores is not None else None
        if s:
            c.n_read += 1
            for b, v in s.items():
                if b in marked_set:
                    c.reads[b] = c.reads.get(b, 0.0) + v

    # how often a marked bee's mark is read: from pieces that clearly read one colour
    r = P.read_rate
    if r is None:
        rates = [c.n_read / c.n_obs for c in pieces.values() if c.n_obs >= 10 and c.reads and max(c.reads.values()) >= 3]
        r = float(np.clip(np.median(rates), 0.05, 0.9)) if rates else 0.3
    k, eps = max(1, len(marked)), P.wrong_colour
    readable = set(marked)  # shrinks after the anchor stage

    # A mark stays hidden for whole stretches (bee turned over, under a neighbour), so consecutive
    # frames without a reading are not independent evidence: count one per ``silence_s`` seconds.
    silence_frames = max(1.0, P.silence_s * fps)

    def colour_ll(c: Piece, ident: str) -> float:
        no_read = (c.n_obs - c.n_read) / silence_frames
        if ident in readable:
            own = c.reads.get(ident, 0.0)
            other = max(0.0, c.n_read - own)
            return own * np.log(r * (1 - eps)) + other * np.log(r * eps / k + 1e-9) + no_read * np.log(1 - r)
        return c.n_read * np.log(P.spurious_rate) + no_read * np.log(1 - P.spurious_rate)

    def normalise(ll: dict[str, float]) -> dict[str, float]:
        fin = {i: v for i, v in ll.items() if np.isfinite(v)}
        if not fin:
            return {}
        m = max(fin.values())
        e = {i: float(np.exp(v - m)) for i, v in fin.items()}
        z = sum(e.values())
        return {i: v / z for i, v in e.items()}

    timeline = {i: _Timeline() for i in ids}

    def motion_ll(ident: str, c: Piece) -> float:
        before, after = timeline[ident].neighbours(c)
        if before is None and after is None:
            return P.first_seen_ll
        ll = 0.0
        if before is not None:
            ll += _join_ll(before.p1, c.p0, (c.start - before.end) / fps, px_per_mm, P)
        if after is not None:
            ll += _join_ll(c.p1, after.p0, (after.start - c.end) / fps, px_per_mm, P)
        return ll

    assigned: dict[int, tuple[str, float, str]] = {}

    def place(c: Piece, ident: str, prob: float, source: str) -> None:
        c.prob = prob
        timeline[ident].add(c)
        assigned[c.cid] = (ident, prob, source)

    # ---- 1. anchors: strong mark evidence ---------------------------------- #
    for c in sorted(pieces.values(), key=lambda c: -(max(c.reads.values()) if c.reads else 0)):
        if not c.reads or max(c.reads.values()) < icfg.min_votes:
            continue
        post = normalise({i: colour_ll(c, i) for i in ids})
        best = max(post, key=post.get)
        purity = c.reads.get(best, 0.0) / max(1e-9, sum(c.reads.values()))
        if best in marked_set and post[best] >= P.anchor_posterior and purity >= icfg.min_purity and timeline[best].free(c):
            place(c, best, float(post[best]), "mark")
    n_anchors = len(assigned)

    # ---- 2. registered bees whose mark was never read clearly --------------- #
    never_read = [b for b in marked if len(timeline[b]) == 0]
    readable -= set(never_read)

    # ---- 3. everything else, longest first ---------------------------------- #
    dropped: list[int] = []
    for c in sorted(pieces.values(), key=lambda c: -(c.end - c.start)):
        if c.cid in assigned:
            continue
        ll: dict[str, float] = {}
        new_ll = None  # one hypothesis for all unused identities that can't be told apart
        elsewhere = 0.0  # weight of "it is really a bee that is placed elsewhere at this time"
        cl_plain = None  # colour likelihood shared by all identities that have no readable mark
        for i in ids:
            tl = timeline[i]
            is_read = i in readable
            if is_read:
                cl = colour_ll(c, i)
            else:
                if cl_plain is None:
                    cl_plain = colour_ll(c, i)
                cl = cl_plain
            if not tl.free(c):
                blocker = tl.blocker(c)
                doubt = 1.0 - (blocker.prob if blocker is not None else 1.0)
                if doubt > 0:
                    elsewhere += doubt * float(np.exp(np.clip(cl + P.first_seen_ll, -700, 50)))
                continue
            if len(tl) == 0 and not is_read:
                if new_ll is None:
                    new_ll = (i, cl + P.first_seen_ll)
                continue
            ll[i] = cl + motion_ll(i, c)
        if new_ll is not None:
            ll[new_ll[0]] = new_ll[1]
        fin = {i: v for i, v in ll.items() if np.isfinite(v)}
        if not fin:
            dropped.append(c.cid)  # no identity can be this piece: more blobs than bees
            continue
        best = max(fin, key=fin.get)
        m = fin[best]
        z = sum(np.exp(v - m) for v in fin.values())
        z += elsewhere / np.exp(np.clip(m, -700, 50)) if elsewhere else 0.0
        z += float(np.exp(np.clip(c.n_obs * P.false_detection_ll + P.first_seen_ll - m, -700, 50)))  # "not a bee"
        place(c, best, float(1.0 / z), "motion")

    lookup = {cid: a for cid, a in assigned.items()}
    det["bee_id"] = [lookup.get(int(c), (None, np.nan, None))[0] for c in piece_of]
    det["id_confidence"] = [lookup.get(int(c), (None, np.nan, None))[1] for c in piece_of]
    det["id_source"] = [lookup.get(int(c), (None, np.nan, None))[2] for c in piece_of]
    n_drop = int(np.isin(piece_of, dropped).sum())
    named = det["bee_id"].notna()
    report.update(
        never_read=never_read, read_rate=round(r, 3), n_pieces=len(pieces), n_anchors=n_anchors,
        dropped_detections=n_drop, dropped_fraction=round(n_drop / max(1, len(det)), 4),
        mean_probability=round(float(det.loc[named, "id_confidence"].mean()), 3) if named.any() else None,
        mark_share=round(float((det["id_source"] == "mark").sum() / max(1, named.sum())), 3),
    )
    return det, report
