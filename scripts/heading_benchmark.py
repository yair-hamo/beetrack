"""Head-direction accuracy against synthetic ground truth (the numbers in CLAUDE.md §6).

    python scripts/heading_benchmark.py /tmp/heading_bench

Generates two synthetic recordings (seed 3 = easy, seed 1 = bees pile up on the cell; cached in the folder),
analyses each with marks and without, and prints per run: the share of frames with head and tail swapped
(heading error > 90°) overall, per behaviour state and per ``heading_source``, and the same restricted to the
trustworthy sources (``trajectories.RELIABLE_HEADING``). Takes about a minute.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from beetrack.config import AnalysisConfig, ExperimentSetup
from beetrack.pipeline import AnalysisPipeline
from beetrack.synthetic import SyntheticArena
from beetrack.trajectories import RELIABLE_HEADING


def bench(root: Path, seed: int, marking: str, duration_s: float = 45) -> dict:
    vid = root / f"synthetic_{seed}"
    if not (vid / "ground_truth.parquet").exists():
        SyntheticArena(seed=seed).generate(vid, duration_s=duration_s)
    setup = ExperimentSetup.load(vid / "setup.json")
    if marking == "none":
        setup = setup.model_copy(update={"marking": "none"})
    out_dir = root / f"results_{seed}_{marking}"
    res = AnalysisPipeline(AnalysisConfig(), setup).run([vid / "synthetic.mp4"], out_dir)
    tr = res.trajectories
    tr = tr[tr["observed"] & tr["heading_deg"].notna()]
    gt = pd.read_parquet(vid / "ground_truth.parquet")
    # match each tracked position to the nearest true bee in that frame (works for anonymous tracks too)
    m = tr.merge(gt, on="frame", suffixes=("", "_gt"))
    m["d"] = np.hypot(m["x_mm"] - m["x_mm_gt"], m["y_mm"] - m["y_mm_gt"])
    m = m.sort_values("d").drop_duplicates(["bee_id", "frame"])
    m = m[m["d"] < 3]
    err = np.degrees(np.abs(np.angle(np.exp(1j * np.radians(m["heading_deg"] - m["heading_deg_gt"])))))
    m = m.assign(flip=np.asarray(err) > 90)
    rel = m["heading_source"].isin(RELIABLE_HEADING)
    return {
        "seed": seed, "marking": marking, "frames": len(m),
        "swapped": round(float(m.flip.mean()), 4),
        "swapped_at_cell": round(float(m[m.state == "visit"].flip.mean()), 4),
        "trustworthy_share": round(float(rel.mean()), 3),
        "swapped_trustworthy": round(float(m[rel].flip.mean()), 4),
        "swapped_trustworthy_at_cell": round(float(m[rel & (m.state == "visit")].flip.mean()), 4),
        "by_source": {s: f"{g.flip.mean():.3f} (n={len(g)})" for s, g in m.groupby("heading_source")},
        "silhouette_rule": res.summary["heading"]["shape"],
    }


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "heading_bench")
    for seed in (3, 1):
        for marking in ("color", "none"):
            print(json.dumps(bench(root, seed, marking)), flush=True)
