"""Head direction: the silhouette cue, heading sources, and the 'inspection' (facing) visit zone."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from beetrack.behavior import VisitDetector
from beetrack.calibration import Geometry
from beetrack.config import AnalysisConfig, ExperimentSetup, VisitConfig, Zone
from beetrack.trajectories import RELIABLE_HEADING, _resolve_heading, learn_shape_sign


def _flips(heading, truth):
    return np.abs(np.angle(np.exp(1j * (heading - truth)))) > np.pi / 2


# --------------------------------------------------------------------------- #
# resolver
# --------------------------------------------------------------------------- #
def test_still_bee_without_any_cue_is_a_guess_and_the_silhouette_fixes_it():
    """A track that starts with the bee standing still: continuity has nothing to go on (a coin toss),
    so the run is labelled 'guess'; a consistent silhouette flips it the right way round."""
    n, truth = 40, np.pi / 2
    axis = np.full(n, -np.pi / 2)            # the axis, pointing the wrong way (180° ambiguity)
    still = np.zeros(n, bool)
    nan = np.full(n, np.nan)
    h, src = _resolve_heading(axis, nan, nan, still)
    assert (src == "").all()                 # nothing at all to anchor on: unknown, not invented
    walking = still.copy(); walking[-3:] = True   # the bee walks off at the end, the right way
    vx, vy = np.zeros(n), np.ones(n)
    h, src = _resolve_heading(axis, vx, vy, walking)
    assert (src[-3:] == "motion").all() and (src[:-3] == "continuity").all()  # backward fill from the walk
    assert not _flips(h, truth).any()
    # the same frames, but the walk is unknown and only the silhouette says where the head is
    shape = np.full(n, truth)
    h, src = _resolve_heading(axis, nan, nan, still, shape=shape)
    assert (src == "shape").all() and not _flips(h, truth).any()
    # …and a silhouette that says nothing consistent leaves it a guess
    h, src = _resolve_heading(axis, nan, nan, still, shape=np.where(np.arange(n) % 2, truth, -truth))
    assert (src == "guess").all()


def test_silhouette_flips_a_detached_run_but_not_an_anchored_one_on_weak_evidence():
    n = 30
    axis = np.zeros(n)
    vx, vy = np.ones(n), np.zeros(n)
    moving = np.zeros(n, bool); moving[:3] = True       # walks right (+x), then stands still
    # after a gap the axis comes back: the continuity choice after a gap is a guess
    axis[12:14] = np.nan
    shape = np.full(n, np.pi)                            # the silhouette says: head points left
    h, src = _resolve_heading(axis, vx, vy, moving, shape=shape)
    assert (src[:3] == "motion").all()
    # anchored run (frames 3-11) needs 80 % disagreement: all votes disagree → flipped too
    assert (src[3:12] == "shape").all() and _flips(h[3:12], 0).all()
    # weaker evidence (≈ 70 % disagree) flips a detached run but not an anchored one
    shape = np.where(np.arange(n) % 4 != 3, np.pi, 0.0)
    h, src = _resolve_heading(axis, vx, vy, moving, shape=shape)
    assert not _flips(h[3:12], 0).any() and (src[3:12] == "continuity").all()
    assert _flips(h[14:], 0).all() and (src[14:] == "shape").all()


# --------------------------------------------------------------------------- #
# learning the silhouette rule
# --------------------------------------------------------------------------- #
def _walkers(skew_fn, n=200, bees=3, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for b in range(bees):
        ang = rng.uniform(-np.pi, np.pi)
        for f in range(n):
            if f % 40 == 0:
                ang = rng.uniform(-np.pi, np.pi)
            rows.append({"bee_id": f"W{b}", "frame": f, "x_px": 100 + 3 * f * np.cos(ang), "y_px": 100 + 3 * f * np.sin(ang),
                         "axis_angle": float(np.angle(np.exp(1j * ang * 2)) / 2), "area_px": 400.0,
                         "axis_skew": skew_fn(rng, ang)})
    return pd.DataFrame(rows)


def test_shape_rule_is_learned_from_walking_bees_and_refused_when_unclear():
    # skew is positive along the +axis direction when the head is there
    def head_skew(rng, ang):
        axis = np.angle(np.exp(1j * ang * 2)) / 2
        return 0.3 if np.cos(ang - axis) > 0 else -0.3
    info = learn_shape_sign(_walkers(head_skew), px_per_mm=5, fps=15, step_frames=1, moving_speed_mm_s=2)
    assert info["sign"] == 1 and info["agreement"] > 0.9
    info = learn_shape_sign(_walkers(lambda rng, a: -head_skew(rng, a)), px_per_mm=5, fps=15, step_frames=1, moving_speed_mm_s=2)
    assert info["sign"] == -1
    # real bees where the silhouette says nothing (seen on a real recording): the cue must switch itself off
    info = learn_shape_sign(_walkers(lambda rng, a: rng.choice([-0.3, 0.3])), px_per_mm=5, fps=15, step_frames=1, moving_speed_mm_s=2)
    assert info["sign"] == 0


# --------------------------------------------------------------------------- #
# facing / inspection
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def geom():
    setup = ExperimentSetup.model_validate({
        "dish": {"center_px": [500, 500], "radius_px": 400, "diameter_mm": 100},
        "queen_cell": {"polygon_px": [[480, 480], [520, 480], [520, 520], [480, 520]]},
    })
    return Geometry.from_setup(setup, 1000, 1000)


def _bee_at_cell(geom, facing: bool, source: str = "mark", seconds: float = 5, fps: float = 10):
    """A bee standing just right of the cell, head toward it (facing) or away from it (backed up)."""
    n = int(seconds * fps)
    edge_x, _ = geom.to_mm(520, 500)
    if facing:   # head 0.5 mm from the cell edge, body further right
        hx, x = edge_x + 0.5, edge_x + 0.5 + 5.0
    else:        # abdomen tip touching, head pointing away
        x, hx = edge_x + 2.0, edge_x + 7.0
    return pd.DataFrame({"bee_id": "W01", "frame": np.arange(n), "time_s": np.arange(n) / fps,
                         "x_mm": x, "y_mm": 0.0, "head_x_mm": hx, "head_y_mm": 0.0,
                         "heading_source": source, "id_confidence": 1.0})


def test_inspection_needs_the_head_at_the_cell_and_pointing_at_it(geom):
    cfg = VisitConfig(zones=[Zone(name="contact", margin_mm=3), Zone(name="inspection", margin_mm=1.5, facing=True)])
    vd = VisitDetector(cfg, geom)
    v = vd.detect(_bee_at_cell(geom, facing=True), fps=10)
    assert set(v.zone) == {"contact", "inspection"} and v.facing_fraction.min() == 1.0
    # backed up to the cell (abdomen toward it, head pointing away): never an inspection
    v = vd.detect(_bee_at_cell(geom, facing=False), fps=10)
    assert "inspection" not in set(v.zone)
    # facing, but the heading comes from a merged blob or a coin toss: no inspection is claimed
    for src in ("cluster", "guess"):
        assert src not in RELIABLE_HEADING
        v = vd.detect(_bee_at_cell(geom, facing=True, source=src), fps=10)
        assert set(v.zone) == {"contact"} and v.facing_fraction.isna().all()


def test_signed_distance_map_matches_the_exact_distance(geom):
    xs = np.array([400.0, 500.0, 530.0, 600.0, np.nan])
    ys = np.array([500.0, 500.0, 500.0, 650.0, 1.0])
    exact = geom.distance_to_cell_mm(xs, ys)
    fast = geom.signed_cell_distance_mm(xs, ys)
    assert np.isnan(fast[-1])
    assert fast[1] < 0                                  # inside the cell
    np.testing.assert_allclose(np.maximum(fast[:-1], 0), exact[:-1], atol=1.5 / geom.px_per_mm)


# --------------------------------------------------------------------------- #
# end to end on the synthetic recording
# --------------------------------------------------------------------------- #
def test_pipeline_reports_heading_sources_and_finds_inspections(result, synthetic):
    t = result.trajectories
    assert "heading_source" in t.columns
    obs = t[t.observed]
    assert set(obs.heading_source.unique()) <= {"mark", "motion", "continuity", "shape", "guess", "cluster", ""}
    info = result.summary["heading"]
    assert info["shape"]["sign"] == 1 and sum(info["sources"].values()) == pytest.approx(1, abs=1e-3)
    # where we say the heading is trustworthy, it is (ground truth: heading per frame)
    gt = pd.read_parquet(synthetic["ground_truth"])
    m = obs[obs.heading_source.isin(RELIABLE_HEADING)].merge(gt, on=["bee_id", "frame"], suffixes=("", "_gt"))
    flips = _flips(np.radians(m.heading_deg), np.radians(m.heading_deg_gt))
    assert len(m) > 1000 and flips.mean() < 0.02
    assert "inspection" in set(result.visits.zone) and "inspection_visits" in result.metrics.columns


def test_unmarked_bees_at_the_cell_mostly_face_the_right_way(synthetic, tmp_path):
    """Regression for the silhouette cue: unmarked bees standing at the cell used to be a coin toss (≈60 % wrong)."""
    from beetrack.pipeline import AnalysisPipeline

    setup = ExperimentSetup.load(synthetic["setup"]).model_copy(update={"marking": "none"})
    res = AnalysisPipeline(AnalysisConfig(), setup).run([synthetic["video"]], tmp_path)
    t = res.trajectories[res.trajectories.observed & res.trajectories.heading_deg.notna()]
    gt = pd.read_parquet(synthetic["ground_truth"])
    m = t.merge(gt, on="frame", suffixes=("", "_gt"))
    m = m.assign(d=np.hypot(m.x_mm - m.x_mm_gt, m.y_mm - m.y_mm_gt)).sort_values("d").drop_duplicates(["bee_id", "frame"])
    m = m[(m.d < 3) & (m.state == "visit")]
    flips = _flips(np.radians(m.heading_deg), np.radians(m.heading_deg_gt))
    assert len(m) > 200 and flips.mean() < 0.4
    reliable = m.heading_source.isin(RELIABLE_HEADING).to_numpy()
    assert flips[reliable].mean() < 0.12
