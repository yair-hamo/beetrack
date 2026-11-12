"""On-disk layout of the data directory::

    data/
    ├── beetrack.sqlite                 metadata (experiments, videos, jobs)
    └── experiments/
        └── 0007/
            ├── videos/                 uploaded segments, original names
            └── results/
                └── job_0012/           one folder per analysis run (kept for provenance)
                    ├── summary.json
                    ├── trajectories.parquet
                    ├── visits.csv
                    └── ...
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path


class DataStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        (self.root / "experiments").mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        return self.root / "beetrack.sqlite"

    def experiment_dir(self, exp_id: int) -> Path:
        return self.root / "experiments" / f"{exp_id:04d}"

    def videos_dir(self, exp_id: int) -> Path:
        d = self.experiment_dir(exp_id) / "videos"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def results_dir(self, exp_id: int, job_id: int) -> Path:
        return self.experiment_dir(exp_id) / "results" / f"job_{job_id:04d}"

    def abs(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root not in p.parents:
            raise ValueError("path escapes the data directory")
        return p

    def rel(self, p: Path) -> str:
        return str(Path(p).resolve().relative_to(self.root))

    def delete_experiment(self, exp_id: int) -> None:
        shutil.rmtree(self.experiment_dir(exp_id), ignore_errors=True)

    @staticmethod
    def safe_filename(name: str) -> str:
        name = Path(name).name
        name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("._")
        return name or "video.mp4"
