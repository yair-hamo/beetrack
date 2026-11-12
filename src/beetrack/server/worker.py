"""Background analysis runner.

One :class:`JobWorker` thread lives inside the web server. It takes queued
jobs one at a time (analyses are CPU/GPU-heavy, so running several at once
only slows all of them) and runs each in a **separate process**:

* a crash or memory blow-up in the analysis can't take the web server down;
* cancelling is a clean ``terminate()``;
* the child writes progress directly to SQLite, and the UI polls ``/api/jobs``.

If the server restarts, jobs left in ``running`` are marked failed
("interrupted") at startup.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import threading
import time
import traceback
from pathlib import Path

from .db import Database, Experiment, Job, utcnow
from .store import DataStore

log = logging.getLogger("beetrack.worker")


def load_run(results_dir: Path):
    """(setup, config) a finished analysis was made with, from its ``summary.json``."""
    import json

    from ..config import AnalysisConfig, ExperimentSetup

    summary = json.loads((results_dir / "summary.json").read_text())
    setup = ExperimentSetup.model_validate(summary["setup"])
    return setup, setup.effective_config(AnalysisConfig.model_validate(summary["config"]))


def _run_job(data_root: str, job_id: int) -> None:
    """Child-process entry point. Every failure, including a bad setup, is reported on the job."""
    store = DataStore(Path(data_root))
    db = Database(store.db_path)
    last = [0.0]

    def progress(stage: str, frac: float, msg: str) -> None:
        now = time.time()
        if now - last[0] < 1.0 and frac < 1.0 and stage != "done":
            return
        last[0] = now
        with db.session() as s2:
            j = s2.get(Job, job_id)
            j.stage, j.progress, j.message = stage, float(frac), msg
            s2.commit()

    try:
        import yaml

        from ..config import AnalysisConfig, ExperimentSetup
        from ..pipeline import AnalysisPipeline

        with db.session() as s:
            job = s.get(Job, job_id)
            exp = s.get(Experiment, job.experiment_id)
            videos = [store.abs(v.rel_path) for v in exp.videos]
            kind, target, exp_id, params = job.kind or "analyze", job.target_job_id, exp.id, dict(job.params or {})
            width, height = (exp.videos[0].width, exp.videos[0].height) if exp.videos else (0, 0)
            setup_json, config_yaml = exp.setup or {}, exp.config_yaml
            out = store.results_dir(exp.id, job.id)
            job.status, job.started_at, job.stage = "running", utcnow(), "render" if kind == "render" else "prepare"
            s.commit()
        if kind == "render":
            _render(store, exp_id, target, videos, params, width, height, progress)
        else:
            setup = ExperimentSetup.model_validate(setup_json)
            cfg = AnalysisConfig.model_validate(yaml.safe_load(config_yaml) or {}) if config_yaml else AnalysisConfig()
            AnalysisPipeline(cfg, setup, progress).run(videos, out)
        with db.session() as s:
            j = s.get(Job, job_id)
            j.status, j.progress, j.stage, j.finished_at = "done", 1.0, "done", utcnow()
            s.commit()
    except Exception as e:
        with db.session() as s:
            j = s.get(Job, job_id)
            j.status, j.finished_at = "failed", utcnow()
            j.error = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
            j.message = str(e)
            s.commit()


def _render(store, exp_id, target_job_id, videos, params, width, height, progress) -> None:
    """Render one result video for a finished analysis into that analysis's results folder.

    The video is drawn with the setup and config *that analysis used* (from its
    summary.json), so it stays right even if the experiment's setup was edited
    since. The file appears under its final name only when complete; its options
    are saved next to it (``<name>.json``) so the UI can show how it was made.
    """
    import json

    import pandas as pd

    from ..video import probe
    from ..videos import VIDEO_FILES, RenderOptions, render

    kind = params.pop("video", "annotated")
    opts = RenderOptions.model_validate(params)
    d = store.results_dir(exp_id, target_job_id)
    setup, cfg = load_run(d)
    traj = pd.read_parquet(d / "trajectories.parquet")
    final = d / VIDEO_FILES[kind]
    tmp = final.with_suffix(".partial.mp4")
    tmp.unlink(missing_ok=True)  # left over from a cancelled render
    fps = probe(videos[0]).fps
    render(kind, videos=videos, setup=setup, cfg=cfg, traj=traj, width=width, height=height, src_fps=fps,
           out=tmp, opts=opts, progress=lambda f, m: progress("render", f, m))
    tmp.replace(final)
    final.with_suffix(".json").write_text(json.dumps({"video": kind, **opts.model_dump(), "description": opts.describe()}))


class JobWorker(threading.Thread):
    def __init__(self, store: DataStore, db: Database, poll_s: float = 1.0):
        super().__init__(daemon=True, name="beetrack-worker")
        self.store, self.db, self.poll_s = store, db, poll_s
        self._stop_event = threading.Event()  # not `_stop`: that name is a private method of threading.Thread
        self._proc: mp.Process | None = None
        self._current: int | None = None
        self._ctx = mp.get_context("spawn")
        self._recover()

    def _recover(self) -> None:
        with self.db.session() as s:
            for j in s.query(Job).filter(Job.status == "running"):
                j.status, j.message, j.finished_at = "failed", "interrupted (server restarted)", utcnow()
            s.commit()

    def cancel(self, job_id: int) -> bool:
        with self.db.session() as s:
            j = s.get(Job, job_id)
            if j is None:
                return False
            if j.status == "queued":
                j.status, j.finished_at, j.message = "cancelled", utcnow(), "cancelled before start"
                s.commit()
                return True
        if self._current == job_id and self._proc is not None and self._proc.is_alive():
            self._proc.terminate()
            return True
        return False

    def stop(self) -> None:
        self._stop_event.set()
        if self._proc is not None and self._proc.is_alive():
            self._proc.terminate()

    def run(self) -> None:
        while not self._stop_event.is_set():
            job_id = self._next()
            if job_id is None:
                self._stop_event.wait(self.poll_s)
                continue
            self._current = job_id
            self._proc = self._ctx.Process(target=_run_job, args=(str(self.store.root), job_id), daemon=True)
            self._proc.start()
            self._proc.join()
            code = self._proc.exitcode
            with self.db.session() as s:
                j = s.get(Job, job_id)
                if j.status in ("running", "queued"):
                    terminated = code is not None and code < 0
                    j.status = "cancelled" if terminated else "failed"
                    j.message = "cancelled by user" if terminated else f"analysis process exited with code {code}"
                    j.finished_at = utcnow()
                    s.commit()
            self._current, self._proc = None, None

    def _next(self) -> int | None:
        with self.db.session() as s:
            j = s.query(Job).filter(Job.status == "queued").order_by(Job.id).first()
            return j.id if j else None
