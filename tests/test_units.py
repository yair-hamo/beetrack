"""Unit tests for the individual pipeline stages."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from beetrack.calibration import Geometry, circle_from_points, detect_dish
from beetrack.config import AnalysisConfig, BeeSpec, ExperimentSetup, IdentityConfig, TrackingConfig, VisitConfig, Zone
from beetrack.behavior import VisitDetector
from beetrack.identity import IdentityResolver
from beetrack.identity.palette import Palette
from beetrack.models import Detection
from beetrack.tracking import OnlineTracker
from beetrack.video import read_frame

# ---------------------------------------------------------------- config ---- #


def test_default_setup_is_valid_except_geometry():
    check = ExperimentSetup().check(AnalysisConfig())
    assert any("dish" in e for e in check["errors"])
    assert not any("both have" in e for e in check["errors"])
    assert any("queen-cell" in w for w in check["warnings"])


def test_two_bees_with_the_same_colour_are_rejected():
    setup = ExperimentSetup(bees=[BeeSpec(bee_id="A", color="red"), BeeSpec(bee_id="B", color="red")])
    assert any("both have a red dot" in e for e in setup.check(AnalysisConfig())["errors"])


def test_unknown_colour_is_rejected():
    setup = ExperimentSetup(bees=[BeeSpec(bee_id="A", color="magenta")])
    assert any("not in the palette" in e for e in setup.check(AnalysisConfig())["errors"])


def test_default_registry_uses_ten_distinct_colours():
    bees = ExperimentSetup().bees
    assert len(bees) == 10 and len({b.color for b in bees}) == 10


def test_legacy_two_spot_setup_still_loads():
    b = BeeSpec.model_validate({"bee_id": "W01", "thorax": "yellow", "abdomen": "blue"})
    assert b.color == "yellow"


def test_config_yaml_roundtrip(tmp_path):
    cfg = AnalysisConfig()
    p = tmp_path / "c.yaml"
    p.write_text(cfg.dump_yaml())
    assert AnalysisConfig.load(p) == cfg


# ----------------------------------------------------------- calibration ---- #


def test_circle_from_points():
    (cx, cy), r = circle_from_points((10, 0), (0, 10), (-10, 0))
    assert (cx, cy, r) == pytest.approx((0, 0, 10))


def test_mm_px_roundtrip_and_orientation():
    geom = Geometry(cx=100, cy=100, radius_px=50, px_per_mm=2, queen_cell=None, width=200, height=200)
    x, y = geom.to_mm(120, 80)  # right and *up* of centre in the image
    assert (float(x), float(y)) == pytest.approx((10, 10))
    assert tuple(map(float, geom.to_px(x, y))) == pytest.approx((120, 80))


def test_detect_dish_on_synthetic(synthetic):
    arena = synthetic["arena"]
    dish = detect_dish(read_frame(synthetic["video"], 0))
    assert dish is not None
    assert dish.center_px[0] == pytest.approx(arena.cx, abs=6)
    assert dish.radius_px == pytest.approx(arena.r_px, rel=0.03)


# --------------------------------------------------------------- palette ---- #


def test_palette_classifies_paint_and_ignores_cuticle():
    pal = Palette(AnalysisConfig().color)
    from beetrack.config import DEFAULT_PALETTE

    def bgr(hexs):
        return tuple(int(hexs[i:i + 2], 16) for i in (5, 3, 1))

    swatches = {c.name: bgr(c.display) for c in DEFAULT_PALETTE}
    swatches[None] = (40, 78, 118)  # amber abdomen band: same hue as orange paint, but dark → not paint
    for name, bgr in swatches.items():
        img = np.full((4, 4, 3), bgr, np.uint8)
        lab = pal.classify(img)[0, 0]
        assert (pal.names[lab] if lab >= 0 else None) == name


# --------------------------------------------------------------- tracker ---- #


def test_tracker_keeps_ids_for_two_walking_bees():
    tr = OnlineTracker(TrackingConfig(), px_per_mm=4, source_fps=15)
    ids = []
    for f in range(30):
        dets = [Detection(f, 100 + 2 * f, 100, 0, 40, 15, 400), Detection(f, 300 - 2 * f, 300, 0, 40, 15, 400)]
        tr.update(f, dets)
        ids.append((dets[0].tracklet, dets[1].tracklet))
    assert len(set(ids)) == 1 and ids[0][0] != ids[0][1]


def test_tracker_cuts_on_impossible_jump():
    tr = OnlineTracker(TrackingConfig(max_speed_mm_s=20), px_per_mm=4, source_fps=15)
    a = Detection(0, 100, 100, 0, 40, 15, 400)
    tr.update(0, [a])
    b = Detection(1, 600, 100, 0, 40, 15, 400)
    tr.update(1, [b])
    assert a.tracklet != b.tracklet


# -------------------------------------------------------------- resolver ---- #


def _det(rows):
    return pd.DataFrame(rows, columns=["frame", "tracklet", "x_px", "y_px"])


def test_resolver_assigns_by_votes_and_respects_overlap():
    # tracklets 0 and 1 overlap in time; both lean to bee A, but 0 has more evidence
    det = _det([(f, 0, 0, 0) for f in range(10)] + [(f, 1, 50, 0) for f in range(10)])
    scores = [{"A": 1.0}] * 10 + [{"A": 1.0}] * 4 + [{"B": 1.0}] * 6
    out = IdentityResolver(IdentityConfig(min_purity=0.55)).resolve(det, scores, ["A", "B"])
    assert set(out[out.tracklet == 0].bee_id) == {"A"}
    assert set(out[out.tracklet == 1].bee_id) == {"B"}


def test_resolver_splits_identity_switch():
    det = _det([(f, 0, f, 0) for f in range(40)])
    scores = [{"A": 1.0}] * 20 + [{"B": 1.0}] * 20
    out = IdentityResolver(IdentityConfig()).resolve(det, scores, ["A", "B"])
    assert list(out.bee_id[:15].unique()) == ["A"] and list(out.bee_id[25:].unique()) == ["B"]


def test_gap_linking_names_unscored_fragment():
    det = _det([(f, 0, 100, 100) for f in range(10)] + [(f, 1, 102, 100) for f in range(12, 20)])
    scores = [{"A": 1.0}] * 10 + [{}] * 8
    out = IdentityResolver(IdentityConfig()).resolve(det, scores, ["A"], max_gap_frames=5, max_dist_px=10)
    assert set(out.bee_id) == {"A"}


# ---------------------------------------------------------------- visits ---- #


def _traj_through_cell(inside_frames, n=300, fps=15.0):
    """Bee at the cell (x=0 mm) on ``inside_frames``, 30 mm away otherwise."""
    x = np.where(np.isin(np.arange(n), inside_frames), 0.0, 30.0)
    return pd.DataFrame({"bee_id": "A", "frame": np.arange(n), "time_s": np.arange(n) / fps, "x_mm": x, "y_mm": 0.0,
                         "head_x_mm": x, "head_y_mm": 0.0, "observed": True})


def _geom_square_cell():
    # cell = 4x4 mm square at the dish centre, 10 px/mm
    sq = np.array([[-20, -20], [20, -20], [20, 20], [-20, 20]], np.float32) + 500
    return Geometry(cx=500, cy=500, radius_px=750, px_per_mm=10, queen_cell=sq, width=1000, height=1000)


def test_visits_merge_short_gaps_and_drop_short_visits():
    fps = 15.0
    frames = list(range(30, 60)) + list(range(70, 100)) + list(range(200, 205))  # 2 s, 0.67 s gap, 2 s; then 0.33 s
    vd = VisitDetector(VisitConfig(zones=[Zone(name="contact", margin_mm=3)], min_visit_s=1.0, merge_gap_s=1.5), _geom_square_cell())
    v = vd.detect(_traj_through_cell(frames, fps=fps), fps)
    assert len(v) == 1
    assert v.iloc[0].start_frame == 30 and v.iloc[0].end_frame == 99
    assert v.iloc[0].duration_s == pytest.approx(70 / fps)


def test_unknown_frames_are_not_counted_as_inside():
    fps = 15.0
    t = _traj_through_cell(list(range(0, 300)), fps=fps)
    t.loc[100:250, ["head_x_mm", "head_y_mm"]] = np.nan  # 10 s unknown in the middle
    vd = VisitDetector(VisitConfig(zones=[Zone(name="contact", margin_mm=3)], merge_gap_s=1.5), _geom_square_cell())
    assert len(vd.detect(t, fps)) == 2


def test_read_frame_falls_back_near_the_end(synthetic):
    """Regression: VFR files report more frames than decode; seeking past the real end used to 500."""
    from beetrack.video import probe

    n = probe(synthetic["video"]).n_frames
    assert read_frame(synthetic["video"], n + 5).shape[2] == 3  # a few frames past the end → last readable frame
    with pytest.raises(IndexError):
        read_frame(synthetic["video"], n + 10_000)


def test_single_dot_scoring():
    from beetrack.identity import ColorCodeIdentifier

    geom = Geometry(cx=0, cy=0, radius_px=100, px_per_mm=4, queen_cell=None, width=10, height=10)
    ci = ColorCodeIdentifier(AnalysisConfig().color, ExperimentSetup().bees, geom)
    by = {b.color: b.bee_id for b in ExperimentSetup().bees}
    assert ci.score([]) == {}
    assert ci.score([("blue", 0, 0, 50.0)]) == {by["blue"]: 1.0}
    assert ci.score([("blue", 0, 0, 50.0), ("red", 0, 0, 10.0)]) == {by["blue"]: 1.0}  # dominant
    shared = ci.score([("blue", 0, 0, 30.0), ("red", 0, 0, 25.0)])                      # ambiguous
    assert set(shared) == {by["blue"], by["red"]} and abs(sum(shared.values()) - 1) < 1e-9


def test_web_page_version_matches_package():
    """app.js warns when page and server versions differ, so they must be bumped together."""
    import re as _re
    from pathlib import Path

    import beetrack

    js = (Path(beetrack.__file__).parent / "server" / "static" / "app.js").read_text()
    assert _re.search(r'const UI_VERSION = "([^"]+)"', js).group(1) == beetrack.__version__


# ------------------------------------------------------------ unmarked ---- #


def _tracklets(rows):
    return pd.DataFrame(rows, columns=["frame", "tracklet", "x_px", "y_px"])


def test_stitch_joins_unambiguous_fragments_and_drops_short_ones():
    from beetrack.config import UnmarkedConfig
    from beetrack.identity.anonymous import stitch_tracklets

    rows = [(f, 0, 100 + f, 100) for f in range(30)]          # 2 s
    rows += [(f, 1, 100 + f, 100) for f in range(32, 70)]     # continues 2 frames later, 3 px further on
    rows += [(f, 2, 900, 900) for f in range(10)]             # short, far away → dropped
    out = stitch_tracklets(_tracklets(rows), fps=15, px_per_mm=4, cfg=UnmarkedConfig(min_track_s=1.0))
    assert set(out[out.tracklet.isin([0, 1])].bee_id) == {"T001"}
    assert out[out.tracklet == 2].bee_id.isna().all()
    assert out.id_confidence.isna().all()


def test_stitch_refuses_to_guess_after_a_contact():
    """Two bees meet and separate: the two outgoing fragments are equally plausible, so nothing is joined."""
    from beetrack.config import UnmarkedConfig
    from beetrack.identity.anonymous import stitch_tracklets

    rows = [(f, 0, 100 + f, 100) for f in range(30)]          # bee arriving, ends at (129,100)
    rows += [(f, 1, 131, 98 - (f - 32)) for f in range(32, 70)]   # leaves upwards
    rows += [(f, 2, 131, 102 + (f - 32)) for f in range(32, 70)]  # leaves downwards
    out = stitch_tracklets(_tracklets(rows), fps=15, px_per_mm=4, cfg=UnmarkedConfig(min_track_s=1.0))
    assert out.groupby("tracklet").bee_id.first().nunique() == 3


def test_unmarked_setup_needs_no_colours():
    setup = ExperimentSetup(marking="none", bees=[], n_bees=10)
    check = setup.check(AnalysisConfig())
    assert not any("bee" in e and "colour" in e for e in check["errors"])
    assert not any("no bees registered" in e for e in check["errors"])
    assert not any("unmarked" in w for w in check["warnings"])  # bee count known → closed group, no warning
    assert setup.expected_bees == 10
    no_count = ExperimentSetup(marking="none", bees=[]).check(AnalysisConfig())["warnings"]
    assert any("unmarked" in w for w in no_count) and any("Bees in the dish" in w for w in no_count)


def test_queen_cell_ellipse_generates_outline():
    from beetrack.config import QueenCell

    q = QueenCell.model_validate({"shape": {"cx": 100, "cy": 50, "length_px": 40, "width_px": 16, "angle_deg": 90}})
    xs, ys = zip(*q.polygon_px)
    assert len(q.polygon_px) == 48
    assert (min(xs), max(xs), min(ys), max(ys)) == pytest.approx((92, 108, 30, 70), abs=0.2)
    # a stale outline sent with a shape is replaced by the shape's outline
    q2 = QueenCell.model_validate({"shape": q.shape.model_dump(), "polygon_px": [[0, 0], [1, 0], [0, 1]]})
    assert q2.polygon_px == q.polygon_px
    with pytest.raises(ValueError):
        QueenCell.model_validate({"polygon_px": [[0, 0], [1, 1]]})


# ------------------------------------------------------------ desktop app ---- #


def test_desktop_data_dir_defaults_to_documents_and_can_be_overridden(monkeypatch, tmp_path):
    from beetrack import desktop

    monkeypatch.setenv("BEETRACK_DATA", str(tmp_path / "x"))
    assert desktop.data_dir() == tmp_path / "x"
    monkeypatch.delenv("BEETRACK_DATA")
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)
    assert desktop.data_dir() == tmp_path / "beetrack"           # no Documents folder → home
    (tmp_path / "Documents").mkdir()
    assert desktop.data_dir() == tmp_path / "Documents" / "beetrack"


def test_desktop_port_selection_skips_busy_ports():
    import socket

    from beetrack import desktop

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        busy = s.getsockname()[1]
        s.listen()
        assert not desktop.port_free(busy)
        assert desktop.choose_port(busy) != busy
    assert desktop.running_beetrack(busy, timeout=0.2) is False   # nothing answers there now


def test_desktop_explicit_busy_port_is_an_error(monkeypatch):
    import socket

    from beetrack import desktop

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        monkeypatch.setenv("BEETRACK_PORT", str(s.getsockname()[1]))
        monkeypatch.setenv("BEETRACK_NO_BROWSER", "1")
        with pytest.raises(SystemExit, match="in use"):
            desktop.main()


def test_video_writer_tries_several_h264_encoders():
    from beetrack.videos import H264_ENCODERS

    names = [e[e.index("-c:v") + 1] for e in H264_ENCODERS]
    assert names[0] == "libx264" and "h264_mf" in names   # LGPL ffmpeg on Windows has h264_mf, not libx264
