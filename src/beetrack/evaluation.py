"""Compare pipeline output with ground truth.

Works with synthetic ground truth (exact) and with **hand annotations** of
real footage: any table with ``frame, bee_id, x_mm, y_mm`` for a sample of
frames. Reporting these numbers for every study is the validation step the
README asks for ("hand-check random frames").

Metrics
-------
* ``id_accuracy``: of all annotated (bee, frame) pairs, the fraction where
  the pipeline places *that same bee* within ``tol_mm`` of the annotation.
* ``coverage``: the fraction where the pipeline has *any* position for that bee.
* ``wrong_id_rate``: the fraction where the bee's position is reported but
  is more than ``tol_mm`` away from the annotation (an identity swap or a bad
  detection).
* ``median_error_mm``: position error over correctly identified pairs.
* Visit comparison per bee and zone: counts and total durations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def evaluate_tracks(pred: pd.DataFrame, truth: pd.DataFrame, tol_mm: float = 4.0) -> dict:
    t = truth[["frame", "bee_id", "x_mm", "y_mm"]]
    p = pred[["frame", "bee_id", "x_mm", "y_mm"]].dropna()
    m = t.merge(p, on=["frame", "bee_id"], how="left", suffixes=("", "_p"))
    err = np.hypot(m["x_mm"] - m["x_mm_p"], m["y_mm"] - m["y_mm_p"])
    has = err.notna()
    ok = has & (err <= tol_mm)
    per_bee = (
        m.assign(ok=ok, has=has)
        .groupby("bee_id")
        .agg(id_accuracy=("ok", "mean"), coverage=("has", "mean"))
        .reset_index()
    )
    return {
        "pairs": int(len(m)),
        "id_accuracy": float(ok.mean()),
        "coverage": float(has.mean()),
        "wrong_id_rate": float((has & ~ok).mean()),
        "median_error_mm": float(err[ok].median()) if ok.any() else float("nan"),
        "per_bee": per_bee,
    }


def compare_visits(pred: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    def agg(v):
        return v.groupby(["zone", "bee_id"]).agg(n=("duration_s", "size"), total_s=("duration_s", "sum"))

    out = agg(truth).merge(agg(pred), left_index=True, right_index=True, how="outer", suffixes=("_true", "_pred")).fillna(0)
    out["total_error_s"] = out["total_s_pred"] - out["total_s_true"]
    return out.reset_index()
