"""Per-pixel paint colour classification in HSV space.

Bee cuticle is dark and moderately saturated, and the background is light
and unsaturated. Paint is either **strongly saturated and bright**
(chromatic colours) or **very bright and unsaturated** (white). A pixel is
paint only if it passes one of those two gates. Chromatic pixels are then
assigned to the nearest palette hue (circular distance on OpenCV's 0–179 hue
wheel).

.. note::
   Real paint under real LEDs rarely matches textbook hues. Tune each
   ``PaintColor.hue`` from a few frames of your own footage, using the
   *Explorer → pixel probe* in the web UI or :func:`Palette.describe_pixels`.
"""

from __future__ import annotations

import cv2
import numpy as np

from ..config import ColorIdConfig

UNASSIGNED = -1


class Palette:
    def __init__(self, cfg: ColorIdConfig):
        self.cfg = cfg
        self.names = [c.name for c in cfg.palette]
        self._chroma_idx = [i for i, c in enumerate(cfg.palette) if not c.white]
        self._chroma_hues = np.array([cfg.palette[i].hue for i in self._chroma_idx], dtype=np.float32)
        self._white_idx = next((i for i, c in enumerate(cfg.palette) if c.white), None)

    @property
    def white_index(self) -> int | None:
        return self._white_idx

    def classify(self, bgr: np.ndarray) -> np.ndarray:
        """Label image: palette index per pixel, ``-1`` for non-paint."""
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        h = hsv[..., 0].astype(np.float32)
        s = hsv[..., 1]
        v = hsv[..., 2]
        out = np.full(h.shape, UNASSIGNED, dtype=np.int16)

        if len(self._chroma_hues):
            chroma = (s >= self.cfg.min_saturation) & (v >= self.cfg.min_value)
            d = np.abs(h[..., None] - self._chroma_hues[None, None, :])
            d = np.minimum(d, 180.0 - d)  # hue is circular
            best = np.argmin(d, axis=-1)
            ok = chroma & (np.take_along_axis(d, best[..., None], -1)[..., 0] <= self.cfg.max_hue_distance)
            out[ok] = np.asarray(self._chroma_idx, dtype=np.int16)[best[ok]]

        if self._white_idx is not None:
            white = (s <= self.cfg.white_max_saturation) & (v >= self.cfg.white_min_value)
            out[white] = self._white_idx
        return out

    def describe_pixels(self, bgr: np.ndarray) -> dict:
        """Median HSV of a patch; used by the UI pixel probe to tune the palette."""
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).reshape(-1, 3)
        h, s, v = np.median(hsv, axis=0)
        lab = self.classify(bgr).ravel()
        counts = {self.names[i]: int((lab == i).sum()) for i in range(len(self.names))}
        return {"h": float(h), "s": float(s), "v": float(v), "classified": counts}
