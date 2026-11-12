"""Core data records passed between pipeline stages.

Stages exchange small dataclasses while running and :class:`pandas.DataFrame`
tables once a stage is complete. The table schemas are documented in
``docs/DATA_FORMATS.md``. Keep the two in sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class Detection:
    """One bee-sized blob in one frame (pixel coordinates).

    ``axis_angle`` is the body-axis orientation in radians, in the image frame
    (x right, y down), with a 180° ambiguity: the detector can't tell head
    from tail. :mod:`beetrack.trajectories` resolves the direction later from
    motion.
    """

    frame: int
    x: float
    y: float
    axis_angle: float
    major_px: float
    minor_px: float
    area_px: float
    # Filled by the colour identifier
    colors: tuple[str, ...] = ()          # observed paint colours, largest spot first
    spots: tuple[tuple[str, float, float], ...] = ()  # (colour, x_px, y_px) of those spots
    color_scores: dict[str, float] = field(default_factory=dict)  # bee_id -> evidence
    # Filled by the tracker
    tracklet: int = -1
    # Set directly by importers that already know identity (e.g. SLEAP ID models)
    bee_id: str | None = None
    head_x: float = float("nan")
    head_y: float = float("nan")

    def as_row(self) -> dict:
        return {
            "frame": self.frame,
            "x_px": self.x,
            "y_px": self.y,
            "axis_angle": self.axis_angle,
            "major_px": self.major_px,
            "minor_px": self.minor_px,
            "area_px": self.area_px,
            "colors": "+".join(self.colors),
            **_spot_cols(self.spots),
            "best_match": max(self.color_scores, key=self.color_scores.get) if self.color_scores else "",
            "best_score": max(self.color_scores.values()) if self.color_scores else 0.0,
            "tracklet": self.tracklet,
            "bee_id": self.bee_id,
            "head_x_px": self.head_x,
            "head_y_px": self.head_y,
        }


def _spot_cols(spots) -> dict:
    out = {}
    for k in (1, 2):
        c, x, y = spots[k - 1] if len(spots) >= k else ("", float("nan"), float("nan"))
        out.update({f"s{k}_color": c, f"s{k}_x": x, f"s{k}_y": y})
    return out


@dataclass(slots=True)
class BlobPatch:
    """Pixels belonging to one detection, kept only while the frame is processed."""

    x0: int
    y0: int
    mask: np.ndarray  # uint8, 255 inside the bee, cropped to its bounding box
