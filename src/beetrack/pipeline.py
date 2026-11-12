"""End-to-end analysis of one recording.

    Recording ─► [detect ─► read colour code ─► link] per frame
              ─► resolve identities ─► trajectories ─► visits ─► metrics ─► files

Usage::

    from beetrack.pipeline import AnalysisPipeline
    result = AnalysisPipeline(cfg, setup).run(["video.mp4"], "results/")

The pipeline is a plain library object with no web or database code, so the
CLI, the web worker, notebooks and tests all run exactly the same analysis.
Every run writes ``summary.json`` with the full config, setup, software
version and timings, so a result can always be traced back to how it was made.
"""

from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import pandas as pd

from . import __version__
from .behavior import VisitDetector, bee_metrics, binned_visits
from .behavior.visits import VISIT_COLUMNS
from .calibration import Geometry
from .config import AnalysisConfig, ExperimentSetup
from .detection import BackgroundDetector
from .identity import ColorCodeIdentifier, IdentityResolver
from .identity.anonymous import stitch_tracklets
from .identity.closed_group import assign_closed_group
from .tracking import OnlineTracker
from .trajectories import TRAJ_COLUMNS, build_trajectories
from .video import Recording

ProgressFn = Callable[[str, float, str], None]
"""``progress(stage, fraction 0–1, message)``."""

OUTPUT_FILES = {
    "detections": "detections.parquet",
    "trajectories": "trajectories.parquet",
    "visits": "visits.csv",
    "bee_metrics": "bee_metrics.csv",
    "binned_visits": "binned_visits.csv",
    "summary": "summary.json",
    "preview": "preview.jpg",
}


class SetupError(ValueError):
    """The experiment setup is incomplete or inconsistent."""


@dataclass
class AnalysisResult:
    out_dir: Path
    detections: pd.DataFrame
    trajectories: pd.DataFrame
    visits: pd.DataFrame
    metrics: pd.DataFrame
    binned: pd.DataFrame
    summary: dict = field(default_factory=dict)


def _noop(stage: str, frac: float, msg: str) -> None:
    pass


def _sanity_warnings(dets_per_frame: float, n_bees: int | None, identified: float, mode: str) -> list[str]:
    """Plain-language warnings when the video doesn't look like the expected arena."""
    out = []
    if mode in ("color", "unmarked") and n_bees:
        if dets_per_frame > 2 * n_bees:
            out.append(
                f"about {dets_per_frame:.0f} blobs per frame for {n_bees} bees: this doesn't look like the expected "
                "arena (bees on a light, evenly lit dish, filmed from above). Check the video and the lighting, and "
                "draw ignore areas over food or other dark objects"
            )
        elif 0 < dets_per_frame < 0.5 * n_bees:
            out.append(f"only about {dets_per_frame:.1f} bees detected per frame for {n_bees} bees; "
                       "many bees are missed (low contrast, or bees hidden in a cluster)")
    if mode == "color" and dets_per_frame > 0 and identified < 0.3:
        out.append(
            f"only {identified:.0%} of detections could be named. Use Setup → 'Find the marks in the video' so the "
            "colours match the paint that is really on the bees"
        )
    return out


class AnalysisPipeline:
    """Runs the whole analysis for one experiment. Create one per run."""

    def __init__(self, cfg: AnalysisConfig, setup: ExperimentSetup, progress: ProgressFn | None = None):
        self.cfg = setup.effective_config(cfg)  # learned marks replace the configured palette
        self.setup = setup
        self.progress = progress or _noop
        # filled while running, reported in summary.json
        self.proc_px_per_mm: float | None = None   # scale used for pixel thresholds (see calibrated_detector)
        self.size_info: dict = {}
        self.threshold_info: dict | None = None
        self.static_px = 0
        self.group_report: dict | None = None

    # ------------------------------------------------------------------ #
    def run(self, videos: list[str | Path], out_dir: str | Path, sleap_h5: str | Path | None = None) -> AnalysisResult:
        t0 = time.time()
        timings: dict[str, float] = {}
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        check = self.setup.check(self.cfg)
        if check["errors"]:
            raise SetupError("; ".join(check["errors"]))
        warnings = list(check["warnings"])

        rec = Recording(list(videos))
        geom = Geometry.from_setup(self.setup, rec.width, rec.height)
        step = rec.step_for(self.cfg.analysis_fps)
        bee_ids = [b.bee_id for b in self.setup.bees]
        self.progress("prepare", 0.0, f"{len(rec.segments)} file(s), {rec.duration_s / 60:.1f} min, step={step}")

        # ---- 1. detection + mark reading + linking ------------------------ #
        ts = time.time()
        scores: list[dict[str, float]] | None = None
        if sleap_h5 is not None:
            det, frames = self._from_sleap(sleap_h5, rec, step)
            mode = "sleap"
        else:
            unmarked = self.setup.marking == "none"
            det, scores, frames = self._detect_and_link(rec, geom, step, use_color=not unmarked)
            mode = "unmarked" if unmarked else "color"
        timings["detect_s"] = time.time() - ts
        if det.empty:
            warnings.append("no bees were detected; check the lighting, the dish outline and the ignore areas")
        ppm = self.proc_px_per_mm or geom.px_per_mm

        # ---- 2. identity -------------------------------------------------- #
        ts = time.time()
        self.progress("identity", 0.0, "resolving identities")
        ic = self.cfg.identity
        n_total = self.setup.expected_bees
        mark_readings = self._mark_readings(scores, bee_ids, len(frames)) if mode == "color" else {}
        if mode == "sleap":
            if not det.empty:
                det["id_confidence"] = 1.0
                unknown = sorted(set(det["bee_id"].dropna()) - set(bee_ids))
                if unknown:
                    warnings.append(f"SLEAP track names not in the bee registry: {unknown}")
        elif det.empty:
            pass
        elif ic.closed_group and n_total:
            marked = bee_ids if mode == "color" else []
            if n_total < len(marked):
                warnings.append(f"'Bees in the dish' ({n_total}) is less than the {len(marked)} registered bees; using {len(marked)}")
                n_total = len(marked)
            if mode == "color":  # cut tracklets where the mark readings say two bees were swapped
                det = det.copy()
                det["tracklet"] = IdentityResolver(ic).split_switches(det, scores)
            det, self.group_report = assign_closed_group(
                det, scores if mode == "color" else None, marked, n_total, rec.fps, ppm, self.cfg.unmarked, ic)
            rep = self.group_report
            bee_ids = rep["marked"] + rep["unmarked"]
            if ic.min_probability > 0:
                low = det["id_confidence"] < ic.min_probability
                det.loc[low, "bee_id"] = None
                rep["below_min_probability"] = int(low.sum())
            if rep["never_read"]:
                warnings.append(
                    "the mark of " + ", ".join(f"{b} ({self._colour_of(b)})" for b in rep["never_read"]) + " was never read "
                    "clearly, so these bees can't be told apart by colour and were followed by motion only. Check that "
                    "these colours are really in the dish (Setup → 'Find the marks in the video')"
                )
            if rep["dropped_detections"]:
                self.progress("identity", 1.0, f"{rep['dropped_detections']} detections beyond {n_total} bees dropped")
        elif mode == "color":
            det = IdentityResolver(ic).resolve(
                det, scores, bee_ids,
                max_gap_frames=int(round(ic.link_max_gap_s * rec.fps)), max_dist_px=ic.link_max_dist_mm * ppm)
            if ic.keep_unidentified:
                det = self._name_leftovers(det, rec.fps, ppm)
                extra = sorted(set(det["bee_id"].dropna()) - set(bee_ids))
                bee_ids = bee_ids + extra
        else:  # unmarked, number of bees unknown: open-ended anonymous tracks
            det = stitch_tracklets(det, rec.fps, ppm, self.cfg.unmarked)
            bee_ids = sorted(det["bee_id"].dropna().unique())
            self.progress("identity", 1.0, f"{len(bee_ids)} anonymous tracks")
        timings["identity_s"] = time.time() - ts

        # ---- 3. trajectories ---------------------------------------------- #
        ts = time.time()
        self.progress("trajectories", 0.0, "building trajectories")
        codes = {b.bee_id: b.color for b in self.setup.bees} if mode == "color" else None
        dot_positions: dict[str, str] = {}
        traj = (build_trajectories(det, geom, self.cfg.trajectories, frames, rec.fps, codes,
                                   dot_position=self.cfg.color.dot_position, report=dot_positions)
                if not det.empty else pd.DataFrame(columns=TRAJ_COLUMNS))
        timings["trajectories_s"] = time.time() - ts

        # ---- 4. visits + metrics ------------------------------------------ #
        ts = time.time()
        self.progress("visits", 0.0, "detecting queen-cell visits")
        duration = len(frames) * step / rec.fps
        zone_names = [z.name for z in self.cfg.visits.zones]
        if geom.queen_cell is not None and not traj.empty:
            visits = VisitDetector(self.cfg.visits, geom).detect(traj, rec.fps)
        else:
            visits = pd.DataFrame(columns=VISIT_COLUMNS)
        metrics = bee_metrics(traj, visits, bee_ids, duration, rec.fps, self.cfg.trajectories.moving_speed_mm_s,
                              zones=zone_names if geom.queen_cell is not None else [])
        binned = binned_visits(visits, bee_ids, duration, self.cfg.visits.bin_s)
        timings["visits_s"] = time.time() - ts

        # ---- 5. write ----------------------------------------------------- #
        self.progress("write", 0.0, "writing results")
        det.to_parquet(out / OUTPUT_FILES["detections"], index=False)
        traj.to_parquet(out / OUTPUT_FILES["trajectories"], index=False)
        visits.to_csv(out / OUTPUT_FILES["visits"], index=False)
        metrics.to_csv(out / OUTPUT_FILES["bee_metrics"], index=False)
        binned.to_csv(out / OUTPUT_FILES["binned_visits"], index=False)
        try:
            cv2.imwrite(str(out / OUTPUT_FILES["preview"]), rec.read(0))
        except Exception:  # preview is best-effort
            pass

        identified = float(det["bee_id"].notna().mean()) if not det.empty else 0.0
        size = dict(self.size_info)
        L = size.get("implied_bee_length_mm")
        if L and not 9.0 <= L <= 15.0 and self.setup.dish is not None:
            suggest = self.setup.dish.diameter_mm * self.cfg.detection.bee_length_mm / L
            warnings.append(
                f"bees measure about {L:.1f} mm long at the current scale, but a worker is about "
                f"{self.cfg.detection.bee_length_mm:.0f} mm: the dish diameter ({self.setup.dish.diameter_mm:g} mm) is "
                f"probably wrong. Suggested inner diameter ≈ {suggest:.0f} mm (Setup → Dish Ø). Detection adapts to "
                "the measured bee size, but all mm values, speeds and the visit zones (3 mm, 10 mm) follow the "
                "diameter, so set it and run again"
            )
            size["suggested_dish_diameter_mm"] = round(float(suggest), 1)
        warnings += _sanity_warnings(len(det) / max(1, len(frames)), self.setup.expected_bees, identified, mode)
        timings["total_s"] = time.time() - t0
        summary = {
            "beetrack_version": __version__,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": mode,
            "marking": self.setup.marking,
            "expected_bees": self.setup.expected_bees,
            "n_tracks": int(len(bee_ids)) if mode == "unmarked" else None,
            "closed_group": self.group_report,
            "mark_readings": mark_readings,
            "mark_positions": dot_positions,
            "videos": [s.as_dict() for s in rec.segments],
            "source_fps": rec.fps,
            "analysed_fps": rec.fps / step,
            "frame_step": step,
            "analysed_frames": int(len(frames)),
            "duration_s": duration,
            "px_per_mm": geom.px_per_mm,
            "bee_size": size,
            "detection_threshold": self.threshold_info,
            "static_structures_px": int(self.static_px),
            "mean_bees_per_frame": float(len(det) / max(1, len(frames))),
            "n_detections": int(len(det)),
            "detections_identified_fraction": identified,
            "n_tracklets": int(det["tracklet"].nunique()) if "tracklet" in det and not det.empty else 0,
            "bees_found": sorted(traj["bee_id"].unique().tolist()) if not traj.empty else [],
            "n_visits": {z: int((visits["zone"] == z).sum()) for z in zone_names},
            "warnings": warnings,
            "timings": timings,
            "config": self.cfg.model_dump(mode="json"),
            "setup": self.setup.model_dump(mode="json"),
        }
        (out / OUTPUT_FILES["summary"]).write_text(json.dumps(summary, indent=2))
        self.progress("done", 1.0, f"finished in {timings['total_s']:.0f} s")
        return AnalysisResult(out, det, traj, visits, metrics, binned, summary)

    # ------------------------------------------------------------------ #
    def _colour_of(self, bee_id: str) -> str:
        return next((b.color for b in self.setup.bees if b.bee_id == bee_id), "?")

    @staticmethod
    def _mark_readings(scores: list[dict[str, float]] | None, bee_ids: list[str], n_frames: int) -> dict[str, int]:
        """How many detections showed each registered bee's mark (a quick check that the colours exist)."""
        counts = dict.fromkeys(bee_ids, 0)
        for s in scores or []:
            for b in s:
                if b in counts:
                    counts[b] += 1
        return counts

    def _name_leftovers(self, det: pd.DataFrame, fps: float, ppm: float) -> pd.DataFrame:
        """Hybrid identity: tracklets whose mark was never read clearly enough stay as anonymous tracks (T001…)."""
        rest = det[det["bee_id"].isna()]
        if rest.empty:
            return det
        named = stitch_tracklets(rest.drop(columns=["bee_id", "id_confidence"]), fps, ppm, self.cfg.unmarked)
        det = det.copy()
        det.loc[named.index, "bee_id"] = named["bee_id"]
        det.loc[named.index, "id_confidence"] = 0.0
        return det

    def calibrated_detector(self, rec: Recording, geom: Geometry) -> tuple[BackgroundDetector, Geometry]:
        """Build the detector and tune it on frames sampled over the recording.

        Returns the detector and the geometry it works in. Three things are learned:

        * **Bee size** (``bee_size: auto``). If the measured bees are implausibly long at
          the dish scale (outside 9–15 mm), the dish diameter is wrong. Then every pixel
          threshold (background filter, blob sizes, tracking gates, mark spots, stitching)
          uses a *processing scale* derived from the bees themselves. Output mm still follow the dish.
        * **The queen cell's own look**, so its wax isn't foreground.
        * **Sensitivity** (``auto_threshold``, when the number of bees is known): the
          threshold whose bee count per frame is closest to the truth, frame by frame;
          among equally good ones, the one nearest the configured ``diff_threshold``.
        """
        dc = self.cfg.detection
        n = max(dc.median_samples if dc.method == "median" else 0, dc.size_samples if dc.bee_size == "auto" else 0)
        samples = rec.sample_frames(n) if n else []
        if samples:
            self.progress("detect", 0.0, "sampling frames (background / bee size)")
        proc = geom
        if dc.bee_size == "auto" and samples:
            # 1) measure with a scale-independent filter: assume the smallest plausible dish (≈ 90 mm),
            #    i.e. the widest filter. Too wide never fragments bees; too narrow does.
            probe = dataclasses.replace(geom, px_per_mm=max(geom.px_per_mm, 2 * geom.radius_px / 90.0))
            area = BackgroundDetector(dc, probe).measure_bee_area(samples)
            if area:
                aspect = dc.bee_length_mm / dc.bee_width_mm
                length_px = float(np.sqrt(4 * area / np.pi * aspect))
                if not 9.0 <= length_px / geom.px_per_mm <= 15.0:
                    # 2) the dish scale is implausible for a worker: process with the bees' own scale
                    proc = dataclasses.replace(geom, px_per_mm=length_px / dc.bee_length_mm)
        detector = BackgroundDetector(dc, proc)
        detector.prepare(samples)
        n_expected = self.setup.expected_bees
        if dc.auto_threshold and n_expected and len(samples) >= 10:
            # balance false positives against misses using the known number of bees
            tune = samples[:: max(1, len(samples) // 20)]
            results = []
            for thr in (10, 14, 18, 22, 26, 30, 36, 42, 50, 60):
                detector.set_threshold(thr, samples)
                c = detector.counts(tune)
                # error = how far the count is from the truth, frame by frame (false detections and misses both count)
                results.append((thr, round(float(c.mean()), 2), round(float(np.abs(c - n_expected).mean()), 2)))
            # smallest error; among (near-)equal ones, the threshold closest to the configured default
            best_err = min(r[2] for r in results)
            best = min((r for r in results if r[2] <= best_err + 0.1), key=lambda r: abs(r[0] - dc.diff_threshold))
            detector.set_threshold(best[0], samples)
            self.threshold_info = {"chosen": best[0], "expected_bees": n_expected, "mean_count": best[1],
                                   "tried": [[t, c] for t, c, _ in results], "errors": [[t, e] for t, _, e in results]}
            self.progress("detect", 0.0, f"sensitivity {best[0]}: ~{best[1]:.1f} bees/frame for {n_expected} expected")
        dish_L = None
        if detector.measured_bee_area_px:
            aspect = dc.bee_length_mm / dc.bee_width_mm
            dish_L = float(np.sqrt(4 * detector.measured_bee_area_px / np.pi * aspect) / geom.px_per_mm)
        self.size_info = {"measured_bee_area_px": detector.measured_bee_area_px,
                          "implied_bee_length_mm": dish_L,
                          "processing_px_per_mm": proc.px_per_mm, "dish_px_per_mm": geom.px_per_mm}
        self.static_px = int(detector.static_mask.sum()) if detector.static_mask is not None else 0
        return detector, proc

    def _detect_and_link(self, rec: Recording, geom: Geometry, step: int, use_color: bool = True):
        detector, proc = self.calibrated_detector(rec, geom)
        self.proc_px_per_mm = proc.px_per_mm
        colorid = ColorCodeIdentifier(self.cfg.color, self.setup.bees, proc, self.setup.mark_model) if use_color else None
        tracker = OnlineTracker(self.cfg.tracking, proc.px_per_mm, rec.fps)

        total = rec.n_frames // step
        if self.cfg.max_frames:
            total = min(total, self.cfg.max_frames)
        rows, chunks, scores, frames = [], [], [], []
        report_every = max(1, total // 200)
        tic = time.time()
        for k, (ref, frame) in enumerate(rec.iter_frames(step, self.cfg.max_frames)):
            dets, patches = detector.detect(frame, ref.index)
            if colorid is not None:
                colorid.identify(frame, dets, patches)
            tracker.update(ref.index, dets)
            for d in dets:
                rows.append(d.as_row())
                scores.append(d.color_scores)
            frames.append(ref.index)
            if len(rows) >= 50_000:  # compact Python dicts into a DataFrame chunk to bound memory
                chunks.append(pd.DataFrame(rows))
                rows = []
            if k % report_every == 0:
                rate = (k + 1) / max(1e-6, time.time() - tic)
                eta = (total - k - 1) / rate if rate else 0
                self.progress("detect", (k + 1) / max(1, total),
                              f"frame {k + 1}/{total} · {rate:.1f} fps · ETA {eta / 60:.1f} min")
        if rows:
            chunks.append(pd.DataFrame(rows))
        det = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        if not det.empty:
            det["time_s"] = det["frame"] / rec.fps
        return det, scores, np.asarray(frames, dtype=np.int64)

    def _from_sleap(self, h5: str | Path, rec: Recording, step: int):
        from .detection.sleap_import import load_sleap_analysis

        self.progress("detect", 0.0, f"importing SLEAP predictions from {Path(h5).name}")
        dets = load_sleap_analysis(h5, frame_step=step)
        det = pd.DataFrame([d.as_row() for d in dets])
        frames = np.arange(0, rec.n_frames, step, dtype=np.int64)
        if not det.empty:
            det["time_s"] = det["frame"] / rec.fps
            det["tracklet"] = det["bee_id"].astype("category").cat.codes
        return det, frames
