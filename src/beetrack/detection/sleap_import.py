"""Import SLEAP predictions (the deep-learning route).

Train a SLEAP model separately (see ``docs/SLEAP.md``), run inference, then
export an *analysis HDF5* file::

    sleap-track video.mp4 -m models/centroid -m models/topdown_id -o preds.slp
    sleap-convert preds.slp --format analysis -o preds.analysis.h5

With an **ID model** (top-down multi-class), SLEAP's track names are the class
names you labelled, i.e. our ``bee_id`` values (``W01``…). Detections then
arrive with identity already known, so beetrack skips colour classification
and identity resolution and continues with trajectories, visits and metrics.

Analysis-file layout (as written by SLEAP, read with h5py)::

    tracks          float (n_tracks, 2, n_nodes, n_frames)  # x/y, NaN = missing
    track_names     bytes (n_tracks,)
    node_names      bytes (n_nodes,)
    track_occupancy (n_frames, n_tracks)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..models import Detection


def _names(arr) -> list[str]:
    return [n.decode() if isinstance(n, (bytes, np.bytes_)) else str(n) for n in arr]


def load_sleap_analysis(
    path: str | Path,
    *,
    head_node: str = "head",
    center_node: str = "thorax",
    tail_node: str = "abdomen",
    frame_step: int = 1,
) -> list[Detection]:
    """Read a SLEAP analysis .h5 into Detections (one per track per frame)."""
    try:
        import h5py
    except ImportError as e:  # pragma: no cover
        raise ImportError("SLEAP import needs h5py: pip install 'beetrack[sleap]'") from e

    with h5py.File(path, "r") as f:
        tracks = f["tracks"][:]  # (n_tracks, 2, n_nodes, n_frames)
        track_names = _names(f["track_names"][:])
        node_names = _names(f["node_names"][:])

    def node(name: str) -> int | None:
        return node_names.index(name) if name in node_names else None

    hi, ci, ti = node(head_node), node(center_node), node(tail_node)
    if ci is None and hi is None:
        raise ValueError(f"SLEAP file has nodes {node_names}; need at least {center_node!r} or {head_node!r}")

    dets: list[Detection] = []
    n_tracks, _, _, n_frames = tracks.shape
    for t in range(n_tracks):
        name = track_names[t] if t < len(track_names) else f"track_{t}"
        for fr in range(0, n_frames, frame_step):
            pts = tracks[t, :, :, fr]  # (2, n_nodes)
            c = pts[:, ci] if ci is not None else pts[:, hi]
            if not np.all(np.isfinite(c)):
                continue
            head = pts[:, hi] if hi is not None else np.array([np.nan, np.nan])
            tail = pts[:, ti] if ti is not None else np.array([np.nan, np.nan])
            if np.all(np.isfinite(head)) and np.all(np.isfinite(tail)):
                vec = head - tail
                length = float(np.hypot(*vec))
            elif np.all(np.isfinite(head)):
                vec = head - c
                length = float(2 * np.hypot(*vec))
            else:
                vec, length = np.array([np.nan, np.nan]), float("nan")
            angle = float(np.arctan2(vec[1], vec[0])) if np.all(np.isfinite(vec)) else float("nan")
            dets.append(
                Detection(
                    frame=fr, x=float(c[0]), y=float(c[1]), axis_angle=angle,
                    major_px=length, minor_px=float("nan"), area_px=float("nan"),
                    bee_id=name, head_x=float(head[0]), head_y=float(head[1]),
                )
            )
    return dets
