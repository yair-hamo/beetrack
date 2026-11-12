"""Regression tests: one per bug found in the v0.3 review, so none of them can come back unnoticed."""

from __future__ import annotations

import threading
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from beetrack.calibration import Geometry
from beetrack.config import AnalysisConfig, BeeSpec, ColorIdConfig, ExperimentSetup, TrajectoryConfig
from beetrack.detection import BackgroundDetector
from beetrack.pipeline import AnalysisPipeline
from beetrack.server.app import create_app
from beetrack.server.db import Database
from beetrack.server.store import DataStore
from beetrack.server.worker import JobWorker
from beetrack.trajectories import _fill_gaps, build_trajectories
from beetrack.video import Recording

# ------------------------------------------------------------- pipeline ---- #


def test_colours_that_are_not_in_the_dish_are_reported(synthetic, tmp_path):
    """A registered colour that no bee wears used to get a (meaningless) name silently."""
    from beetrack.config import PaintColor

    setup = ExperimentSetup.load(synthetic["setup"])
    setup.bees = [b for b in setup.bees if b.bee_id in ("W02", "W03")] + [BeeSpec(bee_id="NOPE", color="magenta")]
    cfg = AnalysisConfig(max_frames=200)
    cfg.color.palette.append(PaintColor(name="magenta", hue=150, display="#ff00ff"))  # a hue nobody in the video wears
    res = AnalysisPipeline(cfg, setup).run([synthetic["video"]], tmp_path)
    assert res.summary["closed_group"]["never_read"] == ["NOPE"]
    assert res.summary["mark_readings"]["NOPE"] == 0 and res.summary["mark_readings"]["W02"] > 20
    assert any("NOPE (magenta) was never read" in w for w in res.summary["warnings"])


def test_setup_check_warns_when_marks_were_not_learned_from_the_video():
    warnings = ExperimentSetup().check(AnalysisConfig())["warnings"]
    assert any("built-in list" in w for w in warnings)
    learned = ExperimentSetup(palette=[{"name": "m1", "labs": [(100, 150, 150)], "tol": 10}], bees=[BeeSpec(bee_id="A", color="m1")])
    assert not any("built-in list" in w for w in learned.check(AnalysisConfig())["warnings"])
    assert not any("built-in list" in w for w in ExperimentSetup(marking="none").check(AnalysisConfig())["warnings"])


def test_results_are_identical_from_run_to_run(synthetic, tmp_path):
    """Splitting touching bees used unseeded k-means, so two runs of the same video could differ."""
    setup = ExperimentSetup.load(synthetic["setup"])
    runs = [AnalysisPipeline(AnalysisConfig(max_frames=150), setup).run([synthetic["video"]], tmp_path / str(k)) for k in range(2)]
    pd.testing.assert_frame_equal(runs[0].trajectories, runs[1].trajectories)
    pd.testing.assert_frame_equal(runs[0].visits, runs[1].visits)


def test_changing_sensitivity_remeasures_the_bee_size(synthetic):
    """A lower threshold grows every blob; with the old size, single bees were counted as two."""
    setup = ExperimentSetup.load(synthetic["setup"])
    rec = Recording([synthetic["video"]])
    det = BackgroundDetector(AnalysisConfig().detection, Geometry.from_setup(setup, rec.width, rec.height))
    samples = rec.sample_frames(30)
    det.prepare(samples)
    normal = det.measured_bee_area_px
    det.set_threshold(10, samples)
    assert det.threshold == 10 and det.measured_bee_area_px > normal
    assert abs(det.counts(samples[:10]).mean() - 10) < 2          # still about ten bees, not twenty


def test_sensitivity_choice_reports_errors_and_prefers_the_default_on_ties(result):
    th = result.summary["detection_threshold"]
    errs = dict(map(tuple, th["errors"]))
    assert errs[th["chosen"]] <= min(errs.values()) + 0.1
    assert {"chosen", "expected_bees", "mean_count", "tried", "errors"} <= set(th)


def test_min_probability_trades_coverage_for_fewer_wrong_names(crowded, crowded_result, tmp_path):
    from beetrack.evaluation import evaluate_tracks

    truth = pd.read_parquet(crowded["ground_truth"])
    setup = ExperimentSetup.load(crowded["setup"])
    setup.id_min_probability = 0.5
    strict = AnalysisPipeline(AnalysisConfig(), setup).run([crowded["video"]], tmp_path)
    all_, sure = evaluate_tracks(crowded_result.trajectories, truth), evaluate_tracks(strict.trajectories, truth)
    assert sure["wrong_id_rate"] < 0.6 * all_["wrong_id_rate"], (all_, sure)
    assert sure["coverage"] < all_["coverage"]
    assert strict.summary["closed_group"]["below_min_probability"] > 0


def test_identity_probability_is_informative(crowded, crowded_result):
    """Positions the software is sure about must be right far more often than those it doubts."""
    truth = pd.read_parquet(crowded["ground_truth"])
    m = truth.merge(crowded_result.trajectories.dropna(subset=["x_mm"]), on=["frame", "bee_id"], suffixes=("", "_p"))
    ok = np.hypot(m.x_mm - m.x_mm_p, m.y_mm - m.y_mm_p) <= 4
    sure, unsure = ok[m.id_confidence >= 0.9], ok[m.id_confidence < 0.5]
    assert len(unsure) > 100, "the crowded video should contain doubtful pieces"
    assert sure.mean() > 0.92
    assert unsure.mean() < sure.mean() - 0.3


def test_names_from_marks_are_reliable_and_names_from_motion_are_flagged(crowded, crowded_result):
    from beetrack.calibration import Geometry as G

    truth = pd.read_parquet(crowded["ground_truth"])
    setup = ExperimentSetup.load(crowded["setup"])
    d = crowded_result.detections
    d = d[d.bee_id.notna()].drop_duplicates(["frame", "bee_id"])
    m = truth.merge(d, on=["frame", "bee_id"])
    px, py = G.from_setup(setup, 1280, 720).to_mm(m.x_px, m.y_px)
    ok = np.hypot(m.x_mm - px, m.y_mm - py) <= 4
    assert ok[m.id_source == "mark"].mean() > 0.94
    assert (m.id_source == "mark").mean() > 0.8          # most positions are named by a mark that was read


def test_visits_and_metrics_carry_identity_probability(result):
    assert result.visits.id_probability.between(0, 1).all()
    assert result.metrics.id_probability.between(0, 1).all()
    assert set(result.detections.id_source.dropna()) <= {"mark", "motion"}


def test_zone_columns_exist_even_without_any_visit(synthetic, tmp_path):
    """Per-bee metrics lost their zone columns when nobody visited, which broke the results table."""
    setup = ExperimentSetup.load(synthetic["setup"])
    cx, cy = setup.dish.center_px
    setup.queen_cell.polygon_px = [(cx - 400, cy - 300), (cx - 395, cy - 300), (cx - 395, cy - 295)]  # outside the dish
    setup.queen_cell.shape = None
    res = AnalysisPipeline(AnalysisConfig(max_frames=60), setup).run([synthetic["video"]], tmp_path)
    assert res.visits.empty
    assert {"contact_visits", "vicinity_visits", "contact_total_s"} <= set(res.metrics.columns)
    assert (res.metrics.contact_visits == 0).all()


def test_wrong_diameter_warning_mentions_the_visit_zones(synthetic, tmp_path):
    setup = ExperimentSetup.load(synthetic["setup"])
    setup.dish.diameter_mm = 250.0
    res = AnalysisPipeline(AnalysisConfig(max_frames=100), setup).run([synthetic["video"]], tmp_path)
    assert any("visit zones" in w for w in res.summary["warnings"])


def test_legacy_dot_on_thorax_config_still_loads():
    assert ColorIdConfig.model_validate({"dot_on_thorax": True}).dot_position == "thorax"
    assert ColorIdConfig.model_validate({"dot_on_thorax": False}).dot_position == "unknown"
    assert AnalysisConfig.model_validate({"color": {"dot_on_thorax": False}}).color.dot_position == "unknown"


# ---------------------------------------------------------- trajectories ---- #


def _det(frames, x, y=100.0):
    n = len(frames)
    return pd.DataFrame({"frame": frames, "bee_id": "A", "x_px": x, "y_px": np.full(n, y), "axis_angle": 0.0, "major_px": 40.0,
                         "minor_px": 15.0, "area_px": 450.0, "id_confidence": 1.0, "head_x_px": np.nan, "head_y_px": np.nan})


GEOM = Geometry(cx=500, cy=500, radius_px=400, px_per_mm=4.0, queen_cell=None, width=1000, height=1000)


def test_a_single_analysed_frame_does_not_crash():
    t = build_trajectories(_det([0], [100.0]), GEOM, TrajectoryConfig(), np.array([0]), 15.0)
    assert len(t) == 1 and np.isnan(t.speed_mm_s.iloc[0])


def test_zero_interpolation_gap_does_not_crash():
    frames = np.arange(30)
    t = build_trajectories(_det(frames, 100.0 + frames), GEOM, TrajectoryConfig(max_interp_gap_s=0), frames, 15.0)
    assert t.x_mm.notna().all()


def test_short_gap_is_filled_but_a_jump_is_not():
    frames = np.arange(40)
    walk = _det(np.r_[0:10, 15:40], np.r_[100.0 + np.arange(10), 115.0 + np.arange(25)])       # 5 frames missing, bee kept walking
    t = build_trajectories(walk, GEOM, TrajectoryConfig(), frames, 15.0)
    assert t.x_mm.notna().all() and t.interpolated.sum() == 5
    jump = _det(np.r_[0:10, 15:40], np.r_[np.full(10, 100.0), np.full(25, 700.0)])            # 150 mm in a third of a second
    t = build_trajectories(jump, GEOM, TrajectoryConfig(), frames, 15.0)
    assert t.x_mm.isna().sum() == 5 and t.interpolated.sum() == 0


def test_long_gap_is_filled_only_if_the_bee_reappears_in_place():
    frames = np.arange(200)
    still = _det(np.r_[0:20, 150:200], np.full(70, 300.0))                                     # hidden 8.7 s, same spot
    assert build_trajectories(still, GEOM, TrajectoryConfig(), frames, 15.0).x_mm.notna().all()
    moved = _det(np.r_[0:20, 150:200], np.r_[np.full(20, 300.0), np.full(50, 340.0)])          # reappears 10 mm away
    assert build_trajectories(moved, GEOM, TrajectoryConfig(), frames, 15.0).x_mm.isna().sum() == 130


def test_fill_gaps_never_fills_the_ends():
    t = pd.DataFrame({"x": [np.nan, 1.0, np.nan, 3.0, np.nan], "y": [np.nan, 0.0, np.nan, 0.0, np.nan]})
    _fill_gaps(t, 5, lambda d, n: True)
    assert t.x.tolist()[1:4] == [1.0, 2.0, 3.0] and np.isnan(t.x.iloc[0]) and np.isnan(t.x.iloc[4])


# ------------------------------------------------------------------ server ---- #


def test_worker_thread_can_be_stopped_and_joined(tmp_path):
    """The worker stored its stop flag as ``_stop``, shadowing a private method of threading.Thread."""
    store = DataStore(tmp_path)
    w = JobWorker(store, Database(store.db_path), poll_s=0.05)
    assert callable(threading.Thread._stop) and callable(w._stop)   # not replaced by an Event
    w.start()
    time.sleep(0.15)
    w.stop()
    w.join(5)
    assert not w.is_alive()


@pytest.fixture(scope="module")
def served(tmp_path_factory, synthetic):
    """An experiment that has been analysed once, served in-process."""
    app = create_app(tmp_path_factory.mktemp("data"))
    with TestClient(app) as c:
        eid = c.post("/api/experiments", json={"name": "regression"}).json()["id"]
        with open(synthetic["video"], "rb") as f:
            assert c.post(f"/api/experiments/{eid}/videos", files={"file": ("v.mp4", f, "video/mp4")}).status_code == 201
        setup = ExperimentSetup.load(synthetic["setup"]).model_dump(mode="json")
        setup["n_bees"] = 10
        assert c.put(f"/api/experiments/{eid}/setup", json=setup).status_code == 200
        assert c.put(f"/api/experiments/{eid}/config", json={"yaml": "max_frames: 150"}).status_code == 200
        job = c.post(f"/api/experiments/{eid}/analyze").json()
        _wait(c, job["id"])
        yield c, eid, job["id"]


def _wait(c, job_id, timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "cancelled"):
            assert j["status"] == "done", j
            return j
        time.sleep(0.5)
    raise AssertionError("job did not finish")


def test_results_report_the_setup_they_were_made_with(served):
    c, eid, _ = served
    r = c.get(f"/api/experiments/{eid}/results").json()
    assert r["setup_changed"] is False
    assert [b["bee_id"] for b in r["run_setup"]["bees"]] == [f"W{i:02d}" for i in range(1, 11)]
    assert "id_probability" in r["visits"][0] and "id_probability" in r["metrics"][0]


def test_editing_the_setup_afterwards_is_flagged_and_does_not_change_old_results(served):
    c, eid, _ = served
    setup = c.get(f"/api/experiments/{eid}").json()["setup"]
    setup["marking"], setup["n_bees"] = "none", 7
    assert c.put(f"/api/experiments/{eid}/setup", json=setup).status_code == 200
    r = c.get(f"/api/experiments/{eid}/results").json()
    assert r["setup_changed"] is True
    assert r["run_setup"]["marking"] == "color" and len(r["run_setup"]["bees"]) == 10   # still the run's own setup
    geo = c.get(f"/api/experiments/{eid}/geometry").json()
    assert geo["marking"] == "color"
    assert c.get(f"/api/experiments/{eid}/frame", params={"t": 3, "trail_s": 2}).status_code == 200
    assert c.get(f"/api/experiments/{eid}/download/annotations.csv").status_code == 200


def test_rendering_is_not_reported_as_analysing_and_keeps_the_analysis_as_latest_job(served):
    c, eid, analysis_id = served
    rj = c.post(f"/api/experiments/{eid}/render", json={"video": "paths", "step_s": 1, "trail_s": -1}).json()
    e = c.get(f"/api/experiments/{eid}").json()
    assert e["status"] in ("rendering", "done")
    assert e["latest_job"]["id"] == analysis_id and e["latest_job"]["kind"] == "analyze"
    _wait(c, rj["id"])
    e = c.get(f"/api/experiments/{eid}").json()
    assert e["status"] == "done" and e["latest_job"]["id"] == analysis_id
    assert c.get(f"/api/experiments/{eid}/download/paths.mp4").content[4:8] == b"ftyp"


def test_a_broken_setup_fails_the_job_with_a_message_instead_of_a_silent_exit(served):
    """Loading the setup happened outside the error handler: a bad setup killed the process with no explanation."""
    c, eid, _ = served
    state = c.app.state
    from beetrack.server.db import Experiment, Job

    with state.db.session() as s:
        e = s.get(Experiment, eid)
        good = dict(e.setup)
        e.setup = {**good, "dish": {"center_px": [1, 1], "radius_px": -5, "diameter_mm": 90}}   # invalid on purpose
        j = Job(experiment_id=eid)
        s.add(j)
        s.commit()
        jid = j.id
    end = time.time() + 60
    while time.time() < end:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(0.3)
    with state.db.session() as s:
        s.get(Experiment, eid).setup = good
        s.commit()
    assert j["status"] == "failed" and "radius_px" in j["error"], j


def test_discover_marks_endpoint_returns_groups_with_examples(served):
    c, eid, _ = served
    r = c.post(f"/api/experiments/{eid}/discover-marks", json={"frames": 40})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["clusters"]) >= 6 and body["cuticle"]["chroma_max"] > 0 and body["min_spot_mm2"] > 0
    assert all(k in body["clusters"][0] for k in ("name", "lab", "tol", "display", "likely_mark", "examples"))


def test_mark_discovery_never_reads_the_queen_cell_or_ignore_areas(synthetic):
    """Bug report (v0.3): 'Find the marks' learned the food and the queen cell's wax as marks, although the
    setup had them outlined. Spots must never come from those areas, even when a bee stands next to them."""
    from beetrack.config import EllipseShape, IgnoreArea
    from beetrack.identity.discover import CuticleModel, collect_spots, discover

    setup = ExperimentSetup.load(synthetic["setup"])
    rec = Recording([synthetic["video"]])
    geom = Geometry.from_setup(setup, rec.width, rec.height)
    det, proc = AnalysisPipeline(AnalysisConfig(), setup.model_copy(update={"marking": "none"})).calibrated_detector(rec, geom)
    # an ignore area over the left half of the dish
    cx, cy, r = geom.cx, geom.cy, geom.radius_px
    setup.ignore_areas = [IgnoreArea(name="food", shape=EllipseShape(cx=cx - r / 2, cy=cy, length_px=r, width_px=2 * r))]
    geom2 = Geometry.from_setup(setup, rec.width, rec.height)
    exclude = geom2.exclusion_mask(include_cell=True)
    assert exclude[int(cy), int(cx - r / 2)] and exclude[tuple(np.round(geom.queen_cell.mean(0)).astype(int)[::-1])]
    model = CuticleModel(66.0, 240.0, 25.0)
    n_spots = 0
    for i in range(0, 600, 20):
        f = rec.read(i)
        dets, patches = det.detect(f, i)
        for s in collect_spots(f, dets, patches, frame_index=i, min_spot_px=3, model=model, exclude=exclude):
            n_spots += 1
            assert not exclude[int(round(s.spot_xy[1])), int(round(s.spot_xy[0]))]
    assert n_spots > 20  # bees elsewhere still give marks
    res = discover(rec, det, n_frames=30, px_per_mm=proc.px_per_mm, exclude=exclude)
    assert res["excluded_px"] == int(exclude.sum()) and res["clusters"]


def test_discover_marks_endpoint_leaves_out_cell_and_ignore_areas(served):
    c, eid, _ = served
    body = c.post(f"/api/experiments/{eid}/discover-marks", json={"frames": 30}).json()
    assert body["excluded_px"] > 0  # the synthetic setup has a queen cell
