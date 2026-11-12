"""REST API (mounted at ``/api``). Endpoint reference: ``docs/API.md``."""

from __future__ import annotations

import io
import json
import shutil
from functools import lru_cache
from typing import Literal
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from .. import __version__
from ..calibration import Geometry, circle_from_points, detect_dish
from ..config import AnalysisConfig, DishGeometry, ExperimentSetup
from ..identity.palette import Palette
from ..pipeline import OUTPUT_FILES
from ..video import probe, read_frame
from .db import Database, Experiment, Job, Video
from .overlay import draw_overlay, encode_jpeg
from .store import DataStore

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- #
# dependencies & helpers
# --------------------------------------------------------------------------- #
def ctx(request: Request):
    return request.app.state


def _exp(state, exp_id: int, s) -> Experiment:
    e = s.get(Experiment, exp_id)
    if e is None:
        raise HTTPException(404, f"experiment {exp_id} not found")
    return e


def _cfg(e: Experiment, raw: bool = False) -> AnalysisConfig:
    """The experiment's config; unless ``raw``, with its learned marks in place of the configured palette."""
    cfg = AnalysisConfig() if not e.config_yaml.strip() else AnalysisConfig.model_validate(yaml.safe_load(e.config_yaml) or {})
    return cfg if raw else _setup(e).effective_config(cfg)


def _setup(e: Experiment) -> ExperimentSetup:
    return ExperimentSetup.model_validate(e.setup or {})


def _latest_done(e: Experiment) -> Job | None:
    """Latest successful *analysis* (render jobs don't produce results of their own)."""
    done = [j for j in e.jobs if j.status == "done" and (j.kind or "analyze") == "analyze"]
    return done[-1] if done else None


def _latest_render(e: Experiment, analysis_id: int, video: str = "annotated") -> Job | None:
    r = [j for j in e.jobs if j.kind == "render" and j.target_job_id == analysis_id
         and (j.params or {}).get("video", "annotated") == video]
    return r[-1] if r else None


def _videos_info(e: Experiment, d: Path) -> dict:
    from ..videos import VIDEO_FILES

    out = {}
    aid = int(d.name.split("_")[1])
    for kind, name in VIDEO_FILES.items():
        f = d / name
        meta = f.with_suffix(".json")
        out[kind] = {
            "exists": f.exists(),
            "size_bytes": f.stat().st_size if f.exists() else 0,
            "options": json.loads(meta.read_text()) if meta.exists() else None,
            "job": _job_dict(_latest_render(e, aid, kind)),
        }
    return out


def _results_dir(state, e: Experiment, job_id: int | None = None) -> Path:
    if job_id is None:
        j = _latest_done(e)
        if j is None:
            raise HTTPException(404, "no finished analysis for this experiment yet")
        job_id = j.id
    d = state.store.results_dir(e.id, job_id)
    if not d.exists():
        raise HTTPException(404, "results folder missing")
    return d


@lru_cache(maxsize=8)
def _read_parquet_cached(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)


def _traj(d: Path) -> pd.DataFrame:
    p = d / OUTPUT_FILES["trajectories"]
    return _read_parquet_cached(str(p), p.stat().st_mtime)


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records"))


def _read_csv(path: Path) -> pd.DataFrame:
    """Read a result CSV; empty or header-less files (e.g. no visits) give an empty table."""
    try:
        return pd.read_csv(path)
    except (pd.errors.EmptyDataError, FileNotFoundError):
        return pd.DataFrame()


def _job_dict(j: Job | None) -> dict | None:
    if j is None:
        return None
    return {
        "id": j.id, "experiment_id": j.experiment_id, "kind": j.kind or "analyze", "target_job_id": j.target_job_id,
        "params": j.params,
        "status": j.status, "stage": j.stage,
        "progress": j.progress, "message": j.message, "error": j.error,
        "created_at": j.created_at.isoformat() + "Z" if j.created_at else None,
        "started_at": j.started_at.isoformat() + "Z" if j.started_at else None,
        "finished_at": j.finished_at.isoformat() + "Z" if j.finished_at else None,
    }


def _video_dict(v: Video) -> dict:
    return {"id": v.id, "filename": v.filename, "size_bytes": v.size_bytes, "fps": v.fps, "n_frames": v.n_frames,
            "width": v.width, "height": v.height, "duration_s": v.duration_s, "position": v.position}


def _analyses(e: Experiment) -> list[Job]:
    return [j for j in e.jobs if (j.kind or "analyze") == "analyze"]


def _run_setup(d: Path) -> tuple[ExperimentSetup, AnalysisConfig]:
    """Setup and config a finished analysis was made with (cached per results folder)."""
    p = d / OUTPUT_FILES["summary"]
    return _load_run_cached(str(d), p.stat().st_mtime)


@lru_cache(maxsize=16)
def _load_run_cached(d: str, mtime: float) -> tuple[ExperimentSetup, AnalysisConfig]:
    from .worker import load_run

    return load_run(Path(d))


def _status(e: Experiment, check: dict) -> str:
    active = [j for j in e.jobs if j.status in ("queued", "running")]
    if any((j.kind or "analyze") == "analyze" for j in active):
        return "analysing"
    if active:
        return "rendering"
    last = (_analyses(e) or [None])[-1]
    if not e.videos:
        return "no video"
    if check["errors"]:
        return "needs setup"
    if _latest_done(e):
        return "done"
    if last and last.status == "failed":
        return "failed"
    return "ready"


def _exp_dict(e: Experiment, full: bool = False) -> dict:
    cfg = _cfg(e)
    setup = _setup(e)
    check = setup.check(cfg)
    d = {
        "id": e.id, "name": e.name, "station": e.station, "recorded_on": e.recorded_on, "notes": e.notes,
        "created_at": e.created_at.isoformat() + "Z", "status": _status(e, check),
        "n_videos": len(e.videos), "duration_s": sum(v.duration_s for v in e.videos),
        "n_bees": setup.expected_bees or len(setup.bees),
        "latest_job": _job_dict((_analyses(e) or [None])[-1]),  # latest analysis (video renders are listed in `jobs`)
        "has_results": _latest_done(e) is not None,
    }
    if full:
        d.update(videos=[_video_dict(v) for v in e.videos], setup=setup.model_dump(mode="json"), check=check,
                 config_yaml=e.config_yaml, jobs=[_job_dict(j) for j in reversed(e.jobs)])
    return d


# --------------------------------------------------------------------------- #
# meta
# --------------------------------------------------------------------------- #
@router.get("/health")
def health(state=Depends(ctx)):
    return {"ok": True, "version": __version__, "data_dir": str(state.store.root)}


@router.get("/defaults")
def defaults():
    cfg = AnalysisConfig()
    return {"config": cfg.model_dump(mode="json"), "config_yaml": cfg.dump_yaml(),
            "palette": [c.model_dump() for c in cfg.color.palette],
            "setup": ExperimentSetup().model_dump(mode="json")}


# --------------------------------------------------------------------------- #
# experiments
# --------------------------------------------------------------------------- #
class ExperimentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    station: str = ""
    recorded_on: str = ""
    notes: str = ""


class ExperimentPatch(BaseModel):
    name: str | None = None
    station: str | None = None
    recorded_on: str | None = None
    notes: str | None = None


@router.get("/experiments")
def list_experiments(state=Depends(ctx)):
    with state.db.session() as s:
        exps = s.query(Experiment).order_by(Experiment.id.desc()).all()
        return [_exp_dict(e) for e in exps]


@router.post("/experiments", status_code=201)
def create_experiment(body: ExperimentIn, state=Depends(ctx)):
    with state.db.session() as s:
        e = Experiment(**body.model_dump(), setup=ExperimentSetup().model_dump(mode="json"))
        s.add(e)
        s.commit()
        state.store.videos_dir(e.id)
        return _exp_dict(e, full=True)


@router.get("/experiments/{exp_id}")
def get_experiment(exp_id: int, state=Depends(ctx)):
    with state.db.session() as s:
        return _exp_dict(_exp(state, exp_id, s), full=True)


@router.patch("/experiments/{exp_id}")
def patch_experiment(exp_id: int, body: ExperimentPatch, state=Depends(ctx)):
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(e, k, v)
        s.commit()
        return _exp_dict(e, full=True)


@router.delete("/experiments/{exp_id}", status_code=204)
def delete_experiment(exp_id: int, state=Depends(ctx)):
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        if any(j.status in ("queued", "running") for j in e.jobs):
            raise HTTPException(409, "an analysis is queued or running; cancel it first")
        s.delete(e)
        s.commit()
    state.store.delete_experiment(exp_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# videos
# --------------------------------------------------------------------------- #
@router.post("/experiments/{exp_id}/videos", status_code=201)
def upload_video(exp_id: int, file: UploadFile = File(...), state=Depends(ctx)):
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        name = state.store.safe_filename(file.filename or "video.mp4")
        dest = state.store.videos_dir(exp_id) / name
        if dest.exists():
            raise HTTPException(409, f"{name} already uploaded to this experiment")
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f, length=8 * 1024 * 1024)
        try:
            info = probe(dest)
        except IOError as err:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, f"not a readable video: {err}")
        if e.videos:
            v0 = e.videos[0]
            if (info.width, info.height) != (v0.width, v0.height) or abs(info.fps - v0.fps) > 0.01:
                dest.unlink(missing_ok=True)
                raise HTTPException(400, "all segments of an experiment need the same resolution and fps "
                                         f"({v0.width}x{v0.height} @ {v0.fps:g})")
        v = Video(experiment_id=exp_id, filename=name, rel_path=state.store.rel(dest), size_bytes=dest.stat().st_size,
                  fps=info.fps, n_frames=info.n_frames, width=info.width, height=info.height,
                  duration_s=info.duration_s, position=len(e.videos))
        s.add(v)
        # first video: try to find the dish automatically
        setup = _setup(e)
        if setup.dish is None:
            try:
                dish = detect_dish(read_frame(dest, 0))
                if dish:
                    setup.dish = dish
                    e.setup = setup.model_dump(mode="json")
            except Exception:
                pass
        s.commit()
        return _video_dict(v)


@router.delete("/experiments/{exp_id}/videos/{video_id}", status_code=204)
def delete_video(exp_id: int, video_id: int, state=Depends(ctx)):
    with state.db.session() as s:
        v = s.get(Video, video_id)
        if v is None or v.experiment_id != exp_id:
            raise HTTPException(404, "video not found")
        state.store.abs(v.rel_path).unlink(missing_ok=True)
        s.delete(v)
        s.commit()
    return Response(status_code=204)


def _read_or_404(path: Path, local: int):
    try:
        return read_frame(path, local)
    except IndexError as err:
        raise HTTPException(404, f"{err} (end of video?)")


def _video_at(state, e: Experiment, t: float) -> tuple[Path, int, int]:
    """(file, local frame, global frame) for time t (s) on the experiment timeline."""
    if not e.videos:
        raise HTTPException(404, "no video uploaded")
    offset = 0
    t = max(0.0, t)
    for v in e.videos:
        if t < v.duration_s or v is e.videos[-1]:
            local = min(int(round(t * v.fps)), max(0, v.n_frames - 1))
            return state.store.abs(v.rel_path), local, offset + local
        t -= v.duration_s
        offset += v.n_frames
    raise HTTPException(404)


@router.get("/experiments/{exp_id}/frame")
def frame(exp_id: int, t: float = 0.0, overlay: bool = True, trail_s: float = 0.0,
          max_width: int = Query(1600, ge=200, le=8000), state=Depends(ctx)):
    """JPEG of the video at time ``t`` (s), optionally with geometry and tracks drawn on."""
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        path, local, glob = _video_at(state, e, t)
        img = _read_or_404(path, local)
        if overlay:
            traj, trail = None, 0
            done = _latest_done(e)
            setup, cfg = _setup(e), _cfg(e)
            if done is not None:
                try:
                    d = state.store.results_dir(e.id, done.id)
                    traj = _traj(d)
                    setup, cfg = _run_setup(d)  # tracks are drawn with the setup they were computed with
                    fr = np.sort(traj["frame"].unique())
                    if len(fr) > 1:
                        trail = int(trail_s * e.videos[0].fps / max(1, np.median(np.diff(fr))))
                except FileNotFoundError:
                    traj = None
            img = draw_overlay(img, setup, cfg, traj, glob, trail)
        return Response(encode_jpeg(img, max_width=max_width), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


@router.get("/experiments/{exp_id}/probe")
def probe_pixel(exp_id: int, x: float, y: float, t: float = 0.0, r: int = 3, state=Depends(ctx)):
    """Median HSV around (x, y) px and how the palette classifies it, for tuning paint hues."""
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        path, local, _ = _video_at(state, e, t)
        img = _read_or_404(path, local)
        xi, yi = int(round(x)), int(round(y))
        patch = img[max(0, yi - r): yi + r + 1, max(0, xi - r): xi + r + 1]
        if patch.size == 0:
            raise HTTPException(400, "point outside the frame")
        out = Palette(_cfg(e).color).describe_pixels(patch)
        b, g, rr = np.median(patch.reshape(-1, 3), axis=0)
        out["hex"] = "#{:02x}{:02x}{:02x}".format(int(rr), int(g), int(b))
        return out


# --------------------------------------------------------------------------- #
# setup & config
# --------------------------------------------------------------------------- #
@router.put("/experiments/{exp_id}/setup")
def put_setup(exp_id: int, body: dict, state=Depends(ctx)):
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        try:
            setup = ExperimentSetup.model_validate(body)
        except ValidationError as err:
            raise HTTPException(422, err.errors(include_url=False))
        e.setup = setup.model_dump(mode="json")
        s.commit()
        return {"setup": e.setup, "check": setup.check(_cfg(e))}


class DishIn(BaseModel):
    diameter_mm: float = Field(150.0, gt=0)
    points: list[tuple[float, float]] | None = Field(None, description="3 rim points (px); omit for auto-detection")


@router.post("/experiments/{exp_id}/dish")
def set_dish(exp_id: int, body: DishIn, state=Depends(ctx)):
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        if body.points:
            if len(body.points) != 3:
                raise HTTPException(422, "need exactly 3 rim points")
            try:
                (cx, cy), r = circle_from_points(*body.points)
            except ValueError as err:
                raise HTTPException(422, str(err))
            dish = DishGeometry(center_px=(cx, cy), radius_px=r, diameter_mm=body.diameter_mm)
        else:
            path, local, _ = _video_at(state, e, 0)
            dish = detect_dish(read_frame(path, local), body.diameter_mm)
            if dish is None:
                raise HTTPException(422, "dish not found automatically; click 3 points on the rim instead")
        setup = _setup(e)
        setup.dish = dish
        e.setup = setup.model_dump(mode="json")
        s.commit()
        return {"setup": e.setup, "check": setup.check(_cfg(e))}


class DiscoverIn(BaseModel):
    frames: int = Field(120, ge=20, le=600, description="Frames sampled over the recording")


@router.post("/experiments/{exp_id}/discover-marks")
def discover_marks(exp_id: int, body: DiscoverIn | None = None, state=Depends(ctx)):
    """Find the paint colours actually present on the bees (no palette needed). Takes a few seconds."""
    from ..identity.discover import discover
    from ..pipeline import AnalysisPipeline
    from ..video import Recording

    body = body or DiscoverIn()
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        if not e.videos:
            raise HTTPException(409, "upload a video first")
        setup, cfg = _setup(e), _cfg(e, raw=True)
        paths = [state.store.abs(v.rel_path) for v in e.videos]
    if setup.dish is None:
        raise HTTPException(409, "set the dish first (Setup → Auto-detect dish)")
    rec = Recording(paths)
    geom = Geometry.from_setup(setup, rec.width, rec.height)
    pl = AnalysisPipeline(cfg, setup.model_copy(update={"marking": "none", "palette": None}))
    detector, proc = pl.calibrated_detector(rec, geom)
    # never learn from the ignore areas (food…) or the queen cell's wax, nor from a 1 mm band around them
    exclude = proc.exclusion_mask(include_cell=True, margin_mm=1.0)
    return discover(rec, detector, n_frames=body.frames, px_per_mm=proc.px_per_mm,
                    dish=(geom.cx, geom.cy, geom.radius_px), exclude=exclude)


class ConfigIn(BaseModel):
    yaml: str = ""


@router.put("/experiments/{exp_id}/config")
def put_config(exp_id: int, body: ConfigIn, state=Depends(ctx)):
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        if body.yaml.strip():
            try:
                AnalysisConfig.model_validate(yaml.safe_load(body.yaml) or {})
            except (yaml.YAMLError, ValidationError) as err:
                raise HTTPException(422, f"invalid config: {err}")
        e.config_yaml = body.yaml
        s.commit()
        return {"ok": True}


# --------------------------------------------------------------------------- #
# jobs
# --------------------------------------------------------------------------- #
@router.post("/experiments/{exp_id}/analyze", status_code=202)
def analyze(exp_id: int, state=Depends(ctx)):
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        if not e.videos:
            raise HTTPException(409, "upload a video first")
        check = _setup(e).check(_cfg(e))
        if check["errors"]:
            raise HTTPException(409, "setup incomplete: " + "; ".join(check["errors"]))
        active = [j for j in e.jobs if j.status in ("queued", "running")]
        if any((j.kind or "analyze") == "analyze" for j in active):
            raise HTTPException(409, "an analysis is already queued or running")
        if active:
            raise HTTPException(409, "a video is being rendered; start the analysis when it has finished")
        j = Job(experiment_id=exp_id)
        s.add(j)
        s.commit()
        return _job_dict(j)


@router.get("/jobs")
def list_jobs(limit: int = 50, state=Depends(ctx)):
    with state.db.session() as s:
        return [_job_dict(j) for j in s.query(Job).order_by(Job.id.desc()).limit(limit)]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, state=Depends(ctx)):
    with state.db.session() as s:
        j = s.get(Job, job_id)
        if j is None:
            raise HTTPException(404, "job not found")
        return _job_dict(j)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, state=Depends(ctx)):
    if not state.worker.cancel(job_id):
        raise HTTPException(409, "job is not queued or running")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
@router.get("/experiments/{exp_id}/results")
def results(exp_id: int, job_id: int | None = None, state=Depends(ctx)):
    """Summary, per-bee metrics, all visits and the time-binned table in one call."""
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        d = _results_dir(state, e, job_id)
        summary = json.loads((d / OUTPUT_FILES["summary"]).read_text())
        run_setup, run_cfg = _run_setup(d)
        current = _setup(e)
        for k in ("config", "setup"):
            summary.pop(k, None)
        return {
            # what this analysis was made with; the experiment's setup may have been edited since
            "run_setup": {"marking": run_setup.marking, "n_bees": run_setup.n_bees,
                          "bees": [b.model_dump() for b in run_setup.bees],
                          "palette": [c.model_dump() for c in run_cfg.color.palette]},
            "setup_changed": run_setup.model_dump(mode="json") != current.model_dump(mode="json"),
            "job_id": int(d.name.split("_")[1]),
            "summary": summary,
            "metrics": _records(_read_csv(d / OUTPUT_FILES["bee_metrics"])),
            "visits": _records(_read_csv(d / OUTPUT_FILES["visits"])),
            "binned": _records(_read_csv(d / OUTPUT_FILES["binned_visits"])),
            "zones": [z.model_dump() for z in run_cfg.visits.zones],
            "videos": (videos := _videos_info(e, d)),
            "annotated_video": videos["annotated"],  # kept for older clients
        }


@router.get("/experiments/{exp_id}/results/trajectories")
def trajectories(exp_id: int, bee: list[str] | None = Query(None), step_s: float = Query(1.0, ge=0),
                 t0: float = 0.0, t1: float | None = None, state=Depends(ctx)):
    """Down-sampled paths, columnar: ``{bee_id: {t, x, y}}`` (mm)."""
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        tr = _traj(_results_dir(state, e))
    tr = tr[(tr["time_s"] >= t0) & ((tr["time_s"] <= t1) if t1 is not None else True)]
    if bee:
        tr = tr[tr["bee_id"].isin(bee)]
    out = {}
    for b, g in tr.groupby("bee_id"):
        if step_s > 0 and len(g) > 1:
            dt = float(np.median(np.diff(g["time_s"].to_numpy())))
            g = g.iloc[:: max(1, int(round(step_s / dt))) if dt > 0 else 1]
        out[b] = {k: [None if not np.isfinite(v) else round(float(v), 2) for v in g[c]]
                  for k, c in (("t", "time_s"), ("x", "x_mm"), ("y", "y_mm"))}
    return out


@router.get("/experiments/{exp_id}/results/heatmap")
def heatmap(exp_id: int, bee: str | None = None, bins: int = Query(60, ge=10, le=300), state=Depends(ctx)):
    """Occupancy (seconds per cell) on a square grid covering the dish."""
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        d = _results_dir(state, e)
        tr = _traj(d)
        setup, _ = _run_setup(d)
    if bee:
        tr = tr[tr["bee_id"] == bee]
    tr = tr.dropna(subset=["x_mm", "y_mm"])
    r = setup.dish.diameter_mm / 2 if setup.dish else 75
    dt = float(np.median(np.diff(np.sort(tr["time_s"].unique())))) if tr["time_s"].nunique() > 1 else 0
    H, xe, ye = np.histogram2d(tr["x_mm"], tr["y_mm"], bins=bins, range=[[-r, r], [-r, r]])
    return {"z": (H.T * dt).round(2).tolist(), "x": ((xe[:-1] + xe[1:]) / 2).round(2).tolist(),
            "y": ((ye[:-1] + ye[1:]) / 2).round(2).tolist()}


@router.get("/experiments/{exp_id}/geometry")
def geometry_mm(exp_id: int, state=Depends(ctx)):
    """Dish and queen-cell outlines in mm (for drawing on result plots)."""
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        setup, cfg = _setup(e), _cfg(e)
        done = _latest_done(e)
        if done is not None and state.store.results_dir(e.id, done.id).exists():
            setup, cfg = _run_setup(state.store.results_dir(e.id, done.id))  # match the plotted trajectories
        if setup.dish is None or not e.videos:
            return {"dish_radius_mm": None, "queen_cell": None, "zones": []}
        geom = Geometry.from_setup(setup, e.videos[0].width, e.videos[0].height)
    out = {"dish_radius_mm": setup.dish.diameter_mm / 2, "queen_cell": None, "zones": [],
           "marking": setup.marking, "bees": [b.model_dump() for b in setup.bees],
           "palette": [c.model_dump() for c in cfg.color.palette]}
    if geom.queen_cell is not None:
        x, y = geom.to_mm(geom.queen_cell[:, 0], geom.queen_cell[:, 1])
        out["queen_cell"] = {"x": x.round(2).tolist(), "y": y.round(2).tolist()}
        for z in cfg.visits.zones:
            p = geom.zone_polygon_px(z)
            zx, zy = geom.to_mm(p[:, 0], p[:, 1])
            out["zones"].append({"name": z.name, "x": zx.round(2).tolist(), "y": zy.round(2).tolist()})
    return out


class RenderIn(BaseModel):
    video: Literal["annotated", "paths", "heatmap"] = "annotated"
    step_s: float | None = Field(None, ge=0, le=3600)
    trail_s: float = Field(3.0, ge=-1, le=86400)
    fps: float = Field(15.0, ge=1, le=60)
    bees: list[str] | None = None


@router.post("/experiments/{exp_id}/render", status_code=202)
def render(exp_id: int, body: RenderIn | None = None, state=Depends(ctx)):
    """Queue rendering of one result video (annotated / paths / heatmap) for the latest analysis."""
    body = body or RenderIn()
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        done = _latest_done(e)
        if done is None:
            raise HTTPException(409, "run the analysis first")
        busy = [j for j in e.jobs if j.status in ("queued", "running")]
        if any((j.kind or "analyze") == "analyze" for j in busy):
            raise HTTPException(409, "an analysis is queued or running; render after it finishes")
        if any((j.params or {}).get("video", "annotated") == body.video for j in busy):
            raise HTTPException(409, f"the {body.video} video is already being rendered")
        j = Job(experiment_id=exp_id, kind="render", target_job_id=done.id, params=body.model_dump())
        s.add(j)
        s.commit()
        return _job_dict(j)


DOWNLOADS = {
    "visits.csv": "visits", "bee_metrics.csv": "bee_metrics", "binned_visits.csv": "binned_visits",
    "summary.json": "summary", "trajectories.parquet": "trajectories", "detections.parquet": "detections",
}


@router.get("/experiments/{exp_id}/download/{name}")
def download(exp_id: int, name: str, job_id: int | None = None, state=Depends(ctx)):
    with state.db.session() as s:
        e = _exp(state, exp_id, s)
        d = _results_dir(state, e, job_id)
        stem = f"exp{e.id:04d}_{state.store.safe_filename(e.name)}"
    if name in ("annotations.csv", "annotations_mot.txt"):
        from ..export import annotations_mot, annotations_table

        with state.db.session() as s:
            v0 = _exp(state, exp_id, s).videos[0]
            width, height = v0.width, v0.height
        setup, _ = _run_setup(d)
        ann = annotations_table(pd.read_parquet(d / OUTPUT_FILES["detections"]), _traj(d), setup, width, height)
        body = ann.to_csv(index=False) if name.endswith(".csv") else annotations_mot(ann)
        return Response(body, media_type="text/csv" if name.endswith(".csv") else "text/plain",
                        headers={"Content-Disposition": f'attachment; filename="{stem}_{name}"'})
    if name in ("annotated.mp4", "paths.mp4", "heatmap.mp4"):
        f = d / name
        if not f.exists():
            raise HTTPException(404, f"{name} not rendered yet (Results → Videos)")
        return FileResponse(f, media_type="video/mp4", filename=f"{stem}_{name}")
    if name == "trajectories.csv":
        df = _traj(d)
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{stem}_trajectories.csv"'})
    if name not in DOWNLOADS:
        raise HTTPException(404, f"unknown file; choose from {sorted(DOWNLOADS) + ['trajectories.csv', 'annotations.csv', 'annotations_mot.txt', 'annotated.mp4', 'paths.mp4', 'heatmap.mp4']}")
    return FileResponse(d / OUTPUT_FILES[DOWNLOADS[name]], filename=f"{stem}_{name}")
