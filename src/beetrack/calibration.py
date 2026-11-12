"""Geometry: pixel↔mm scale, the arena mask, and queen-cell zones.

Coordinate conventions (used everywhere in outputs):

* **Pixels**: image frame, origin top-left, x right, y down.
* **Millimetres**: origin at the **dish centre**, x right, **y up** (a normal
  math frame), so plots aren't upside-down. ``to_mm`` / ``to_px`` are the only
  functions that convert between the two.
* **Angles** in mm space: degrees, counter-clockwise from +x.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import DishGeometry, ExperimentSetup, Zone


def detect_dish(frame: np.ndarray, diameter_mm: float = 150.0) -> DishGeometry | None:
    """Find the dish rim with a Hough transform. Returns ``None`` if not found.

    Looks for the largest strong circle whose radius is 30–50 % of the shorter
    image side, which is how the rig frames the dish. Always check the result
    in the UI; if it's wrong, set the dish manually by clicking 3 rim points.
    """
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    scale = 640.0 / max(grey.shape)
    small = cv2.resize(grey, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else grey
    s = scale if scale < 1 else 1.0
    small = cv2.medianBlur(small, 5)
    short = min(small.shape)
    circles = cv2.HoughCircles(
        small, cv2.HOUGH_GRADIENT, dp=1.2, minDist=short,
        param1=80, param2=40, minRadius=int(0.30 * short), maxRadius=int(0.52 * short),
    )
    if circles is None:
        return None
    x, y, r = max(circles[0], key=lambda c: c[2])
    return DishGeometry(center_px=(float(x / s), float(y / s)), radius_px=float(r / s), diameter_mm=diameter_mm)


def circle_from_points(p1, p2, p3) -> tuple[tuple[float, float], float]:
    """Circle through three rim points (used by the UI's 3-click dish tool)."""
    (x1, y1), (x2, y2), (x3, y3) = p1, p2, p3
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-9:
        raise ValueError("points are collinear")
    ux = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / d
    uy = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / d
    return (ux, uy), float(np.hypot(x1 - ux, y1 - uy))


@dataclass
class Geometry:
    """Pre-computed geometry for one experiment at the video's resolution."""

    cx: float
    cy: float
    radius_px: float
    px_per_mm: float
    queen_cell: np.ndarray | None  # (N, 2) float32 polygon, pixels
    width: int
    height: int
    ignore: list[np.ndarray] | None = None  # polygons (pixels) where nothing is detected
    learn_cell_background: bool = False

    @classmethod
    def from_setup(cls, setup: ExperimentSetup, width: int, height: int) -> "Geometry":
        if setup.dish is None:
            raise ValueError("experiment setup has no dish geometry")
        d = setup.dish
        poly = None
        if setup.queen_cell is not None:
            poly = np.asarray(setup.queen_cell.polygon_px, dtype=np.float32)
        return cls(
            cx=d.center_px[0], cy=d.center_px[1], radius_px=d.radius_px,
            px_per_mm=(2 * d.radius_px) / d.diameter_mm, queen_cell=poly, width=width, height=height,
            ignore=[np.asarray(a.polygon_px, dtype=np.float32) for a in setup.ignore_areas],
            learn_cell_background=bool(setup.queen_cell and setup.queen_cell.learn_background),
        )

    # --- unit conversion ---------------------------------------------------- #
    def mm(self, length_mm: float) -> float:
        return length_mm * self.px_per_mm

    def to_mm(self, x_px, y_px):
        x_px, y_px = np.asarray(x_px, float), np.asarray(y_px, float)
        return (x_px - self.cx) / self.px_per_mm, (self.cy - y_px) / self.px_per_mm

    def to_px(self, x_mm, y_mm):
        x_mm, y_mm = np.asarray(x_mm, float), np.asarray(y_mm, float)
        return self.cx + x_mm * self.px_per_mm, self.cy - y_mm * self.px_per_mm

    # --- masks ---------------------------------------------------------------- #
    def arena_mask(self, margin_mm: float = 0.0) -> np.ndarray:
        """uint8 mask, 255 inside the dish (shrunk by ``margin_mm``), 0 outside."""
        m = np.zeros((self.height, self.width), np.uint8)
        r = max(1, int(round(self.radius_px - self.mm(margin_mm))))
        cv2.circle(m, (int(round(self.cx)), int(round(self.cy))), r, 255, -1)
        return m

    def ignore_mask(self) -> np.ndarray | None:
        if not self.ignore:
            return None
        m = np.zeros((self.height, self.width), np.uint8)
        cv2.fillPoly(m, [np.round(p).astype(np.int32) for p in self.ignore], 255)
        return m

    def exclusion_mask(self, include_cell: bool, margin_mm: float = 1.0) -> np.ndarray | None:
        """bool mask of pixels where no mark may be read: the ignore areas (and the queen cell if
        ``include_cell``), grown by ``margin_mm``. None if there is nothing to exclude."""
        m = np.zeros((self.height, self.width), np.uint8)
        ign, cell = self.ignore_mask(), self.queen_cell_mask() if include_cell else None
        for part in (ign, cell):
            if part is not None:
                m |= part
        if not m.any():
            return None
        r = int(round(self.mm(margin_mm)))
        if r > 0:
            m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
        return m > 0

    def queen_cell_mask(self) -> np.ndarray | None:
        if self.queen_cell is None:
            return None
        m = np.zeros((self.height, self.width), np.uint8)
        cv2.fillPoly(m, [np.round(self.queen_cell).astype(np.int32)], 255)
        return m

    # --- zones ---------------------------------------------------------------- #
    def distance_to_cell_mm(self, x_px: np.ndarray, y_px: np.ndarray) -> np.ndarray:
        """Distance (mm) from each point to the queen-cell outline; 0 if inside, NaN if point missing."""
        if self.queen_cell is None:
            raise ValueError("no queen cell defined")
        contour = self.queen_cell.reshape(-1, 1, 2)
        out = np.full(len(x_px), np.nan)
        for i, (x, y) in enumerate(zip(x_px, y_px)):
            if np.isfinite(x) and np.isfinite(y):
                d = cv2.pointPolygonTest(contour, (float(x), float(y)), True)  # + inside, - outside
                out[i] = max(0.0, -d) / self.px_per_mm
        return out

    def zone_polygon_px(self, zone: Zone, samples: int = 64) -> np.ndarray:
        """Approximate outline of the cell grown by ``zone.margin_mm`` (for drawing)."""
        mask = self.queen_cell_mask()
        if mask is None:
            raise ValueError("no queen cell defined")
        r = int(round(self.mm(zone.margin_mm)))
        if r > 0:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
            mask = cv2.dilate(mask, k)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(contours, key=cv2.contourArea).reshape(-1, 2)
        return c.astype(np.float32)
