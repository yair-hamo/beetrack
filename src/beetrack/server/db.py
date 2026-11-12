"""Persistence: a single SQLite file next to the experiment folders.

SQLite in WAL mode lets the web process and the analysis child process write
at the same time (the child updates job progress). The database stores only
metadata. Videos and results are ordinary files in the data directory (see
:mod:`.store`), so they can be copied, backed up or opened in Python and R
without the server.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    station: Mapped[str] = mapped_column(String(50), default="")
    recorded_on: Mapped[str] = mapped_column(String(20), default="")  # ISO date
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    setup: Mapped[dict] = mapped_column(JSON, default=dict)          # ExperimentSetup JSON
    config_yaml: Mapped[str] = mapped_column(Text, default="")        # overrides; "" = defaults

    videos: Mapped[list["Video"]] = relationship(back_populates="experiment", cascade="all, delete-orphan",
                                                 order_by="Video.position")
    jobs: Mapped[list["Job"]] = relationship(back_populates="experiment", cascade="all, delete-orphan",
                                             order_by="Job.id")


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"))
    filename: Mapped[str] = mapped_column(String(300))
    rel_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=0)
    n_frames: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)

    experiment: Mapped[Experiment] = relationship(back_populates="videos")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"))
    kind: Mapped[str] = mapped_column(String(20), default="analyze")  # analyze | render
    target_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # render: which analysis to draw
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # render: {"video": ..., options}
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed|cancelled
    stage: Mapped[str] = mapped_column(String(40), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    experiment: Mapped[Experiment] = relationship(back_populates="jobs")


class Database:
    def __init__(self, path: Path):
        self.url = f"sqlite:///{path}"
        self.engine = create_engine(self.url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        Base.metadata.create_all(self.engine)
        self._migrate()
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def _migrate(self) -> None:
        """Add columns introduced after a database was created (SQLite can't do it via create_all)."""
        added = {"jobs": [("kind", "VARCHAR(20) NOT NULL DEFAULT 'analyze'"), ("target_job_id", "INTEGER"), ("params", "JSON")]}
        with self.engine.begin() as conn:
            for table, cols in added.items():
                have = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
                for name, ddl in cols:
                    if name not in have:
                        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def session(self) -> Session:
        return self.Session()
