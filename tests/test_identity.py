"""Identity assignment: the closed group (exactly N bees, with probabilities) and track stitching.

These tests build small detection tables by hand, so each rule is checked on
its own: marks name a piece, motion continues an identity, an identity is in
one place at a time, extra blobs are dropped, and probabilities mean something.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from beetrack.config import IdentityConfig, UnmarkedConfig
from beetrack.identity.anonymous import stitch_tracklets
from beetrack.identity.closed_group import ClosedGroupParams, assign_closed_group

FPS, PPM = 15.0, 4.0


def _piece(tracklet, frames, x, y, read=None, every=1):
    """Rows + scores for one tracklet at a fixed place; ``read`` = bee whose mark is read every ``every`` frames."""
    rows = [(f, tracklet, x, y) for f in frames]
    scores = [({read: 1.0} if read and i % every == 0 else {}) for i, _ in enumerate(frames)]
    return rows, scores


def _table(*pieces):
    rows, scores = [], []
    for r, s in pieces:
        rows += r
        scores += s
    return pd.DataFrame(rows, columns=["frame", "tracklet", "x_px", "y_px"]), scores


def _assign(det, scores, marked, n, **kw):
    return assign_closed_group(det, scores, marked, n, FPS, PPM, UnmarkedConfig(), IdentityConfig(), **kw)


def _name(out, tracklet):
    names = out[out.tracklet == tracklet].bee_id.unique()
    assert len(names) == 1
    return names[0]


# ------------------------------------------------------------------ marks ---- #


def test_a_piece_with_clear_mark_readings_is_named_by_its_mark():
    det, scores = _table(_piece(0, range(60), 100, 100, read="A", every=2), _piece(1, range(60), 300, 300, read="B", every=2))
    out, rep = _assign(det, scores, ["A", "B"], 2)
    assert _name(out, 0) == "A" and _name(out, 1) == "B"
    assert set(out.id_source) == {"mark"} and rep["n_anchors"] == 2 and rep["never_read"] == []
    assert (out.id_confidence > 0.95).all()


def test_unread_piece_continues_the_identity_that_was_there():
    """A is read, vanishes for 3 frames, and an unreadable piece starts at the same spot: it is A, by motion."""
    det, scores = _table(_piece(0, range(0, 40), 100, 100, read="A", every=2),
                         _piece(1, range(0, 100), 400, 400, read="B", every=2),
                         _piece(2, range(43, 100), 102, 100))
    out, _ = _assign(det, scores, ["A", "B"], 2)
    assert _name(out, 2) == "A"
    assert set(out[out.tracklet == 2].id_source) == {"motion"}


def test_an_identity_cannot_jump_across_the_dish():
    """The unread piece starts 100 mm from where A ended one frame earlier: it can't be A."""
    det, scores = _table(_piece(0, range(0, 40), 100, 100, read="A", every=2), _piece(1, range(41, 100), 500, 100))
    out, _ = _assign(det, scores, ["A"], 2)
    assert _name(out, 1) == "U01"


def test_an_identity_is_in_one_place_at_a_time():
    """Two pieces overlap in time and both read A: only one can be A."""
    det, scores = _table(_piece(0, range(60), 100, 100, read="A", every=2), _piece(1, range(60), 300, 300, read="A", every=3))
    out, _ = _assign(det, scores, ["A"], 2)
    assert _name(out, 0) == "A" and _name(out, 1) == "U01"
    assert not out.duplicated(["frame", "bee_id"]).any()


def test_registered_colour_that_is_never_read_is_reported_and_demoted():
    """B's colour isn't in the dish. B stays in the group but is reported, not silently treated as marked."""
    det, scores = _table(_piece(0, range(80), 100, 100, read="A", every=2), _piece(1, range(80), 300, 300))
    out, rep = _assign(det, scores, ["A", "B"], 2)
    assert rep["never_read"] == ["B"]
    assert _name(out, 0) == "A" and _name(out, 1) == "B"   # the only identity left
    assert set(out[out.tracklet == 1].id_source) == {"motion"}


# ------------------------------------------------------------ closed group ---- #


def test_never_more_identities_than_bees_and_extra_blobs_are_dropped():
    """Three simultaneous pieces but only two bees: the shortest one is a false detection."""
    det, scores = _table(_piece(0, range(100), 100, 100), _piece(1, range(100), 300, 300), _piece(2, range(40, 50), 200, 200))
    out, rep = assign_closed_group(det, None, [], 2, FPS, PPM, UnmarkedConfig(), IdentityConfig())
    assert sorted(out.bee_id.dropna().unique()) == ["U01", "U02"]
    assert out[out.tracklet == 2].bee_id.isna().all()
    assert rep["dropped_detections"] == 10 and rep["dropped_fraction"] == pytest.approx(10 / 210, abs=1e-3)
    assert out.groupby("frame").bee_id.nunique().max() <= 2


def test_unused_unmarked_labels_are_interchangeable_so_first_pieces_are_certain():
    """Calling the first bee 'U01' rather than 'U02' is not a guess: the probability must not be 1/N."""
    det, scores = _table(_piece(0, range(100), 100, 100), _piece(1, range(100), 300, 300))
    out, rep = assign_closed_group(det, None, [], 5, FPS, PPM, UnmarkedConfig(), IdentityConfig())
    assert out.bee_id.nunique() == 2
    assert (out.id_confidence > 0.9).all() and rep["mean_probability"] > 0.9


def test_ambiguous_continuation_gets_a_low_probability():
    """Two bees end side by side; one unread piece starts between them: it could be either."""
    det, scores = _table(_piece(0, range(0, 40), 100, 100, read="A", every=2), _piece(1, range(0, 40), 108, 100, read="B", every=2),
                         _piece(2, range(42, 90), 104, 100))
    out, _ = _assign(det, scores, ["A", "B"], 2)
    p = out[out.tracklet == 2].id_confidence.iloc[0]
    assert 0.3 < p < 0.7, p


def test_probabilities_are_valid_and_report_is_complete():
    det, scores = _table(_piece(0, range(50), 100, 100, read="A", every=2), _piece(1, range(50), 300, 300))
    out, rep = _assign(det, scores, ["A"], 3)
    named = out[out.bee_id.notna()]
    assert named.id_confidence.between(0, 1).all()
    assert {"n_total", "marked", "unmarked", "never_read", "read_rate", "n_pieces", "n_anchors", "dropped_detections",
            "dropped_fraction", "mean_probability", "mark_share"} <= set(rep)
    assert rep["unmarked"] == ["U01", "U02"]


def test_empty_table_gives_an_empty_result_with_the_same_report_keys():
    det = pd.DataFrame(columns=["frame", "tracklet", "x_px", "y_px"])
    out, rep = _assign(det, [], ["A"], 2)
    assert out.empty and {"bee_id", "id_confidence", "id_source"} <= set(out.columns)
    assert rep["marked"] == ["A"] and rep["unmarked"] == ["U01"] and rep["dropped_detections"] == 0


def test_fixed_read_rate_parameter_is_respected():
    det, scores = _table(_piece(0, range(50), 100, 100, read="A", every=2))
    _, rep = _assign(det, scores, ["A"], 1, params=ClosedGroupParams(read_rate=0.2))
    assert rep["read_rate"] == 0.2


def test_many_pieces_are_handled_quickly():
    """Timelines use bisection, so thousands of pieces must not take quadratic time."""
    import time

    rng = np.random.default_rng(0)
    pieces = []
    for k in range(3000):
        start = int(rng.integers(0, 200_000))
        pieces.append(_piece(k, range(start, start + 20), float(rng.uniform(0, 600)), float(rng.uniform(0, 600))))
    det, _ = _table(*pieces)
    t = time.time()
    out, rep = assign_closed_group(det, None, [], 10, FPS, PPM, UnmarkedConfig(), IdentityConfig())
    assert time.time() - t < 20
    assert out.bee_id.nunique() <= 10 and not out[out.bee_id.notna()].duplicated(["frame", "bee_id"]).any()


# --------------------------------------------------------------- stitching ---- #


def test_stitching_only_looks_a_short_time_ahead():
    """A track that restarts at the same place after a long pause is a new track (no guessing across long gaps)."""
    rows = [(f, 0, 100, 100) for f in range(40)] + [(f, 1, 100, 100) for f in range(40 + 15 * 5, 200)]
    det = pd.DataFrame(rows, columns=["frame", "tracklet", "x_px", "y_px"])
    out = stitch_tracklets(det, FPS, PPM, UnmarkedConfig(stitch_max_gap_s=2.0, min_track_s=1.0))
    assert out.groupby("tracklet").bee_id.first().nunique() == 2


def test_stitching_chains_several_fragments():
    rows = []
    for k in range(5):
        rows += [(f, k, 100 + f, 100) for f in range(k * 30, k * 30 + 27)]  # 3-frame gaps, bee walking right
    det = pd.DataFrame(rows, columns=["frame", "tracklet", "x_px", "y_px"])
    out = stitch_tracklets(det, FPS, PPM, UnmarkedConfig(min_track_s=1.0))
    assert set(out.bee_id) == {"T001"}
