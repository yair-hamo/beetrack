"""Application factory: ``create_app(data_dir)`` wires store, database, worker and routes."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .api import router
from .db import Database
from .store import DataStore
from .worker import JobWorker

STATIC = Path(__file__).parent / "static"


def _migrate_setups(db: Database) -> None:
    """Rewrite stored setups in the current schema (e.g. v0.1 thorax/abdomen bees → one dot colour)."""
    from ..config import ExperimentSetup
    from .db import Experiment

    with db.session() as s:
        for e in s.query(Experiment):
            try:
                new = ExperimentSetup.model_validate(e.setup or {}).model_dump(mode="json")
            except Exception:
                continue  # leave unreadable setups for the user to fix in the UI
            if new != e.setup:
                e.setup = new
        s.commit()


def create_app(data_dir: str | Path = "data", start_worker: bool = True) -> FastAPI:
    store = DataStore(Path(data_dir))
    db = Database(store.db_path)
    _migrate_setups(db)
    worker = JobWorker(store, db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_worker:
            worker.start()
        yield
        worker.stop()

    app = FastAPI(title="beetrack", version=__version__, lifespan=lifespan,
                  description="Upload arena videos, set up experiments, run analyses and explore bee visits.")
    app.state.store, app.state.db, app.state.worker = store, db, worker
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    return app
