"""Classical bee segmentation: dark bodies on a light, uniform background.

Algorithm
---------
1. **Background estimate**:
   * ``morphological`` (default): a grey-level *closing* with a disc wider
     than a bee removes every dark object narrower than the disc, leaving the
     empty arena. It's computed per frame, so bees that rest for a long time
     (typically *on the queen cell*, the behaviour we measure) are still
     detected. Large dark structures such as the queen cell are wider than the
     disc and stay in the background.
   * ``median``: per-pixel median of frames sampled over the video. Faster,
     but an immobile bee becomes part of the background.
2. **Foreground** = pixels at least ``diff_threshold`` grey levels darker than
   the background, inside the dish (minus a rim margin).
3. **Clean-up**: morphological open/close, fill holes (bright paint spots
   on the back otherwise punch holes in the mask).
4. **Blobs**: connected components; too small = noise; ``k`` bee-areas big =
   ``k`` touching bees, split with k-means on pixel coordinates.
5. **Shape**: centroid + second moments give the body axis (180° ambiguous)
   and major/minor lengths.
"""

from __future__ import annotations

import cv2
import numpy as np

from ..calibration import Geometry
from ..config import DetectionConfig
from ..models import BlobPatch, Detection


class BackgroundDetector:
    def __init__(self, cfg: DetectionConfig, geom: Geometry):
        self.cfg = cfg
        self.geom = geom
        self.arena = geom.arena_mask(cfg.arena_margin_mm)
        cell = geom.queen_cell_mask()
        if cfg.ignore_queen_cell and cell is not None:
            self.arena[cell > 0] = 0
        ign = geom.ignore_mask()
        if ign is not None:
            self.arena[ign > 0] = 0  # user-drawn areas: food, water, tape…
        self._cell_region = cell if (geom.learn_cell_background and cell is not None) else None
        bee_area_mm2 = np.pi / 4 * cfg.bee_length_mm * cfg.bee_width_mm
        self.bee_area_px = bee_area_mm2 * geom.px_per_mm**2
        self.min_area_px = cfg.min_area_fraction * self.bee_area_px
        # Closing disc must be wider than a bee but narrower than the queen cell.
        self._bg_scale = 0.5
        d = int(round(geom.mm(cfg.bee_width_mm * 1.8) * self._bg_scale)) | 1
        self._bg_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(d, 3), max(d, 3)))
        k = max(3, int(round(geom.mm(0.8))) | 1)
        self._clean_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        self._median_bg: np.ndarray | None = None
        self._static: np.ndarray | None = None   # bool mask of static dark structures
        self.threshold = cfg.diff_threshold
        self.measured_bee_area_px: float | None = None

    # ------------------------------------------------------------------ #
    def prepare(self, sample_frames: list[np.ndarray]) -> None:
        if self.cfg.method == "median" and sample_frames:
            greys = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in sample_frames])
            self._median_bg = np.median(greys, axis=0).astype(np.uint8)
        self.set_threshold(self.threshold, sample_frames)

    def set_threshold(self, threshold: int, sample_frames: list[np.ndarray]) -> None:
        """Change the sensitivity and re-learn everything that depends on it.

        A lower threshold makes every blob a little larger, so the size of one bee
        (used to decide how many bees a blob holds) must be measured again;
        otherwise single bees start being split in two.
        """
        self.threshold = int(threshold)
        self.learn_static(sample_frames)
        self.measured_bee_area_px = None
        if self.cfg.bee_size == "auto" and sample_frames:
            est = self.measure_bee_area(sample_frames)
            if est is not None:
                self.measured_bee_area_px = est
                self.bee_area_px = est
                self.min_area_px = self.cfg.min_area_fraction * est

    def learn_static(self, frames: list[np.ndarray]) -> None:
        """Find dark structures that never move and give them a temporal-median background."""
        self._static = None
        if len(frames) < 10 or (self.cfg.static_suppression <= 0 and self._cell_region is None):
            return
        greys = [cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (3, 3), 0) for f in frames]
        if self._median_bg is None:
            self._median_bg = np.median(np.stack(greys), axis=0).astype(np.uint8)
        k = max(3, int(round(self.geom.mm(1.0))) | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        cell_static = cv2.dilate(self._cell_region, kernel) > 0 if self._cell_region is not None else None
        if self.cfg.static_suppression <= 0:
            self._static = cell_static  # only the queen cell learns its own appearance
            return
        frac = np.zeros(greys[0].shape, np.float32)
        for g in greys:
            frac += cv2.subtract(self.background(g, force_morph=True), g) > self.threshold
        frac /= len(greys)
        static = cv2.dilate((frac >= self.cfg.static_suppression).astype(np.uint8), kernel).astype(bool)
        if cell_static is not None:
            static |= cell_static
        self._static = static if static.any() else None

    @property
    def static_mask(self) -> np.ndarray | None:
        return self._static

    def counts(self, frames: list[np.ndarray]) -> np.ndarray:
        """Number of detections in each frame (used to tune the sensitivity)."""
        return np.array([len(self.detect(f, 0)[0]) for f in frames], float)

    def measure_bee_area(self, frames: list[np.ndarray]) -> float | None:
        """Typical area (px) of one bee, measured from the video.

        Most blobs are single bees; smaller ones are legs, shadows and debris,
        larger ones are clusters. We take the **most common** blob size among
        blobs of plausible single-bee size, which is 0.08–3 % of the dish area
        (a 12 mm worker covers about 0.2 % of a 150 mm dish and 0.7 % of a 90 mm one).
        The mode is found on a smoothed log-size histogram. Returns None if too few blobs.
        """
        dish_area = np.pi * self.geom.radius_px**2
        lo, hi = 0.0008 * dish_area, 0.03 * dish_area
        areas = []
        for f in frames:
            n, _, stats, _ = cv2.connectedComponentsWithStats(self.foreground(f), connectivity=8)
            a = stats[1:, cv2.CC_STAT_AREA].astype(float)
            areas.extend(a[(a >= lo) & (a <= hi)])
        if len(areas) < 20:
            return None
        hist, edges = np.histogram(np.log(areas), bins=30, range=(np.log(lo), np.log(hi)))
        hist = np.convolve(hist, [1, 2, 3, 2, 1], "same")
        i = int(np.argmax(hist))
        return float(np.exp((edges[i] + edges[i + 1]) / 2))

    def implied_bee_length_mm(self) -> float | None:
        """Bee length the measured size implies at the current dish scale (None if not measured)."""
        if not self.measured_bee_area_px:
            return None
        aspect = self.cfg.bee_length_mm / self.cfg.bee_width_mm
        length_px = np.sqrt(4 * self.measured_bee_area_px / np.pi * aspect)
        return float(length_px / self.geom.px_per_mm)

    def background(self, grey: np.ndarray, force_morph: bool = False) -> np.ndarray:
        if not force_morph and self.cfg.method == "median" and self._median_bg is not None:
            return self._median_bg
        small = cv2.resize(grey, None, fx=self._bg_scale, fy=self._bg_scale, interpolation=cv2.INTER_AREA)
        closed = cv2.morphologyEx(small, cv2.MORPH_CLOSE, self._bg_kernel)
        return cv2.resize(closed, (grey.shape[1], grey.shape[0]), interpolation=cv2.INTER_LINEAR)

    def foreground(self, frame: np.ndarray) -> np.ndarray:
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        grey = cv2.GaussianBlur(grey, (3, 3), 0)
        bg = self.background(grey)
        if self._static is not None and self._median_bg is not None:
            bg = np.where(self._static, self._median_bg, bg)  # static structures: compare with the long-term median
        diff = cv2.subtract(bg, grey)  # positive where darker than background
        _, fg = cv2.threshold(diff, self.threshold, 255, cv2.THRESH_BINARY)
        fg &= self.arena
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self._clean_kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self._clean_kernel)
        # fill holes left by bright paint spots
        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(fg)
        cv2.drawContours(filled, contours, -1, 255, -1)
        return filled

    # ------------------------------------------------------------------ #
    def detect(self, frame: np.ndarray, frame_index: int) -> tuple[list[Detection], list[BlobPatch]]:
        fg = self.foreground(frame)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
        dets: list[Detection] = []
        patches: list[BlobPatch] = []
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < self.min_area_px:
                continue
            x0, y0, w, h = (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
                            stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT])
            sub = (labels[y0:y0 + h, x0:x0 + w] == i)
            k = int(np.clip(round(area / self.bee_area_px), 1, self.cfg.max_bees_per_blob))
            if k == 1:
                parts = [sub]
            else:
                parts = self._split(sub, k)
            for part in parts:
                d = _shape(part, x0, y0, frame_index)
                if d is None or d.area_px < self.min_area_px * 0.6:
                    continue
                dets.append(d)
                patches.append(BlobPatch(x0, y0, part.astype(np.uint8) * 255))
        return dets, patches

    @staticmethod
    def _split(sub: np.ndarray, k: int) -> list[np.ndarray]:
        ys, xs = np.nonzero(sub)
        pts = np.column_stack([xs, ys]).astype(np.float32)
        if len(pts) < k * 5:
            return [sub]
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
        cv2.setRNGSeed(len(pts))  # k-means starts from random centres: seed it, so the same video gives the same result
        _, lab, _ = cv2.kmeans(pts, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
        lab = lab.ravel()
        parts = []
        for j in range(k):
            m = np.zeros_like(sub)
            sel = lab == j
            m[ys[sel], xs[sel]] = True
            parts.append(m)
        return parts


def _shape(mask: np.ndarray, x0: int, y0: int, frame_index: int) -> Detection | None:
    """Centroid, orientation and axis lengths from image moments."""
    m = cv2.moments(mask.astype(np.uint8), binaryImage=True)
    if m["m00"] <= 0:
        return None
    cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
    mu20, mu02, mu11 = m["mu20"] / m["m00"], m["mu02"] / m["m00"], m["mu11"] / m["m00"]
    angle = 0.5 * np.arctan2(2 * mu11, mu20 - mu02)
    common = np.sqrt(4 * mu11**2 + (mu20 - mu02) ** 2)
    l1 = max(0.0, (mu20 + mu02 + common) / 2)
    l2 = max(0.0, (mu20 + mu02 - common) / 2)
    return Detection(
        frame=frame_index, x=x0 + cx, y=y0 + cy, axis_angle=float(angle),
        major_px=float(4 * np.sqrt(l1)), minor_px=float(4 * np.sqrt(l2)), area_px=float(m["m00"]),
    )
