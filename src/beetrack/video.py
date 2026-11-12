"""Video access: metadata, frame iteration across multi-file recordings.

A recording is a list of *segments* (e.g. 1-hour files written by the
recorder). :class:`Recording` presents them as one continuous timeline: global
frame indices and seconds since the start of the first segment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    fps: float
    n_frames: int
    width: int
    height: int

    @property
    def duration_s(self) -> float:
        return self.n_frames / self.fps if self.fps else 0.0

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "fps": self.fps,
            "n_frames": self.n_frames,
            "width": self.width,
            "height": self.height,
            "duration_s": self.duration_s,
        }


def probe(path: str | Path) -> VideoInfo:
    """Read basic metadata without decoding the whole file."""
    path = Path(path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"cannot open video: {path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()
    if fps <= 0 or fps > 1000:
        raise IOError(f"video reports an invalid frame rate ({fps}): {path}")
    return VideoInfo(path, fps, n, w, h)


def read_frame(path: str | Path, index: int, max_back: int = 120) -> np.ndarray:
    """Random access to one frame (BGR). Slow-ish; meant for UI previews.

    Variable-frame-rate files (screen recordings, phone videos) often report
    more frames in the header than actually decode, and seeking near the end
    fails. Then we fall back to the nearest readable *earlier* frame (up to
    ``max_back`` frames back): a preview a fraction of a second early beats
    an error.
    """
    index = max(0, int(index))
    cap = cv2.VideoCapture(str(path))
    try:
        step = 1
        target = index
        while target >= max(0, index - max_back):
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            ok, frame = cap.read()
            if ok:
                return frame
            if target == 0:
                break
            target = max(0, target - step)
            step = min(step * 2, 32)
    finally:
        cap.release()
    raise IndexError(f"frame {index} not readable in {Path(path).name}")


@dataclass(frozen=True)
class FrameRef:
    """Location of an analysed frame on the recording timeline."""

    index: int        # global index in source-frame units (segments concatenated)
    time_s: float     # seconds from the start of the recording
    segment: int      # which file it came from


class Recording:
    """One or more video segments analysed as a single timeline.

    All segments must share resolution and frame rate (they come from one
    camera with locked settings).
    """

    def __init__(self, paths: list[str | Path]):
        if not paths:
            raise ValueError("a recording needs at least one video file")
        self.segments: list[VideoInfo] = [probe(p) for p in paths]
        first = self.segments[0]
        for s in self.segments[1:]:
            if (s.width, s.height) != (first.width, first.height):
                raise ValueError(f"{s.path.name}: resolution differs from {first.path.name}")
            if abs(s.fps - first.fps) > 0.01:
                raise ValueError(f"{s.path.name}: fps {s.fps} differs from {first.fps}")
        self.fps = first.fps
        self.width, self.height = first.width, first.height
        self._offsets = np.cumsum([0] + [s.n_frames for s in self.segments[:-1]]).tolist()

    @property
    def n_frames(self) -> int:
        return sum(s.n_frames for s in self.segments)

    @property
    def duration_s(self) -> float:
        return self.n_frames / self.fps

    def locate(self, global_index: int) -> tuple[int, int]:
        """Global frame index -> (segment number, local frame index)."""
        seg = int(np.searchsorted(self._offsets, global_index, side="right") - 1)
        return seg, global_index - self._offsets[seg]

    def read(self, global_index: int) -> np.ndarray:
        seg, local = self.locate(global_index)
        return read_frame(self.segments[seg].path, local)

    def step_for(self, analysis_fps: float) -> int:
        """Analyse every n-th frame so the effective rate is ≤ ``analysis_fps``."""
        return max(1, int(round(self.fps / analysis_fps)))

    def iter_frames(self, step: int = 1, max_frames: int | None = None) -> Iterator[tuple[FrameRef, np.ndarray]]:
        """Yield every ``step``-th frame across all segments (sequential decode)."""
        produced = 0
        for seg_i, info in enumerate(self.segments):
            cap = cv2.VideoCapture(str(info.path))
            if not cap.isOpened():
                raise IOError(f"cannot open video: {info.path}")
            offset = self._offsets[seg_i]
            local = 0
            try:
                while True:
                    g = offset + local
                    if g % step:
                        if not cap.grab():  # skip without full decode
                            break
                        local += 1
                        continue
                    ok, frame = cap.read()
                    if not ok:
                        break
                    yield FrameRef(g, g / self.fps, seg_i), frame
                    produced += 1
                    local += 1
                    if max_frames is not None and produced >= max_frames:
                        return
            finally:
                cap.release()

    def sample_frames(self, n: int) -> list[np.ndarray]:
        """``n`` frames spread evenly over the recording (for background models)."""
        idx = np.linspace(0, max(0, self.n_frames - 1), num=min(n, max(1, self.n_frames))).astype(int)
        out = []
        for i in idx:
            try:
                out.append(self.read(int(i)))
            except IndexError:
                continue
        return out
