"""Per-bee summary metrics and time-binned visit statistics.

Every metric is computed only over time when the bee was **tracked**
(observed or interpolated). ``tracked_fraction`` reports how much that was;
low coverage means the bee's numbers deserve less trust.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def bee_metrics(traj: pd.DataFrame, visits: pd.DataFrame, bee_ids: list[str], duration_s: float, fps: float,
                moving_speed_mm_s: float, zones: list[str] | None = None) -> pd.DataFrame:
    """One row per bee: movement, coverage, identity probability, and per-zone visit statistics.

    ``zones`` lists the zone names to report, so the columns exist even when
    nobody visited (default: the zones present in ``visits``).
    """
    rows = []
    if zones is None:
        zones = sorted(visits["zone"].unique()) if not visits.empty else []
    for bee in bee_ids:
        g = traj[traj["bee_id"] == bee].sort_values("frame")
        row: dict = {"bee_id": bee}
        if g.empty:
            row.update(tracked_fraction=0.0, observed_fraction=0.0, distance_m=np.nan,
                       mean_speed_mm_s=np.nan, moving_fraction=np.nan, id_probability=np.nan)
        else:
            tracked = g["x_mm"].notna()
            step = np.hypot(np.diff(g["x_mm"].to_numpy()), np.diff(g["y_mm"].to_numpy()))
            row.update(
                tracked_fraction=float(tracked.mean()),
                observed_fraction=float(g["observed"].mean()),
                distance_m=float(np.nansum(step) / 1000.0),
                mean_speed_mm_s=float(g.loc[tracked, "speed_mm_s"].mean()),
                moving_fraction=float((g.loc[tracked, "speed_mm_s"] > moving_speed_mm_s).mean()),
                id_probability=(float(g.loc[tracked, "id_confidence"].mean())
                                if "id_confidence" in g and g.loc[tracked, "id_confidence"].notna().any() else np.nan),
            )
        for z in zones:
            v = visits[(visits["bee_id"] == bee) & (visits["zone"] == z)]
            tracked_s = row["tracked_fraction"] * duration_s
            row.update({
                f"{z}_visits": int(len(v)),
                f"{z}_total_s": float(v["duration_s"].sum()),
                f"{z}_mean_s": float(v["duration_s"].mean()) if len(v) else np.nan,
                f"{z}_median_s": float(v["duration_s"].median()) if len(v) else np.nan,
                f"{z}_max_s": float(v["duration_s"].max()) if len(v) else np.nan,
                f"{z}_first_visit_s": float(v["start_s"].min()) if len(v) else np.nan,
                f"{z}_visits_per_h": float(len(v) / (tracked_s / 3600)) if tracked_s > 0 else np.nan,
                f"{z}_time_fraction": float(v["duration_s"].sum() / tracked_s) if tracked_s > 0 else np.nan,
            })
        rows.append(row)
    return pd.DataFrame(rows)


def binned_visits(visits: pd.DataFrame, bee_ids: list[str], duration_s: float, bin_s: float) -> pd.DataFrame:
    """Seconds spent in each zone per bee per time bin (visits split across bins)."""
    edges = np.arange(0, duration_s + bin_s, bin_s)
    rows = []
    zones = sorted(visits["zone"].unique()) if not visits.empty else []
    for z in zones:
        vz = visits[visits["zone"] == z]
        for bee in bee_ids:
            vb = vz[vz["bee_id"] == bee]
            for lo, hi in zip(edges[:-1], edges[1:]):
                s = np.clip(vb["start_s"].to_numpy(), lo, hi)
                e = np.clip(vb["start_s"].to_numpy() + vb["duration_s"].to_numpy(), lo, hi)
                starts_in = ((vb["start_s"] >= lo) & (vb["start_s"] < hi)).sum()
                rows.append({"zone": z, "bee_id": bee, "bin_start_s": lo, "bin_end_s": hi,
                             "seconds": float((e - s).sum()), "visits_started": int(starts_in)})
    # always keep the header, even with no visits, so the CSV stays readable
    return pd.DataFrame(rows, columns=BINNED_COLUMNS)


BINNED_COLUMNS = ["zone", "bee_id", "bin_start_s", "bin_end_s", "seconds", "visits_started"]
