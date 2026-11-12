from __future__ import annotations

from typing import Protocol

import numpy as np

from ..models import BlobPatch, Detection


class Detector(Protocol):
    """Interface every per-frame detector implements."""

    def prepare(self, sample_frames: list[np.ndarray]) -> None:
        """One-off initialisation from frames spread over the video (may be a no-op)."""

    def detect(self, frame: np.ndarray, frame_index: int) -> tuple[list[Detection], list[BlobPatch]]:
        """Return detections and their pixel masks (same order) for one BGR frame."""
