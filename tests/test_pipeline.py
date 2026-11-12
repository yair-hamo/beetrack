"""End-to-end tests on synthetic video with exact ground truth.

The thresholds are regression guards. If a change lowers accuracy below
them, the test fails, so pipeline quality can't silently degrade.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from beetrack.config import AnalysisConfig, ExperimentSetup
from beetrack.evaluation import compare_visits, evaluate_tracks
from beetrack.pipeline import OUTPUT_FILES, AnalysisPipeline, SetupError


def test_all_outputs_written(result):
    for name in OUTPUT_FILES.values():
        assert (result.out_dir / name).exists(), name
    summary = json.loads((result.out_dir / "summary.json").read_text())
    assert summary["config"]["analysis_fps"] == 15.0
    assert len(summary["bees_found"]) == 10


def test_identity_accuracy(result, synthetic):
    truth = pd.read_parquet(synthetic["ground_truth"])
    ev = evaluate_tracks(result.trajectories, truth, tol_mm=4.0)
    assert ev["id_accuracy"] > 0.80, ev
    assert ev["wrong_id_rate"] < 0.10, ev
    assert ev["median_error_mm"] < 1.5, ev


def test_visit_detection_close_to_truth(result, synthetic):
    truth = pd.read_csv(synthetic["visits"])
    cmp = compare_visits(result.visits, truth)
    for zone, g in cmp.groupby("zone"):
        true_s, pred_s = g.total_s_true.sum(), g.total_s_pred.sum()
        assert pred_s == pytest.approx(true_s, rel=0.35), (zone, true_s, pred_s)
        assert abs(g.n_pred.sum() - g.n_true.sum()) <= max(3, 0.35 * g.n_true.sum()), (zone, g)


def test_trajectory_table_schema(result):
    t = result.trajectories
    assert {"bee_id", "frame", "time_s", "x_mm", "y_mm", "head_x_mm", "heading_deg", "speed_mm_s", "observed"} <= set(t.columns)
    assert t.groupby("bee_id").frame.is_monotonic_increasing.all()
    r = np.hypot(t.x_mm, t.y_mm).max()
    assert r < 75, "positions must stay inside the 150 mm dish"


def test_metrics_cover_every_registered_bee(result):
    assert sorted(result.metrics.bee_id) == [f"W{i:02d}" for i in range(1, 11)]
    assert "contact_visits" in result.metrics.columns


def test_no_queen_cell_still_writes_readable_outputs(synthetic, tmp_path):
    """Regression: with no visits, binned_visits.csv used to be empty with no header (500 in the UI)."""
    setup = ExperimentSetup.load(synthetic["setup"])
    setup.queen_cell = None
    cfg = AnalysisConfig(max_frames=60)
    res = AnalysisPipeline(cfg, setup).run([synthetic["video"]], tmp_path)
    assert res.visits.empty and any("queen-cell" in w for w in res.summary["warnings"])
    for name in ("visits", "binned_visits", "bee_metrics"):
        df = pd.read_csv(tmp_path / OUTPUT_FILES[name])  # must not raise EmptyDataError
        assert len(df.columns) > 0, name


def test_missing_dish_is_a_setup_error(synthetic, tmp_path):
    setup = ExperimentSetup.load(synthetic["setup"])
    setup.dish = None
    with pytest.raises(SetupError):
        AnalysisPipeline(AnalysisConfig(), setup).run([synthetic["video"]], tmp_path)


def test_sleap_import(tmp_path, synthetic):
    h5py = pytest.importorskip("h5py")
    n_frames = 30
    tracks = np.full((2, 2, 3, n_frames), np.nan)  # (tracks, xy, nodes, frames)
    for f in range(n_frames):
        tracks[0, :, 0, f] = (650 + f, 300)   # head
        tracks[0, :, 1, f] = (640 + f, 300)   # thorax
        tracks[0, :, 2, f] = (620 + f, 300)   # abdomen
        tracks[1, :, :, f] = np.array([[600, 600, 600], [420, 430, 450]])
    p = tmp_path / "preds.analysis.h5"
    with h5py.File(p, "w") as f:
        f["tracks"] = tracks
        f["track_names"] = np.array([b"W01", b"W02"])
        f["node_names"] = np.array([b"head", b"thorax", b"abdomen"])
    setup = ExperimentSetup.load(synthetic["setup"])
    cfg = AnalysisConfig()
    res = AnalysisPipeline(cfg, setup).run([synthetic["video"]], tmp_path / "out", sleap_h5=p)
    assert res.summary["mode"] == "sleap"
    w1 = res.trajectories[(res.trajectories.bee_id == "W01") & res.trajectories.observed]
    assert len(w1) == n_frames
    assert w1.heading_deg.abs().max() < 5  # head points +x (right)


def test_unmarked_mode_tracks_paths_without_colours(synthetic, tmp_path):
    setup = ExperimentSetup.load(synthetic["setup"])
    setup.marking, setup.n_bees = "none", None  # bee count unknown → open-ended anonymous tracks
    res = AnalysisPipeline(AnalysisConfig(), setup).run([synthetic["video"]], tmp_path)
    assert res.summary["mode"] == "unmarked" and res.summary["n_tracks"] >= 10
    t = res.trajectories.dropna(subset=["x_mm"])
    assert t.bee_id.str.fullmatch(r"T\d{3}").all()
    # every real bee position is covered by some track
    truth = pd.read_parquet(synthetic["ground_truth"])
    m = truth.merge(t, on="frame", suffixes=("", "_p"))
    m["d"] = np.hypot(m.x_mm - m.x_mm_p, m.y_mm - m.y_mm_p)
    assert (m.groupby(["frame", "bee_id"]).d.min() <= 4).mean() > 0.95
    # population-level time at the cell is close to the truth
    tv = pd.read_csv(synthetic["visits"])
    true_s = tv[tv.zone == "vicinity"].duration_s.sum()
    pred_s = res.visits[res.visits.zone == "vicinity"].duration_s.sum()
    assert pred_s == pytest.approx(true_s, rel=0.3)
    assert sorted(res.metrics.bee_id) == sorted(t.bee_id.unique())


def test_wrong_dish_diameter_is_detected_and_does_not_break_detection(synthetic, tmp_path):
    """The bee size is measured from the video, so a wrong (or unknown) diameter can't split bees."""
    setup = ExperimentSetup.load(synthetic["setup"])
    setup.dish.diameter_mm = 250.0  # truth is 150 mm
    res = AnalysisPipeline(AnalysisConfig(max_frames=150), setup).run([synthetic["video"]], tmp_path)
    assert 8 <= res.summary["mean_bees_per_frame"] <= 12, res.summary["mean_bees_per_frame"]
    suggested = res.summary["bee_size"]["suggested_dish_diameter_mm"]
    assert suggested == pytest.approx(150, rel=0.2), suggested
    assert any("dish diameter" in w for w in res.summary["warnings"])


def test_correct_diameter_gives_no_size_warning(result):
    assert not any("bees measure" in w for w in result.summary["warnings"])
    assert result.summary["bee_size"]["measured_bee_area_px"] > 0


def test_annotations_export(result, synthetic):
    from beetrack.export import annotations_mot, annotations_table

    setup = ExperimentSetup.load(synthetic["setup"])
    ann = annotations_table(result.detections, result.trajectories, setup, 1280, 720)
    assert len(ann) > 1000 and ann.observed.all()
    assert (ann.bbox_width > 10).all() and (ann.bbox_width < 150).all()
    inside = (ann.x_px >= ann.bbox_left) & (ann.x_px <= ann.bbox_left + ann.bbox_width)
    assert inside.mean() > 0.99
    line = annotations_mot(ann).splitlines()[0].split(",")
    assert len(line) == 10 and line[-3:] == ["-1", "-1", "-1"]


@pytest.mark.parametrize("kind", ["annotated", "paths", "heatmap"])
def test_result_videos_respect_step_and_trail(kind, result, synthetic, tmp_path):
    import cv2

    from beetrack.videos import RenderOptions, render

    setup = ExperimentSetup.load(synthetic["setup"])
    opts = RenderOptions(step_s=1.0, trail_s=-1, fps=10)
    out = render(kind, videos=[synthetic["video"]], setup=setup, cfg=AnalysisConfig(), traj=result.trajectories,
                 width=1280, height=720, src_fps=15.0, out=tmp_path / f"{kind}.mp4", opts=opts)
    cap = cv2.VideoCapture(str(out))
    n, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    assert abs(n - 45) <= 1, n          # 45 s of recording at 1 s/step
    assert fps == pytest.approx(10, abs=0.1)


def _never_twice_at_once(traj):
    t = traj.dropna(subset=["x_mm"])
    return not t.duplicated(["frame", "bee_id"]).any()


def test_closed_group_unmarked_has_exactly_n_identities(synthetic, tmp_path):
    """Known number of bees: never more identities than bees, each with a probability."""
    setup = ExperimentSetup.load(synthetic["setup"])
    setup.marking, setup.n_bees = "none", 10
    res = AnalysisPipeline(AnalysisConfig(), setup).run([synthetic["video"]], tmp_path)
    t = res.trajectories.dropna(subset=["x_mm"])
    assert sorted(t.bee_id.unique()) == [f"U{i:02d}" for i in range(1, 11)]
    assert t.groupby("frame").bee_id.nunique().max() <= 10
    assert _never_twice_at_once(res.trajectories)
    assert t.id_confidence.between(0, 1).all()
    truth = pd.read_parquet(synthetic["ground_truth"])
    m = truth.merge(t, on="frame", suffixes=("", "_p"))
    m["d"] = np.hypot(m.x_mm - m.x_mm_p, m.y_mm - m.y_mm_p)
    assert (m.groupby(["frame", "bee_id"]).d.min() <= 4).mean() > 0.9  # every real bee is still covered
    assert res.summary["closed_group"]["n_total"] == 10


def test_closed_group_with_colours_is_bounded_and_accurate(result, synthetic):
    """The default synthetic run: 10 marked bees in the registry → exactly those 10 identities."""
    t = result.trajectories.dropna(subset=["x_mm"])
    assert sorted(t.bee_id.unique()) == [f"W{i:02d}" for i in range(1, 11)]
    assert _never_twice_at_once(result.trajectories)
    rep = result.summary["closed_group"]
    assert rep["unmarked"] == [] and rep["mean_probability"] > 0.8


def test_closed_group_mixes_marked_and_unmarked(synthetic, tmp_path):
    """Only 4 bees registered but 10 in the dish → W01–W04 + U01–U06."""
    setup = ExperimentSetup.load(synthetic["setup"])
    setup.bees, setup.n_bees = setup.bees[:4], 10
    res = AnalysisPipeline(AnalysisConfig(max_frames=300), setup).run([synthetic["video"]], tmp_path)
    ids = sorted(res.trajectories.dropna(subset=["x_mm"]).bee_id.unique())
    assert ids == sorted([f"W{i:02d}" for i in range(1, 5)] + [f"U{i:02d}" for i in range(1, 7)])
    assert _never_twice_at_once(res.trajectories)


def test_ignore_areas_suppress_detections(synthetic, tmp_path):
    from beetrack.config import EllipseShape, IgnoreArea

    setup = ExperimentSetup.load(synthetic["setup"])
    cx, cy = setup.dish.center_px
    r = setup.dish.radius_px
    setup.ignore_areas = [IgnoreArea(name="everything", shape=EllipseShape(cx=cx, cy=cy, length_px=2.2 * r, width_px=2.2 * r))]
    res = AnalysisPipeline(AnalysisConfig(max_frames=30), setup).run([synthetic["video"]], tmp_path)
    assert res.summary["n_detections"] == 0


def test_mark_discovery_finds_the_synthetic_paints(synthetic):
    from beetrack.calibration import Geometry
    from beetrack.identity.discover import discover
    from beetrack.video import Recording

    setup = ExperimentSetup.load(synthetic["setup"])
    rec = Recording([synthetic["video"]])
    geom = Geometry.from_setup(setup, rec.width, rec.height)
    det, proc = AnalysisPipeline(AnalysisConfig(), setup).calibrated_detector(rec, geom)
    res = discover(rec, det, n_frames=60, px_per_mm=proc.px_per_mm, dish=(geom.cx, geom.cy, geom.radius_px))
    marks = [c for c in res["clusters"] if c["likely_mark"]]
    assert len(marks) >= 6, [c["name"] for c in res["clusters"]]          # 10 paints; some may merge
    names = " ".join(c["name"] for c in marks)
    for colour in ("blue", "green", "pink"):
        assert colour in names or colour == "pink" and "red" in names, names
    assert all(c["examples"] and c["examples"][0].startswith("data:image/jpeg;base64,") for c in marks)
