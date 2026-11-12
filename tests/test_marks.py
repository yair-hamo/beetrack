"""Marks: learning the paint colours from a video, fluorescent paints, and which way a marked bee faces."""

from __future__ import annotations

import cv2
import numpy as np
import pandas as pd
import pytest

from beetrack.calibration import Geometry
from beetrack.config import AnalysisConfig, BeeSpec, ColorIdConfig, ExperimentSetup, MarkModel, PaintColor
from beetrack.evaluation import evaluate_tracks
from beetrack.identity.discover import CuticleModel, Spot, cluster_spots, color_name, discover, mark_likeness
from beetrack.pipeline import AnalysisPipeline
from beetrack.synthetic import NEON, SyntheticArena
from beetrack.trajectories import learn_mark_positions
from beetrack.video import Recording


def _lab(hexs: str) -> np.ndarray:
    r, g, b = (int(hexs[i:i + 2], 16) for i in (1, 3, 5))
    return cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)


# ------------------------------------------------------------ colour names ---- #


@pytest.mark.parametrize("hexs, name", [
    ("#ffffff", "white"), ("#111111", "black"), ("#2f6fe0", "blue"), ("#2fb24c", "green"), ("#e0352b", "red"),
    ("#f055b4", "pink"), ("#9b4de0", "purple"), ("#f07a1e", "orange"), ("#22c3e6", "cyan"),
])
def test_colour_names(hexs, name):
    assert color_name(_lab(hexs)) == name


# ----------------------------------------------------------- cuticle model ---- #


def _body_pixels(n=4000, seed=0):
    """Brown/amber bee pixels: hue around 70°, modest colourfulness."""
    rng = np.random.default_rng(seed)
    L = rng.uniform(30, 150, n)
    chroma = rng.uniform(8, 32, n)
    hue = np.radians(rng.normal(70, 10, n))
    return np.column_stack([L, 128 + chroma * np.cos(hue), 128 + chroma * np.sin(hue)]).astype(np.float32)


def test_cuticle_model_learns_the_bees_own_hue_and_colourfulness():
    m = CuticleModel.learn(_body_pixels())
    assert m.hue_deg == pytest.approx(70, abs=6)
    assert 15 < m.chroma_max < 35


def test_ordinary_colours_outside_the_bee_hue_are_marks():
    m = CuticleModel.learn(_body_pixels())
    for hexs in ("#2f6fe0", "#2fb24c", "#f055b4"):
        coloured, _ = m.outside(_lab(hexs)[None, None, :], hue_gap=40, min_chroma=10)
        assert coloured.all(), hexs


def test_body_pixels_are_not_marks():
    px = _body_pixels(seed=1)
    m = CuticleModel.learn(px)
    coloured, white = m.outside(px[None, :, :], hue_gap=40, min_chroma=10)
    assert coloured.mean() < 0.02 and white.mean() < 0.02


@pytest.mark.parametrize("hexs", [NEON["neon orange"], NEON["neon yellow"]])
def test_fluorescent_paint_in_the_bees_own_hue_is_found_by_its_vividness(hexs):
    """Neon orange and yellow share the amber hue of a bee: only their colourfulness sets them apart."""
    m = CuticleModel.learn(_body_pixels())
    px = _lab(hexs)[None, None, :]
    assert m.outside(px, hue_gap=40, min_chroma=10)[0].all()
    old_model = CuticleModel(m.hue_deg, m.l_white, None)  # before v0.3: hue only
    assert not old_model.outside(px, hue_gap=40, min_chroma=10)[0].any()


def test_white_paint_is_brighter_than_any_body_pixel():
    m = CuticleModel.learn(_body_pixels())
    _, white = m.outside(_lab("#f8f8f8")[None, None, :], hue_gap=40, min_chroma=10)
    assert white.all()


# -------------------------------------------------------------- clustering ---- #


def _spots(lab, n, jitter, seed, frame0=0):
    rng = np.random.default_rng(seed)
    return [Spot(np.asarray(lab, np.float32) + rng.normal(0, jitter, 3).astype(np.float32), 20.0, frame0 + i, (0, 0), (0, 0))
            for i in range(n)]


def test_clustering_separates_colours_and_merges_lightness_variants():
    blue, pink = _lab("#2f6fe0"), _lab("#f055b4")
    darker_blue = blue + np.array([-30, 0, 0], np.float32)   # the same paint in shadow
    spots = _spots(blue, 40, 2, 0) + _spots(darker_blue, 30, 2, 1) + _spots(pink, 40, 2, 2)
    groups = cluster_spots(spots)
    assert len(groups) == 2
    assert sorted(len(g["members"]) for g in groups) == [40, 70]
    assert all(6 <= g["tol"] <= 24 for g in groups)


def test_clustering_is_reproducible():
    spots = _spots(_lab("#2f6fe0"), 40, 3, 0) + _spots(_lab("#2fb24c"), 40, 3, 1) + _spots(_lab("#e0352b"), 40, 3, 2)
    a, b = cluster_spots(spots), cluster_spots(spots)
    assert [g["lab"] for g in a] == [g["lab"] for g in b]


def test_too_few_spots_give_no_groups():
    assert cluster_spots(_spots(_lab("#2f6fe0"), 3, 1, 0)) == []


def test_glare_is_flagged_as_unlikely_mark():
    assert mark_likeness([240, 128, 128], edge_fraction=0.1) == (False, "very bright and colourless: probably a reflection")
    assert mark_likeness(_lab("#2f6fe0"), edge_fraction=0.9)[0] is False
    assert mark_likeness(_lab("#2f6fe0"), edge_fraction=0.1) == (True, "")


# ---------------------------------------------- end to end: neon, abdomen ---- #


@pytest.fixture(scope="module")
def neon(tmp_path_factory):
    """Six bees with fluorescent marks on the ABDOMEN (behind the body centre)."""
    out = tmp_path_factory.mktemp("neon")
    paths = SyntheticArena(seed=4, colours=NEON, mark_at="abdomen").generate(out, duration_s=40)
    paths["truth"] = pd.read_parquet(paths["ground_truth"])
    return paths


@pytest.fixture(scope="module")
def neon_discovery(neon):
    setup = ExperimentSetup.load(neon["setup"]).model_copy(update={"marking": "none", "n_bees": 6})
    rec = Recording([neon["video"]])
    geom = Geometry.from_setup(setup, rec.width, rec.height)
    det, proc = AnalysisPipeline(AnalysisConfig(), setup).calibrated_detector(rec, geom)
    return discover(rec, det, n_frames=60, px_per_mm=proc.px_per_mm, dish=(geom.cx, geom.cy, geom.radius_px))


def test_discovery_finds_all_six_fluorescent_paints(neon_discovery):
    big = [c for c in neon_discovery["clusters"] if c["likely_mark"] and c["n_spots"] >= 30]
    names = {c["name"] for c in big}
    assert len(big) == 6, [(c["name"], c["n_spots"]) for c in neon_discovery["clusters"]]
    assert "orange" in names, names                      # same hue as the bees: found by vividness
    assert neon_discovery["cuticle"]["chroma_max"] < 40
    assert all(c["examples"] for c in big)


@pytest.fixture(scope="module")
def neon_result(neon, neon_discovery, tmp_path_factory):
    """The whole flow the UI does: discover → one bee per group → analyse."""
    big = [c for c in neon_discovery["clusters"] if c["likely_mark"] and c["n_spots"] >= 30]
    truth_lab = {n: _lab(h) for n, h in NEON.items()}
    setup = ExperimentSetup.load(neon["setup"])
    by_colour = {b.color: b.bee_id for b in setup.bees}
    palette, bees = [], []
    for c in big:  # give each group the bee whose real paint is closest (a person does this by looking at the crops)
        paint = min(truth_lab, key=lambda n: np.linalg.norm((truth_lab[n] - np.array(c["lab"]))[1:]))
        palette.append(PaintColor(name=c["name"], labs=[tuple(c["lab"])], tol=c["tol"], display=c["display"]))
        bees.append(BeeSpec(bee_id=by_colour[paint], color=c["name"]))
    cu = neon_discovery["cuticle"]
    setup = setup.model_copy(update={
        "palette": palette, "bees": bees, "n_bees": 6,
        "mark_model": MarkModel(cuticle_hue_deg=cu["hue_deg"], l_white=cu["l_white"], chroma_max=cu["chroma_max"])})
    return AnalysisPipeline(AnalysisConfig(), setup).run([neon["video"]], tmp_path_factory.mktemp("neon_results"))


def test_learned_fluorescent_marks_identify_the_bees(neon_result, neon):
    ev = evaluate_tracks(neon_result.trajectories, neon["truth"], tol_mm=4.0)
    assert ev["id_accuracy"] > 0.85, ev
    assert ev["wrong_id_rate"] < 0.08, ev
    assert neon_result.summary["closed_group"]["never_read"] == []
    assert min(neon_result.summary["mark_readings"].values()) > 50


def test_mark_position_is_learned_as_abdomen_and_heads_point_the_right_way(neon_result, neon):
    """The marks are BEHIND the body centre. Assuming 'thorax' (the old behaviour) would turn every bee around."""
    positions = neon_result.summary["mark_positions"]
    assert set(positions.values()) == {"abdomen"}, positions
    m = neon["truth"].merge(neon_result.trajectories.dropna(subset=["x_mm"]), on=["frame", "bee_id"], suffixes=("", "_p"))
    m = m[np.hypot(m.x_mm - m.x_mm_p, m.y_mm - m.y_mm_p) <= 4]
    err = np.abs(((m.heading_deg_p - m.heading_deg + 180) % 360) - 180)
    assert (err > 90).mean() < 0.15, (err > 90).mean()


def test_forcing_the_wrong_mark_position_flips_the_bees(neon_result, neon, tmp_path):
    """Sanity check of the test above: with dot_position='thorax' on abdomen-marked bees, headings are mostly reversed."""
    setup = ExperimentSetup.model_validate(neon_result.summary["setup"])
    cfg = AnalysisConfig(max_frames=300, color=ColorIdConfig(dot_position="thorax"))
    res = AnalysisPipeline(cfg, setup).run([neon["video"]], tmp_path)
    m = neon["truth"].merge(res.trajectories.dropna(subset=["x_mm"]), on=["frame", "bee_id"], suffixes=("", "_p"))
    m = m[(np.hypot(m.x_mm - m.x_mm_p, m.y_mm - m.y_mm_p) <= 4) & m.observed_p]
    err = np.abs(((m.heading_deg_p - m.heading_deg + 180) % 360) - 180)
    assert (err > 90).mean() > 0.5


# ------------------------------------------------- mark position, by hand ---- #


def _walking_bee(mark_ahead: bool, n=60, read_every=2):
    """A bee walking right (+x in the image) at 10 mm/s with its mark 5 px ahead of or behind the centre."""
    rows = []
    for f in range(n):
        x = 100 + f * 10 / 15 * 4.0   # 10 mm/s, 4 px/mm, 15 fps
        seen = f % read_every == 0
        rows.append({"frame": f, "bee_id": "A", "x_px": x, "y_px": 200.0, "major_px": 48.0,
                     "s1_color": "blue" if seen else "", "s1_x": x + (5 if mark_ahead else -5) if seen else np.nan,
                     "s1_y": 200.0 if seen else np.nan, "s2_color": "", "s2_x": np.nan, "s2_y": np.nan})
    return pd.DataFrame(rows)


def test_mark_ahead_of_the_centre_is_thorax_and_behind_is_abdomen():
    args = dict(px_per_mm=4.0, fps=15.0, step_frames=1, moving_speed_mm_s=2.0)
    assert learn_mark_positions(_walking_bee(True), {"A": "blue"}, **args) == {"A": 1}
    assert learn_mark_positions(_walking_bee(False), {"A": "blue"}, **args) == {"A": -1}


def test_a_bee_that_stands_still_borrows_the_answer_only_from_an_agreeing_group():
    args = dict(px_per_mm=4.0, fps=15.0, step_frames=1, moving_speed_mm_s=2.0)
    still = _walking_bee(True).assign(bee_id="S", x_px=300.0, s1_x=305.0)
    b = _walking_bee(False).assign(bee_id="B", y_px=260.0, s1_y=260.0)
    c = _walking_bee(False).assign(bee_id="C", y_px=320.0, s1_y=320.0)
    codes = {"S": "blue", "B": "blue", "C": "blue"}
    assert learn_mark_positions(pd.concat([still, b, c]), codes, **args) == {"S": -1, "B": -1, "C": -1}
    # only one bee could be judged: not enough to speak for the others
    assert learn_mark_positions(pd.concat([still, b]), codes, **args)["S"] == 0
    # the judged bees disagree: no borrowing
    a = _walking_bee(True).assign(bee_id="C", y_px=320.0, s1_y=320.0)
    assert learn_mark_positions(pd.concat([still, b, a]), codes, **args)["S"] == 0
